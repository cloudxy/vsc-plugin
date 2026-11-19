import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

const port = await loadModule('canvas-port-layer-group.js', {crypto, window: {addEventListener() {}, removeEventListener() {}}, document: {createElement() { return {style: {}, classList: {add() {}, remove() {}}, append() {}, setAttribute() {}}; }, createElementNS() { return {style: {}, dataset: {}, classList: {add() {}}, setAttribute() {}, addEventListener() {}}; }}});
const cards = await loadModule('canvas-node-cards.js', {crypto, window: {addEventListener() {}, removeEventListener() {}}, document: {createElementNS() { return {setAttribute() {}, append() {}}; }}});

const node = (id, type, extra = {}) => ({id, type, title: extra.title || id, x: extra.x || 0, y: extra.y || 0, text: '', params: extra.params || {}, media_id: extra.media_id ?? null, job_id: null, group: extra.group || ''});

test('upload, lrc and api copy match the reference strings', async () => {
  assert.equal(port.API_ERRORS.video_format_not_supported, '仅支持上传 MP4、MOV 格式视频');
  assert.equal(port.API_ERRORS.lrc_empty, 'LRC 文件内容为空');
  assert.equal(port.API_ERRORS.lrc_invalid, '未找到有效的歌词时间标签');
  assert.equal(port.API_ERRORS.untitled_canvas, '未命名画布');
  assert.equal(port.API_ERRORS.collaboration_credential_invalid, '协作连接凭据无效');
  assert.equal(port.API_ERRORS.empty_response, '接口返回数据为空');
  assert.equal(port.API_ERRORS.run_record_missing, '运行记录不存在');
  assert.equal(port.API_ERRORS.fixed_reference_edge_not_deletable, '固定引用连线不可删除');
  assert.equal(port.validateVideoFile({name: 'take.mp4', type: 'video/mp4'}).ok, true);
  assert.equal(port.validateVideoFile({name: 'take.webm', type: 'video/webm'}).ok, false);
  assert.equal(port.validateVideoFile({name: 'still.png', type: 'image/png'}).ok, true);
  assert.equal(port.validateLrcText('').code, 'lrc_empty');
  assert.equal(port.validateLrcText('plain words').code, 'lrc_invalid');
  assert.equal(port.validateLrcText('[00:01.20] 雨夜').ok, true);
  const notices = [];
  const files = [{name: 'a.png', type: 'image/png'}, {name: 'b.webm', type: 'video/webm'}, {name: 'c.mov', type: 'video/quicktime'}, {name: 'd.lrc', type: 'text/plain', text: async () => ''}, {name: 'e.lrc', type: 'text/plain', text: async () => '[00:02] 一句'}];
  const prepared = await port.prepareCanvasUploadFiles(files, message => notices.push(message));
  assert.deepEqual(prepared.map(file => file.name), ['a.png', 'c.mov', 'e.lrc']);
  assert.ok(notices.includes(port.API_ERRORS.video_format_not_supported));
  assert.ok(notices.includes(port.API_ERRORS.lrc_empty));
  const limited = port.limitUploadFiles(Array.from({length: 22}, (_, index) => ({name: String(index)})), 20);
  assert.equal(limited.files.length, 20);
  assert.match(limited.message, /单次最多上传 20 个文件，已仅处理前 20 个/);
  assert.equal(port.canvasApiErrorText('run_record_missing'), port.API_ERRORS.run_record_missing);
  assert.equal(port.readApiError({}), port.API_ERRORS.empty_response);
  assert.equal(port.submitChord({metaKey: true, key: 'Enter'}), true);
  assert.equal(port.submitChord({ctrlKey: true, shiftKey: true, key: 'Enter'}), false);
});

