import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import {pathToFileURL} from 'node:url';

const require = createRequire(import.meta.url);
const {Document, Element} = require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.contains = function(node) {
  while (node) { if (node === this) return true; node = node.parentElement; }
  return false;
};

test('mode choices use declared purpose and required capabilities without starting work', async () => {
  globalThis.document = new Document('');
  const storage = new Map();
  globalThis.sessionStorage = {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  const root = document.createElement('section');
  document.body.append(root);
  const {createClassicProduction} = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-production.js'));
  const rows = [{id:'shot', parent_id:'group', title:'镜头'}];
  const model = (id, capabilities, enabled=true) => ({id, model_key:id, modality:'video', enabled, adapter_available:true, capabilities, default_params:{resolution:'720p'}});
  const models = [
    model('ordinary', {purposes:['reference_to_video']}),
    model('motion-good', {purposes:['motion_transfer'],reference_media:true,reference_video:true,max_duration_ms:15000}),
    model('motion-no-video', {purposes:['motion_transfer'],reference_media:true}),
    model('motion-wrong-purpose', {purposes:['image_to_video'],reference_media:true,reference_video:true}),
    model('motion-disabled', {purposes:['motion_transfer'],reference_media:true,reference_video:true}, false),
    model('avatar-good', {purposes:['digital_human'],reference_media:true,reference_audio:true,subject_mask:true}),
    model('avatar-no-audio', {purposes:['digital_human'],reference_media:true,subject_mask:true}),
    model('avatar-wrong-purpose', {purposes:['image_to_video'],reference_media:true,reference_audio:true,subject_mask:true}),
  ];
  const modes = {
    omni:{modality:'video',slots:{reference_image:'image',reference_video:'video',reference_audio:'audio'},purpose:'reference_to_video'},
    motion:{modality:'video',slots:{character:'image',motion_video:'video'},purpose:'motion_transfer',required_capabilities:['reference_media','reference_video']},
    digital_human:{modality:'video',slots:{portrait:'image',subject_mask:'image',speech:'audio'},purpose:'digital_human',required_capabilities:['reference_media','reference_audio','subject_mask']},
  };
  const writes = [];
  const api = async (url, init={}) => {
    if (init.method && init.method !== 'GET') { writes.push({url, method:init.method}); throw new Error('unexpected write'); }
    if (url.includes('section=shots')) return {scope:{kind:'shot',id:'shot'},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:rows}}};
    if (url.includes('/classic-production?')) return {shot:rows[0],sibling_shots:rows,revision:5,drafts:[],models,media:[],media_total:0,modes};
    if (url.includes('/working-selections?')) return {items:[],revision:5};
    return {items:[],total:0};
  };
  const ctx = {api,session:()=>({actor:'human',identityId:'human',writable:true,csrf:'x',revision:5}),setRevision(){},notice(){},navigate(){},media(){}};
  const app = createClassicProduction(root,ctx);
  const scope = {projectId:'p',objectId:'shot',productionKind:'video'};
  const choices = () => root.querySelector('.classic-model-choices').querySelectorAll('button').map(node=>node.dataset.modelId);
  const switchMode = async label => {const button=root.querySelector('.classic-modes').querySelectorAll('button').find(node=>node.textContent===label);assert.ok(button);await button.click();};
  try {
    await app.load({...scope,mode:'omni'});
    assert.deepEqual(choices(), ['', 'ordinary']);
    await switchMode('动作模仿');
    assert.deepEqual(choices(), ['', 'motion-good', 'motion-disabled']);
    const good = root.querySelector('.classic-model-choices').querySelectorAll('button').find(node=>node.dataset.modelId==='motion-good');
    await good.click();
    assert.equal(root.querySelector('.classic-model-choices').querySelectorAll('button').find(node=>node.dataset.modelId==='motion-good').getAttribute('aria-selected'),'true');
    assert.ok(root.textContent.includes('输出时长 ≤ 15s'));
    assert.ok(!root.textContent.includes('30s 内'));
    await switchMode('数字人');
    assert.deepEqual(choices(), ['', 'avatar-good']);
    assert.ok(root.textContent.includes('预览报价并确认识别'));
    assert.deepEqual(writes, []);
  } finally {
    app.suspend();
  }
});
