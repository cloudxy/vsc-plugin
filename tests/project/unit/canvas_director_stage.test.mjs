import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  ASPECTS, BODY_PRESETS, CAMERA_PRESETS, COPY, JOINT_AXES, LIGHT_TYPES, PALETTE, POSE_PRESETS, PRIMITIVES, SHORTCUT_GROUPS,
  addCameraFromView, applyDirectorStageTypes, applyIdentityColors, applyRecognition, autoFrame, clampCrowd, clampFov,
  defaultPreview, defaultStage, ensureDirectorStageDocuments, groupObjects, hexToRgb, hslToHex, identitySignature,
  linkedImageBlocked, markIdentityStale, parseStage, planPreviewEdit, projectPoint, referenceFrameCount,
  referenceVideoConstraints, rgbToHsl, selectedCharactersSyncHint, setLookAt, stableStringify, syncDirectorStagePanorama,
  syncSelectedCharacters, ungroupObjects,
} from '../../../src/vsc/interfaces/web/static/canvas-director-stage.js';

test('catalogs match the director stage contract', () => {
  assert.equal(BODY_PRESETS.length, 8);
  assert.equal(BODY_PRESETS[0].id, 'male_basic');
  assert.equal(BODY_PRESETS[0].label, '男性素体');
  assert.equal(POSE_PRESETS.length, 21);
  assert.equal(PRIMITIVES.map(item => item[0]).join(','), 'cube,sphere,cylinder,cone,pyramid,torus');
  assert.equal(CAMERA_PRESETS.length, 14);
  assert.equal(CAMERA_PRESETS[1].id, 'front_medium');
  assert.equal(CAMERA_PRESETS.find(item => item.id === 'dutch').label, '荷兰角');
  assert.equal(JOINT_AXES.length, 25);
  assert.deepEqual(JOINT_AXES.slice(0, 3), ['body_bend', 'body_tilt', 'body_turn']);
  assert.deepEqual(LIGHT_TYPES.map(item => item[0]), ['directional', 'point', 'spot']);
  assert.equal(PALETTE[0], '#829BB5');
  assert.equal(PALETTE.length, 12);
  assert.deepEqual(SHORTCUT_GROUPS.map(group => group.label), ['创作', '移动画布', '缩放', '其他']);
  assert.ok(ASPECTS.includes('16:9'));
});

test('new node types keep a single visible director label', () => {
  const types = {director: {label: '导演台', ports: {prompt: 'text'}}, spatial: {label: '三维预演', ports: {}}};
  const ports = {};
  applyDirectorStageTypes(types, ports);
  assert.equal(types['director-stage'].label, '导演台');
  assert.deepEqual(types['director-stage'].ports, {panorama_image: 'image'});
  assert.equal(types['3d-preview'].label, '3D预演');
  assert.deepEqual(types['3d-preview'].ports, {});
  assert.equal(types.director.label, '站位导演台');
  assert.equal(ports.panorama_image, '全景图');
  assert.equal(ports.directorStageCapture, '导演台截图');
});

test('empty documents seed and panorama edges sync without rewriting a stable sphere', () => {
  const document = {nodes: [
    {id: 'stage-1', type: 'director-stage', text: ''},
    {id: 'preview-1', type: '3d-preview', text: ''},
    {id: 'img-1', type: 'image', title: '球幕', media_id: 'media-1'},
  ], edges: []};
  ensureDirectorStageDocuments(document);
  const stage = parseStage(document.nodes[0].text);
  const preview = JSON.parse(document.nodes[1].text);
  assert.equal(stage.schemaVersion, 1);
  assert.equal(stage.cameras[0].id, 'cam-front-medium');
  assert.equal(stage.cameras[0].fov, 50);
  assert.equal(stage.panorama.radius, 60);
  assert.equal(preview.documentRef.schemaVersion, 1);
  assert.equal(preview.timelineSummary.durationSeconds, 15);
  assert.equal(preview.timelineSummary.shotCount, 1);
  const seeded = document.nodes[0].text;
  syncDirectorStagePanorama(document);
  assert.equal(document.nodes[0].text, seeded);
  document.edges.push({id: 'edge-1', source: 'img-1', target: 'stage-1', port: 'panorama_image'});
  syncDirectorStagePanorama(document);
  const linked = parseStage(document.nodes[0].text);
  assert.equal(linked.panorama.sourceType, 'linked');
  assert.equal(linked.panorama.linkedNodeId, 'img-1');
  assert.equal(linked.panorama.origin, 'linked');
  assert.equal(linked.panorama.radius, 60);
  document.edges.pop();
  syncDirectorStagePanorama(document);
  const cleared = parseStage(document.nodes[0].text);
  assert.equal(cleared.panorama.sourceType, 'none');
  assert.equal(cleared.panorama.radius, 60);
  assert.equal(cleared.panorama.rotationY, 0);
});