test('asset payloads, group layout and workflow projection stay explicit', () => {
  const created = port.buildProjectAssetPayload({name: '林夏', kind: 'character', mediaId: 'media-1'});
  assert.equal(created.base_revision, 0);
  assert.equal(created.forms[0].base_version_id, null);
  assert.equal(created.forms[0].media_id, 'media-1');
  assert.equal(created.asset_id, undefined);
  const updated = port.buildProjectAssetPayload({name: '林夏', kind: 'location', mediaId: 'media-1', assetId: 'asset-1', baseRevision: 3, formVersionId: 'form-1'});
  assert.equal(updated.asset_id, 'asset-1');
  assert.equal(updated.base_revision, 3);
  assert.equal(port.buildBlockingPayload({mediaId: 'media-1'}).message, 'BU 站位单元须属于真实场次');
  const blocking = port.buildBlockingPayload({sceneId: 'scene-1', episodeId: 'ep-1', mediaId: 'media-1', document: {objects: []}});
  assert.equal(blocking.payload.mode, 'blocking');
  assert.equal(blocking.payload.document.panorama_media_id, 'media-1');
  const frame = node('frame', 'text', {group: '分组 1', params: {canvas_subkind: 'group_frame'}});
  const a = node('a', 'image', {x: 10, y: 0, group: '分组 1', media_id: 'm'});
  const b = node('b', 'image', {x: 400, y: 20, group: '分组 1', media_id: 'n'});
  const document = {nodes: [frame, a, b, node('other', 'text', {group: '别的'})], edges: [{id: 'e1', source: 'frame', target: 'a', port: 'prompt'}, {id: 'e2', source: 'a', target: 'b', port: 'reference'}]};
  const opened = port.ungroupDocument(document, 'frame');
  assert.equal(opened.document.nodes.some(item => item.id === 'frame'), false);
  assert.equal(opened.document.nodes.find(item => item.id === 'a').group, '');
  assert.equal(opened.document.nodes.find(item => item.id === 'other').group, '别的');
  assert.equal(opened.document.edges.some(edge => edge.source === 'frame'), false);
  const row = port.arrangeMembers([a, b], 'vertical', {x: 40, y: 80});
  assert.equal(row[0].x, 40);
  assert.ok(row[1].y > row[0].y);
  const pretty = port.beautifyMembers([a, b], {x: 41, y: 83});
  assert.equal(pretty[0].x % 20, 0);
  assert.equal(pretty[0].y % 20, 0);
  const active = port.projectWorkflows([
    {id: 's1', jobs: []},
    {id: 's2', jobs: [{id: 'job', status: 'created'}], needs_approval: true},
    {id: 's3', jobs: [{id: 'run', status: 'running'}]},
    {id: 's4', jobs: [{id: 'done', status: 'succeeded'}]},
  ], ['s3']);
  assert.deepEqual(active.map(item => item.status), ['waiting_dependency', 'waiting_auth']);
  assert.equal(active[1].current_step + '/' + active[1].total_steps, '2/4');
  const summary = port.summarizeAgentProgress({assets: [{asset_kind: 'character'}, {record_kind: 'blocking', asset_kind: 'blocking'}], artifacts: [{title: '分集候选', approved: true}], episodes: [{kind: 'episode'}, {kind: 'episode'}]});
  assert.deepEqual(summary.lines, ['统一资产 1', '分集候选已保存 1/2', '已发布资产 1']);
  assert.deepEqual([...port.CONTEXT_MENU_ITEMS], ['撤销', '重做', '复制', '创建副本', '粘贴', '删除', '聚焦视口', '从此参考生成']);
  assert.equal(port.SAVE_ASSET_SUCCESS, '已保存到资产库');
  assert.equal(port.referencePortFor(node('img', 'image'), 'image'), 'reference');
  assert.equal(port.referencePortFor(node('vid', 'video'), 'video'), 'reference_video');
});

test('fixed reference metadata blocks edge deletion and batch move notices the source', () => {
  const down = node('d', 'image', {params: {fixed_reference: JSON.stringify({edge_ids: ['keep']})}});
  const doc = {nodes: [node('s', 'image'), down], edges: [{id: 'keep', source: 's', target: 'd', port: 'reference'}]};
  assert.equal(cards.isFixedReferenceEdge(doc.edges[0], doc), true);
  assert.equal(cards.removeEdge(doc, 'keep').ok, false);
  assert.equal(cards.removeEdge(doc, 'keep').message, '固定引用连线不可删除');
  const listed = node('d2', 'image', {params: {fixed_reference: 'edge-a,edge-b'}});
  assert.equal(cards.isFixedReferenceEdge({id: 'edge-b', source: 's', target: 'd2', port: 'reference'}, {nodes: [node('s', 'image'), listed], edges: []}), true);
  assert.equal(cards.isFixedReferenceEdge({id: 'other', source: 's', target: 'd', port: 'reference'}, {nodes: [node('s', 'image', {params: {fixed_reference: '*'}}), down], edges: []}), false);
});
