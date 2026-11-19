import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {Document, Element} = require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal = function(){this.open = true;};
Element.prototype.close = function(){this.open = false;};
const doc = new Document('');
doc.documentElement = doc.createElement('html');
globalThis.document = doc;
doc.removeEventListener = () => {};
globalThis.CSS = {escape: value => String(value)};
const matches = Element.prototype.matches;
Element.prototype.matches = function(selector){
 const focusSelector = selector.match(/^\[data-focus-key="([^"]+)"\]$/);
 return focusSelector ? this.dataset.focusKey === focusSelector[1] : matches.call(this, selector);
};

const ai = await import('../../../src/vsc/interfaces/web/static/character-studio-ai.js');
const store = await import('../../../src/vsc/interfaces/web/static/character-studio-store.js');
const {createCharacterStudio} = await import('../../../src/vsc/interfaces/web/static/character-studio.js');
const flush = () => new Promise(resolve => setTimeout(resolve, 20));
const pngBytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 0]);

function memoryStorage(){
 const memory = new Map();
 return {
  getItem: key => memory.has(key) ? memory.get(key) : null,
  setItem: (key, value) => memory.set(key, String(value)),
  removeItem: key => memory.delete(key),
 };
}
function installWindow(){
 const previous = globalThis.window;
 globalThis.window = {
  location: {protocol: 'http:', hostname: 'localhost'},
  addEventListener(){},
  removeEventListener(){},
  localStorage: memoryStorage(),
 };
 return () => {if (previous === undefined) delete globalThis.window; else globalThis.window = previous;};
}
function gptConfig(model, endpointMode, fidelity = 'high', customModel = ''){
 return store.mergeStoredConfig({
  activeProvider: 'gpt',
  useProxy: false,
  imagePassMode: 'url',
  sendStitchedSheet: false,
  gptParams: {endpointMode, inputFidelity: fidelity},
  providers: {gpt: {apiKey: 'sk-test-key', model, customModel, baseUrl: 'https://api.openai.com/v1'}},
 });
}
const oneRef = {portrait: {原图: 'https://cdn.example/portrait.png'}, costume: null, pose: null, extraImages: []};
async function captureGpt(config, recipe = oneRef){
 const calls = [];
 const original = globalThis.fetch;
 globalThis.fetch = async (url, init) => {
  calls.push({url: String(url), body: init?.body});
  return {ok: true, status: 200, headers: new Headers({'content-type': 'application/json'}), json: async () => ({data: [{b64_json: 'AA=='}]})};
 };
 try {
  await ai.generateCharacterImage({recipe, prompt: '合成角色', config});
 } finally {globalThis.fetch = original;}
 return calls;
}

test('GPT Image 2 and newer omit input_fidelity while older models keep the requested value', () => {
 assert.equal(ai.getGptInputFidelity('gpt-image-1', 'high'), 'high');
 assert.equal(ai.getGptInputFidelity('gpt-image-1.5', 'low'), 'low');
 assert.equal(ai.getGptInputFidelity('gpt-image-1-2024-12-01', 'high'), 'high');
 assert.equal(ai.getGptInputFidelity('gpt-image-1-mini', 'low'), 'low');
 assert.equal(ai.getGptInputFidelity('gpt-image-1-mini', 'high'), undefined);
 assert.equal(ai.getGptInputFidelity(' gpt-image-1-mini-2024-01-01 ', 'low'), 'low');
 for (const model of ['gpt-image-2', 'gpt-image-2.5', 'gpt-image-2.6-sunburst', 'gpt-image-2.6-flare', 'custom-alias']) {
  assert.equal(ai.getGptInputFidelity(model, 'high'), undefined, model);
  assert.equal(ai.getGptInputFidelity(model, 'low'), undefined, model);
 }
 assert.deepEqual(ai.PROVIDER_META.gpt.models.map(model => model.value).slice(0, 2), ['gpt-image-2.6-sunburst', 'gpt-image-2.6-flare']);
 assert.ok(ai.PROVIDER_META.gpt.models.some(model => model.value === 'gpt-image-2.5'));
});

