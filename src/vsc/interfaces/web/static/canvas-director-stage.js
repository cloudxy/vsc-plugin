/** In-canvas director stage and 3D preview. Documents stay on the node text. */

export const COPY = {
  node_locked_by_other: '节点正在被其他协作者编辑',
  readonly_save_screenshot: '只读模式下无法保存截图',
  readonly_save_stage: '只读模式下无法保存导演台',
  linked_image_ai_import_unsupported: '已连接图片暂不支持直接识图，请重新上传本地图片',
  identity_colors_stale: '场景已变化，请重新应用身份配色。',
  identity_applied: '身份配色已应用，请重新截图用于下游。',
  framing_occluded: '核心对象仍有遮挡，请检查场景或手动调整机位。',
  model_uploading_placeholder: '模型上传中… 已本地导入占位模型',
  selected_characters_sync_hint: '已选中 {count} 个角色，修改将同步应用到全部选中对象',
  camera_added_from_current_view: '已按当前视角添加机位',
  four_screenshot_nodes_created: '已创建四方位截图节点',
  twelve_screenshot_nodes_created: '已创建十二方位截图节点',
  panorama_uploaded_connected: '全景图已上传并连接到导演台',
  panorama_generated_connected: '720°全景图已生成并连接到导演台',
  history_panorama_connected: '历史全景图已连接到导演台',
  edit_conflict: '场景已有新版本。请先放弃本地修改并加载最新版本，再编辑。',
  discard_edits: '放弃修改并加载最新版本',
  send_to_canvas: '发送到画布',
  to_canvas: '去画布生成',
  webgl_unavailable: '3D 预演无法加载',
  clear_color: '清除颜色',
  pick_screen_color: '吸取屏幕颜色',
  recommended_colors: '推荐颜色',
  unsaved_leave: '场景修改尚未保存，确定放弃并关闭？',
  strategy_insert: '作为站位参考层插入，不覆盖当前全景、角色和机位',
  strategy_replace: '作为站位参考层插入，覆盖当前全景、角色和机位',
  open_director: '打开导演台',
  open_preview: '打开 3D 预演',
  director_description: '在3D空间中搭建场景并进行多视角截图',
  preview_description: '3D 场景预演节点',
};

export const PALETTE = ['#829BB5','#C49A7C','#98AA87','#AF91B2','#BF8585','#7FAAA5','#C4B276','#8D91B8','#B18E9F','#91AEBB','#A5AA73','#A18B79'];
export const BODY_PRESETS = [
  {id:'male_basic', label:'男性素体', color:'#7FB2FF'},
  {id:'female_low_poly', label:'女性素体', color:'#FF8FB5'},
  {id:'generous', label:'宽厚素体', color:'#F0A35C'},
  {id:'robust', label:'健壮素体', color:'#F25F5C'},
  {id:'slender', label:'纤细素体', color:'#72D6C9'},
  {id:'young', label:'少年素体', color:'#8DD36F'},
  {id:'children', label:'儿童素体', color:'#FFD166'},
  {id:'two_heads_tall', label:'二头身', color:'#B28DFF'},
];
export const POSE_PRESETS = [
  ['stand','站立'],['walk','行走'],['run','奔跑'],['sit','坐姿'],['crouch','蹲姿'],['kneel_single','单膝跪'],
  ['kneel_double','双膝跪'],['combat','格斗架势'],['arms_crossed','抱臂'],['hands_on_hips','叉腰'],['wave','招手'],
  ['reach','伸手抓取'],['lean','倚靠'],['look_phone','低头看手机'],['think','托腮思考'],['bow','鞠躬'],
  ['push','推搡'],['kick','踢腿'],['throw','投掷'],['t_pose','T-Pose 校准'],['arms_up','举手'],
];
export const PRIMITIVES = [['cube','立方体'],['sphere','球体'],['cylinder','圆柱体'],['cone','圆锥'],['pyramid','棱锥'],['torus','环状体']];
export const CAMERA_PRESETS = [
  {id:'front_closeup', label:'正面特写', position:[0,1.55,1.8], look:[0,1.5,0], fov:35},
  {id:'front_medium', label:'正面中景', position:[0,1.5,4], look:[0,1.2,0], fov:50},
  {id:'front_wide', label:'正面全景', position:[0,1.8,7], look:[0,1,0], fov:60},
  {id:'back_medium', label:'背面中景', position:[0,1.5,-4], look:[0,1.2,0], fov:50},
  {id:'over_shoulder_l', label:'过肩镜头', position:[-0.8,1.55,-1.6], look:[0.4,1.3,1.2], fov:50},
  {id:'over_shoulder_r', label:'过肩镜头（右）', position:[0.8,1.55,-1.6], look:[-0.4,1.3,1.2], fov:50},
  {id:'side_close', label:'侧面近景', position:[2.2,1.45,0.4], look:[0,1.4,0], fov:50},
  {id:'side_tracking', label:'侧面跟拍', position:[4.2,1.3,1.2], look:[0,1.1,0], fov:50},
  {id:'low_angle', label:'低角度仰拍', position:[0.4,0.4,3.2], look:[0,1.5,0], fov:50},
  {id:'low_wide', label:'低角度广角', position:[1.2,0.35,4.5], look:[0,1.2,0], fov:50},
  {id:'top_45', label:'45° 俯拍', position:[3.2,4.4,3.6], look:[0,0.8,0], fov:50},
  {id:'top_wide', label:'俯拍全景', position:[0.2,7.2,5.4], look:[0,0.4,0], fov:50},
  {id:'birdseye', label:'鸟瞰', position:[0,9.5,0.4], look:[0,0,0], fov:50},
  {id:'dutch', label:'荷兰角', position:[1.4,1.4,3.2], look:[0,1.2,0], fov:50},
];
export const JOINT_AXES = [
  'body_bend','body_tilt','body_turn','head_nod','head_tilt','head_turn','torso_bend','torso_tilt','torso_turn',
  'left_shoulder_pitch','left_shoulder_roll','left_shoulder_yaw','right_shoulder_pitch','right_shoulder_roll','right_shoulder_yaw',
  'left_elbow','right_elbow','left_hip_pitch','left_hip_roll','left_hip_yaw','right_hip_pitch','right_hip_roll','right_hip_yaw',
  'left_knee','right_knee',
];
export const LIGHT_TYPES = [['directional','太阳光'],['point','点光源'],['spot','聚光灯']];
export const ASPECTS = ['16:9','9:16','1:1','4:3','21:9','2.35:1'];
export const SHORTCUT_GROUPS = [
  {id:'create', label:'创作', items:[['G','成组'],['⌥G','解组'],['⇧G','合并分镜组'],['L','连线'],['D','复制节点和连线'],['Enter','生成'],['Tab','新建节点'],['⌥拖动','复制']]},
  {id:'pan', label:'移动画布', items:[['Space+拖动','平移画布'],['双指滑动','平移画布'],['鼠标中键','平移画布']]},
  {id:'zoom', label:'缩放', items:[['0','适配画布'],['捏合','缩放'],['滚轮','缩放']]},
  {id:'other', label:'其他', items:[['⌘Z','撤销'],['⇧⌘Z','重做'],['⌫','删除']]},
];

const POSE_IDS = new Set(POSE_PRESETS.map(item => item[0]));
const PRIMITIVE_IDS = new Set(PRIMITIVES.map(item => item[0]));

export function applyDirectorStageTypes(types, ports){
  types['director-stage'] = {label:'导演台', ports:{panorama_image:'image'}, source:true};
  types['3d-preview'] = {label:'3D预演', ports:{}, source:true};
  if(types.director) types.director = {...types.director, label:'站位导演台'};
  if(ports){
    ports.panorama_image = '全景图';
    ports.directorStageCapture = '导演台截图';
  }
  return types;
}

export function stableStringify(value){
  if(value === null || value === undefined) return 'null';
  if(typeof value === 'boolean') return value ? 'true' : 'false';
  if(typeof value === 'number'){
    if(!Number.isFinite(value)) throw new Error('场景数值无效');
    if(Number.isInteger(value)) return value.toFixed(1);
    return JSON.stringify(value);
  }
  if(typeof value === 'string') return JSON.stringify(value);
  if(Array.isArray(value)) return '[' + value.map(item => stableStringify(item)).join(',') + ']';
  const keys = Object.keys(value).filter(key => value[key] !== undefined).sort();
  return '{' + keys.map(key => JSON.stringify(key) + ':' + stableStringify(value[key])).join(',') + '}';
}

function vec(value, fallback=[0,0,0]){
  const source = Array.isArray(value) && value.length === 3 ? value : fallback;
  return source.map(item => Number(item) || 0);
}

export function blankObject(kind, id, name){
  return {
    id, kind, name: name || kind, variant:'', pose:'stand', joints:{}, color:'#829BB5',
    transform:{position:[0,0,0], rotation:[0,0,0], scale:[1,1,1]},
    visible:true, locked:false, groupId:null, opacity:1, identity:null,
    primitive: kind === 'primitive' ? 'cube' : '', crowd: kind === 'crowd' ? {rows:3, columns:3, spacing:1} : null,
    lightType: kind === 'light' ? 'directional' : '', semanticRole:kind, refId:id, placeholder:'',
  };
}

function cameraFromPreset(preset, id){
  return {
    id, name:preset.label, preset:preset.id,
    transform:{position:vec(preset.position), rotation:[0,0,0], scale:[1,1,1]},
    fov:preset.fov, aspectRatio:'16:9', lookAtTargetId:null, lookAtPoint:vec(preset.look),
    screenshots:[], framing:null, roll:preset.id === 'dutch' ? 12 : 0,
  };
}

