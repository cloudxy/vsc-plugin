import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  AUDIO_GENERATION_MODES,
  VIDEO_GENERATION_MODES,
  avQuoteFields,
  joinStyles,
  klingAudioBlocked,
  lyricsEnabled,
  mountAvAudioTools,
  mountAvGeneratorModes,
  mountAvVideoFrameTools,
  speedInRange,
  splitStyles,
} from '../../../src/vsc/interfaces/web/static/canvas-av-modes.js';

class FakeElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.listeners = {};
    this.className = '';
    this.value = '';
    this.disabled = false;
    this.title = '';
    this.placeholder = '';
    this.type = '';
    this.parentElement = null;
    this.style = {};
    this.classList = {
      contains: name => this.className.split(' ').includes(name),
    };
  }
  set textContent(value) { this._text = String(value ?? ''); }
  get textContent() { return (this._text || '') + this.children.map(child => child.textContent).join(''); }
  append(...nodes) {
    for (const node of nodes) {
      node.remove?.();
      node.parentElement = this;
      this.children.push(node);
    }
  }
  insertBefore(node, before) {
    node.remove?.();
    node.parentElement = this;
    const index = this.children.indexOf(before);
    this.children.splice(index < 0 ? this.children.length : index, 0, node);
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
  replaceChildren(...nodes) {
    for (const child of [...this.children]) child.remove();
    this._text = '';
    this.append(...nodes);
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('[')) {
      const match = selector.match(/^\[([^\=\]]+)(?:="([^"]*)")?\]$/);
      if (!match) return false;
      const name = match[1];
      const key = name.startsWith('data-') ? name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase()) : name;
      const value = name.startsWith('data-') ? (this.dataset[key] ?? this.attrs[name]) : this.attrs[name];
      return match[2] == null ? value != null : String(value) === match[2];
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const found = [];
    const walk = node => {
      for (const child of node.children || []) {
        found.push(child);
        walk(child);
      }
    };
    walk(this);
    return found.filter(node => node.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) {
      if (selector.split(',').some(part => node.matches?.(part.trim()))) return node;
    }
    return null;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type) {
    const event = {target: this, stopPropagation() {}};
    for (const fn of this.listeners[type] || []) fn(event);
  }
}

function documentFor() {
  const document = {
    createElement(tag) {
      const node = new FakeElement(tag);
      node.ownerDocument = document;
      return node;
    },
  };
  return document;
}

function hostFor(state, remount) {
  const calls = [];
  return {
    calls,
    live: () => true,
    save: async () => true,
    change(_state, fn) { fn(); remount?.(); },
    draw() { remount?.(); },
    notice(_state, text) { calls.push({notice: text}); },
    markEdited() { calls.push({edited: true}); },
    checkpoint() {},
    remember() {},
    revision() {},
    setVersion() {},
    cleanDocument: doc => doc,
    url: () => '/canvas',
    projectBase: () => '/project',
    api: async path => {
      calls.push({api: path});
      return {builtin: [], custom: [{id: 'mine-1', name: '我的推镜', prompt_fragment: '向前', favorite: true}], revision: 1};
    },
    auxiliaryWrite: async (_state, slot, path, payload) => {
      calls.push({slot, path, payload});
      return {canvas_revision: 2, revision: 4, node_ids: ['made-1']};
    },
  };
}

function videoEff() {
  return {
    durations: [4, 5, 8, 10],
    duration: 5,
    resolutions: ['480P', '720P', '1080P'],
    resolution: '720P',
    ratios: ['16:9', '9:16'],
    ratio: '16:9',
    spec: {modality: 'video', generate_audio: true, model_key: 'doubao-seedance-2-5'},
    activeModel: {modelKey: 'doubao-seedance-2-5'},
  };
}

test('mode lists, styles, speed bounds and quote fields', () => {
  assert.deepEqual(VIDEO_GENERATION_MODES.map(mode => mode.label), ['文生视频', '首尾帧', '全能参考', '多图参考', '音频生视频', '视频编辑']);
  assert.deepEqual(AUDIO_GENERATION_MODES.map(mode => mode.label), ['描述生成', '歌词生成', '视觉参考配乐']);
  assert.equal(joinStyles(['摇滚', '流行', '不存在']), '流行,摇滚');
  assert.deepEqual(splitStyles('电子,流行,电子'), ['流行', '电子']);
  assert.equal(speedInRange(0.1), true);
  assert.equal(speedInRange(4), true);
  assert.equal(speedInRange(4.1), false);
  assert.equal(lyricsEnabled('soundtrack'), false);
  const node = {id: 'a', type: 'audio', params: {vsc_audio_mode: 'lyrics', vsc_audio_lyrics: '明月', vsc_audio_lyrics_b: '故乡', vsc_audio_voice: 'zh_female_vv_uranus_bigtts', vsc_audio_style: '古风', vsc_gen_duration: 30, vsc_seed_sample_rate: 24000, vsc_seed_format: 'mp3'}};
  const fields = avQuoteFields(node);
  assert.equal(fields.op_type, 'audio_generate');
  assert.equal(fields.audio_mode, 'lyrics');
  assert.equal(fields.lyrics_chars, 4);
  assert.equal(fields.music_style, '古风');
  assert.equal(fields.duration, 30);
  assert.equal(fields.seed_sample_rate, 24000);
  const video = {id: 'v', type: 'video', params: {vsc_operation: 'text_video', vsc_gen_duration: 8, vsc_gen_resolution: '1080P', vsc_gen_ratio: '16:9', vsc_gen_generate_audio: true, vsc_camera_motion_id: 'builtin-push-in'}};
  assert.equal(avQuoteFields(video).camera_motion_id, 'builtin-push-in');
  assert.equal(avQuoteFields(video).duration, 8);
  assert.equal(klingAudioBlocked({id: 'v'}, [{target: 'v', port: 'reference_video'}], 'kling-o3'), true);
  assert.equal(klingAudioBlocked({id: 'v'}, [], 'kling-o3'), false);
});