test('GPT JSON and responses bodies send input_fidelity only when the model accepts it', async () => {
 const sunburst = await captureGpt(gptConfig('gpt-image-2.6-sunburst', 'images_edits_json', 'high'));
 assert.equal(JSON.parse(sunburst[0].body).input_fidelity, undefined);
 assert.match(sunburst[0].url, /\/v1\/images\/edits$/);
 const classic = await captureGpt(gptConfig('gpt-image-1', 'images_edits_json', 'low'));
 assert.equal(JSON.parse(classic[0].body).input_fidelity, 'low');
 const miniHigh = await captureGpt(gptConfig('custom', 'responses', 'high', 'gpt-image-1-mini'));
 const miniTool = JSON.parse(miniHigh[0].body).tools[0];
 assert.equal(miniTool.input_fidelity, undefined);
 assert.equal(JSON.parse(miniHigh[0].body).model, 'gpt-image-1-mini');
 assert.match(miniHigh[0].url, /\/v1\/responses$/);
 const miniLow = await captureGpt(gptConfig('custom', 'responses', 'low', 'gpt-image-1-mini'));
 assert.equal(JSON.parse(miniLow[0].body).tools[0].input_fidelity, 'low');
 const chat = await captureGpt(gptConfig('gpt-image-1', 'chat', 'high'));
 assert.equal(JSON.parse(chat[0].body).input_fidelity, undefined);
 assert.match(chat[0].url, /\/v1\/chat\/completions$/);

 const original = globalThis.fetch;
 const calls = [];
 globalThis.fetch = async (url, init) => {
  calls.push(init.body);
  return {ok: true, status: 200, headers: new Headers(), json: async () => ({data: [{b64_json: 'AA=='}]})};
 };
 try {
  await ai.generateCharacterImage({
   recipe: {extraImages: [{url: 'data:image/png;base64,AA=='}]},
   prompt: '合成角色',
   config: gptConfig('gpt-image-2.6-flare', 'images_edits', 'high'),
  });
  await ai.generateCharacterImage({
   recipe: {extraImages: [{url: 'data:image/png;base64,AA=='}]},
   prompt: '合成角色',
   config: gptConfig('gpt-image-1.5', 'images_edits', 'high'),
  });
 } finally {globalThis.fetch = original;}
 assert.equal(calls[0].get('input_fidelity'), null);
 assert.equal(calls[1].get('input_fidelity'), 'high');
});

test('stored GPT and Kling choices stay, and PixAI is locked to the official origin', () => {
 const merged = store.mergeStoredConfig({
  activeProvider: 'kling',
  providers: {
   gpt: {model: 'gpt-image-2.5', apiKey: 'sk-kept', baseUrl: 'https://api.openai.com/v1'},
   kling: {model: 'kling-v2', apiKey: 'kling-kept', baseUrl: 'https://api.klingai.com'},
   pixai: {model: 'not-a-model', apiKey: 'pixai-kept', baseUrl: 'https://evil.example', customModel: 'override'},
   agy_auth: {model: 'image-generator'},
  },
  pixaiParams: {aspectRatio: '99:1', size: '4k', mode: 'ultra', negativePrompt: 'x'.repeat(5000), seed: '12'},
 });
 assert.equal(merged.activeProvider, 'kling');
 assert.equal(merged.providers.gpt.model, 'gpt-image-2.5');
 assert.equal(merged.providers.gpt.apiKey, 'sk-kept');
 assert.equal(merged.providers.kling.model, 'kling-v2');
 assert.equal(merged.providers.kling.baseUrl, 'https://api.klingai.com');
 assert.equal(merged.providers.pixai.model, ai.PIXAI_MODEL);
 assert.equal(merged.providers.pixai.baseUrl, 'https://api.pixai.art');
 assert.equal(merged.providers.pixai.customModel, '');
 assert.equal(merged.providers.pixai.apiKey, 'pixai-kept');
 assert.equal(merged.pixaiParams.aspectRatio, '3:4');
 assert.equal(merged.pixaiParams.size, '1k');
 assert.equal(merged.pixaiParams.mode, 'ultra');
 assert.equal(merged.pixaiParams.negativePrompt.length, 4096);
 assert.equal(merged.pixaiParams.seed, 12);
 assert.equal(merged.providers.agy_auth.model, 'image-generator');
 const fresh = store.mergeStoredConfig(null);
 assert.equal(fresh.activeProvider, 'agy_auth');
 assert.equal(fresh.providers.gpt.model, 'gpt-image-2.6-sunburst');
 assert.equal(fresh.useProxy, false);
 const switched = store.mergeStoredConfig({activeProvider: 'pixai'});
 assert.equal(switched.useProxy, true);
 const flash = store.mergeStoredConfig({providers: {pixai: {model: ai.PIXAI_FLASH_MODEL}}, pixaiParams: {mode: 'pro', seed: 1.5}});
 assert.equal(flash.pixaiParams.mode, 'default');
 assert.equal(flash.pixaiParams.seed, undefined);
});