export function defaultStage(){
  return {
    schemaVersion:1,
    scene:{
      backgroundMode:'sky', gridVisible:true, groundVisible:true, skyColor:'#87CEEB',
      groundOpacity:1, groundHeight:0, unit:'m', sceneScale:1, sceneTranslation:[0,0,0], sceneRotation:[0,0,0],
    },
    viewport:{activeView:'director', directorView:{yaw:0.6, pitch:0.35, distance:12, target:[0,1,0]}},
    objects:[], groups:[], cameras:[cameraFromPreset(CAMERA_PRESETS[1], 'cam-front-medium')], selection:[],
    panorama:{sourceType:'none', mediaId:null, linkedNodeId:null, url:'', fileName:'', rotationY:0, radius:60, status:'idle', errorMessage:'', origin:'none'},
    capture:{guides:{thirds:false, safe:false}},
    ui:{snapToGrid:true, uniformScale:true},
    identityStale:false, identitySignature:'',
  };
}

export function defaultPreview(documentId){
  return {
    schemaVersion:1,
    documentRef:{documentId: documentId || 'preview', revision:1, schemaVersion:1},
    timelineSummary:{durationSeconds:15, shotCount:1},
    mode:'preview', playhead:0, stage:defaultStage(),
  };
}

export function parseStage(text){
  if(!text || typeof text !== 'string') return null;
  try{
    const value = JSON.parse(text);
    if(!value || value.schemaVersion !== 1 || !Array.isArray(value.objects) || !value.scene) return null;
    return value;
  }catch{ return null; }
}

export function parsePreview(text){
  if(!text || typeof text !== 'string') return null;
  try{
    const value = JSON.parse(text);
    if(!value || value.schemaVersion !== 1 || !value.documentRef || !value.stage) return null;
    return value;
  }catch{ return null; }
}

export function ensureDirectorStageDocuments(document){
  for(const node of document?.nodes || []){
    if(node.type === 'director-stage' && !String(node.text || '').trim()) node.text = stableStringify(defaultStage());
    if(node.type === '3d-preview' && !String(node.text || '').trim()) node.text = stableStringify(defaultPreview(node.id));
  }
  return document;
}

function samePanorama(left, right){
  const keys = ['sourceType','mediaId','linkedNodeId','url','fileName','rotationY','radius','status','errorMessage','origin'];
  return keys.every(key => left?.[key] === right?.[key]);
}

export function syncDirectorStagePanorama(document){
  const nodes = document?.nodes || [];
  const byId = Object.fromEntries(nodes.map(node => [node.id, node]));
  for(const node of nodes){
    if(node.type !== 'director-stage') continue;
    const stage = parseStage(node.text);
    if(!stage) continue;
    const edge = (document.edges || []).find(item => item.target === node.id && item.port === 'panorama_image');
    const source = edge ? byId[edge.source] : null;
    const next = {...stage.panorama};
    if(source && source.type === 'image'){
      next.sourceType = 'linked';
      next.linkedNodeId = source.id;
      next.mediaId = source.media_id || next.mediaId || null;
      next.fileName = source.title || next.fileName || '';
      next.status = source.media_id ? 'ready' : 'idle';
      if(!next.origin || next.origin === 'none' || next.origin === 'linked') next.origin = 'linked';
      next.radius = next.radius || 60;
    }else if(stage.panorama.sourceType === 'linked'){
      next.sourceType = 'none';
      next.mediaId = null;
      next.linkedNodeId = null;
      next.url = '';
      next.fileName = '';
      next.status = 'idle';
      next.errorMessage = '';
      next.origin = 'none';
    }else continue;
    if(samePanorama(stage.panorama, next)) continue;
    stage.panorama = next;
    node.text = stableStringify(stage);
  }
  return document;
}

export function projectPoint(point, view, width, height){
  const eye = vec(view.position, [0,1.5,4]);
  const look = vec(view.look, [0,1,0]);
  let fx = look[0] - eye[0], fy = look[1] - eye[1], fz = look[2] - eye[2];
  const fl = Math.hypot(fx, fy, fz) || 1;
  fx /= fl; fy /= fl; fz /= fl;
  let rx = -fz, ry = 0, rz = fx;
  const rl = Math.hypot(rx, ry, rz) || 1;
  rx /= rl; ry /= rl; rz /= rl;
  const ux = ry * fz - rz * fy, uy = rz * fx - rx * fz, uz = rx * fy - ry * fx;
  const dx = point[0] - eye[0], dy = point[1] - eye[1], dz = point[2] - eye[2];
  const camX = dx * rx + dy * ry + dz * rz;
  const camY = dx * ux + dy * uy + dz * uz;
  const camZ = dx * fx + dy * fy + dz * fz;
  if(camZ <= 0.05) return null;
  const fov = ((view.fov || 50) * Math.PI) / 180;
  const aspect = width / Math.max(1, height);
  const scale = 1 / Math.tan(fov / 2);
  const ndcX = (camX / camZ) * (scale / aspect);
  const ndcY = (camY / camZ) * scale;
  return {x:(ndcX * 0.5 + 0.5) * width, y:(1 - (ndcY * 0.5 + 0.5)) * height, depth:camZ};
}

export function activeView(stage){
  if(stage.viewport?.activeView && stage.viewport.activeView !== 'director'){
    const camera = (stage.cameras || []).find(item => item.id === stage.viewport.activeView);
    if(camera){
      const look = camera.lookAtTargetId
        ? (stage.objects.find(item => item.id === camera.lookAtTargetId)?.transform.position || camera.lookAtPoint || [0,1,0])
        : (camera.lookAtPoint || [0,1,0]);
      return {position:vec(camera.transform?.position), look:vec(look), fov:clampFov(camera.fov), roll:camera.roll || 0};
    }
  }
  const view = stage.viewport?.directorView || {yaw:0.6, pitch:0.35, distance:12, target:[0,1,0]};
  const target = vec(view.target, [0,1,0]);
  const yaw = Number(view.yaw) || 0, pitch = Number(view.pitch) || 0, distance = Number(view.distance) || 12;
  return {
    position:[
      target[0] + distance * Math.cos(pitch) * Math.sin(yaw),
      target[1] + distance * Math.sin(pitch),
      target[2] + distance * Math.cos(pitch) * Math.cos(yaw),
    ],
    look:target, fov:50, roll:0,
  };
}

export function clampFov(value){
  const number = Number(value);
  if(!Number.isFinite(number)) return 50;
  return Math.min(90, Math.max(15, number));
}

export function clampCrowd(rows, columns, spacing){
  const nextRows = Math.min(20, Math.max(1, Math.round(Number(rows) || 1)));
  const nextColumns = Math.min(40, Math.max(1, Math.round(Number(columns) || 1)));
  const nextSpacing = Math.min(5, Math.max(0.2, Number(spacing) || 0.2));
  return {rows:nextRows, columns:nextColumns, spacing:nextSpacing};
}

export function identitySignature(stage){
  return (stage.objects || []).filter(item => ['character','prop','primitive','crowd','uploaded_model'].includes(item.kind) && !String(item.semanticRole || '').startsWith('environment.')).map(item => item.id + ':' + item.kind).join('|');
}

export function markIdentityStale(stage){
  const signature = identitySignature(stage);
  if(stage.identitySignature && stage.identitySignature !== signature) stage.identityStale = true;
  return stage;
}

export function applyIdentityColors(stage){
  const before = JSON.stringify((stage.cameras || []).map(camera => camera.screenshots));
  const targets = (stage.objects || []).filter(item => ['character','prop','primitive','crowd','uploaded_model'].includes(item.kind) && !String(item.semanticRole || '').startsWith('environment.'));
  targets.forEach((item, index) => {
    const color = PALETTE[index % PALETTE.length];
    item.identity = {objectKey:item.id, refId:item.refId || item.id, semanticRole:item.semanticRole || item.kind, colorCode:String(index + 1).padStart(2, '0'), markerColor:color};
    item.color = color;
  });
  if(JSON.stringify((stage.cameras || []).map(camera => camera.screenshots)) !== before) throw new Error('身份配色不能改写已有截图');
  stage.identitySignature = identitySignature(stage);
  stage.identityStale = false;
  return {stage, message:COPY.identity_applied};
}

export function groupObjects(stage, objectIds, groupId){
  const picked = (stage.objects || []).filter(item => objectIds.includes(item.id));
  if(picked.length < 2) throw new Error('打组至少需要两个对象');
  if(!(stage.groups || []).some(group => group.id === groupId)) stage.groups.push({id:groupId, name:'分组'});
  for(const item of picked) item.groupId = groupId;
  return stage;
}

export function ungroupObjects(stage, groupId){
  for(const item of stage.objects || []) if(item.groupId === groupId) item.groupId = null;
  stage.groups = (stage.groups || []).filter(group => group.id !== groupId);
  return stage;
}

export function selectedCharactersSyncHint(count){
  return COPY.selected_characters_sync_hint.replace('{count}', String(count));
}

export function syncSelectedCharacters(stage, ids, patch){
  const targets = (stage.objects || []).filter(item => ids.includes(item.id) && item.kind === 'character');
  for(const item of targets){
    if(patch.pose && POSE_IDS.has(patch.pose)) item.pose = patch.pose;
    if(patch.color) item.color = patch.color;
    if(patch.variant && BODY_PRESETS.some(body => body.id === patch.variant)) item.variant = patch.variant;
    if(patch.joints) item.joints = {...item.joints, ...patch.joints};
    if(patch.transform) item.transform = {...item.transform, ...patch.transform};
    if(patch.opacity != null) item.opacity = Math.min(1, Math.max(0, Number(patch.opacity)));
  }
  return {count:targets.length, hint:selectedCharactersSyncHint(targets.length)};
}

function bounds(item){
  const position = vec(item.transform?.position);
  if(item.kind === 'crowd' && item.crowd){
    const width = Math.max(0, item.crowd.columns - 1) * item.crowd.spacing;
    const depth = Math.max(0, item.crowd.rows - 1) * item.crowd.spacing;
    return [position[0] - width / 2, position[1], position[2] - depth / 2, position[0] + width / 2, position[1] + 1.7, position[2] + depth / 2];
  }
  return [position[0] - 0.4, position[1], position[2] - 0.4, position[0] + 0.4, position[1] + 1.7, position[2] + 0.4];
}