test('projectPoint keeps a point in front of the camera', () => {
  const view = {position: [0, 1.5, 4], look: [0, 1.2, 0], fov: 50};
  const projected = projectPoint([0, 1.2, 0], view, 960, 540);
  assert.ok(projected);
  assert.ok(projected.depth > 0.05);
  assert.ok(projected.x > 400 && projected.x < 560);
  assert.equal(projectPoint([0, 1.5, 8], view, 960, 540), null);
});

test('object tree grouping, character sync and identity colors', () => {
  const stage = defaultStage();
  stage.objects.push(
    {id: 'a', kind: 'character', name: '甲', color: '#111111', pose: 'stand', joints: {}, transform: {position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1]}, opacity: 1, semanticRole: 'character'},
    {id: 'b', kind: 'character', name: '乙', color: '#222222', pose: 'stand', joints: {}, transform: {position: [1, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1]}, opacity: 1, semanticRole: 'character'},
  );
  assert.throws(() => groupObjects(stage, ['a'], 'group-1'));
  groupObjects(stage, ['a', 'b'], 'group-1');
  assert.equal(stage.objects[0].groupId, 'group-1');
  assert.equal(stage.groups[0].id, 'group-1');
  const synced = syncSelectedCharacters(stage, ['a', 'b'], {pose: 'wave', color: '#7FB2FF'});
  assert.equal(synced.hint, '已选中 2 个角色，修改将同步应用到全部选中对象');
  assert.equal(selectedCharactersSyncHint(2), synced.hint);
  assert.equal(stage.objects[1].pose, 'wave');
  stage.cameras[0].screenshots = [{id: 'rec-1', mediaId: 'shot-1', label: '当前视角1', mode: 'current'}];
  const before = JSON.stringify(stage.cameras[0].screenshots);
  const applied = applyIdentityColors(stage);
  assert.equal(applied.message, COPY.identity_applied);
  assert.equal(JSON.stringify(stage.cameras[0].screenshots), before);
  assert.equal(stage.objects[0].identity.markerColor, PALETTE[0]);
  assert.equal(stage.objects[0].identity.colorCode, '01');
  assert.equal(stage.identityStale, false);
  stage.objects.push({id: 'c', kind: 'prop', name: '道具', semanticRole: 'prop'});
  markIdentityStale(stage);
  assert.equal(stage.identityStale, true);
  assert.equal(identitySignature(stage).includes('c:prop'), true);
  ungroupObjects(stage, 'group-1');
  assert.equal(stage.objects[0].groupId, null);
  assert.equal(stage.groups.length, 0);
});