test('video mode slot switches operation and converges duration', () => {
  const doc = documentFor();
  const inspector = doc.createElement('div');
  const bottom = doc.createElement('div');
  bottom.className = 'cgc-bottom-bar';
  const slot = doc.createElement('div');
  slot.className = 'cgc-mode-slot';
  inspector.append(bottom);
  bottom.append(slot);
  const node = {id: 'v', type: 'video', params: {vsc_gen_duration: 5, vsc_gen_generate_audio: true}};
  const state = {document: {edges: []}, _cav: {open: '', cameraTab: 'square'}};
  const mount = () => {
    slot.replaceChildren();
    mountAvGeneratorModes({root: slot, node, eff: videoEff(), state, host});
  };
  const host = hostFor(state, mount);
  mount();
  assert.equal(slot.querySelector('[aria-label="视频生成模式"]') != null, true);
  assert.equal(slot.querySelector('[aria-label="视频时长"]').value, '5');
  assert.equal(slot.querySelector('[aria-label="分辨率"]').value, '720P');
  assert.equal(slot.querySelector('[aria-label="比例"]').value, '16:9');
  slot.querySelector('[data-mode="head_tail_video"]').fire('click');
  assert.equal(node.params.vsc_operation, 'head_tail_video');
  assert.equal(slot.querySelector('[data-mode="head_tail_video"]').getAttribute('aria-pressed'), 'true');
  slot.querySelector('[aria-label="视频时长"]').value = '10';
  slot.querySelector('[aria-label="视频时长"]').fire('change');
  assert.equal(node.params.vsc_gen_duration, 10);
  slot.querySelector('[aria-label="运镜"]').fire('click');
  return Promise.resolve().then(() => new Promise(resolve => setTimeout(resolve, 0))).then(() => {
    assert.equal(slot.querySelector('[aria-label="运镜库"]') != null, true);
    assert.match(slot.textContent, /推进镜头/);
    slot.querySelector('[data-camera-tab="favorites"]').fire('click');
    assert.match(slot.textContent, /我的推镜/);
    slot.querySelector('[data-motion-id="mine-1"]').fire('click');
    assert.equal(node.params.vsc_camera_motion_id, 'mine-1');
    assert.equal(node.params.vsc_camera_motion_prompt, '向前');
  });
});

test('kling reference video disables generated audio', () => {
  const doc = documentFor();
  const slot = doc.createElement('div');
  const toggle = doc.createElement('button');
  toggle.className = 'cgc-audio-toggle';
  slot.append(toggle);
  const node = {id: 'v', type: 'video', params: {vsc_gen_model_id: 'kling-o3', vsc_gen_generate_audio: true}};
  const state = {document: {edges: [{target: 'v', port: 'reference_video'}]}};
  mountAvGeneratorModes({root: slot, node, eff: {spec: {generate_audio: true, model_key: 'kling-o3'}, activeModel: {modelKey: 'kling-o3'}, durations: [5], duration: 5, resolutions: ['720P'], resolution: '720P', ratios: ['16:9'], ratio: '16:9'}, state, host: hostFor(state)});
  assert.equal(toggle.disabled, true);
  assert.equal(toggle.title, '可灵 O3 有参考视频时不支持生成音频');
});