export function autoFrame(stage, cameraId, subjectIds, contextIds, scope){
  if(!['subject','relationship','environment'].includes(scope)) throw new Error('取景范围无效');
  const byId = Object.fromEntries((stage.objects || []).map(item => [item.id, item]));
  const subjects = subjectIds.map(id => byId[id]).filter(item => item && item.visible !== false);
  if(!subjects.length) throw new Error('无法完成取景，请检查核心对象及模型加载状态。');
  const boxes = subjects.map(bounds);
  if(scope === 'relationship' || scope === 'environment'){
    for(const id of contextIds || []) if(byId[id] && byId[id].visible !== false) boxes.push(bounds(byId[id]));
  }
  const low = [0,1,2].map(index => Math.min(...boxes.map(box => box[index])));
  const high = [0,1,2].map(index => Math.max(...boxes.map(box => box[index + 3])));
  const center = [0,1,2].map(index => (low[index] + high[index]) / 2);
  const span = Math.max(...[0,1,2].map(index => high[index] - low[index])) || 1;
  const camera = (stage.cameras || []).find(item => item.id === cameraId);
  if(!camera) throw new Error('机位不存在');
  camera.transform.position = [center[0], center[1] + span * 0.35, center[2] + Math.max(2.5, span * 1.6)];
  camera.lookAtTargetId = subjectIds.length === 1 && scope === 'subject' ? subjectIds[0] : null;
  camera.lookAtPoint = camera.lookAtTargetId ? null : center;
  let blocked = false;
  for(const other of stage.objects || []){
    if(subjectIds.includes(other.id) || other.visible === false) continue;
    const box = bounds(other);
    const midZ = (camera.transform.position[2] + center[2]) / 2;
    if(box[0] <= center[0] && center[0] <= box[3] && box[2] <= midZ && midZ <= box[5] && box[1] < center[1] + 1.2) blocked = true;
  }
  camera.framing = {
    scope, subjectIds:[...subjectIds], contextIds:[...(contextIds || [])],
    status: blocked ? 'occluded' : 'ok',
    fingerprints: subjects.map(item => item.id + ':' + Number(item.transform.position[0]).toFixed(2)).join(','),
    warning: blocked ? COPY.framing_occluded : '',
  };
  return camera;
}

export function setLookAt(camera, mode, targetId, point){
  if(mode === 'target'){
    camera.lookAtTargetId = targetId || null;
    camera.lookAtPoint = null;
  }else{
    camera.lookAtTargetId = null;
    camera.lookAtPoint = vec(point || camera.lookAtPoint || [0,1,0]);
  }
  return camera;
}

export function addCameraFromView(stage){
  const view = activeView({...stage, viewport:{...stage.viewport, activeView:'director'}});
  const id = 'cam-view-' + ((stage.cameras || []).length + 1);
  stage.cameras.push({
    id, name:'当前视角', preset:'front_medium',
    transform:{position:view.position, rotation:[0,0,0], scale:[1,1,1]},
    fov:clampFov(view.fov || 50), aspectRatio:'16:9', lookAtTargetId:null, lookAtPoint:view.look,
    screenshots:[], framing:null, roll:0,
  });
  return COPY.camera_added_from_current_view;
}

export function linkedImageBlocked(document, stageId, imageNodeId){
  const stageNode = (document.nodes || []).find(node => node.id === stageId);
  const stage = parseStage(stageNode?.text || '');
  const linked = (document.edges || []).some(edge => edge.target === stageId && edge.port === 'panorama_image' && edge.source === imageNodeId);
  if(linked || stage?.panorama?.linkedNodeId === imageNodeId) return COPY.linked_image_ai_import_unsupported;
  return null;
}

export function applyRecognition(stage, recognized, strategy){
  const incomingObjects = recognized.objects || [];
  const incomingCameras = recognized.cameras || [];
  if(strategy === 'replace'){
    stage.objects = (stage.objects || []).filter(item => item.kind === 'light');
    if(incomingCameras.length) stage.cameras = incomingCameras;
    stage.panorama = defaultStage().panorama;
    stage.objects.push(...incomingObjects);
  }else if(strategy === 'insert'){
    const known = new Set((stage.objects || []).map(item => item.id));
    for(const item of incomingObjects){
      while(known.has(item.id)) item.id = (item.id + '-x').slice(0, 100);
      known.add(item.id);
      stage.objects.push(item);
    }
    const knownCameras = new Set((stage.cameras || []).map(item => item.id));
    for(const camera of incomingCameras){
      while(knownCameras.has(camera.id)) camera.id = (camera.id + '-x').slice(0, 100);
      knownCameras.add(camera.id);
      stage.cameras.push(camera);
    }
  }else throw new Error('识图策略仅支持插入或覆盖');
  markIdentityStale(stage);
  return stage;
}

export function planPreviewEdit(preview, text, hasImage=false){
  const stage = preview.stage;
  const message = String(text || '');
  if(!message.trim()) throw new Error('请输入场景修改说明');
  if(['删除','去掉','移除'].some(word => message.includes(word)) && stage.objects.length) stage.objects.pop();
  else if(['太阳','日光','方向光'].some(word => message.includes(word))) stage.objects.push({...blankObject('light', 'light-' + (stage.objects.length + 1), '太阳光'), lightType:'directional', transform:{position:[4,6,2], rotation:[0,0,0], scale:[1,1,1]}});
  else if(message.includes('聚光')) stage.objects.push({...blankObject('light', 'light-' + (stage.objects.length + 1), '聚光灯'), lightType:'spot', transform:{position:[0,3,2], rotation:[0,0,0], scale:[1,1,1]}});
  else if(['点光','灯泡','灯光'].some(word => message.includes(word))) stage.objects.push({...blankObject('light', 'light-' + (stage.objects.length + 1), '点光源'), lightType:'point', transform:{position:[1,2.2,1], rotation:[0,0,0], scale:[1,1,1]}});
  else if(['角色','人物','演员'].some(word => message.includes(word))){
    const person = blankObject('character', 'actor-' + (stage.objects.length + 1), '对话角色');
    person.variant = message.includes('女') ? 'female_low_poly' : 'male_basic';
    person.color = BODY_PRESETS.find(item => item.id === person.variant).color;
    person.transform.position = [stage.objects.length * 0.8, 0, 0];
    stage.objects.push(person);
  }else{
    const prop = blankObject('prop', 'prop-' + (stage.objects.length + 1), hasImage ? '参考道具' : (message.trim().slice(0, 24) || '道具'));
    prop.transform.position = [0, 0, stage.objects.length * 0.4];
    stage.objects.push(prop);
  }
  markIdentityStale(stage);
  preview.documentRef.revision = Number(preview.documentRef.revision || 1) + 1;
  return preview;
}

export function referenceVideoConstraints({durationSeconds, width, height, fps, sizeBytes}){
  const errors = [];
  if(!(durationSeconds > 0 && durationSeconds <= 15)) errors.push('duration');
  if(Math.max(width || 0, height || 0) > 960) errors.push('edge');
  if(Math.abs((fps || 0) - 24) > 0.2) errors.push('fps');
  if((sizeBytes || 0) > 8 * 1024 * 1024) errors.push('size');
  return errors;
}

export function referenceFrameCount(seconds){
  const frames = Math.round(Number(seconds) * 24);
  if(!Number.isFinite(frames) || frames < 1 || frames > 360) throw new Error('参考视频时长须大于 0 且不超过 15 秒');
  return frames;
}