test('PixAI accepts exactly three official images and builds one create payload', async () => {
 const recipe = {
  portrait: {原图: 'portrait.png'},
  costume: {预览图: 'costume-preview.png', 原图: 'costume-full.png'},
  pose: {原图: 'pose.png', source: 'upload'},
  extraImages: [],
 };
 assert.deepEqual(ai.pixAiSources(recipe), ['portrait.png', 'costume-preview.png', 'pose.png']);
 assert.throws(() => ai.pixAiSources({...recipe, extraImages: [{url: 'extra.png'}]}), /请先移除附加参考图/);
 assert.throws(() => ai.pixAiSources({portrait: recipe.portrait, costume: null, pose: recipe.pose}), /请补齐人像、服装、姿势/);
 assert.throws(() => ai.pixAiBaseUrl('https://api.pixai.art.evil.com'), /仅支持官方地址/);
 assert.equal(ai.pixAiBaseUrl('https://api.pixai.art/'), 'https://api.pixai.art');
 const payload = ai.pixAiPayload('角色', {aspectRatio: '9:16', size: '1.5k', mode: 'pro', negativePrompt: '模糊', seed: 7}, ['a', 'b', 'c'], ai.PIXAI_MODEL);
 assert.equal(payload.modelVersionId, ai.PIXAI_MODEL);
 assert.deepEqual(payload.contextImages, ['a', 'b', 'c']);
 assert.equal(payload.mode, 'pro');
 assert.equal(payload.negativePrompt, '模糊');
 assert.equal(payload.batchSize, 1);
 assert.equal(payload.promptHelper, 'disable');
 assert.equal(payload.seed, 7);
 assert.equal(payload.lora, undefined);
 const flash = ai.pixAiPayload('角色', {aspectRatio: '3:4', size: '1k', mode: 'default', negativePrompt: '不要'}, ['a', 'b', 'c'], ai.PIXAI_FLASH_MODEL);
 assert.equal(flash.negativePrompt, undefined);
 assert.equal(flash.mode, undefined);
 assert.throws(() => ai.pixAiPayload('角色', {mode: 'pro', negativePrompt: ''}, ['a', 'b', 'c'], ai.PIXAI_FLASH_MODEL), /Flash/);
 assert.throws(() => ai.pixAiPayload(' ', {mode: 'default', negativePrompt: ''}, ['a', 'b', 'c']), /1–10000/);
 assert.throws(() => ai.pixAiPayload('角色', {mode: 'default', negativePrompt: '', seed: 1.2}, ['a', 'b', 'c']), /安全整数/);
 assert.equal(await ai.pixAiImageMime(new Blob([pngBytes])), 'image/png');
 const avif = new Uint8Array(16);
 avif.set([0, 0, 0, 24, 102, 116, 121, 112, 97, 118, 105, 102]);
 assert.equal(await ai.pixAiImageMime(new Blob([avif])), 'image/avif');
 assert.equal(await ai.pixAiImageMime(new Blob(['not-an-image'])), null);
});

