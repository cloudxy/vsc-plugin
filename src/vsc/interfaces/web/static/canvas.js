/* Disposable resource graph view. No action here writes production facts. */
const NS = 'http://www.w3.org/2000/svg';
const NAMES = {object:'创作对象', media:'素材', artifact:'文案版本', source:'来源版本', operation:'加工过程', job:'生成过程', slot:'用途槽位', timeline:'时间线', item:'剪辑片段', render:'渲染过程', line:'剧本行', script_line:'剧本行', state:'状态版本', voice:'声线版本', instance:'使用实例', cue:'声音提示', performance:'动作与特效'};
const LAYERS = {source:0, artifact:0, line:1, script_line:1, object:2, state:2, voice:2, instance:3, cue:3, performance:3, media:4, operation:5, job:5, slot:6, item:7, timeline:8, render:9};
const W = 206, H = 90;
function element(tag, text, cls) { const el = document.createElement(tag); if(text !== undefined) el.textContent = text; if(cls) el.className = cls; return el; }
function svg(tag, attributes = {}, text) { const el = document.createElementNS(NS, tag); Object.entries(attributes).forEach(([k,v]) => el.setAttribute(k, String(v))); if(text !== undefined) el.textContent = text; return el; }
function finite(value) { return Number.isFinite(value) && Math.abs(value) < 1e8; }