export function hexToRgb(value){
  if(!/^#[0-9a-fA-F]{6}$/.test(String(value || ''))) throw new Error('颜色需要六位十六进制值');
  const number = parseInt(value.slice(1), 16);
  return {r:(number >> 16) & 255, g:(number >> 8) & 255, b:number & 255};
}

export function rgbToHsl(red, green, blue){
  const r = red / 255, g = green / 255, b = blue / 255;
  const high = Math.max(r, g, b), low = Math.min(r, g, b);
  const lightness = (high + low) / 2;
  let hue = 0, saturation = 0;
  if(high !== low){
    const delta = high - low;
    saturation = lightness > 0.5 ? delta / (2 - high - low) : delta / (high + low);
    if(high === r) hue = ((g - b) / delta) % 6;
    else if(high === g) hue = (b - r) / delta + 2;
    else hue = (r - g) / delta + 4;
    hue *= 60;
    if(hue < 0) hue += 360;
  }
  return {h:Math.round(hue * 100) / 100, s:Math.round(saturation * 10000) / 100, l:Math.round(lightness * 10000) / 100};
}

export function hslToHex(hue, saturation, lightness){
  const s = saturation / 100, l = lightness / 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const hp = ((hue % 360) + 360) % 360 / 60;
  const x = c * (1 - Math.abs(hp % 2 - 1));
  const channel = hp < 1 ? [c,x,0] : hp < 2 ? [x,c,0] : hp < 3 ? [0,c,x] : hp < 4 ? [0,x,c] : hp < 5 ? [x,0,c] : [c,0,x];
  const m = l - c / 2;
  const hex = channel.map(item => Math.round((item + m) * 255).toString(16).padStart(2, '0')).join('');
  return '#' + hex.toUpperCase();
}

export function mapSpatialScene(scene){
  const stage = defaultStage();
  const kindMap = {actor:'character', box:'primitive', sphere:'primitive', light:'light', mesh:'uploaded_model', reference:'prop'};
  stage.objects = (scene?.objects || []).slice(0, 80).map((item, index) => {
    const kind = kindMap[item.kind] || 'prop';
    const id = String(item.id || ('spatial-' + (index + 1))).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 100) || ('spatial-' + (index + 1));
    const object = blankObject(kind, id, item.name || kind);
    object.transform.position = vec(item.position);
    object.transform.scale = vec(item.scale, [1,1,1]);
    if(/^#[0-9a-fA-F]{6}$/.test(item.color || '')) object.color = item.color.toUpperCase();
    if(kind === 'character') object.variant = BODY_PRESETS.some(body => body.id === item.body) ? item.body : 'male_basic';
    if(kind === 'primitive') object.primitive = item.kind === 'sphere' ? 'sphere' : 'cube';
    if(kind === 'light') object.lightType = ['point','spot','directional'].includes(item.light_type) ? item.light_type : 'directional';
    return object;
  });
  return stage;
}

function el(tag, text, className){
  const node = document.createElement(tag);
  if(text != null) node.textContent = text;
  if(className) node.className = className;
  return node;
}

function button(label, fn){
  const node = el('button', label);
  node.type = 'button';
  node.addEventListener('click', event => { event.preventDefault(); Promise.resolve(fn()).catch(error => console.error(error)); });
  return node;
}

export function mountDirectorStageCard(host, node, card){
  if(!node || !['director-stage','3d-preview','director','spatial'].includes(node.type)) return;
  const preview = node.type === '3d-preview' || node.type === 'spatial';
  const control = host.button(preview ? COPY.open_preview : COPY.open_director, () => openFromCard(host, node));
  control.dataset.action = preview ? 'open-animation-preview' : 'open-director-stage';
  if(host.lockedByOther?.(node)){
    control.disabled = true;
    control.title = COPY.node_locked_by_other;
  }
  card.append(control);
}

export function mountDirectorStageInspector(host, node, inspector){
  if(!node || !['director-stage','3d-preview'].includes(node.type)) return false;
  const preview = node.type === '3d-preview';
  inspector.append(el('p', preview ? COPY.preview_description : COPY.director_description));
  const control = host.button(preview ? COPY.open_preview : COPY.open_director, () => openFromCard(host, node));
  control.dataset.action = preview ? 'open-animation-preview' : 'open-director-stage';
  if(host.lockedByOther?.(node)){ control.disabled = true; control.title = COPY.node_locked_by_other; }
  inspector.append(control);
  return true;
}

function openFromCard(host, node){
  if(host.lockedByOther?.(node)){ host.notice(COPY.node_locked_by_other); return; }
  if(node.type === '3d-preview') return openAnimationPreview(host, node);
  if(node.type === 'spatial') return openLegacySpatialPreview(host, node);
  if(node.type === 'director') return openLegacyDirectorStage(host, node);
  return openDirectorStage(host, node);
}

export function openLegacyDirectorStage(host, node){
  const parsed = parseStage(node.text);
  openDirectorStage(host, node, parsed || defaultStage(), true);
}

export function openLegacySpatialPreview(host, node){
  const parsed = parsePreview(node.text) || (parseStage(node.text) ? {...defaultPreview(node.id), stage:parseStage(node.text)} : null);
  openAnimationPreview(host, node, parsed, true);
  if(!parsed && node.domain_object_id && host.api){
    host.api(host.base() + '/spatial-scenes/' + encodeURIComponent(node.domain_object_id)).then(scene => {
      const mapped = mapSpatialScene(scene.document || scene);
      const preview = defaultPreview(node.id);
      preview.stage = mapped;
      const overlay = host.root?.querySelector?.('.cds-overlay');
      if(overlay?.session && overlay.session.node === node && !overlay.session.touched){
        overlay.session.preview = preview;
        overlay.session.stage = preview.stage;
        overlay.session.paint?.();
      }
    }).catch(() => host.notice(COPY.webgl_unavailable));
  }
}

export function openDirectorStage(host, node, seeded=null, legacy=false){
  const stage = seeded || parseStage(node.text) || defaultStage();
  openWorkbench(host, node, {kind:'director', stage, legacy});
}

export function openAnimationPreview(host, node, seeded=null, legacy=false){
  const preview = seeded || parsePreview(node.text) || defaultPreview(node.id);
  openWorkbench(host, node, {kind:'preview', stage:preview.stage, preview, legacy});
}

function writeBack(host, node, session){
  if(host.readOnly?.()){ host.notice(COPY.readonly_save_stage); return; }
  host.change(() => {
    if(session.kind === 'preview'){
      session.preview.stage = session.stage;
      node.text = stableStringify(session.preview);
    }else node.text = stableStringify(session.stage);
  });
}

async function postCanvas(host, path, payload){
  const result = await host.api(host.url() + path, {
    method:'POST', headers:host.headers(),
    body:JSON.stringify({payload:{...payload, canvas_id:host.state.id, canvas_revision:host.version(), node_id:payload.node_id}, expected_revision:host.revision(), idempotency_key:host.newId()}),
  });
  if(result?.revision != null) host.setRevision(result.revision);
  return result;
}

const WEBGL_VS = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.0,1.0);}';
const WEBGL_FS = 'precision mediump float;uniform vec4 c;void main(){gl_FragColor=c;}';