test('PixAI create rejection clears the local task and an unknown result keeps it', async () => {
 const restoreWindow = installWindow();
 const saved = structuredClone(store.getState());
 const notices = [];
 const recipe = {
  portrait: {原图: 'data:image/png;base64,iVBORw0KGgo='},
  costume: {原图: 'data:image/png;base64,iVBORw0KGgo='},
  pose: {原图: 'data:image/png;base64,iVBORw0KGgo=', source: 'upload'},
  extraImages: [{id: 'extra', url: 'data:image/png;base64,iVBORw0KGgo=', name: '附加'}],
 };
 store.configureStudio({api: async () => ({}), notice: message => notices.push(message), session: () => ({actor: 'a', csrf: 'c'}), csrf: () => 'c'});
 await flush();
 store.getState().hydrated = true;
 store.updateApiConfig({activeProvider: 'pixai', useProxy: false});
 store.updateProviderConfig('pixai', {apiKey: 'pixai-key', model: ai.PIXAI_MODEL});
 store.getState().recipe = recipe;
 const original = globalThis.fetch;
 const calls = [];
 const imageResponse = () => ({ok: true, status: 200, headers: new Headers({'content-type': 'image/png'}), blob: async () => new Blob([pngBytes], {type: 'image/png'})});
 let createStatus = 400;
 globalThis.fetch = async (url) => {
  const target = String(url);
  calls.push(target);
  if (target.startsWith('data:')) return imageResponse();
  if (target.endsWith('/v1/media/upload')) return {ok: true, status: 200, headers: new Headers(), json: async () => ({id: `media-${calls.length}`})};
  return {ok: false, status: createStatus, headers: new Headers(), text: async () => createStatus === 400 ? 'invalid prompt' : 'upstream down'};
 };
 try {
  await store.startGeneration('三图角色');
  await flush();
  assert.equal(calls.length, 0, 'extra references stop PixAI before any upload');
  assert.match(store.getState().generationError, /请先移除附加参考图/);
  store.getState().recipe = {...recipe, extraImages: []};
  store.getState().generationError = '';
  await store.startGeneration('三图角色');
  await flush();
  assert.equal(store.getState().pixaiTask, null);
  assert.match(notices.at(-1), /HTTP 400/);
  assert.ok(calls.some(url => url.endsWith('/v2/image/create')));
  assert.equal(calls.filter(url => url.includes('/v1/task/')).length, 0);

  calls.length = 0;
  createStatus = 500;
  await store.startGeneration('三图角色');
  await flush();
  assert.equal(store.getState().pixaiTask?.unknown, true);
  assert.equal(store.getState().pixaiTask?.task, null);
  assert.match(store.getState().generationError, /提交结果未知/);
  const blocked = notices.length;
  store.getState().generationError = '';
  await store.startGeneration('再次提交');
  await flush();
  assert.equal(notices.length, blocked + 1);
  assert.match(notices.at(-1), /存在待确认的 PixAI 任务/);
  assert.equal(store.getState().isGenerating, false);
  store.updateApiConfig({activeProvider: 'agy_auth'});
  store.getState().recipe = {portrait: null, costume: null, pose: null, extraImages: []};
  await store.startGeneration('其他通道仍可尝试');
  await flush();
  assert.match(store.getState().generationError, /至少 1 张参考图/);
  assert.doesNotMatch(notices.at(-1), /待确认的 PixAI/);
 } finally {
  globalThis.fetch = original;
  store.getState().pixaiTask = null;
  store.getState().isGenerating = false;
  store.getState().generationError = '';
  Object.assign(store.getState(), saved);
  restoreWindow();
 }
});