test('crowd, framing, look-at and camera from the current view', () => {
  assert.deepEqual(clampCrowd(0, 99, 0.1), {rows: 1, columns: 40, spacing: 0.2});
  assert.equal(clampFov(10), 15);
  assert.equal(clampFov(120), 90);
  const stage = defaultStage();
  stage.objects.push(
    {id: 'hero', kind: 'character', name: '主角', visible: true, transform: {position: [0, 0, 0]}, semanticRole: 'character'},
    {id: 'extra', kind: 'prop', name: '遮挡', visible: true, transform: {position: [0, 0, 1.2]}, semanticRole: 'prop'},
  );
  const camera = autoFrame(stage, 'cam-front-medium', ['hero'], ['extra'], 'subject');
  assert.deepEqual(camera.framing.subjectIds, ['hero']);
  assert.equal(camera.framing.scope, 'subject');
  assert.equal(camera.lookAtTargetId, 'hero');
  setLookAt(camera, 'point', null, [1, 2, 3]);
  assert.equal(camera.lookAtTargetId, null);
  assert.deepEqual(camera.lookAtPoint, [1, 2, 3]);
  const added = addCameraFromView(stage);
  assert.equal(added, COPY.camera_added_from_current_view);
  assert.equal(stage.cameras.length, 2);
});

test('recognition strategies and linked panorama rejection', () => {
  const stage = defaultStage();
  stage.objects.push({id: 'light-1', kind: 'light', name: '太阳光'});
  stage.panorama.origin = 'upload';
  const recognized = {objects: [{id: 'recog-a', kind: 'character', name: '识图角色A'}], cameras: [{id: 'recog-cam', preset: 'front_medium', name: '识图机位'}]};
  applyRecognition(stage, recognized, 'insert');
  assert.equal(stage.objects.some(item => item.id === 'light-1'), true);
  assert.equal(stage.panorama.origin, 'upload');
  applyRecognition(stage, recognized, 'insert');
  assert.equal(stage.objects.some(item => item.id === 'recog-a-x'), true);
  const replaced = defaultStage();
  replaced.objects.push({id: 'light-1', kind: 'light', name: '太阳光'}, {id: 'old', kind: 'prop', name: '旧道具'});
  applyRecognition(replaced, recognized, 'replace');
  assert.equal(replaced.objects.some(item => item.kind === 'light'), true);
  assert.equal(replaced.objects.some(item => item.id === 'old'), false);
  assert.equal(replaced.panorama.sourceType, 'none');
  const document = {nodes: [{id: 'stage-1', type: 'director-stage'}], edges: [{target: 'stage-1', source: 'img-1', port: 'panorama_image'}]};
  assert.equal(linkedImageBlocked(document, 'stage-1', 'img-1'), COPY.linked_image_ai_import_unsupported);
  assert.equal(linkedImageBlocked(document, 'stage-1', 'img-2'), null);
});

test('preview edits, color conversion and reference video limits', () => {
  const preview = defaultPreview('preview-1');
  planPreviewEdit(preview, '添加一个女角色', false);
  assert.equal(preview.stage.objects.at(-1).variant, 'female_low_poly');
  assert.equal(preview.documentRef.revision, 2);
  planPreviewEdit(preview, '加一盏太阳光', false);
  assert.equal(preview.stage.objects.at(-1).lightType, 'directional');
  planPreviewEdit(preview, '再加聚光', false);
  assert.equal(preview.stage.objects.at(-1).lightType, 'spot');
  planPreviewEdit(preview, '点光源', false);
  assert.equal(preview.stage.objects.at(-1).lightType, 'point');
  const before = preview.stage.objects.length;
  planPreviewEdit(preview, '删除最后一个', false);
  assert.equal(preview.stage.objects.length, before - 1);
  assert.deepEqual(hexToRgb('#829BB5'), {r: 130, g: 155, b: 181});
  const hsl = rgbToHsl(130, 155, 181);
  assert.match(hslToHex(hsl.h, hsl.s, hsl.l), /^#[0-9A-F]{6}$/);
  assert.equal(hslToHex(0, 0, 0), '#000000');
  assert.deepEqual(referenceVideoConstraints({durationSeconds: 1, width: 640, height: 360, fps: 24, sizeBytes: 1000}), []);
  assert.deepEqual(referenceVideoConstraints({durationSeconds: 16, width: 1000, height: 100, fps: 30, sizeBytes: 9 * 1024 * 1024}), ['duration', 'edge', 'fps', 'size']);
  assert.equal(referenceFrameCount(1), 24);
  assert.throws(() => referenceFrameCount(16));
  assert.equal(stableStringify({b: 1, a: true}).includes('"a":true'), true);
});