function webglKit(gl){
  if(!gl) return null;
  if(gl._cdsKit) return gl._cdsKit;
  const vertex = gl.createShader(gl.VERTEX_SHADER);
  gl.shaderSource(vertex, WEBGL_VS);
  gl.compileShader(vertex);
  const fragment = gl.createShader(gl.FRAGMENT_SHADER);
  gl.shaderSource(fragment, WEBGL_FS);
  gl.compileShader(fragment);
  if(!gl.getShaderParameter(vertex, gl.COMPILE_STATUS) || !gl.getShaderParameter(fragment, gl.COMPILE_STATUS)) return null;
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if(!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  const buffer = gl.createBuffer();
  gl._cdsKit = {program, buffer, location:gl.getAttribLocation(program, 'p'), color:gl.getUniformLocation(program, 'c')};
  return gl._cdsKit;
}

function shaderReady(gl){
  return Boolean(webglKit(gl));
}

function drawWebglQuad(gl, kit, x, y, w, h, width, height, rgba){
  const x0 = (x / width) * 2 - 1, y0 = 1 - (y / height) * 2;
  const x1 = ((x + w) / width) * 2 - 1, y1 = 1 - ((y + h) / height) * 2;
  const data = new Float32Array([x0, y0, x1, y0, x0, y1, x0, y1, x1, y0, x1, y1]);
  gl.useProgram(kit.program);
  gl.bindBuffer(gl.ARRAY_BUFFER, kit.buffer);
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(kit.location);
  gl.vertexAttribPointer(kit.location, 2, gl.FLOAT, false, 0, 0);
  gl.uniform4f(kit.color, rgba[0], rgba[1], rgba[2], rgba[3]);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
}

function scenePoint(stage, point){
  const scene = stage.scene || {};
  const scale = Number(scene.sceneScale || 1);
  const translation = vec(scene.sceneTranslation);
  const yaw = (vec(scene.sceneRotation)[1] || 0) * Math.PI / 180;
  const cos = Math.cos(yaw), sin = Math.sin(yaw);
  const x = point[0] * scale, y = point[1] * scale, z = point[2] * scale;
  return [x * cos - z * sin + translation[0], y + translation[1], x * sin + z * cos + translation[2]];
}

export function canUseWebGL(){
  if(typeof document === 'undefined' || !document.createElement) return false;
  const probe = document.createElement('canvas');
  const gl = probe.getContext?.('webgl') || probe.getContext?.('experimental-webgl');
  if(!gl) return false;
  return shaderReady(gl);
}

function paintScene(canvas, stage, view, guides){
  const width = canvas.width, height = canvas.height;
  const sky = stage.scene?.skyColor || '#87CEEB';
  const objects = (stage.objects || []).filter(item => item.visible !== false);
  const gl = canvas.dataset.renderer === 'webgl' ? (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')) : null;
  const kit = gl ? webglKit(gl) : null;
  if(gl && kit){
    const rgb = hexToRgb(sky);
    gl.viewport(0, 0, width, height);
    gl.clearColor(rgb.r / 255, rgb.g / 255, rgb.b / 255, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if(stage.scene?.groundVisible !== false){
      const alpha = Number(stage.scene.groundOpacity ?? 1);
      drawWebglQuad(gl, kit, 0, height * 0.62, width, height * 0.38, width, height, [0.43, 0.48, 0.41, alpha]);
    }
    if(stage.scene?.gridVisible !== false){
      for(let index = 1; index < 8; index++) drawWebglQuad(gl, kit, width * index / 8, height * 0.62, 1, height * 0.38, width, height, [1, 1, 1, 0.18]);
    }
  }
  const ctx = canvas.dataset.renderer === '2d' ? canvas.getContext('2d') : null;
  if(ctx){
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);
    if(stage.scene?.groundVisible !== false){
      ctx.globalAlpha = Number(stage.scene.groundOpacity ?? 1);
      ctx.fillStyle = '#6d7a68';
      ctx.fillRect(0, height * 0.62, width, height * 0.38);
      ctx.globalAlpha = 1;
    }
    if(stage.panorama?.sourceType && stage.panorama.sourceType !== 'none'){
      ctx.strokeStyle = 'rgba(255,255,255,.35)';
      ctx.beginPath();
      ctx.arc(width / 2, height * 0.42, Math.min(width, height) * 0.28, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  const drawList = [];
  for(const item of objects){
    const projected = projectPoint(scenePoint(stage, vec(item.transform.position)), view, width, height);
    if(!projected) continue;
    drawList.push({item, projected});
  }
  drawList.sort((a, b) => b.projected.depth - a.projected.depth);
  if(ctx){
    if(stage.scene?.gridVisible !== false){
      ctx.strokeStyle = 'rgba(255,255,255,.18)';
      for(let index = 1; index < 8; index++){
        ctx.beginPath(); ctx.moveTo(width * index / 8, height * 0.62); ctx.lineTo(width * index / 8, height); ctx.stroke();
      }
    }
    for(const row of drawList){
      ctx.globalAlpha = Number(row.item.opacity ?? 1);
      ctx.fillStyle = row.item.color || '#829BB5';
      const size = 18 + 80 / Math.max(1, row.projected.depth);
      ctx.fillRect(row.projected.x - size / 2, row.projected.y - size, size, size * 1.4);
      ctx.globalAlpha = 1;
    }
    if(guides?.thirds){
      ctx.strokeStyle = 'rgba(255,255,255,.45)';
      ctx.strokeRect(width / 3, height / 3, width / 3, height / 3);
    }
    if(guides?.safe){
      ctx.strokeStyle = 'rgba(255,220,120,.7)';
      ctx.strokeRect(width * 0.1, height * 0.1, width * 0.8, height * 0.8);
    }
  }else if(gl && kit){
    for(const row of drawList){
      const rgb = hexToRgb(row.item.color || '#829BB5');
      const size = 18 + 80 / Math.max(1, row.projected.depth);
      drawWebglQuad(gl, kit, row.projected.x - size / 2, row.projected.y - size, size, size * 1.4, width, height, [rgb.r / 255, rgb.g / 255, rgb.b / 255, Number(row.item.opacity ?? 1)]);
    }
    if(guides?.thirds) drawWebglQuad(gl, kit, width / 3, height / 3, width / 3, 1, width, height, [1, 1, 1, 0.45]);
    if(guides?.safe) drawWebglQuad(gl, kit, width * 0.1, height * 0.1, width * 0.8, 1, width, height, [1, 0.86, 0.47, 0.7]);
  }
  return drawList;
}

function ensureRenderer(canvas){
  if(canvas.dataset.renderer) return;
  if(canUseWebGL()){
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if(gl && webglKit(gl)){ canvas.dataset.renderer = 'webgl'; return; }
  }
  canvas.getContext('2d');
  canvas.dataset.renderer = '2d';
}

function openWorkbench(host, node, session){
  const root = host.root || document.body;
  root.querySelector('.cds-overlay')?.remove();
  const overlay = el('div', null, 'cds-overlay');
  overlay.dataset.kind = session.kind;
  session.node = node;
  session.touched = false;
  session.tool = 'move';
  session.query = '';
  session.overlay = overlay;
  const bar = el('div', null, 'cds-bar');
  const title = el('h2', session.kind === 'preview' ? '3D预演' : '导演台');
  const close = button('关闭', () => { clearInterval(session.timer); overlay.remove(); });
  close.dataset.action = session.kind === 'preview' ? 'open-animation-preview' : 'open-director-stage';
  bar.append(title, el('span', null, 'cds-spacer'), button('快捷键', () => toggleKeys(session)), close);
  const body = el('div', null, 'cds-body');
  const side = el('aside', null, 'cds-side');
  const viewport = el('div', null, 'cds-viewport');
  const canvas = el('canvas');
  canvas.width = 960; canvas.height = 540;
  viewport.append(canvas);
  const inspector = el('aside', null, 'cds-inspector');
  body.append(side, viewport, inspector);
  overlay.append(bar, body);
  root.append(overlay);
  overlay.session = session;
  session.paint = () => paintPanels(host, session, side, inspector, canvas);
  bindViewport(host, session, canvas);
  session.paint();
}

function toggleKeys(session){
  session.showKeys = !session.showKeys;
  session.paint();
}

function bindViewport(host, session, canvas){
  let draft = null;
  canvas.addEventListener('pointerdown', event => {
    const hit = hitTest(canvas, session.stage, event);
    if(!hit || hit.locked) return;
    draft = {id:hit.id, x:event.clientX, y:event.clientY, position:vec(hit.transform.position), rotation:vec(hit.transform.rotation), scale:vec(hit.transform.scale, [1,1,1])};
    session.stage.selection = [hit.id];
    canvas.setPointerCapture?.(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if(!draft) return;
    const item = session.stage.objects.find(row => row.id === draft.id);
    if(!item) return;
    const dx = (event.clientX - draft.x) / 80;
    const dy = (event.clientY - draft.y) / 80;
    if(session.tool === 'rotate') item.transform.rotation = [draft.rotation[0], draft.rotation[1] + dx * 40, draft.rotation[2]];
    else if(session.tool === 'scale'){
      const factor = Math.max(0.01, draft.scale[0] + dx);
      item.transform.scale = session.stage.ui?.uniformScale === false ? [factor, Math.max(0.01, draft.scale[1] - dy), draft.scale[2]] : [factor, factor, factor];
    }else{
      let x = draft.position[0] + dx, z = draft.position[2] + dy;
      if(session.stage.ui?.snapToGrid !== false){ x = Math.round(x * 2) / 2; z = Math.round(z * 2) / 2; }
      item.transform.position = [x, draft.position[1], z];
    }
    session.touched = true;
    paintScene(canvas, session.stage, activeView(session.stage), session.stage.capture?.guides);
  });
  const finish = () => { if(!draft) return; draft = null; writeBack(host, session.node, session); };
  canvas.addEventListener('pointerup', finish);
  canvas.addEventListener('pointercancel', finish);
}

function hitTest(canvas, stage, event){
  const rect = canvas.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * canvas.width;
  const y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * canvas.height;
  const rows = paintScene(canvas, stage, activeView(stage), stage.capture?.guides);
  let best = null, distance = 28;
  for(const row of rows){
    const delta = Math.hypot(row.projected.x - x, row.projected.y - y);
    if(delta < distance){ distance = delta; best = row.item; }
  }
  return best;
}

function paintPanels(host, session, side, inspector, canvas){
  ensureRenderer(canvas);
  side.replaceChildren();
  inspector.replaceChildren();
  if(session.showKeys){ side.append(shortcutPanel()); }
  side.append(objectTree(host, session));
  if(session.kind === 'director') side.append(directorLibrary(host, session));
  else side.append(previewLibrary(host, session));
  inspector.append(session.kind === 'director' ? directorInspector(host, session) : previewInspector(host, session));
  paintScene(canvas, session.stage, activeView(session.stage), session.stage.capture?.guides);
  if(session.kind === 'preview') mountMonitors(session, canvas.parentElement);
}

function shortcutPanel(){
  const box = el('div', null, 'cds-keys');
  box.append(el('h3', '快捷键'));
  for(const group of SHORTCUT_GROUPS){
    const section = el('section');
    section.append(el('strong', group.label));
    for(const [key, label] of group.items) section.append(el('p', key + '  ' + label));
    box.append(section);
  }
  return box;
}

function objectTree(host, session){
  const box = el('div');
  const search = el('input');
  search.type = 'search';
  search.placeholder = '搜索对象';
  search.value = session.query || '';
  search.addEventListener('input', () => { session.query = search.value; session.paint(); });
  box.append(search);
  const query = (session.query || '').trim().toLowerCase();
  for(const item of session.stage.objects || []){
    if(query && !String(item.name).toLowerCase().includes(query)) continue;
    const row = el('div', null, 'cds-tree-item');
    const pick = el('input');
    pick.type = 'checkbox';
    pick.checked = (session.stage.selection || []).includes(item.id);
    pick.addEventListener('change', () => {
      const selected = new Set(session.stage.selection || []);
      if(pick.checked) selected.add(item.id); else selected.delete(item.id);
      session.stage.selection = [...selected];
      session.touched = true;
      writeBack(host, session.node, session);
    });
    const eye = button(item.visible === false ? '显' : '隐', () => { item.visible = item.visible === false; session.touched = true; writeBack(host, session.node, session); });
    const lock = button(item.locked ? '解锁' : '锁定', () => { item.locked = !item.locked; session.touched = true; writeBack(host, session.node, session); });
    row.append(pick, el('span', item.name), eye, lock);
    box.append(row);
  }
  const selected = session.stage.selection || [];
  box.append(button('打组', () => { groupObjects(session.stage, selected, 'group-' + selected.join('-').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 80)); session.touched = true; writeBack(host, session.node, session); }));
  box.append(button('解组', () => { const current = session.stage.objects.find(item => selected.includes(item.id)); if(current?.groupId) ungroupObjects(session.stage, current.groupId); session.touched = true; writeBack(host, session.node, session); }));
  const characters = (session.stage.objects || []).filter(item => selected.includes(item.id) && item.kind === 'character');
  if(characters.length > 1) box.append(el('p', selectedCharactersSyncHint(characters.length), 'cds-note'));
  if(session.stage.identityStale) box.append(el('p', COPY.identity_colors_stale, 'cds-note'));
  return box;
}

function addObject(host, session, object){
  session.stage.objects.push(object);
  session.stage.selection = [object.id];
  markIdentityStale(session.stage);
  session.touched = true;
  writeBack(host, session.node, session);
}

function directorLibrary(host, session){
  const box = el('div');
  box.append(el('h3', '添加'));
  for(const body of BODY_PRESETS){
    box.append(button(body.label, () => {
      const object = blankObject('character', 'char-' + (session.stage.objects.length + 1), body.label);
      object.variant = body.id; object.color = body.color;
      addObject(host, session, object);
    }));
  }
  for(const [id, label] of PRIMITIVES){
    box.append(button(label, () => addObject(host, session, {...blankObject('primitive', 'mesh-' + (session.stage.objects.length + 1), label), primitive:id})));
  }
  box.append(button('群众阵列', () => addObject(host, session, blankObject('crowd', 'crowd-' + (session.stage.objects.length + 1), '群众阵列'))));
  const file = el('input');
  file.type = 'file'; file.accept = '.glb,model/gltf-binary';
  file.addEventListener('change', () => {
    if(!file.files?.[0]) return;
    const object = blankObject('uploaded_model', 'glb-' + (session.stage.objects.length + 1), file.files[0].name);
    object.placeholder = COPY.model_uploading_placeholder;
    addObject(host, session, object);
    host.notice(COPY.model_uploading_placeholder);
  });
  box.append(el('p', '上传 GLB'), file);
  return box;
}

function previewLibrary(host, session){
  const box = el('div');
  box.append(el('h3', '项目资产'));
  const search = el('input');
  search.type = 'search'; search.placeholder = '搜索资产';
  const list = el('div');
  const paint = rows => {
    list.replaceChildren();
    const query = search.value.trim().toLowerCase();
    for(const row of rows.filter(item => !query || String(item.name || item.title || '').toLowerCase().includes(query))){
      list.append(button(row.name || row.title, () => addObject(host, session, blankObject('prop', 'asset-' + (session.stage.objects.length + 1), row.name || row.title || '资产'))));
    }
  };
  search.addEventListener('input', () => paint(session.assets || []));
  box.append(search, list);
  if(host.api){
    host.api(host.base() + '/media?limit=30').then(data => { session.assets = data.items || []; paint(session.assets); }).catch(() => paint([]));
  }
  return box;
}

function directorInspector(host, session){
  const box = el('div');
  const stage = session.stage;
  box.append(viewTools(host, session));
  box.append(sceneTools(host, session));
  const selected = (stage.objects || []).filter(item => (stage.selection || []).includes(item.id));
  if(selected.length) box.append(objectTools(host, session, selected));
  box.append(cameraTools(host, session));
  box.append(captureTools(host, session));
  box.append(panoramaTools(host, session));
  box.append(recognizeTools(host, session));
  box.append(button('应用身份配色', () => {
    const result = applyIdentityColors(stage);
    session.touched = true;
    writeBack(host, session.node, session);
    host.notice(result.message);
  }));
  return box;
}

function viewTools(host, session){
  const row = el('div', null, 'cds-row');
  for(const [id, label] of [['move','移动'],['rotate','旋转'],['scale','缩放']]){
    const control = button(label, () => { session.tool = id; session.paint(); });
    if(session.tool === id) control.classList.add('is-active');
    row.append(control);
  }
  row.append(button('导演视角', () => { session.stage.viewport.activeView = 'director'; session.touched = true; writeBack(host, session.node, session); }));
  row.append(button('机位视角', () => { session.stage.viewport.activeView = session.stage.cameras[0]?.id || 'director'; session.touched = true; writeBack(host, session.node, session); }));
  row.append(button('重置视角', () => { session.stage.viewport.directorView = defaultStage().viewport.directorView; session.stage.viewport.activeView = 'director'; session.touched = true; writeBack(host, session.node, session); }));
  row.append(button('全屏', () => { const node = session.overlay; if(document.fullscreenElement) document.exitFullscreen?.(); else node.requestFullscreen?.(); }));
  return row;
}

function sceneTools(host, session){
  const box = el('div');
  const scene = session.stage.scene;
  const grid = el('input'); grid.type = 'checkbox'; grid.checked = scene.gridVisible !== false;
  grid.addEventListener('change', () => { scene.gridVisible = grid.checked; session.touched = true; writeBack(host, session.node, session); });
  const ground = el('input'); ground.type = 'checkbox'; ground.checked = scene.groundVisible !== false;
  ground.addEventListener('change', () => { scene.groundVisible = ground.checked; session.touched = true; writeBack(host, session.node, session); });
  const snap = el('input'); snap.type = 'checkbox'; snap.checked = session.stage.ui?.snapToGrid !== false;
  snap.addEventListener('change', () => { session.stage.ui.snapToGrid = snap.checked; session.touched = true; writeBack(host, session.node, session); });
  const uniform = el('input'); uniform.type = 'checkbox'; uniform.checked = session.stage.ui?.uniformScale !== false;
  uniform.addEventListener('change', () => { session.stage.ui.uniformScale = uniform.checked; session.touched = true; writeBack(host, session.node, session); });
  box.append(labeled('网格', grid), labeled('地面', ground), labeled('网格吸附', snap), labeled('统一缩放', uniform));
  box.append(slider(host, session, '地面透明度', scene.groundOpacity, 0, 1, 0.05, value => { scene.groundOpacity = value; }));
  box.append(slider(host, session, '地面高度', scene.groundHeight, -20, 20, 0.1, value => { scene.groundHeight = value; }));
  box.append(slider(host, session, '整场缩放', scene.sceneScale, 0.01, 20, 0.01, value => { scene.sceneScale = value; }));
  scene.sceneRotation = vec(scene.sceneRotation);
  scene.sceneTranslation = vec(scene.sceneTranslation);
  box.append(slider(host, session, '整场旋转', scene.sceneRotation[1], -180, 180, 1, value => { scene.sceneRotation = [scene.sceneRotation[0], value, scene.sceneRotation[2]]; }));
  box.append(slider(host, session, '整场平移 X', scene.sceneTranslation[0], -50, 50, 0.1, value => { scene.sceneTranslation = [value, scene.sceneTranslation[1], scene.sceneTranslation[2]]; }));
  box.append(slider(host, session, '整场平移 Y', scene.sceneTranslation[1], -50, 50, 0.1, value => { scene.sceneTranslation = [scene.sceneTranslation[0], value, scene.sceneTranslation[2]]; }));
  box.append(slider(host, session, '整场平移 Z', scene.sceneTranslation[2], -50, 50, 0.1, value => { scene.sceneTranslation = [scene.sceneTranslation[0], scene.sceneTranslation[1], value]; }));
  const unit = el('select');
  for(const item of ['m','cm']){ const option = el('option', item); option.value = item; unit.append(option); }
  unit.value = scene.unit || 'm';
  unit.addEventListener('change', () => { scene.unit = unit.value; session.touched = true; writeBack(host, session.node, session); });
  box.append(labeled('单位', unit));
  box.append(colorField(host, session, '天空色', scene.skyColor || '#87CEEB', value => { scene.skyColor = value || '#87CEEB'; }));
  return box;
}

function objectTools(host, session, selected){
  const box = el('div');
  const first = selected[0];
  box.append(el('h3', selected.length > 1 ? selectedCharactersSyncHint(selected.filter(item => item.kind === 'character').length || selected.length) : first.name));
  box.append(slider(host, session, '透明度', first.opacity ?? 1, 0, 1, 0.05, value => patchSelected(session, selected, item => { item.opacity = value; })));
  if(selected.some(item => item.kind === 'character')){
    const pose = el('select');
    for(const [id, label] of POSE_PRESETS){ const option = el('option', label); option.value = id; pose.append(option); }
    pose.value = POSE_IDS.has(first.pose) ? first.pose : 'stand';
    pose.addEventListener('change', () => patchSelected(session, selected, item => { if(item.kind === 'character') item.pose = pose.value; }, host));
    box.append(labeled('姿势预设', pose));
    const body = el('select');
    for(const item of BODY_PRESETS){ const option = el('option', item.label); option.value = item.id; body.append(option); }
    body.value = first.variant || 'male_basic';
    body.addEventListener('change', () => patchSelected(session, selected, item => {
      if(item.kind !== 'character') return;
      item.variant = body.value;
      item.color = BODY_PRESETS.find(row => row.id === body.value).color;
    }, host));
    box.append(labeled('素体', body));
    for(const axis of JOINT_AXES){
      box.append(slider(host, session, axis, first.joints?.[axis] || 0, -180, 180, 1, value => patchSelected(session, selected, item => { if(item.kind === 'character') item.joints[axis] = value; })));
    }
  }
  if(first.kind === 'crowd'){
    const crowd = clampCrowd(first.crowd?.rows, first.crowd?.columns, first.crowd?.spacing);
    box.append(slider(host, session, '行', crowd.rows, 1, 20, 1, value => { first.crowd = clampCrowd(value, first.crowd.columns, first.crowd.spacing); }));
    box.append(slider(host, session, '列', crowd.columns, 1, 40, 1, value => { first.crowd = clampCrowd(first.crowd.rows, value, first.crowd.spacing); }));
    box.append(slider(host, session, '间距', crowd.spacing, 0.2, 5, 0.1, value => { first.crowd = clampCrowd(first.crowd.rows, first.crowd.columns, value); }));
  }
  if(first.kind === 'primitive'){
    const primitive = el('select');
    for(const [id, label] of PRIMITIVES){ const option = el('option', label); option.value = id; if(PRIMITIVE_IDS.has(id)) primitive.append(option); }
    primitive.value = first.primitive || 'cube';
    primitive.addEventListener('change', () => { first.primitive = primitive.value; session.touched = true; writeBack(host, session.node, session); });
    box.append(labeled('几何体', primitive));
  }
  box.append(colorField(host, session, '颜色', first.color || '#829BB5', value => patchSelected(session, selected, item => { item.color = value || item.color; })));
  return box;
}

function patchSelected(session, selected, apply, host){
  const characters = selected.filter(item => item.kind === 'character');
  const targets = characters.length > 1 ? characters : selected;
  for(const item of targets) apply(item);
  session.touched = true;
  if(host) writeBack(host, session.node, session);
}

function cameraTools(host, session){
  const box = el('div');
  box.append(el('h3', '机位'));
  for(const preset of CAMERA_PRESETS){
    box.append(button(preset.label, () => {
      const camera = cameraFromPreset(preset, 'cam-' + preset.id + '-' + (session.stage.cameras.length + 1));
      session.stage.cameras.push(camera);
      session.stage.viewport.activeView = camera.id;
      session.touched = true;
      writeBack(host, session.node, session);
      host.notice(preset.label);
    }));
  }
  box.append(button('按当前视角添加机位', () => { host.notice(addCameraFromView(session.stage)); session.touched = true; writeBack(host, session.node, session); }));
  const camera = session.stage.cameras.find(item => item.id === session.stage.viewport.activeView) || session.stage.cameras[0];
  if(camera){
    box.append(slider(host, session, 'FOV', clampFov(camera.fov), 15, 90, 1, value => { camera.fov = clampFov(value); }));
    const aspect = el('select');
    for(const item of ASPECTS){ const option = el('option', item); option.value = item; aspect.append(option); }
    aspect.value = ASPECTS.includes(camera.aspectRatio) ? camera.aspectRatio : '16:9';
    aspect.addEventListener('change', () => { camera.aspectRatio = aspect.value; session.touched = true; writeBack(host, session.node, session); });
    box.append(labeled('画幅', aspect));
    const mode = el('select');
    mode.append(el('option', '注视对象'), el('option', '手动注视点'));
    mode.children[0].value = 'target'; mode.children[1].value = 'point';
    mode.value = camera.lookAtTargetId ? 'target' : 'point';
    const target = el('select');
    for(const item of session.stage.objects){ const option = el('option', item.name); option.value = item.id; target.append(option); }
    mode.addEventListener('change', () => { setLookAt(camera, mode.value, target.value || null, camera.lookAtPoint); session.touched = true; writeBack(host, session.node, session); });
    target.addEventListener('change', () => { setLookAt(camera, 'target', target.value, null); session.touched = true; writeBack(host, session.node, session); });
    box.append(labeled('注视', mode), target);
    const thirds = el('input'); thirds.type = 'checkbox'; thirds.checked = Boolean(session.stage.capture?.guides?.thirds);
    thirds.addEventListener('change', () => { session.stage.capture.guides.thirds = thirds.checked; session.touched = true; writeBack(host, session.node, session); });
    const safe = el('input'); safe.type = 'checkbox'; safe.checked = Boolean(session.stage.capture?.guides?.safe);
    safe.addEventListener('change', () => { session.stage.capture.guides.safe = safe.checked; session.touched = true; writeBack(host, session.node, session); });
    box.append(labeled('三分', thirds), labeled('安全框', safe));
    const scope = el('select');
    for(const [id, label] of [['subject','主体'],['relationship','关系'],['environment','环境']]){ const option = el('option', label); option.value = id; scope.append(option); }
    box.append(labeled('取景', scope), button('自动取景', () => {
      const ids = session.stage.selection?.length ? session.stage.selection : session.stage.objects.slice(0, 1).map(item => item.id);
      autoFrame(session.stage, camera.id, ids, session.stage.objects.map(item => item.id).filter(id => !ids.includes(id)), scope.value);
      session.touched = true;
      writeBack(host, session.node, session);
      if(camera.framing?.warning) host.notice(camera.framing.warning);
    }));
  }
  return box;
}

function captureTools(host, session){
  const row = el('div', null, 'cds-row');
  row.append(el('h3', '截图'));
  for(const [mode, label] of [['current','当前视角'],['four','四方位'],['twelve','十二方位']]){
    row.append(button(label, () => sendShots(host, session, mode)));
  }
  row.append(button(COPY.send_to_canvas, () => sendShots(host, session, 'current')));
  return row;
}

async function sendShots(host, session, mode){
  if(host.readOnly?.()){ host.notice(COPY.readonly_save_screenshot); return; }
  const canvas = session.overlay.querySelector('canvas');
  const count = mode === 'twelve' ? 12 : mode === 'four' ? 4 : 1;
  const images = [];
  const original = session.stage.viewport.activeView;
  const presets = CAMERA_PRESETS.slice(0, count);
  for(let index = 0; index < count; index++){
    if(count > 1){
      const preset = presets[index % presets.length];
      session.stage.viewport.activeView = 'director';
      session.stage.viewport.directorView = {yaw:index * 0.4, pitch:0.3, distance:8 + index, target:preset.look};
    }
    paintScene(canvas, session.stage, activeView(session.stage), session.stage.capture?.guides);
    images.push(canvas.toDataURL('image/png').split(',')[1]);
  }
  session.stage.viewport.activeView = original;
  const result = await postCanvas(host, '/director-screenshot', {node_id:session.node.id, mode, images});
  await host.refresh?.();
  host.notice(mode === 'four' ? COPY.four_screenshot_nodes_created : mode === 'twelve' ? COPY.twelve_screenshot_nodes_created : COPY.send_to_canvas);
  return result;
}

function panoramaTools(host, session){
  const box = el('div');
  box.append(el('h3', '全景球幕'));
  const pano = session.stage.panorama;
  box.append(slider(host, session, '旋转', pano.rotationY || 0, -180, 180, 1, value => { pano.rotationY = value; }));
  box.append(slider(host, session, '半径', pano.radius || 60, 1, 200, 1, value => { pano.radius = value; }));
  const file = el('input'); file.type = 'file'; file.accept = 'image/*';
  file.addEventListener('change', () => uploadPanorama(host, session, file.files?.[0]));
  box.append(el('p', '本地上传'), file);
  box.append(button('历史全景图', () => showHistory(host, session, box)));
  box.append(button('生成 720° 全景', () => generatePanorama(host, session)));
  if(pano.sourceType && pano.sourceType !== 'none') box.append(el('p', '当前球幕：' + pano.sourceType + (pano.fileName ? ' · ' + pano.fileName : '')));
  return box;
}

async function uploadPanorama(host, session, file){
  if(!file || host.readOnly?.()){ if(host.readOnly?.()) host.notice(COPY.readonly_save_stage); return; }
  const bytes = new Uint8Array(await file.arrayBuffer());
  const headers = {...host.headers(), 'X-Filename': file.name || 'panorama.png'};
  delete headers['Content-Type'];
  const staged = await host.api(host.base() + '/uploads', {method:'POST', headers, body:bytes});
  host.setRevision(staged.revision);
  const media = await host.api(host.base() + '/media', {method:'POST', headers:host.headers(), body:JSON.stringify({payload:{staged_upload:staged.staged_upload, name:file.name || '全景图', rights:'unknown', source:{kind:'director-panorama-upload', content:'local panorama'}}, expected_revision:host.revision(), idempotency_key:host.newId()})});
  host.setRevision(media.revision);
  host.change(() => {
    const id = 'pano-' + host.newId();
    const node = session.node;
    host.state.document.nodes.push({id, type:'image', title:file.name || '全景图', x:node.x - 320, y:node.y, text:'', params:{director_panorama_origin:'upload'}, media_id:media.id, job_id:null, group:''});
    host.state.document.edges = host.state.document.edges.filter(edge => !(edge.target === node.id && edge.port === 'panorama_image'));
    host.state.document.edges.push({id:'pano-edge-' + host.newId(), source:id, target:node.id, port:'panorama_image'});
    const stage = parseStage(node.text) || session.stage;
    stage.panorama.origin = 'upload';
    stage.panorama.fileName = file.name || '';
    stage.panorama.radius = stage.panorama.radius || 60;
    node.text = stableStringify(stage);
  });
  host.notice(COPY.panorama_uploaded_connected);
}

async function showHistory(host, session, box){
  const page = await postCanvas(host, '/pic-recognize/list', {node_id:session.node.id, kind:'panorama', offset:0, limit:20});
  const list = el('div');
  for(const row of page.list || []){
    list.append(button(row.id.slice(0, 8), () => connectHistory(host, session, row)));
  }
  if(!(page.list || []).length) list.append(el('p', '暂无历史全景图'));
  box.append(list);
}

function connectHistory(host, session, row){
  let parsed = {};
  try{ parsed = JSON.parse(row.result || '{}'); }catch{ parsed = {}; }
  host.change(() => {
    const stage = parseStage(session.node.text) || session.stage;
    stage.panorama.sourceType = 'history';
    stage.panorama.origin = 'history';
    stage.panorama.mediaId = row.media_id || parsed.mediaId || null;
    stage.panorama.status = 'ready';
    stage.panorama.radius = stage.panorama.radius || 60;
    if(parsed.imageNodeId && host.state.document.nodes.some(item => item.id === parsed.imageNodeId)){
      host.state.document.edges = host.state.document.edges.filter(edge => !(edge.target === session.node.id && edge.port === 'panorama_image'));
      host.state.document.edges.push({id:'pano-edge-' + host.newId(), source:parsed.imageNodeId, target:session.node.id, port:'panorama_image'});
      stage.panorama.origin = 'history';
    }
    session.node.text = stableStringify(stage);
    session.stage = stage;
  });
  host.notice(COPY.history_panorama_connected);
}

async function generatePanorama(host, session){
  if(host.readOnly?.()){ host.notice(COPY.readonly_save_stage); return; }
  const source = (host.state.document.edges || []).find(edge => edge.target === session.node.id && edge.port !== 'panorama_image' && host.state.document.nodes.some(node => node.id === edge.source && node.type === 'image'));
  await postCanvas(host, '/director-panorama', {node_id:session.node.id, ...(source ? {source_node_id:source.source} : {})});
  await host.refresh?.();
  host.notice(COPY.panorama_generated_connected);
}

function recognizeTools(host, session){
  const box = el('div');
  box.append(el('h3', 'AI 识图导入'));
  const images = (host.state.document.nodes || []).filter(node => node.type === 'image');
  const select = el('select');
  for(const node of images){ const option = el('option', node.title); option.value = node.id; select.append(option); }
  const strategy = el('select');
  const insert = el('option', '插入到当前场景'); insert.value = 'insert';
  const replace = el('option', '覆盖当前场景'); replace.value = 'replace';
  strategy.append(insert, replace);
  box.append(select, strategy, el('p', COPY.strategy_insert), el('p', COPY.strategy_replace));
  box.append(button('开始识图', async () => {
    const blocked = linkedImageBlocked(host.state.document, session.node.id, select.value);
    if(blocked){ host.notice(blocked); return; }
    await postCanvas(host, '/pic-recognize', {node_id:session.node.id, image_node_id:select.value, strategy:strategy.value});
    await host.refresh?.();
    host.notice(strategy.value === 'replace' ? COPY.strategy_replace : COPY.strategy_insert);
  }));
  box.append(button('识图记录', () => listRecognize(host, session, box)));
  return box;
}

async function listRecognize(host, session, box){
  const page = await postCanvas(host, '/pic-recognize/list', {node_id:session.node.id, kind:'recognize', offset:0, limit:20});
  const list = el('div');
  for(const row of page.list || []){
    list.append(button('删除 ' + row.id.slice(0, 8), async () => {
      await postCanvas(host, '/pic-recognize/delete', {node_id:session.node.id, task_id:row.id, canvas_id:host.state.id});
      host.notice('已删除识图记录');
    }));
  }
  box.append(list);
}

function previewInspector(host, session){
  const box = el('div');
  const preview = session.preview;
  const chat = el('textarea');
  chat.placeholder = '描述要修改的场景，例如添加角色或太阳光';
  const file = el('input'); file.type = 'file'; file.accept = 'image/*';
  box.append(el('div', null, 'cds-chat'), chat, file);
  box.append(button('按对话改场景', async () => {
    const hasImage = Boolean(file.files?.[0]);
    try{
      planPreviewEdit(preview, chat.value, hasImage);
      session.stage = preview.stage;
      session.touched = true;
      writeBack(host, session.node, session);
    }catch(error){ host.notice(error.message); }
  }));
  const transport = el('div', null, 'cds-row');
  transport.append(
    button(session.playing ? '暂停' : '播放', () => togglePlay(host, session)),
    button('-5 秒', () => seek(host, session, -5)),
    button('+5 秒', () => seek(host, session, 5)),
    button('成片预演', () => { preview.mode = 'preview'; preview.timelineSummary.durationSeconds = 15; preview.timelineSummary.shotCount = 1; session.touched = true; writeBack(host, session.node, session); }),
    button('场景调度', () => { preview.mode = 'schedule'; session.touched = true; writeBack(host, session.node, session); }),
  );
  box.append(transport, el('p', '播放头 ' + Number(preview.playhead || 0).toFixed(1) + 's / ' + preview.timelineSummary.durationSeconds + 's · ' + (preview.mode === 'schedule' ? '场景调度' : '成片预演')));
  for(const [id, label] of LIGHT_TYPES){
    box.append(button(label, () => {
      const names = {directional:'添加太阳光', point:'添加点光源', spot:'添加聚光灯'};
      planPreviewEdit(preview, names[id], false);
      session.stage = preview.stage;
      session.touched = true;
      writeBack(host, session.node, session);
    }));
  }
  box.append(button('保存场景', async () => {
    const ok = await host.save?.();
    if(ok === false && (host.state.lastSaveError?.status === 409 || host.state.lastSaveError?.code === 'canvas_revision_conflict')) showConflict(host, session, box);
  }));
  const seconds = el('input'); seconds.type = 'number'; seconds.min = '1'; seconds.max = '15'; seconds.value = '1';
  box.append(labeled('参考视频秒数', seconds), button('导出压缩参考视频', () => exportVideo(host, session, Number(seconds.value))), button(COPY.to_canvas, () => exportVideo(host, session, Number(seconds.value))));
  box.append(viewTools(host, session), sceneTools(host, session));
  return box;
}

function showConflict(host, session, box){
  const note = el('p', COPY.edit_conflict, 'cds-note');
  const discard = button(COPY.discard_edits, async () => { await host.discardAndReload?.(); session.overlay.remove(); });
  box.append(note, discard);
}

function togglePlay(host, session){
  if(session.playing){ clearInterval(session.timer); session.playing = false; session.paint(); return; }
  session.playing = true;
  session.timer = setInterval(() => {
    const duration = session.preview.timelineSummary.durationSeconds || 15;
    session.preview.playhead = Math.min(duration, Number(session.preview.playhead || 0) + 0.1);
    if(session.preview.playhead >= duration){ clearInterval(session.timer); session.playing = false; }
    session.paint();
  }, 100);
}

function seek(host, session, delta){
  const duration = session.preview.timelineSummary.durationSeconds || 15;
  session.preview.playhead = Math.min(duration, Math.max(0, Number(session.preview.playhead || 0) + delta));
  session.touched = true;
  writeBack(host, session.node, session);
}

function mountMonitors(session, viewport){
  viewport.querySelector('.cds-monitor')?.remove();
  const box = el('div', null, 'cds-monitor');
  const top = el('canvas'); top.width = 220; top.height = 110;
  const monitor = el('canvas'); monitor.width = 220; monitor.height = 110;
  const topView = {position:[0,12,0.2], look:[0,0,0], fov:50};
  const camera = session.stage.cameras[0];
  const cameraView = camera ? {position:vec(camera.transform.position), look:vec(camera.lookAtPoint || [0,1,0]), fov:clampFov(camera.fov)} : activeView(session.stage);
  top.dataset.renderer = '2d'; monitor.dataset.renderer = '2d';
  paintScene(top, session.stage, topView, null);
  paintScene(monitor, session.stage, cameraView, session.stage.capture?.guides);
  box.append(el('p', '俯视图'), top, el('p', '机位监视器'), monitor);
  viewport.append(box);
}

async function exportVideo(host, session, seconds){
  if(host.readOnly?.()){ host.notice(COPY.readonly_save_stage); return; }
  const frames = referenceFrameCount(Math.min(15, Math.max(1, seconds || 1)));
  const canvas = session.overlay.querySelector('canvas');
  paintScene(canvas, session.stage, activeView(session.stage), session.stage.capture?.guides);
  const image = canvas.toDataURL('image/png').split(',')[1];
  let localUrl = null;
  if(typeof MediaRecorder !== 'undefined' && canvas.captureStream){
    try{
      const recorder = new MediaRecorder(canvas.captureStream(24));
      const chunks = [];
      recorder.ondataavailable = event => { if(event.data?.size) chunks.push(event.data); };
      const stopped = new Promise(resolve => { recorder.onstop = resolve; });
      recorder.start();
      setTimeout(() => recorder.stop(), Math.min(1500, frames * 20));
      await stopped;
      if(chunks.length) localUrl = URL.createObjectURL(new Blob(chunks, {type:chunks[0].type || 'video/webm'}));
    }catch{ localUrl = null; }
  }
  const result = await postCanvas(host, '/reference-video', {node_id:session.node.id, images:[image], frame_count:frames});
  await host.refresh?.();
  if(result?.media_id){
    const link = el('a', '下载压缩参考视频');
    link.href = localUrl || (host.base() + '/media/' + encodeURIComponent(result.media_id) + '/content');
    link.download = 'director-reference.mp4';
    session.overlay.querySelector('.cds-inspector')?.append(link);
  }
  host.notice(COPY.to_canvas);
  return result;
}

function labeled(text, control){
  const row = el('label', text, 'cds-row');
  row.append(control);
  return row;
}

function slider(host, session, label, value, min, max, step, apply){
  const input = el('input');
  input.type = 'range'; input.min = String(min); input.max = String(max); input.step = String(step); input.value = String(value ?? min);
  input.addEventListener('change', () => { apply(Number(input.value)); session.touched = true; writeBack(host, session.node, session); });
  return labeled(label, input);
}

function colorField(host, session, label, value, apply){
  const box = el('div');
  box.append(el('p', label));
  const format = el('select');
  for(const item of ['HEX','RGB','HSL']){ const option = el('option', item); option.value = item; format.append(option); }
  const text = el('input'); text.value = value || '#829BB5';
  const channels = el('div', null, 'cds-row');
  const paintChannels = () => {
    channels.replaceChildren();
    let rgb = {r:130, g:155, b:181};
    try{ rgb = hexToRgb(text.value.startsWith('#') ? text.value : hslOrRgbToHex(format.value, text.value)); }catch{ return; }
    const hsl = rgbToHsl(rgb.r, rgb.g, rgb.b);
    const specs = format.value === 'HSL' ? [['H', hsl.h, 0, 360], ['S', hsl.s, 0, 100], ['L', hsl.l, 0, 100]] : [['R', rgb.r, 0, 255], ['G', rgb.g, 0, 255], ['B', rgb.b, 0, 255]];
    if(format.value === 'HEX') return;
    for(const [name, current, min, max] of specs){
      const input = el('input'); input.type = 'range'; input.min = String(min); input.max = String(max); input.value = String(Math.round(current));
      input.addEventListener('change', () => {
        const next = {};
        for(const control of channels.querySelectorAll('input')) next[control.previousSibling?.textContent || name] = Number(control.value);
        const hex = format.value === 'HSL' ? hslToHex(next.H ?? hsl.h, next.S ?? hsl.s, next.L ?? hsl.l) : '#' + [next.R ?? rgb.r, next.G ?? rgb.g, next.B ?? rgb.b].map(item => item.toString(16).padStart(2, '0')).join('').toUpperCase();
        text.value = hex;
        apply(hex);
        session.touched = true;
        writeBack(host, session.node, session);
      });
      channels.append(el('span', name), input);
    }
  };
  format.addEventListener('change', paintChannels);
  text.addEventListener('change', () => {
    const hex = text.value.startsWith('#') ? text.value.toUpperCase() : hslOrRgbToHex(format.value, text.value);
    text.value = hex; apply(hex); session.touched = true; writeBack(host, session.node, session); paintChannels();
  });
  const palette = el('div', null, 'cds-row');
  palette.append(el('span', COPY.recommended_colors));
  for(const color of PALETTE){
    const swatch = button('', () => { text.value = color; apply(color); session.touched = true; writeBack(host, session.node, session); });
    swatch.className = 'cds-swatch'; swatch.style.background = color; swatch.title = color;
    palette.append(swatch);
  }
  const pick = button(COPY.pick_screen_color, async () => {
    if(typeof EyeDropper !== 'function'){ host.notice('当前浏览器不支持屏幕吸色，请改用色值或推荐色板。'); return; }
    try{
      const result = await new EyeDropper().open();
      text.value = result.sRGBHex.toUpperCase();
      apply(text.value);
      session.touched = true;
      writeBack(host, session.node, session);
    }catch{ /* user cancelled */ }
  });
  const clear = button(COPY.clear_color, () => { text.value = '#829BB5'; apply('#829BB5'); session.touched = true; writeBack(host, session.node, session); });
  box.append(format, text, channels, palette, pick, clear);
  return box;
}

function hslOrRgbToHex(format, value){
  const parts = String(value).split(/[^\d.]+/).filter(Boolean).map(Number);
  if(format === 'HSL' && parts.length >= 3) return hslToHex(parts[0], parts[1], parts[2]);
  if(parts.length >= 3) return '#' + parts.slice(0, 3).map(item => item.toString(16).padStart(2, '0')).join('').toUpperCase();
  return '#829BB5';
}