test('studio keeps the existing page and adds PixAI without removing other providers', async () => {
 const restoreWindow = installWindow();
 const root = doc.createElement('section');
 doc.body.append(root);
 const notices = [];
 const saved = structuredClone(store.getState());
 globalThis.confirm = () => true;
 const studio = createCharacterStudio(root, {
  api: async () => ({}),
  notice: message => notices.push(message),
  session: () => ({actor: 'a', csrf: 'c'}),
  navigate(){},
 });
 try {
  const buttons = () => [...root.querySelectorAll('button')];
  const byText = text => buttons().find(button => button.textContent === text);
  const selects = () => [...root.querySelectorAll('select')];
  const fidelitySelect = () => selects().find(select => select.options.length === 2 && [...select.options].every(option => option.value === 'high' || option.value === 'low'));
  await studio.load({mode: 'studio'});
  await flush();
  assert.equal(root.querySelector('h1').textContent, 'AI 角色合成台');
  assert.ok([...root.querySelectorAll('p')].some(node => /从人像颜值库、服装穿搭库、动作姿势库挑选参考/.test(node.textContent)));
  const providerSelect = selects().find(select => select.options.some(option => option.value === 'agy_auth'));
  assert.deepEqual(providerSelect.options.map(option => option.value), ai.PROVIDER_ORDER);
  providerSelect.value = 'gpt';
  await providerSelect.onchange();
  await flush();
  const model = () => selects().find(select => select.options.some(option => option.value === 'gpt-image-2.6-sunburst'));
  assert.equal(model().value, 'gpt-image-2.6-sunburst');
  assert.equal(fidelitySelect().disabled, true);
  assert.match(root.textContent, /当前模型使用默认参考还原度，无需设置此参数。/);
  model().value = 'gpt-image-1';
  await model().onchange();
  await flush();
  assert.equal(fidelitySelect().disabled, false);
  model().value = 'custom';
  await model().onchange();
  await flush();
  const custom = root.querySelector('[data-focus-key="custom-model"]');
  custom.value = 'gpt-image-1-mini';
  await custom.onchange();
  await flush();
  assert.equal(fidelitySelect().disabled, false);

  providerSelect.value = 'pixai';
  await providerSelect.onchange();
  await flush();
  assert.equal(store.getState().apiConfig.useProxy, true);
  assert.equal(byText('查看拼图').hidden, true);
  assert.match(root.textContent, /PixAI 三图/);
  assert.equal(root.querySelector('.cs-dropzone'), null);
  assert.equal(selects().some(select => [...select.options].some(option => option.value === 'base64' && option.textContent === 'Base64')), false);
  assert.match(root.textContent, /服务端 CORS 代理/);
  assert.match(selects().find(select => select.options.some(option => option.value === ai.PIXAI_MODEL)).textContent, /Tsubaki\.3/);
  const pasted = await doc.body.dispatch('paste', {clipboardData: {files: [{type: 'image/png', name: 'clip.png'}]}, target: doc.body});
  assert.equal(pasted.defaultPrevented, true);
  assert.match(notices.at(-1), /三张独立参考图/);
  assert.equal(store.getState().recipe.extraImages.length, 0);

  store.getState().pixaiTask = {provider: 'pixai', unknown: true, paused: true, task: null};
  store.updateApiConfig({});
  await flush();
  assert.match(root.textContent, /待确认 PixAI 任务/);
  assert.ok(byText('按编号恢复'));
  await byText('放弃记录').onclick();
  await flush();
  assert.equal(store.getState().pixaiTask, null);
  assert.equal(byText('放弃记录'), undefined);

  providerSelect.value = 'agy_auth';
  await providerSelect.onchange();
  await flush();
  assert.equal(byText('查看拼图').hidden, false);
  assert.ok(root.querySelector('.cs-dropzone'));
  await studio.load({mode: 'settings', hub: 'api', tab: 'image', provider: 'pixai'});
  await flush();
  const base = root.querySelector('[data-focus-key="set-base"]');
  assert.equal(base.disabled, true);
  assert.equal(base.value, 'https://api.pixai.art');
  assert.match(root.textContent, /首版只使用官方地址/);
  assert.match(root.textContent, /不使用 URL \/ Base64 传参/);
  const tabs = root.querySelectorAll('.cs-provider-tab');
  assert.deepEqual(tabs.map(tab => tab.dataset.groupId), ['google', 'xai', 'gpt', 'qwen', 'doubao', 'pixai', 'kling']);
 } finally {
  studio.suspend();
  root.remove();
  delete globalThis.confirm;
  Object.assign(store.getState(), saved);
  restoreWindow();
 }
});
