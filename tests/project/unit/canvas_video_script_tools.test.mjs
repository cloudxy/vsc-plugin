import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this._text = '';
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.style = {};
    this.dataset = {};
    this.parentElement = null;
    this.className = '';
    this.value = '';
    this.disabled = false;
    this.hidden = false;
    this.checked = false;
    this.title = '';
    this.type = '';
    this.placeholder = '';
    const self = this;
    this.classList = {
      add(...names) { self.className = [...new Set([...self.className.split(' '), ...names])].filter(Boolean).join(' '); },
      remove(...names) { self.className = self.className.split(' ').filter(name => !names.includes(name)).join(' '); },
      contains(name) { return self.className.split(' ').includes(name); },
      toggle(name, force) {
        const next = force == null ? !self.classList.contains(name) : Boolean(force);
        if (next) self.classList.add(name); else self.classList.remove(name);
        return next;
      },
    };
  }
  set textContent(value) { this._text = String(value ?? ''); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...nodes) {
    for (const node of nodes) {
      if (!node) continue;
      node.remove();
      node.parentElement = this;
      this.children.push(node);
    }
  }
  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
  replaceChildren(...nodes) {
    for (const child of [...this.children]) child.remove();
    this._text = '';
    this.append(...nodes);
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('[')) {
      const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      if (!match) return false;
      return match[2] == null ? this.attrs[match[1]] != null : this.attrs[match[1]] === match[2];
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const found = [];
    const walk = node => { for (const child of node.children) { found.push(child); walk(child); } };
    walk(this);
    return selector === '*' ? found : found.filter(node => node.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  async fire(type, properties = {}) {
    const event = {target: this, button: 0, preventDefault() {}, stopPropagation() {}, ...properties};
    for (const fn of [...(this.listeners[type] || [])]) await fn(event);
  }
}

const document = {
  createElement(tag) { return new Element(tag); },
  body: null,
};
document.body = document.createElement('body');
const tools = await loadModule('canvas-video-script-tools.js', {document});

function descendants(root) {
  const found = [];
  const walk = node => { for (const child of node.children || []) { found.push(child); walk(child); } };
  walk(root);
  return found;
}
function byText(root, text) {
  return descendants(root).find(node => node.textContent === text);
}
function host() {
  const root = document.createElement('div');
  const state = {document: {nodes: [], edges: []}, notices: [], calls: [], copied: ''};
  return {
    state,
    root,
    get document() { return state.document; },
    newId: () => `id-${state.document.nodes.length + state.document.edges.length + 1}`,
    notice(text) { state.notices.push(String(text)); },
    change(fn) { fn(); },
    async apply(operation, settings, nodeId) { state.calls.push({operation, settings, nodeId}); return {ready: true}; },
    async quote() { return {ready: true, total_price: 4, provider_called: false}; },
    async copyText(text) { state.copied = text; },
    async scriptDraft() { return {exists: true, content: {scenes: [{dialogue: [{text: '权威正文'}]}]}}; },
    openClip(node) { state.calls.push({operation: 'clip', nodeId: node.id}); },
    openMulti(node) { state.calls.push({operation: 'multi', nodeId: node.id}); },
  };
}

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

test('shell hooks and stylesheet are attached without rewriting the canvas module', () => {
  const shell = readFileSync(resolve(repo, 'src/vsc/interfaces/web/static/creative-canvas.js'), 'utf8');
  const html = readFileSync(resolve(repo, 'src/vsc/interfaces/web/templates/index.html'), 'utf8');
  assert.match(shell, /from '\.\/canvas-video-script-tools\.js'/);
  assert.match(shell, /routeVideoScriptAction\(op,videoScriptHost\(s\),node,panel\)/);
  assert.match(shell, /mountVideoScriptCard\(card,videoScriptHost\(s\),node\)/);
  assert.match(shell, /mountSampleBadge\(card,videoScriptHost\(s\),node\)/);
  assert.match(shell, /mountVideoScriptMenu\(tools,videoScriptHost\(s\),node,card\)/);
  assert.match(shell, /mountImageUpscaleButton\(processItems,videoScriptHost\(s\),node\)/);
  assert.match(shell, /mountEditCanvasExport\(row,videoScriptHost\(s\),node,/);
  assert.match(shell, /mountAiMvBrief\(empty,videoScriptHost\(s\)\)/);
  assert.match(html, /canvas-av-modes\.css"><link rel="stylesheet" href="\/static\/canvas-video-script-tools\.css"><link rel="stylesheet" href="\/static\/canvas-agent-stream\.css"/);
});

test('video menu, diagnostics, image upscale and sample badge', async () => {
  assert.deepEqual(tools.COPY.menu, ['区间剪辑', '多视频合成剪辑', '深度动作捕捉', '智能去字幕', '片段重拍', '视频高清', '智能拉片', '视频故事解析', '提取带时码剧本', '角色音色命名']);
  assert.equal(tools.mediaDiagnostic('crop_session_expired'), '裁剪会话已失效');
  assert.equal(tools.mediaDiagnostic('audio_decode_unsupported'), '当前浏览器不支持音频解码');
  assert.equal(tools.mediaDiagnostic('asset_voice_name', '林夏'), '林夏音色');
  const h = host();
  const card = document.createElement('article');
  const video = document.createElement('video');
  card.append(video);
  const menu = document.createElement('nav');
  const node = {id: 'vid-1', type: 'video', params: {media_diagnostic: 'video_size_read_failed', duration_seconds: 12}, x: 10, y: 20};
  tools.mountVideoScriptMenu(menu, h, node, card);
  for (const label of tools.COPY.menu) assert.ok(byText(menu, label), label);
  assert.equal(byText(card, '视频尺寸读取失败').className, 'cvst-media-diagnostic');
  await byText(menu, '区间剪辑').fire('click');
  await byText(menu, '视频故事解析').fire('click');
  assert.equal(h.state.calls[0].operation, 'clip');
  assert.equal(h.state.calls.at(-1).operation, 'video_story');
  await byText(menu, '角色音色命名').fire('click');
  const name = h.root.querySelector('input');
  name.value = '林夏';
  await byText(h.root, '确定').fire('click');
  assert.equal(node.params.role_voice_name, '林夏');
  assert.equal(h.state.notices.at(-1), '林夏音色');
  const imageParent = document.createElement('div');
  const image = {id: 'img-1', params: {image_spec: {count: 1, mime: 'image/gif', bytes: 10, width: 10, height: 10}}};
  tools.mountImageUpscaleButton(imageParent, h, image);
  await byText(imageParent, '高清放大').fire('click');
  const panel = h.root.querySelector('.cvst-image-upscale');
  assert.match(panel.textContent, /支持单张 JPEG\/PNG，最大 4\.7MB、4096×4096，宽高比为 1:3 至 3:1。/);
  for (const label of ['通用', '低清修复', '3D 动画', '高保真', '文字优化', '2x', '4x', '6x']) assert.ok(byText(panel, label), label);
  await byText(panel, '文字优化').fire('click');
  await byText(panel, '6x').fire('click');
  await byText(panel, '生成').fire('click');
  assert.equal(panel.querySelector('.cvst-report').textContent, '仅支持单张 JPEG 或 PNG');
  image.params.image_spec = {count: 1, mime: 'image/png', bytes: 20, width: 64, height: 64};
  await byText(panel, '生成').fire('click');
  assert.deepEqual(h.state.calls.at(-1), {operation: 'image_upscale', settings: {model_type: 'text_optimization', scale: 6}, nodeId: 'img-1'});
  assert.equal(tools.isSampleVideo({height: 480}), false);
  assert.equal(tools.isSampleVideo({resolution: '1080P', draft_task_id: 'keep', sample: true}), false);
  assert.equal(tools.isSampleVideo({resolution: '480p'}), true);
  const plain = document.createElement('article');
  assert.equal(tools.mountSampleBadge(plain, h, {type: 'video', params: {resolution: '1080P', draft_task_id: 'keep'}}), false);
  assert.equal(plain.children.length, 0);
  const sampleCard = document.createElement('article');
  const sample = {id: 'sample-1', type: 'video', params: {sample: true, draft_task_id: 'draft-9', created_at: '2026-11-19T00:00:00Z', duration_seconds: 2}};
  assert.equal(tools.mountSampleBadge(sampleCard, h, sample), true);
  assert.match(sampleCard.textContent, /样片 · 480P/);
  assert.match(sampleCard.textContent, /14天/);
  const upgrade = descendants(sampleCard).find(node => node.className === 'cvst-upgrade');
  await upgrade.fire('click');
  assert.equal(upgrade.textContent, '生成 1080P · ✦ 4');
  assert.equal(h.state.calls.at(-1).operation, 'sample_upgrade');
  assert.equal(h.state.calls.at(-1).settings.resolution, '1080P');
  assert.equal(h.state.calls.at(-1).settings.draft_task_id, 'draft-9');
});

test('remake, erase, depth and in-canvas export', async () => {
  const h = host();
  const node = {id: 'vid-2', params: {duration_seconds: 8}};
  tools.mountVideoScriptMenu(document.createElement('nav'), h, node, document.createElement('article'));
  const menu = document.createElement('nav');
  tools.mountVideoScriptMenu(menu, h, node, document.createElement('article'));
  await byText(menu, '片段重拍').fire('click');
  const remake = h.root.querySelector('.cvst-remake');
  await byText(remake, '添加 4 秒片段').fire('click');
  await byText(remake, '提交生成').fire('click');
  assert.match(remake.querySelector('.cvst-report').textContent, /时间标签与重拍片段不一致/);
  const prompt = remake.querySelector('textarea');
  prompt.value = '[00:00.000-00:04.000] 重拍开场';
  await prompt.fire('input');
  await byText(remake, '720P').fire('click');
  await byText(remake, '提交生成').fire('click');
  assert.equal(h.state.calls.at(-1).operation, 'video_segment_remake');
  assert.equal(h.state.calls.at(-1).settings.resolution, '720P');
  await byText(menu, '智能去字幕').fire('click');
  const erase = h.root.querySelector('.cvst-erase');
  assert.ok(byText(erase, '智能擦除') && byText(erase, '框选擦除') && byText(erase, '撤销') && byText(erase, '重做') && byText(erase, '重置'));
  for (let index = 0; index < 10; index += 1) await byText(erase, '框选').fire('click');
  assert.equal(erase.eraseSession.boxes.length, 10);
  await byText(erase, '框选').fire('click');
  assert.equal(h.state.notices.at(-1), '最多框选 10 个擦除区域');
  await byText(erase, '撤销').fire('click');
  assert.equal(erase.eraseSession.boxes.length, 9);
  await byText(erase, '重做').fire('click');
  assert.equal(erase.eraseSession.boxes.length, 10);
  await byText(erase, '重置').fire('click');
  assert.equal(erase.eraseSession.boxes.length, 0);
  const session = tools.createEraseSession();
  assert.throws(() => { for (let index = 0; index < 11; index += 1) session.push({x: 0, y: 0, w: 0.1, h: 0.1}); }, /最多框选 10 个擦除区域/);
  await byText(menu, '深度动作捕捉').fire('click');
  const depth = h.root.querySelector('.canvas-video-depth-panel');
  node.params.duration_seconds = 200;
  await byText(depth, '确认提取').fire('click');
  assert.equal(depth.querySelector('.cvst-report').textContent, '480P 最长支持 3 分钟');
  await byText(depth, '720p').fire('click');
  await byText(depth, '确认提取').fire('click');
  assert.equal(depth.querySelector('.cvst-report').textContent, '720P 最长支持 30 秒');
  node.params.duration_seconds = 8;
  await byText(depth, '480p').fire('click');
  await byText(depth, '确认提取').fire('click');
  assert.equal(h.state.calls.at(-1).operation, 'video_depth_map');
  const row = document.createElement('div');
  const edit = {id: 'edit-1', params: {}};
  tools.mountEditCanvasExport(row, h, edit, {videos: [], audios: []});
  await assert.rejects(() => byText(row, '导出').fire('click'), /当前轨道中没有可导出的视频片段/);
  tools.mountEditCanvasExport(row, h, edit, {videos: [{id: 'a', params: {}}, {id: 'b', params: {rightClipTime: 1.2}}], audios: [{id: 'bed'}, {id: 'extra'}]});
  await assert.rejects(() => descendants(row).filter(item => item.textContent === '导出').at(-1).fire('click'), /最多只能接入 1 条背景或参考音轨/);
  const clean = document.createElement('div');
  tools.mountEditCanvasExport(clean, h, {id: 'edit-2', params: {segments_json: JSON.stringify([{source_node_id: 'a', start_seconds: 0}, {source_node_id: 'b', start_seconds: 0.2, end_seconds: 1}])}}, {videos: [], audios: [{id: 'bed'}]});
  await byText(clean, '导出').fire('click');
  assert.equal(h.state.calls.at(-1).operation, 'multi_video_edit');
  assert.equal(h.state.calls.at(-1).settings.background_audio_node_id, 'bed');
  assert.equal(h.state.calls.at(-1).settings.segments.length, 2);
  assert.equal(tools.validateRemake({duration: 3, segments: [{start: 0, end: 4}], prompt: ''}).message, '仅支持不短于 4 秒的视频');
  assert.equal(tools.validateRemake({duration: 12, segments: [{start: 0, end: 5}, {start: 4, end: 8}], prompt: '[00:00.000-00:05.000][00:04.000-00:08.000]'}).message, '重拍片段之间不能重叠');
  assert.equal(tools.validateDepth({clarity: '720p', duration: 31}).message, '720P 最长支持 30 秒');
});

test('story table, lyrics, storyboard, script and readonly document', async () => {
  const h = host();
  const rows = [{shot: '01', range: '00:00.000-00:01.000', shot_size: '中景', angle: '平视', movement: '推进', focus: '35mm', light: '自然光', narrative: '建立', description: '红场', image_prompt: '红', motion_prompt: '推', voice: '无对白', music: '无音乐轨', keyframe: '00:00.500'}];
  const story = {id: 'story-1', x: 0, y: 0, text: JSON.stringify({rows}), params: {schema: 'video_story_node/v1', locked: true, canvas_subkind: 'video_story'}};
  const storyCard = document.createElement('article');
  assert.equal(tools.mountVideoScriptCard(storyCard, h, story), true);
  assert.deepEqual(descendants(storyCard).filter(node => node.tagName === 'TH').map(node => node.textContent), tools.STORY_COLUMNS.map(([, label]) => label));
  assert.equal(byText(storyCard, '重新解析'), undefined);
  await byText(storyCard, '复制机位').fire('click');
  assert.equal(h.state.copied, '平视');
  assert.equal(h.state.notices.at(-1), '复制成功');
  await byText(storyCard, '全屏查看').fire('click');
  assert.ok(h.root.querySelector('.cvst-story-fullscreen'));
  await byText(storyCard, '派生镜头节点').fire('click');
  assert.equal(h.document.nodes[0].title, '镜头 01');
  assert.equal(h.document.edges[0].port, 'derived_from');
  const lyrics = {id: 'ly-1', text: '第一句\n第二句', params: {schema: 'lyrics_timeline/v1', canvas_subkind: 'lyrics_timeline', source: 'ai_align', line_count: 2, duration_seconds: 8}};
  const lyricsCard = document.createElement('article');
  tools.mountVideoScriptCard(lyricsCard, h, lyrics);
  assert.match(lyricsCard.textContent, /共 2 行/);
  assert.match(lyricsCard.textContent, /时长 8/);
  assert.match(lyricsCard.textContent, /AI 音频对齐/);
  const editor = lyricsCard.querySelector('textarea');
  editor.value = '第一句\n';
  await assert.rejects(() => byText(lyricsCard, '保存').fire('click'), /歌词内容不能为空/);
  await byText(lyricsCard, '放大歌词时间线').fire('click');
  const dialog = h.root.querySelector('.cvst-lyrics-dialog');
  const area = dialog.querySelector('textarea');
  area.value = '第一句\n改过的第二句';
  await area.fire('input');
  await byText(dialog, '关闭').fire('click');
  assert.match(dialog.textContent, /请先保存或取消歌词编辑后再关闭/);
  await byText(dialog, '取消').fire('click');
  assert.equal(dialog.parentElement, null);
  assert.equal(tools.lyricsSourceBadge('lrc'), 'LRC 导入');
  assert.equal(tools.validateLyrics('').message, '歌词内容不能为空');
  const badBoard = {id: 'board-bad', text: '{"shots":[{"text":" "}]}', params: {schema: 'lyrics_storyboard_result'}};
  const badCard = document.createElement('article');
  tools.mountVideoScriptCard(badCard, h, badBoard);
  assert.equal(badCard.querySelector('.canvas-lyrics-storyboard-content').textContent.includes('歌词分镜格式异常'), true);
  const board = {id: 'board-1', x: 0, y: 0, text: JSON.stringify({shots: [{index: 1, instrumental: true}, {index: 2, text: '副歌'}]}), params: {canvas_subkind: 'lyrics_storyboard'}};
  const boardCard = document.createElement('article');
  tools.mountVideoScriptCard(boardCard, h, board);
  assert.match(boardCard.textContent, /共 2 个镜头/);
  assert.match(boardCard.textContent, /镜头 1 纯音乐段/);
  assert.match(boardCard.textContent, /镜头 2 副歌/);
  await byText(boardCard, '铺开视频生成器').fire('click');
  assert.equal(h.document.nodes.at(-1).title, '镜头 2');
  const script = {id: 'script-1', text: '', params: {canvas_subkind: 'script_generator'}};
  const scriptCard = document.createElement('article');
  tools.mountVideoScriptCard(scriptCard, h, script);
  assert.match(scriptCard.textContent, /暂无脚本镜头/);
  for (const label of ['剧本生成分镜脚本', '角色生成分镜脚本', '视频参考生成分镜脚本', '创意视图', '脚本视图', '全部显示', '全部隐藏']) assert.ok(byText(scriptCard, label), label);
  const field = scriptCard.querySelector('textarea');
  field.value = '';
  await field.fire('input');
  await byText(scriptCard, '视频参考生成分镜脚本').fire('click');
  assert.match(scriptCard.querySelector('.cvst-script-status').textContent, /暂无脚本镜头/);
  field.value = '角色甲、角色乙';
  await field.fire('input');
  await byText(scriptCard, '角色生成分镜脚本').fire('click');
  assert.equal(h.state.calls.at(-1).settings.starter, 'characters');
  assert.match(scriptCard.textContent, /角色甲 的镜头/);
  await byText(scriptCard, '脚本视图').fire('click');
  assert.equal(scriptCard.querySelector('.cvst-script').classList.contains('cvst-view-script'), true);
  await byText(scriptCard, '全部隐藏').fire('click');
  assert.equal(field.hidden, true);
  await byText(scriptCard, '全部显示').fire('click');
  assert.equal(field.hidden, false);
  const docNode = {id: 'doc-1', text: '节点预览节选\n节选', params: {canvas_subkind: 'script_document', scope_key: ''}};
  const docCard = document.createElement('article');
  tools.mountVideoScriptCard(docCard, h, docNode);
  const docEditor = docCard.querySelector('textarea');
  docEditor.value = '画布上改过的字';
  await docEditor.fire('change');
  assert.equal(docNode.text, '画布上改过的字');
  assert.equal(h.state.calls.some(call => call.operation === 'script_document_bind'), false);
  await byText(docCard, '查看剧本资料').fire('click');
  const viewer = h.root.querySelector('.cvst-script-dialog');
  assert.match(viewer.textContent, /不会改写剧本资料/);
  assert.match(viewer.textContent, /权威正文/);
  const guide = document.createElement('div');
  tools.mountAiMvBrief(guide, h);
  const form = guide.querySelector('form');
  await byText(form, '保存 Brief').fire('click');
  assert.equal(form.querySelector('.cvst-report').textContent, '请先接入一段音乐');
  form.querySelector('[aria-label="音乐"]').value = 'music-1';
  form.querySelector('[aria-label="参考图"]').value = 'i1,i2,i3,i4,i5';
  await byText(form, '保存 Brief').fire('click');
  assert.equal(form.querySelector('.cvst-report').textContent, '参考图最多 4 张');
  form.querySelector('[aria-label="参考图"]').value = 'i1,i2';
  await byText(form, '保存 Brief').fire('click');
  assert.equal(h.document.nodes.at(-1).params.canvas_subkind, 'mv_brief');
  assert.equal(h.state.calls.at(-1).operation, 'mv_brief');
  assert.equal(h.state.calls.at(-1).settings.mv_type, 'mixed');
  assert.equal(tools.validateImageSpec({count: 2, mime: 'image/png', bytes: 1, width: 8, height: 8}).message, '仅支持单张 JPEG 或 PNG');
  assert.equal(tools.validateImageSpec({count: 1, mime: 'image/png', bytes: 4.7 * 1024 * 1024 + 1, width: 8, height: 8}).message, '图片不能超过 4.7MB');
  assert.equal(tools.validateImageSpec({count: 1, mime: 'image/jpeg', bytes: 10, width: 5000, height: 1000}).message, '图片宽高不能超过 4096');
  assert.equal(tools.validateImageSpec({count: 1, mime: 'image/png', bytes: 10, width: 100, height: 400}).message, '宽高比须在 1:3 至 3:1 之间');
  assert.equal(tools.sampleDeadline('2026-10-27T00:00:00Z').days, 7);
  assert.equal(tools.sampleDeadline('2026-10-28T02:00:00Z').days, 14);
});