export function createResourceCanvas(container, {onSelect = () => {}, onScope=()=>{},onCollection=()=>{},onError = () => {}} = {}) {
  let current = null, graph = {nodes:[], edges:[]}, nodes = new Map(), positions = {}, selected = null;
  let camera = {x:0,y:0,w:1200,h:650}, abort = null, sequence = 0, disposed = false, offset = 0;
  let hiddenKinds = new Set(), highlight = new Set(), drag = null, moved = false, saveTimer = null, hasSavedLayout = false;
  let mode = 'creative', comparisonSource=null;
  const host = element('div', undefined, 'resource-canvas');
  const toolbar = element('div', undefined, 'canvas-toolbar');
  const search = element('input'); search.type='search'; search.placeholder='搜索当前已加载节点'; search.setAttribute('aria-label','搜索画布节点');
  const status = element('p', '选择作品后查看已登记关系。', 'canvas-status'); status.setAttribute('aria-live','polite');
  const groups = element('div', undefined, 'canvas-groups');
  const body = element('div', undefined, 'canvas-body');
  const scene = svg('svg', {class:'canvas-surface', viewBox:'0 0 1200 650', tabindex:0, role:'group', 'aria-label':'素材关系画布，可拖动空白平移、滚轮缩放'});
  const defs = svg('defs'), marker = svg('marker',{id:'resource-graph-arrow-'+Math.random().toString(36).slice(2),viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});
  marker.append(svg('path',{d:'M 0 0 L 10 5 L 0 10 z',class:'canvas-arrow'})); defs.append(marker); scene.append(defs);
  const edgeLayer=svg('g'), nodeLayer=svg('g'); scene.append(edgeLayer,nodeLayer);
  const minimap=svg('svg',{class:'canvas-minimap',viewBox:'0 0 1200 650',role:'img','aria-label':'画布小地图，点击定位'});
  const details=element('aside',undefined,'canvas-details'); details.setAttribute('aria-label','关系详情');
  const overview=element('div',undefined,'canvas-overview');overview.hidden=true;
  body.append(scene,minimap,details); host.append(toolbar,groups,status,overview,body); container.replaceChildren(host);
  function button(label, fn) { const b=element('button',label); b.type='button'; b.addEventListener('click',fn); toolbar.append(b); return b; }
  toolbar.append(search);
  const modes=element('select');modes.setAttribute('aria-label','关系视图');
  for(const [value,label] of [['creative','创作关联'],['production','制作来源'],['usage','采用与用料'],['impact','版本与影响']]){const o=element('option',label);o.value=value;modes.append(o);}modes.value=mode;toolbar.append(modes);
  modes.addEventListener('change',()=>{mode=modes.value;selected=null;highlight.clear();offset=0;if(!current?.overview)request({offset:'0'});});
  button('全范围检索',searchEverywhere);
  button('定位', searchFocus); button('适应范围',fit); button('−',()=>zoom(1.25)); button('+',()=>zoom(.8));
  button('上游一层',()=>expand('upstream')); button('下游一层',()=>expand('downstream'));
  button('突出上游',()=>mark('upstream')); button('突出下游',()=>mark('downstream'));
  button('清除突出',()=>{highlight.clear();render();}); button('重置布局',()=>{positions={};layout();fit();scheduleSave();});
  button('影响报告',()=>impactReport(selected));
  button('标记原版本',()=>{if(!selected){status.textContent='先选择要比较的原版本。';return;}comparisonSource=selected;status.textContent='已标记原版本；选择替换版本后比较影响，不会改动正式采用。';});
  button('比较替换影响',()=>impactReport(comparisonSource,selected));
  button('项目分组概览',()=>{onScope(null);return load({...current,objectId:null,focus:null,overview:true});});
  const previous=button('上一页',()=>page(Math.max(0,offset-100))), next=button('下一页',()=>page(graph.next_offset));
  search.addEventListener('keydown',e=>{if(e.key==='Enter') searchFocus();});

  function storageKey() { return 'vsc.canvas.v1:'+JSON.stringify([current?.userId || 'read-only',current?.projectId,current?.objectId || 'all']); }
  function restore() {
    positions={}; hiddenKinds=new Set(); hasSavedLayout=false;
    try {
      const data=JSON.parse(localStorage.getItem(storageKey()) || 'null');
      if(data && data.version===1) {
        for(const [id,p] of Object.entries(data.positions || {})) if(p && finite(p.x)&&finite(p.y)) positions[id]={x:p.x,y:p.y};
        if(data.camera && ['x','y','w','h'].every(k=>finite(data.camera[k])) && data.camera.w>0 && data.camera.h>0) {camera=data.camera;hasSavedLayout=true;}
        hiddenKinds=new Set((data.hiddenKinds || []).filter(k=>k in NAMES));
      }
    } catch { /* Browser privacy mode or an old layout must not break browsing. */ }
  }
  function save() {
    if(!current) return;
    // Only opaque entity IDs and view geometry are persisted, never labels,
    // prompts, media content, URLs, decisions or a production revision.
    try { localStorage.setItem(storageKey(),JSON.stringify({version:1,positions,camera,hiddenKinds:[...hiddenKinds]})); } catch { /* Optional preference store. */ }
  }
  function scheduleSave() { clearTimeout(saveTimer); saveTimer=setTimeout(save,180); }
  function layout() {
    const rows={};
    for(const n of graph.nodes) {
      const layer=LAYERS[n.kind] ?? 2, row=rows[layer] || 0; rows[layer]=row+1;
      if(!positions[n.id]) positions[n.id]={x:layer*285,y:row*140};
    }
  }
  function visibleNodes() { return graph.nodes.filter(n=>!hiddenKinds.has(n.kind)); }
  function updateView() { scene.setAttribute('viewBox',`${camera.x} ${camera.y} ${camera.w} ${camera.h}`); drawMini(); }
  function bounds() {
    const ps=visibleNodes().map(n=>positions[n.id]).filter(Boolean);
    if(!ps.length) return {x:0,y:0,w:1200,h:650};
    const x=Math.min(...ps.map(p=>p.x))-45,y=Math.min(...ps.map(p=>p.y))-45;
    return {x,y,w:Math.max(350,Math.max(...ps.map(p=>p.x))+W+45-x),h:Math.max(250,Math.max(...ps.map(p=>p.y))+H+45-y)};
  }
  function fit() {
    const b=bounds(), rect=scene.getBoundingClientRect(), aspect=(rect.width || 1200)/(rect.height || 650);
    camera={...b}; if(camera.w/camera.h>aspect) camera.h=camera.w/aspect; else camera.w=camera.h*aspect;
    updateView();scheduleSave();
  }
  function zoom(factor,clientX,clientY) {
    const rect=scene.getBoundingClientRect(), rx=clientX===undefined ? .5 : (clientX-rect.left)/(rect.width || 1), ry=clientY===undefined ? .5 : (clientY-rect.top)/(rect.height || 1);
    const nw=Math.max(250,Math.min(30000,camera.w*factor)), applied=nw/camera.w;
    camera={x:camera.x+camera.w*rx*(1-applied),y:camera.y+camera.h*ry*(1-applied),w:nw,h:camera.h*applied};
    updateView();scheduleSave();
  }
  function center(id) { const p=positions[id];if(!p)return;camera.x=p.x+W/2-camera.w/2;camera.y=p.y+H/2-camera.h/2;updateView();scheduleSave(); }
  function searchFocus() {
    const q=search.value.trim().toLocaleLowerCase();if(!q)return;
    const n=graph.nodes.find(n=>(n.label+' '+n.entity_id).toLocaleLowerCase().includes(q));
    if(n){hiddenKinds.delete(n.kind);selected=n.id;render();center(n.id);showDetails(n);} else status.textContent='当前已加载节点中没有匹配项；可翻页或从素材列表定位。';
  }
  function showDetails(value, edge=false) {
    details.replaceChildren(element('h3',edge?value.label:value.label || NAMES[value.kind]));
    if(!edge){
      const summary=value.summary || {}, labels={kind:'对象类型',modality:'素材格式',status:'状态',role:'用途',line_kind:'内容类型',text:'内容',version:'版本',duration_ms:'实际时长（毫秒）',asset_kind:'资产类型',instance_key:'使用实例',cue_kind:'声音类型',performance_kind:'动作／特效类型',variant_key:'状态／外观'};
      const dl=element('dl',undefined,'canvas-facts');for(const [key,label] of Object.entries(labels))if(summary[key]!=null){dl.append(element('dt',label),element('dd',String(summary[key])));}details.append(dl);
      const renditions=summary.renditions || [],purpose=summary.preview_purpose || ({image:'thumbnail',video:'poster',audio:'waveform'}[summary.modality]);
      if(value.kind==='media'&&purpose&&(summary.preview_available===true||renditions.some(r=>r.purpose===purpose))){const preview=element('img');preview.loading='lazy';preview.alt=value.label || '素材预览';preview.className='canvas-preview';preview.src='/api/v1/projects/'+encodeURIComponent(current.projectId)+'/media/'+encodeURIComponent(value.entity_id)+'/preview?purpose='+encodeURIComponent(purpose);preview.addEventListener('error',()=>preview.remove(),{once:true});details.append(preview);}
    }
    const evidence=element('details');evidence.append(element('summary','固定引用与关系证据'),element('pre',JSON.stringify(edge?value.evidence:{type:NAMES[value.kind],id:value.entity_id,...value.summary},null,2)));details.append(evidence);
    if(edge) details.append(element('p','来源 → 使用者／产出；证据来自当前查询快照。'));
    else if(['media','artifact','object'].includes(value.kind)) {
      const open=element('button','打开详情');open.type='button';open.addEventListener('click',()=>onSelect(value));details.append(open);
    }
    if(!edge&&value.summary?.artifact_id){const b=element('button','查看关联文案');b.type='button';b.addEventListener('click',()=>onSelect({kind:'artifact',entity_id:value.summary.artifact_id}));details.append(b);}
  }
  async function impactReport(source,replacement){
    if(!source||!current?.projectId){status.textContent='先选择要追踪的节点；替换比较还需标记原版本。';return;}
    abort?.abort();abort=new AbortController();const ticket=++sequence,project=current.projectId;
    const params=new URLSearchParams({source,depth:'4',limit:'100'});if(replacement)params.set('replacement',replacement);
    if(graph.revision!=null)params.set('revision',String(graph.revision));status.textContent='正在查询实际消费者与影响证据…';
    try{const response=await fetch('/api/v1/projects/'+encodeURIComponent(project)+'/impact?'+params,{credentials:'same-origin',signal:abort.signal});const data=await response.json();if(ticket!==sequence||disposed)return;if(!response.ok)throw new Error(data.message||data.detail||'影响查询失败');if(data.project_id!==project)throw new Error('影响响应与项目不一致');details.replaceChildren(element('h3','影响报告'));if(data.comparison)details.append(element('p',data.comparison.reason||''));const labels={affected_pending_review:'受影响，待复核',unaffected:'有证据表明本项不受影响',unknown:'影响尚未确定'};for(const row of data.consumers || []){const card=element('section',undefined,'canvas-impact-item'),b=element('button',row.label||row.entity_id);b.type='button';b.addEventListener('click',()=>focus(row.id));card.append(b,element('p',(labels[row.classification]||row.classification)+' · '+(row.direct===true?'直接使用':typeof row.distance==='number'?'间接使用':'关联范围待核实')+' · '+row.reason));details.append(card);}for(const message of data.warnings || [])details.append(element('p',message));if(data.truncated)details.append(element('p','报告已截断，未展示部分的影响仍未知；可缩小范围继续查询。'));if(!(data.consumers || []).length)details.append(element('p','当前范围没有查到已登记的实际消费者；尚未登记的关系仍无法判断。'));status.textContent='影响报告基于快照 '+data.revision+'；复核结果与具体修复另行记录。';}catch(error){if(ticket!==sequence||disposed||error.name==='AbortError')return;status.textContent=error.message;onError(error);}
  }
  async function loadGrouping(){
    abort?.abort();abort=new AbortController();const ticket=++sequence,project=current.projectId;overview.replaceChildren();overview.hidden=false;body.hidden=true;groups.replaceChildren();previous.disabled=next.disabled=true;
    status.textContent='正在读取项目分组概览…';
    try{const response=await fetch('/api/v1/projects/'+encodeURIComponent(project)+'/workbench?section=overview&limit=24',{credentials:'same-origin',signal:abort.signal});const data=await response.json();if(ticket!==sequence||disposed)return;if(!response.ok)throw new Error(data.message||data.detail||'分组读取失败');if(data.project_id!==project)throw new Error('分组项目不一致');overview.append(element('h3','选择创作范围查看关系'));const grid=element('div',undefined,'canvas-overview-grid');for(const row of data.sections?.children?.items || []){const card=element('button',(row.title||row.display_code||row.id));card.type='button';card.append(element('small',row.kind==='asset'?'资产身份':({work:'部',episode:'集',scene:'场',sequence:'镜组',shot:'镜头'}[row.kind]||row.kind)));card.addEventListener('click',()=>{current.objectId=row.id;current.overview=false;onScope(row.id);overview.hidden=true;body.hidden=false;offset=0;request({offset:'0'});});grid.append(card);}overview.append(grid);const labels={shots:'镜头',lines:'剧本与台词',assets:'资产',instances:'使用实例',cues:'声音',performances:'动作与特效',bindings:'采用与候选',materials:'素材',versions:'文案版本'};const totals=element('div',undefined,'canvas-overview-grid');for(const [key,name]of Object.entries(labels)){const count=data.summary?.[key];if(typeof count!=='number')continue;const b=element('button',name+' · '+count);b.type='button';b.addEventListener('click',()=>onCollection(key));totals.append(b);}overview.append(element('p','资料按范围与用途展开；候选和历史在需要时加载。全范围检索可定位未加载对象。'),totals);status.textContent='项目聚合快照 '+data.revision+'；选择左侧结构可逐层进入场镜。';}catch(error){if(ticket!==sequence||disposed||error.name==='AbortError')return;status.textContent=error.message;onError(error);}
  }
  async function searchEverywhere(){
    const q=search.value.trim();if(!q||!current?.projectId)return;
    abort?.abort();abort=new AbortController();const ticket=++sequence,project=current.projectId;
    status.textContent='正在检索全项目已登记资料…';
    try{const response=await fetch('/api/v1/projects/'+encodeURIComponent(project)+'/workbench?'+new URLSearchParams({section:'overview',query:q,limit:'12'}),{credentials:'same-origin',signal:abort.signal});const data=await response.json();if(ticket!==sequence||disposed)return;if(!response.ok)throw new Error(data.message||data.detail||'检索失败');if(data.project_id!==project)throw new Error('检索项目不一致');current.overview=false;overview.hidden=true;body.hidden=false;details.replaceChildren(element('h3','全项目检索结果'));let count=0;const kinds={children:'object',shots:'object',assets:'object',lines:'line',instances:'instance',cues:'cue',performances:'performance',versions:'artifact',bindings:'slot',materials:'media'};for(const [key,kind]of Object.entries(kinds)){for(const row of data.sections?.[key]?.items || []){const b=element('button',(NAMES[kind]||key)+' · '+(row.title||row.name||row.text||row.label||row.id));b.type='button';b.addEventListener('click',()=>focus(kind+':'+row.id));details.append(b);count++;}}status.textContent=count?'已找到 '+count+' 项摘要，点击定位；更多结果可在创作工作台按类型分页。':'全项目未找到匹配的已登记资料。';}catch(error){if(ticket!==sequence||disposed||error.name==='AbortError')return;status.textContent=error.message;onError(error);}
  }
  function mark(direction) {
    if(!selected)return;
    highlight=new Set([selected]);let changed=true;
    while(changed){changed=false;for(const e of graph.edges){const from=direction==='upstream'?e.target:e.source,to=direction==='upstream'?e.source:e.target;if(highlight.has(from)&&!highlight.has(to)){highlight.add(to);changed=true;}}}
    render();status.textContent='已突出当前已加载范围的'+(direction==='upstream'?'上游':'下游')+'；截断边界外的关系请继续展开。';
  }
  function render() {
    layout();edgeLayer.replaceChildren();nodeLayer.replaceChildren();groups.replaceChildren();
    const visible=new Set(visibleNodes().map(n=>n.id));
    for(const group of graph.groups || []) {
      const b=element('button',`${NAMES[group.kind] || group.kind} ${group.total}`);b.type='button';b.setAttribute('aria-pressed',String(!hiddenKinds.has(group.kind)));b.title='显示／折叠此类已加载节点';
      b.addEventListener('click',()=>{if(hiddenKinds.has(group.kind))hiddenKinds.delete(group.kind);else hiddenKinds.add(group.kind);render();scheduleSave();});groups.append(b);
    }
    const pairCounts=new Map(), pairSeen=new Map();
    for(const e of graph.edges){const key=e.source+'>'+e.target;pairCounts.set(key,(pairCounts.get(key)||0)+1);}
    for(const e of graph.edges) {
      if(!visible.has(e.source)||!visible.has(e.target))continue;
      const pair=e.source+'>'+e.target,index=pairSeen.get(pair)||0;pairSeen.set(pair,index+1);
      const separation=(index-((pairCounts.get(pair)||1)-1)/2)*25;
      const a=positions[e.source],b=positions[e.target],x=a.x+W,y=a.y+H/2,tx=b.x,ty=b.y+H/2,mx=(x+tx)/2;
      const g=svg('g',{class:'canvas-edge'+(e.kind==='selected'?' is-selected':'')+(e.kind==='candidate'?' is-candidate':'')+(highlight.size&&!(highlight.has(e.source)&&highlight.has(e.target))?' is-muted':'')});
      g.append(svg('path',{d:`M ${x} ${y} C ${mx} ${y+separation*1.5} ${mx} ${ty+separation*1.5} ${tx} ${ty}`,'marker-end':`url(#${marker.id})`}));
      const role=e.evidence?.role || e.evidence?.asset_type;
      g.append(svg('text',{x:mx,y:(y+ty)/2+separation-5,'text-anchor':'middle'},e.label+(role?' · '+role:'')));
      g.append(svg('title',{},e.label+' · '+JSON.stringify(e.evidence || {})));
      g.addEventListener('click',ev=>{ev.stopPropagation();showDetails(e,true);});edgeLayer.append(g);
    }
    for(const n of visibleNodes()) {
      const p=positions[n.id],g=svg('g',{'data-node-id':n.id,transform:`translate(${p.x} ${p.y})`,tabindex:0,role:'button','aria-label':`${NAMES[n.kind]}：${n.label}`,class:'canvas-node kind-'+n.kind+(selected===n.id?' is-active':'')+(highlight.size&&!highlight.has(n.id)?' is-muted':'')});
      g.append(svg('rect',{width:W,height:H,rx:['job','operation','render'].includes(n.kind)?30:10}));
      g.append(svg('text',{x:14,y:22,class:'canvas-kind'},NAMES[n.kind] || n.kind));
      const label=String(n.label || n.entity_id);g.append(svg('text',{x:14,y:45},label.length>22?label.slice(0,21)+'…':label));
      const state=n.summary?.status || n.summary?.modality || n.summary?.kind || '';
      const duration=n.summary?.duration_ms;g.append(svg('text',{x:14,y:69,class:'canvas-kind'},state+(duration?' · '+(duration/1000).toFixed(1)+'s':'')+(n.summary?.availability==='missing_location'?' · 缺失位置':'')));
      g.append(svg('title',{},label));
      g.addEventListener('click',()=>{if(moved)return;selected=n.id;render();showDetails(n);});
      g.addEventListener('dblclick',()=>onSelect(n));
      g.addEventListener('keydown',ev=>{if(ev.key==='Enter'){selected=n.id;render();showDetails(n);onSelect(n);}});
      nodeLayer.append(g);
    }
    previous.disabled=offset===0 || !!current?.focus;next.disabled=graph.next_offset==null || !!current?.focus;
    updateView();
  }
  function drawMini() {
    minimap.replaceChildren();const b=bounds();minimap.setAttribute('viewBox',`${b.x} ${b.y} ${b.w} ${b.h}`);
    for(const n of visibleNodes()){const p=positions[n.id];minimap.append(svg('rect',{x:p.x,y:p.y,width:W,height:H,class:'canvas-mini-node'}));}
    minimap.append(svg('rect',{x:camera.x,y:camera.y,width:camera.w,height:camera.h,class:'canvas-mini-view'}));
  }
  minimap.addEventListener('click',ev=>{const matrix=minimap.getScreenCTM();if(!matrix)return;const p=new DOMPoint(ev.clientX,ev.clientY).matrixTransform(matrix.inverse());camera.x=p.x-camera.w/2;camera.y=p.y-camera.h/2;updateView();scheduleSave();});
  scene.addEventListener('wheel',ev=>{ev.preventDefault();zoom(Math.exp(Math.max(-250,Math.min(250,ev.deltaY))*.002),ev.clientX,ev.clientY);},{passive:false});
  scene.addEventListener('pointerdown',ev=>{
    if(ev.button!==0)return;const group=ev.target.closest('[data-node-id]'),rect=scene.getBoundingClientRect();
    if(!group&&ev.target.closest('.canvas-edge'))return;
    const id=group?.getAttribute('data-node-id');drag={id,x:ev.clientX,y:ev.clientY,start:id?{...positions[id]}:{...camera},sx:camera.w/(rect.width || 1),sy:camera.h/(rect.height || 1)};moved=false;scene.setPointerCapture(ev.pointerId);
  });
  scene.addEventListener('pointermove',ev=>{
    if(!drag)return;const dx=ev.clientX-drag.x,dy=ev.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)moved=true;
    if(drag.id){positions[drag.id]={x:drag.start.x+dx*drag.sx,y:drag.start.y+dy*drag.sy};render();}
    else {camera.x=drag.start.x-dx*drag.sx;camera.y=drag.start.y-dy*drag.sy;updateView();}
  });
  function endDrag(event){if(!drag)return;const clicked=event.type==='pointerup'&&!moved&&drag.id;drag=null;if(clicked&&nodes.has(clicked)){selected=clicked;render();showDetails(nodes.get(clicked));}scheduleSave();setTimeout(()=>{moved=false;},0);}
  scene.addEventListener('pointerup',endDrag);scene.addEventListener('pointercancel',endDrag);

  async function request(options,{merge=false}={}) {
    if(!current || disposed)return;
    abort?.abort();abort=new AbortController();const ticket=++sequence, context={...current};
    const params=new URLSearchParams({depth:'2',limit:'100',mode,...options});
    if(context.objectId&&!options.focus)params.set('object_id',context.objectId);
    if(merge && graph.revision!==undefined)params.set('revision',String(graph.revision));
    status.textContent='正在读取已登记关系…';
    try {
      const response=await fetch('/api/v1/projects/'+encodeURIComponent(context.projectId)+'/graph?'+params,{credentials:'same-origin',signal:abort.signal});
      const data=await response.json();
      if(ticket!==sequence||disposed)return;
      if(!response.ok)throw new Error(data.message || data.detail || '关系查询失败');
      if(data.project_id!==context.projectId)throw new Error('关系响应与当前作品不一致');
      if(merge){const allNodes=new Map(graph.nodes.map(n=>[n.id,n])),allEdges=new Map(graph.edges.map(e=>[e.id,e]));data.nodes.forEach(n=>allNodes.set(n.id,n));data.edges.forEach(e=>allEdges.set(e.id,e));if(allNodes.size>600)throw new Error('当前视图已达到 600 个节点，请按对象范围重新载入后继续展开。');graph={...data,nodes:[...allNodes.values()],edges:[...allEdges.values()],next_offset:graph.next_offset};}
      else graph=data;
      nodes=new Map(graph.nodes.map(n=>[n.id,n]));render();
      const reasons={page:'概览还有下一页',node_limit:'达到节点限额',edge_limit:'达到关系限额',depth_or_scope:'深度／范围边界外还有关系'};
      status.textContent=`${graph.nodes.length} 个节点 · ${graph.edges.length} 条关系 · 快照 ${graph.revision}`+(data.truncated?' · '+(data.truncation_reasons || []).map(r=>reasons[r] || r).join('、'):'')+'。'+(data.warnings || []).join(' ');
      if(!graph.nodes.length)status.textContent+=' 当前范围尚无可展示的登记节点。';
      if(options.focus && nodes.has(options.focus)){selected=options.focus;hiddenKinds.delete(nodes.get(selected).kind);render();center(selected);showDetails(nodes.get(selected));}
      else if(!hasSavedLayout && !merge)fit();
      return data;
    } catch(error) {if(ticket!==sequence||disposed||error.name==='AbortError')return;status.textContent=error.message;onError(error);}
  }
  async function load(context) {
    save();clearTimeout(saveTimer);abort?.abort();sequence++;
    if(!context.projectId||current?.projectId!==context.projectId)comparisonSource=null;
    current={projectId:context.projectId,objectId:context.objectId || null,userId:context.userId || null,focus:context.focus || null,overview:!!context.overview};
    graph={nodes:[],edges:[]};nodes=new Map();selected=null;highlight.clear();offset=0;details.replaceChildren();restore();render();
    if(!current.projectId){status.textContent='选择作品后查看已登记关系。';overview.hidden=true;body.hidden=false;return;}
    if(current.overview&&!current.objectId&&!current.focus)return loadGrouping();
    overview.hidden=true;body.hidden=false;
    return request(current.focus?{focus:current.focus}:{offset:'0'});
  }
  async function focus(id) {
    if(!current?.projectId)return;
    current.overview=false;overview.hidden=true;body.hidden=false;
    selected=id;
    if(nodes.has(id)){hiddenKinds.delete(nodes.get(id).kind);render();center(id);showDetails(nodes.get(id));return;}
    current.focus=id;offset=0;return request({focus:id});
  }
  async function expand(direction) {if(!selected){status.textContent='先选择一个节点，再展开其上下游。';return;}return request({focus:selected,direction,depth:'1'},{merge:true});}
  async function page(value) {if(value==null)return;offset=value;current.focus=null;return request({offset:String(offset),...(graph.revision!==undefined?{revision:String(graph.revision)}:{})});}
  return {load,focus,refresh:()=>current?load({...current}):Promise.resolve(),destroy(){disposed=true;abort?.abort();sequence++;clearTimeout(saveTimer);save();container.replaceChildren();}};
}