test('audio modes show lyrics columns, soundtrack hint and seed settings', () => {
  const doc = documentFor();
  const inspector = doc.createElement('div');
  const prompt = doc.createElement('textarea');
  prompt.setAttribute('aria-label', '文本或提示词');
  const bottom = doc.createElement('div');
  bottom.className = 'cgc-bottom-bar';
  const slot = doc.createElement('div');
  inspector.append(prompt, bottom);
  bottom.append(slot);
  const node = {id: 'a', type: 'audio', params: {vsc_audio_mode: 'lyrics', vsc_gen_duration: 15, vsc_audio_lyrics: '一', vsc_audio_lyrics_b: '二'}};
  const state = {document: {edges: []}, _cav: {open: 'seed', cameraTab: 'square'}};
  const mount = () => {
    slot.replaceChildren();
    mountAvGeneratorModes({root: slot, node, eff: {spec: {modality: 'audio'}}, state, host});
  };
  const host = hostFor(state, mount);
  mount();
  assert.equal(slot.querySelector('[data-mode="歌词生成"]') == null, true);
  assert.equal(slot.querySelector('[data-mode="lyrics"]').textContent, '歌词生成');
  const lyrics = inspector.querySelectorAll('textarea').filter(node => node.getAttribute('aria-label') === '请输入歌词' || node.getAttribute('aria-label') === '副歌');
  assert.equal(lyrics.length, 2);
  lyrics[0].value = '明月';
  lyrics[0].fire('input');
  assert.equal(node.params.vsc_audio_lyrics, '明月');
  assert.equal(host.calls.some(call => call.edited), true);
  inspector.querySelector('[data-style="古风"]').fire('click');
  assert.equal(node.params.vsc_audio_style, '古风');
  assert.equal(slot.querySelector('[aria-label="采样率"]').value, '24000');
  slot.querySelector('[aria-label="采样率"]').value = '48000';
  slot.querySelector('[aria-label="采样率"]').fire('change');
  assert.equal(node.params.vsc_seed_sample_rate, 48000);
  slot.querySelector('[data-mode="soundtrack"]').fire('click');
  assert.equal(node.params.vsc_audio_mode, 'soundtrack');
  assert.match(inspector.textContent, /不支持歌词和自定义人声/);
  assert.equal(inspector.querySelector('[aria-label="请输入歌词"]'), null);
  assert.equal(slot.querySelector('[aria-label="音色"]').disabled, true);
  assert.equal(prompt.placeholder, '描述想要的配乐风格（可选）');
  assert.equal(avQuoteFields(node).audio_mode, 'soundtrack');
  assert.equal(avQuoteFields(node).lyrics_chars, undefined);
});

test('audio clip and video frame tools call local derive endpoints', async () => {
  const doc = documentFor();
  const card = doc.createElement('article');
  card.className = 'cc-node';
  const video = doc.createElement('video');
  video.currentTime = 1.25;
  const tools = doc.createElement('nav');
  card.append(video, tools);
  const audioNode = {id: 'aud', type: 'audio', params: {}};
  const videoNode = {id: 'vid', type: 'video', params: {}};
  const state = {version: 3, revision: 1, document: {nodes: [audioNode], edges: []}, selected: new Set(['aud'])};
  const host = hostFor(state);
  host.api = async path => {
    host.calls.push({api: path});
    return {document: {nodes: [...state.document.nodes, {id: 'made-1', type: 'audio', title: '新音频', x: 1, y: 1, text: '', params: {}, media_id: 'm', job_id: null}], edges: [{id: 'e1', source: 'aud', target: 'made-1', port: 'derived_from'}]}, revision: 4};
  };
  mountAvAudioTools(state, audioNode, card, host);
  card.querySelector('[aria-label="开始时间（秒）"]').value = '0.4';
  card.querySelector('[aria-label="结束时间（秒）"]').value = '1.2';
  card.querySelectorAll('button').find(button => button.textContent === '生成截取音频').fire('click');
  for (let step = 0; step < 8; step += 1) await Promise.resolve();
  const clip = host.calls.find(call => call.path === '/canvas/process-audio');
  assert.equal(clip.payload.operation, 'clip');
  assert.equal(clip.payload.start_seconds, 0.4);
  assert.equal(clip.payload.end_seconds, 1.2);
  assert.equal(state.document.nodes.some(node => node.id === 'made-1'), true);
  assert.equal(state.document.edges.some(edge => edge.port === 'derived_from'), true);

  const speedHost = hostFor(state);
  speedHost.api = async () => ({document: {nodes: state.document.nodes, edges: state.document.edges}, revision: 5});
  const speedCard = doc.createElement('div');
  mountAvAudioTools(state, audioNode, speedCard, speedHost);
  speedCard.querySelector('[aria-label="输入变速倍率"]').value = '9';
  speedCard.querySelectorAll('button').find(button => button.textContent === '确认变速').fire('click');
  assert.equal(speedHost.calls.some(call => call.notice === '变速倍率须在 0.1x–4.0x'), true);

  const frameHost = hostFor({...state, document: {nodes: [videoNode], edges: []}});
  frameHost.api = async () => ({document: {nodes: [videoNode, {id: 'made-1', type: 'image'}], edges: [{id: 'e2', source: 'vid', target: 'made-1', port: 'derived_from'}]}, revision: 6});
  mountAvVideoFrameTools(state, videoNode, tools, frameHost);
  tools.querySelector('[data-frame="current"]').fire('click');
  for (let step = 0; step < 8; step += 1) await Promise.resolve();
  const frame = frameHost.calls.find(call => String(call.path).endsWith('/capture-frame'));
  assert.equal(frame.payload.frame, 'current');
  assert.equal(frame.payload.time_seconds, 1.25);
  const bare = doc.createElement('nav');
  const bareHost = hostFor(state);
  mountAvVideoFrameTools(state, videoNode, bare, bareHost);
  bare.querySelector('[data-frame="current"]').fire('click');
  assert.equal(bareHost.calls.some(call => call.notice === '请先播放或定位视频后再截取当前帧'), true);
});
