/* Left rail, add-node menu, element/history drawer, asset library and shortcut
   panel. Shortcut chords are display-only; A3 replaces them by assigning
   globalThis.VSC_CANVAS_SHORTCUTS or by passing resolveShortcutDefinitions(). */
export const DRAWER_DEFAULT_WIDTH=431;
export const DRAWER_MIN_WIDTH=360;
export const DRAWER_MAX_WIDTH=720;
export const DRAWER_WIDTH_STEP=24;
export const DRAWER_WIDTH_KEY='vsc-canvas-left-drawer-width';
export const SIDEBAR_WIDTH_KEY='sidebarWidth';
export const HISTORY_SELECTION_LIMIT=100;
export const HISTORY_PAGE_SIZE=24;

export const CANVAS_SHORTCUT_DEFINITIONS=Object.freeze([
  {id:'creation',title:'创作',items:[
    {id:'group',label:'成组',keys:[{mod:true},{text:'G'}]},
    {id:'mergeStoryboardGroup',label:'合并分镜组',keys:[{mod:true},{text:'⌥'},{text:'G'}]},
    {id:'ungroup',label:'解组',keys:[{mod:true},{text:'⇧'},{text:'G'}]},
    {id:'connect',label:'连线',keys:[{text:'L'}]},
    {id:'duplicateWithEdges',label:'复制节点和连线',keys:[{mod:true},{text:'D'}]},
    {id:'generate',label:'生成',keys:[{mod:true},{text:'Enter'}]},
    {id:'addNode',label:'新建节点',keys:[{text:'Tab'}]},
    {id:'altDragCopy',label:'节点复制',keys:[{text:'Option'},{text:'+拖动节点'}]},
    {id:'altDragDuplicate',label:'创建副本',keys:[{mod:true},{text:'Option'},{text:'+拖动'}]},
  ]},
  {id:'zoom',title:'缩放',items:[
    {id:'zoomIn',label:'放大',keys:[{mod:true},{text:'+'}]},
    {id:'zoomOut',label:'缩小',keys:[{mod:true},{text:'−'}]},
    {id:'fit',label:'适应画布',keys:[{mod:true},{text:'0'}]},
    {id:'pinch',label:'触控板',keys:[{symbol:'pinch'}]},
    {id:'wheel',label:'鼠标',keys:[{symbol:'wheel'}]},
  ]},
  {id:'pan',title:'移动画布',items:[
    {id:'spacePan',label:'键盘',keys:[{text:'Space'},{symbol:'drag'}]},
    {id:'touchPan',label:'触控板',keys:[{symbol:'two-finger'}]},
    {id:'mousePan',label:'鼠标',keys:[{symbol:'middle'}]},
    {id:'select',label:'移动',keys:[{text:'V'}]},
    {id:'hand',label:'抓手工具',keys:[{text:'H'}]},
    {id:'organize',label:'整理画布',keys:[{text:'⌥'},{text:'⇧'},{text:'F'}]},
  ]},
  {id:'other',title:'其他',items:[
    {id:'undo',label:'撤销',keys:[{mod:true},{text:'Z'}]},
    {id:'redo',label:'重做',keys:[{mod:true},{text:'⇧'},{text:'Z'}]},
    {id:'search',label:'画布节点搜索',keys:[{mod:true},{text:'F'}]},
    {id:'delete',label:'删除',keys:[{symbol:'backspace'}]},
  ]},
]);

const SHORTCUT_SYMBOLS={pinch:'捏合',wheel:'滚轮',drag:'拖动',middle:'中键','two-finger':'双指',backspace:'⌫'};

export function resolveShortcutDefinitions(injected){
  if(Array.isArray(injected)&&injected.length)return injected;
  try{const external=globalThis.VSC_CANVAS_SHORTCUTS;if(Array.isArray(external)&&external.length)return external;}catch{}
  return CANVAS_SHORTCUT_DEFINITIONS;
}

export function readDrawerWidth(raw){
  if(raw==null||raw==='')return DRAWER_DEFAULT_WIDTH;
  const n=Number(raw);
  if(!Number.isFinite(n))return DRAWER_DEFAULT_WIDTH;
  return Math.min(DRAWER_MAX_WIDTH,Math.max(DRAWER_MIN_WIDTH,Math.round(n)));
}

export function nextDrawerWidth(base,delta){
  const start=readDrawerWidth(base);
  const stepped=start+Math.round(Number(delta)/DRAWER_WIDTH_STEP)*DRAWER_WIDTH_STEP;
  return Math.min(DRAWER_MAX_WIDTH,Math.max(DRAWER_MIN_WIDTH,stepped));
}

export function hiddenStorageKey(projectId,canvasId){
  return 'vsc-canvas-history-hidden:'+String(projectId||'')+':'+String(canvasId||'');
}

export function readHiddenIds(raw){
  try{const parsed=JSON.parse(raw||'[]');return new Set(Array.isArray(parsed)?parsed.map(String):[]);}catch{return new Set();}
}

export function historyRecordsFromJobs(jobs){
  const records=[];
  for(const job of jobs||[]){
    const outputs=Array.isArray(job.outputs)&&job.outputs.length?job.outputs:[null];
    outputs.forEach((output,index)=>{
      const media=output?.media&&typeof output.media==='object'?output.media:null;
      const mediaId=output?.media_id||media?.id||media?.media_id||null;
      const outputId=output?.id||output?.output_id||'';
      records.push({
        id:output?`${job.id}:${outputId||mediaId||index}`:String(job.id),
        jobId:job.id,
        outputId:String(outputId||''),
        modality:output?.modality||job.modality||'image',
        title:job.purpose||job.title||'历史记录',
        status:job.status||'',
        mediaId:mediaId||null,
      });
    });
  }
  return records;
}

export function historyNodeFromRecord(record,point,id){
  const modality=['image','video','audio','text'].includes(record.modality)?record.modality:'image';
  return {
    id,
    type:modality,
    title:record.title||'历史记录',
    x:point?.x??100,
    y:point?.y??100,
    text:'',
    params:{source:'canvas_history',job_id:record.jobId||record.job_id||'',output_id:record.outputId||record.output_id||''},
    media_id:record.mediaId||record.media_id||null,
    job_id:record.jobId||record.job_id||null,
    group:'',
  };
}

export function toggleHistorySelection(selected,id,on){
  const next=new Set(selected||[]);
  if(!on){next.delete(id);return {selected:next,limited:false};}
  if(next.has(id))return {selected:next,limited:false};
  if(next.size>=HISTORY_SELECTION_LIMIT)return {selected:next,limited:true};
  next.add(id);
  return {selected:next,limited:false};
}

export function applyHiddenIds(records,hidden){
  const hide=hidden instanceof Set?hidden:new Set(hidden||[]);
  return (records||[]).filter(record=>!hide.has(record.id));
}

export function historyDownloadPlan(records,selectedIds){
  const chosen=(records||[]).filter(record=>selectedIds?.has?.(record.id));
  const files=chosen.filter(record=>record.mediaId);
  return {files,missing:chosen.length-files.length};
}

export function historyZipEntryName(record,index){
  const ext=record.modality==='video'?'mp4':record.modality==='audio'?'mp3':'png';
  const base=String(record.title||'history').replace(/[^\w\u4e00-\u9fff.-]+/g,'_').slice(0,40)||'history';
  return `canvas-history/${base}-${index+1}.${ext}`;
}

function crc32(bytes){
  let c=~0;
  for(let i=0;i<bytes.length;i++){c^=bytes[i];for(let k=0;k<8;k++)c=(c>>>1)^(0xedb88320&-(c&1));}
  return ~c>>>0;
}

export function buildZip(files){
  const encoder=new TextEncoder();
  const locals=[];
  const central=[];
  let offset=0;
  for(const file of files||[]){
    const name=encoder.encode(file.name);
    const data=file.data instanceof Uint8Array?file.data:new Uint8Array(file.data||[]);
    const crc=crc32(data);
    const local=new DataView(new ArrayBuffer(30));
    local.setUint32(0,0x04034b50,true);
    local.setUint16(4,20,true);
    local.setUint16(6,0x0800,true);
    local.setUint16(8,0,true);
    local.setUint32(14,crc,true);
    local.setUint32(18,data.length,true);
    local.setUint32(22,data.length,true);
    local.setUint16(26,name.length,true);
    const localBytes=new Uint8Array(local.buffer);
    locals.push(localBytes,name,data);
    const cen=new DataView(new ArrayBuffer(46));
    cen.setUint32(0,0x02014b50,true);
    cen.setUint16(4,20,true);
    cen.setUint16(6,20,true);
    cen.setUint16(8,0x0800,true);
    cen.setUint16(10,0,true);
    cen.setUint32(16,crc,true);
    cen.setUint32(20,data.length,true);
    cen.setUint32(24,data.length,true);
    cen.setUint16(28,name.length,true);
    cen.setUint32(42,offset,true);
    central.push(new Uint8Array(cen.buffer),name);
    offset+=localBytes.length+name.length+data.length;
  }
  const centralSize=central.reduce((sum,part)=>sum+part.length,0);
  const end=new DataView(new ArrayBuffer(22));
  end.setUint32(0,0x06054b50,true);
  end.setUint16(8,(files||[]).length,true);
  end.setUint16(10,(files||[]).length,true);
  end.setUint32(12,centralSize,true);
  end.setUint32(16,offset,true);
  const parts=[...locals,...central,new Uint8Array(end.buffer)];
  const out=new Uint8Array(parts.reduce((sum,part)=>sum+part.length,0));
  let cursor=0;
  for(const part of parts){out.set(part,cursor);cursor+=part.length;}
  return out;
}

export function zipEntryNames(bytes){
  const view=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes||[]);
  const names=[];
  let offset=0;
  const decoder=new TextDecoder();
  while(offset+30<=view.length){
    const sig=view[offset]|(view[offset+1]<<8)|(view[offset+2]<<16)|(view[offset+3]<<24);
    if(sig!==0x04034b50)break;
    const nameLen=view[offset+26]|(view[offset+27]<<8);
    const extraLen=view[offset+28]|(view[offset+29]<<8);
    const size=view[offset+18]|(view[offset+19]<<8)|(view[offset+20]<<16)|(view[offset+21]<<24);
    names.push(decoder.decode(view.subarray(offset+30,offset+30+nameLen)));
    offset+=30+nameLen+extraLen+size;
  }
  return names;
}

function storageGet(key){
  try{if(typeof localStorage!=='undefined'&&localStorage){const value=localStorage.getItem(key);if(value!=null)return value;}}catch{}
  try{if(typeof sessionStorage!=='undefined'&&sessionStorage)return sessionStorage.getItem(key);}catch{}
  return null;
}
function storageSet(key,value){
  try{if(typeof localStorage!=='undefined'&&localStorage){localStorage.setItem(key,value);return true;}}catch{}
  try{if(typeof sessionStorage!=='undefined'&&sessionStorage){sessionStorage.setItem(key,value);return true;}}catch{}
  return false;
}
function browserWindow(){
  try{if(typeof window!=='undefined'&&window)return window;}catch{}
  return globalThis;
}
function browserDocument(){
  try{if(typeof document!=='undefined'&&document)return document;}catch{}
  return globalThis.document;
}

const RAIL_ICONS={
  add:'M12 5v14M5 12h14',
  close:'M6 6l12 12M18 6L6 18',
  elements:'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  history:'M12 8v5l3 2M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9',
  assets:'M3 7V5h6l2 2h10v11H3z',
  shortcuts:'M4 7h16v10H4zM8 11h.01M12 11h.01M16 11h.01M8 15h8',
  guide:'M4 5.5h6.5A2.5 2.5 0 0 1 13 8v11a2.5 2.5 0 0 0-2.5-2.5H4zM20 5.5h-6.5A2.5 2.5 0 0 0 11 8v11a2.5 2.5 0 0 1 2.5-2.5H20z',
  pointer:'M5 3l6.5 16 1.8-6.2L20 11z',
};
const NODE_LABELS={text:'文本',image:'图片',video:'视频',edit:'视频剪辑','director-stage':'导演台','3d-preview':'3D预演',director:'站位导演台',spatial:'三维预演',audio:'音频'};
const ASSET_KIND_NAMES={character:'人设',location:'场景',prop:'道具',blocking:'站位',voice:'音频',style:'风格',costume:'服装',object:'道具',creature:'生物',vehicle:'载具',plant:'植物'};
const ASSET_KIND_OPTIONS=[['character','人设'],['location','场景'],['prop','道具'],['blocking','站位'],['voice','音频']];

function svgIcon(doc,d){
  const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');
  const path=doc.createElementNS(svg.namespaceURI,'path');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('width','18');svg.setAttribute('height','18');svg.setAttribute('aria-hidden','true');
  path.setAttribute('d',d);path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','1.7');path.setAttribute('stroke-linecap','round');path.setAttribute('stroke-linejoin','round');
  svg.append(path);return svg;
}

export function mountCanvasLeftChrome(s,deps){
  const doc=browserDocument();
  const rail=deps.el('nav',null,'cc-rail cld-rail');
  deps.bindAttribute(rail,'aria-label',deps.msg('ui.canvas_tools'));
  const create=deps.el('section',null,'cc-create-menu');
  const buttons={};
  const setPressed=key=>{for(const [name,button] of Object.entries(buttons))if(name!=='add')button.setAttribute('aria-pressed',String(name===key));};
  const addIcon=svgIcon(doc,RAIL_ICONS.add);
  const addButton=deps.button(s,'添加节点',()=>{s.createPoint=null;create.style.removeProperty('left');create.style.removeProperty('top');create.hidden=!create.hidden;});
  addButton.classList.add('cld-add');
  deps.bindAttribute(addButton,'aria-label','添加节点');addButton.title='添加节点';addButton.replaceChildren(addIcon);
  let menuHidden=true;
  const syncMenu=()=>{
    if(menuHidden)create.setAttribute('hidden','');else create.removeAttribute('hidden');
    if(menuHidden)addButton.classList.remove('is-open');else addButton.classList.add('is-open');
    addButton.setAttribute('aria-pressed',String(!menuHidden));
    addIcon.querySelector('path').setAttribute('d',menuHidden?RAIL_ICONS.add:RAIL_ICONS.close);
  };
  Object.defineProperty(create,'hidden',{configurable:true,get(){return menuHidden;},set(value){menuHidden=Boolean(value);syncMenu();}});
  create.hidden=true;
  const iconButton=(key,label,path,fn)=>{
    const button=deps.button(s,label,fn);
    deps.bindAttribute(button,'aria-label',label);button.title=label;button.replaceChildren(svgIcon(doc,path));
    buttons[key]=button;return button;
  };
  buttons.add=addButton;
  const closeThen=fn=>()=>{create.hidden=true;setPressed('');return fn();};
  rail.append(
    addButton,
    iconButton('elements','画布元素',RAIL_ICONS.elements,()=>openBrowser('elements')),
    iconButton('history','历史记录',RAIL_ICONS.history,()=>openBrowser('history')),
    iconButton('assets','资产库',RAIL_ICONS.assets,()=>openAssets()),
    iconButton('shortcuts','快捷键',RAIL_ICONS.shortcuts,()=>openShortcuts()),
    iconButton('guide','创作指引',RAIL_ICONS.guide,()=>deps.openGuide()),
    iconButton('pointer','指针/抓手',RAIL_ICONS.pointer,()=>deps.togglePointer()),
  );
  buttons.pointer.classList.add('cld-pointer');

  create.append(deps.el('h3','添加节点'));
  const extra=deps.el('details');extra.append(deps.el('summary','更多工具'));
  for(const typeKey of ['text','image','video','edit','director-stage','3d-preview','audio','music_mix','processing','director','spatial']){
    const info=deps.types[typeKey];
    const button=deps.take(deps.actions,String(deps.msg('ui.add_value0',{value0:info.label})));
    if(!button)continue;
    button.dataset.nodeType=typeKey;
    if(NODE_LABELS[typeKey])deps.setText(button,NODE_LABELS[typeKey]);
    if(['director-stage','3d-preview'].includes(typeKey)){
      button.dataset.badge='NEW';button.classList.add('cc-has-new-badge');
      const badge=doc.createElement('span');badge.className='cc-new-badge';badge.textContent='NEW';button.append(badge);
    }
    button.addEventListener('click',()=>{create.hidden=true;});
    (['music_mix','processing','director','spatial'].includes(typeKey)?extra:create).append(button);
  }
  const addSpecial=(titleText,subkind,extraParams={},groupName='')=>{
    const button=deps.button(s,'添加'+titleText,()=>{create.hidden=true;deps.change(()=>{
      const id=deps.newId();
      const point=s.createPoint||{x:100+s.document.nodes.length%4*280,y:140+Math.floor(s.document.nodes.length/4)*230};
      s.createPoint=null;
      s.document.nodes.push({id,type:'text',title:titleText,x:point.x,y:point.y,text:'',params:{canvas_subkind:subkind,...extraParams},media_id:null,job_id:null,group:groupName});
      s.selected=new Set([id]);
    });});
    button.dataset.badge='NEW';button.classList.add('cc-has-new-badge');
    const badge=doc.createElement('span');badge.className='cc-new-badge';badge.textContent='NEW';button.append(badge);
    extra.append(button);
  };
  addSpecial('分镜故事板','video_story',{story_rows:JSON.stringify([{shot:'S01',framing:'中景',visual:'主角推门步入雨夜街道',duration:4}])});
  addSpecial('视频拆解','video_breakdown',{});
  addSpecial('分组框','group_frame',{group_color:'#292929',group_locked:false},'分组 1');
  create.append(extra,deps.el('h3','添加资源'));
  const resource=(label,action,fn)=>{
    const button=deps.button(s,label,closeThen(fn));
    button.dataset.action=action;create.append(button);return button;
  };
  resource('上传','upload',()=>deps.uploadResources());
  resource('从资产库导入','library',()=>openAssets());
  resource('从历史记录选择','history',()=>openBrowser('history'));

  function rememberedWidth(){return readDrawerWidth(storageGet(SIDEBAR_WIDTH_KEY)??storageGet(DRAWER_WIDTH_KEY)??s.drawerWidth);}
  function attachResizer(panel){
    const width=rememberedWidth();
    panel.style.width=width+'px';s.drawerWidth=width;
    const resizer=deps.el('div',null,'cc-drawer-resizer');
    deps.bindAttribute(resizer,'aria-label','拖动调整宽度');
    resizer.addEventListener('pointerdown',event=>{
      event.preventDefault();
      const startX=event.clientX,baseW=s.drawerWidth||width;
      const view=browserWindow();
      const move=e=>{if(!deps.live())return;const next=nextDrawerWidth(baseW,e.clientX-startX);s.drawerWidth=next;panel.style.width=next+'px';};
      const up=()=>{view.removeEventListener('pointermove',move);view.removeEventListener('pointerup',up);storageSet(DRAWER_WIDTH_KEY,String(s.drawerWidth));storageSet(SIDEBAR_WIDTH_KEY,String(s.drawerWidth));};
      view.addEventListener('pointermove',move);view.addEventListener('pointerup',up);
    });
    return resizer;
  }
  function openBrowser(tab){
    create.hidden=true;deps.closeSurfaces();setPressed(tab==='history'?'history':'elements');
    const panel=mountBrowserDrawer(s,deps,{initialTab:tab,attachResizer});
    s.root.append(panel);return panel.refresh();
  }
  function openAssets(){
    create.hidden=true;deps.closeSurfaces();setPressed('assets');
    const panel=mountAssetDrawer(s,deps,{attachResizer});
    s.root.append(panel);return panel.refresh();
  }
  function openShortcuts(){
    const existing=s.root.querySelector('.cld-shortcuts');
    create.hidden=true;
    if(existing){existing.remove();setPressed('');return;}
    deps.closeSurfaces();setPressed('shortcuts');
    const panel=mountShortcutPanel(s,deps);
    s.root.append(panel);return panel;
  }
  return {rail,create,openBrowser,openAssets,openShortcuts};
}

function mountShortcutPanel(s,deps){
  const panel=deps.el('section',null,'cld-shortcuts');
  panel.dataset.canvasShortcutPanel='true';
  deps.bindAttribute(panel,'aria-label','快捷键');
  const groups=resolveShortcutDefinitions(deps.shortcuts);
  for(const group of groups){
    const column=deps.el('div',null,'cld-shortcut-col');
    column.append(deps.el('h3',group.title));
    for(const item of group.items||[]){
      const row=deps.el('div',null,'cld-shortcut-row');
      const keys=deps.el('span',null,'cld-keys');
      for(const key of item.keys||[]){
        const chip=deps.el('span',key.mod?'⌘':key.symbol?SHORTCUT_SYMBOLS[key.symbol]||key.symbol:key.text||'','cld-key');
        if(key.symbol)chip.dataset.symbol=key.symbol;
        if(key.mod)chip.dataset.mod='true';
        keys.append(chip);
      }
      row.append(deps.el('span',item.label,'cld-shortcut-label'),keys);
      column.append(row);
    }
    panel.append(column);
  }
  return panel;
}

function mountBrowserDrawer(s,deps,{initialTab,attachResizer}){
  const panel=deps.el('section',null,'cc-elements cc-side-panel cld-drawer cld-elements');
  panel.dataset.cldDrawer='elements';
  const tabs=deps.el('nav',null,'cc-drawer-tabs');
  const toolbar=deps.el('div',null,'cld-browser-tools');
  const body=deps.el('div',null,'cld-browser-body');
  const pager=deps.el('div',null,'cld-pager');
  let activeTab=initialTab==='history'?'history':'elements';
  let filterType='all';
  let query='';
  let batch=false;
  let selected=new Set();
  let offset=0;
  let request=0;
  const hiddenKey=hiddenStorageKey(s.project,s.id);
  let hidden=readHiddenIds(storageGet(hiddenKey));
  const tabElements=deps.button(s,'画布元素',()=>{activeTab='elements';batch=false;selected=new Set();return render();});
  const tabHistory=deps.button(s,'历史记录',()=>{activeTab='history';offset=0;return render();});
  tabs.append(tabElements,tabHistory);
  const search=deps.input('搜索节点名称','');
  search.type='search';
  deps.bindAttribute(search,'placeholder','搜索节点名称');
  search.addEventListener('input',()=>{query=search.value;if(activeTab==='elements')paintElements();else render().catch(error=>deps.notice(error.message));});
  const typeSelect=deps.input('全部',filterType,'select');
  for(const [value,label] of [['all','全部'],['text','文本'],['image','图片'],['video','视频'],['audio','音频']])typeSelect.append(deps.option(value,label));
  typeSelect.addEventListener('change',()=>{filterType=typeSelect.value;offset=0;if(activeTab==='elements')paintElements();else render().catch(error=>deps.notice(error.message));});
  const batchButton=deps.button(s,'批量选择',()=>{batch=!batch;if(!batch)selected=new Set();return render();});
  batchButton.classList.add('cld-batch');
  toolbar.append(search,typeSelect,batchButton);
  const list=deps.el('div',null,'cc-elements-grid3 cld-card-grid');
  body.append(list);
  function paintElements(){
    list.replaceChildren();pager.replaceChildren();batchButton.hidden=true;
    const q=query.trim();
    const matches=s.document.nodes.filter(node=>{
      const typeOk=filterType==='all'||node.type===filterType;
      return typeOk&&(!q||String(node.title||'').includes(q)||String(node.text||'').includes(q));
    });
    for(const node of matches){
      const card=deps.button(s,node.title||deps.types[node.type]?.label||'节点',()=>{
        s.selected=new Set([node.id]);
        if(s.stage){const z=s.document.viewport.zoom||1,ox=s.displayOffset?.x||80,oy=s.displayOffset?.y||48;s.stage.scrollLeft=Math.max(0,(node.x+ox)*z-180);s.stage.scrollTop=Math.max(0,(node.y+oy)*z-120);}
        deps.draw();
      });
      card.className='cc-element-card';card.dataset.nodeType=node.type;
      const thumb=deps.el('span',deps.types[node.type]?.label||node.type,'cc-element-thumb');
      card.prepend(thumb);list.append(card);
    }
    if(!list.children.length)list.append(deps.el('p',matches.length||s.document.nodes.length?deps.msg('ui.no_nodes'):deps.msg('ui.no_nodes'),'cc-panel-empty'));
  }
  function placeRecord(record){
    if(!record.mediaId)throw new Error('该记录没有可放回的媒体');
    if(s.document.nodes.length>=200)throw new Error('画布最多200个节点');
    const id=deps.newId();
    const point=deps.point();
    deps.change(()=>{s.document.nodes.push(historyNodeFromRecord(record,point,id));s.selected=new Set([id]);});
  }
  async function paintHistory(){
    batchButton.hidden=false;
    const token=++request;
    list.replaceChildren(deps.el('p','加载中…','cc-panel-empty'));
    const data=await deps.api(`${deps.base()}/creative-canvas-jobs?include_outputs=true&exclude_hidden=true&limit=${HISTORY_PAGE_SIZE}&offset=${offset}`);
    if(!deps.live()||!panel.isConnected||token!==request||activeTab!=='history')return;
    let records=applyHiddenIds(historyRecordsFromJobs(data.items),hidden);
    const q=query.trim();
    if(q)records=records.filter(record=>String(record.title||'').includes(q)||String(record.status||'').includes(q));
    if(filterType!=='all')records=records.filter(record=>record.modality===filterType);
    list.replaceChildren();
    if(batch){
      const bar=deps.el('div',null,'cld-history-batch');
      bar.append(deps.el('span','已选 '+selected.size+' 项'),deps.button(s,'下载 ZIP',()=>downloadHistory(records)),deps.button(s,'隐藏',()=>confirmHide(records)));
      list.append(bar);
    }
    for(const record of records){
      const card=deps.el('article',null,'cld-history-card');
      card.dataset.historyId=record.id;
      if(batch){
        const check=deps.input('选择 '+record.title);check.type='checkbox';check.className='cld-history-check';check.checked=selected.has(record.id);
        check.addEventListener('change',()=>{
          const result=toggleHistorySelection(selected,record.id,check.checked);
          selected=result.selected;
          if(result.limited){check.checked=false;deps.notice('最多选择 100 条历史记录');}
          const count=list.querySelector('.cld-history-batch span');
          if(count)deps.setText(count,'已选 '+selected.size+' 项');
        });
        card.append(check);
      }
      const title=deps.el('p',record.title+(record.status?' · '+record.status:''));
      const actions=deps.el('div',null,'cld-history-actions');
      const preview=deps.button(s,'查看',()=>previewRecord(record));
      const place=deps.button(s,'导入画布',()=>placeRecord(record));
      place.disabled=!record.mediaId;
      actions.append(preview,place);
      card.append(title,actions);list.append(card);
    }
    if(!records.length)list.append(deps.el('p','暂无生成记录','cc-panel-empty'));
    const page=Math.floor(offset/HISTORY_PAGE_SIZE)+1;
    const total=Number(data.total);
    const hasNext=Number.isFinite(total)?offset+HISTORY_PAGE_SIZE<total:(data.items||[]).length===HISTORY_PAGE_SIZE;
    pager.replaceChildren();
    const prev=deps.button(s,'‹',()=>{offset=Math.max(0,offset-HISTORY_PAGE_SIZE);return render();});
    deps.bindAttribute(prev,'aria-label','上一页');prev.disabled=offset<=0;
    const current=deps.button(s,String(page),()=>{});
    current.classList.add('is-active');current.setAttribute('aria-current','page');
    const next=deps.button(s,'›',()=>{offset+=HISTORY_PAGE_SIZE;return render();});
    deps.bindAttribute(next,'aria-label','下一页');next.disabled=!hasNext;
    pager.append(prev,current,next);
  }
  function previewRecord(record){
    const dialog=deps.el('dialog',null,'cc-asset-preview cld-history-preview');
    deps.bindAttribute(dialog,'aria-label',record.title||'历史记录');
    if(record.mediaId){
      const visual=deps.el(record.modality==='video'?'video':record.modality==='audio'?'audio':'img');
      visual.src=`${deps.base()}/media/${encodeURIComponent(record.mediaId)}/content`;
      if(record.modality==='image')deps.bindAttribute(visual,'alt',record.title||'历史记录');else visual.controls=true;
      dialog.append(visual);
    }else dialog.append(deps.el('p','该记录没有可预览的媒体'));
    const footer=deps.el('footer');
    footer.append(deps.el('strong',record.title||'历史记录'),deps.button(s,'导入画布',()=>{placeRecord(record);dialog.close();}));
    dialog.append(footer,deps.button(s,'×',()=>dialog.close()));
    s.root.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    dialog.showModal?.();
  }
  function confirmHide(records){
    const chosen=records.filter(record=>selected.has(record.id));
    if(!chosen.length)throw new Error('请先选择历史记录');
    const dialog=deps.el('dialog',null,'cld-confirm');
    deps.bindAttribute(dialog,'aria-label','隐藏历史记录');
    dialog.append(deps.el('p',`确认隐藏所选 ${chosen.length} 条历史记录？该操作不会删除画布节点和资源文件。`));
    const actions=deps.el('div',null,'cld-confirm-actions');
    actions.append(deps.button(s,'取消',()=>dialog.close()),deps.button(s,'隐藏',async()=>{
      for(const record of chosen)hidden.add(record.id);
      storageSet(hiddenKey,JSON.stringify([...hidden].slice(-500)));
      const jobIds=[...new Set(chosen.map(record=>record.jobId).filter(Boolean))];
      if(jobIds.length&&typeof deps.headers==='function'){
        try{
          await deps.api(`${deps.base()}/creative-canvas-jobs/visibility`,{method:'POST',headers:deps.headers(),body:JSON.stringify({payload:{job_ids:jobIds,hidden:true},expected_revision:s.revision,idempotency_key:deps.newId()})});
        }catch(error){if(error?.status!==404)throw error;}
      }
      selected=new Set();batch=false;dialog.close();
      deps.notice(`已隐藏 ${chosen.length} 条历史记录`);
      return render();
    }));
    dialog.append(actions);s.root.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    dialog.showModal?.();
  }
  async function downloadHistory(records){
    const plan=historyDownloadPlan(records,selected);
    if(!plan.files.length)throw new Error('所选记录没有可下载资源');
    const fetchImpl=typeof fetch!=='undefined'?fetch:globalThis.fetch;
    const files=[];let failed=0;
    for(const [index,record] of plan.files.entries()){
      try{
        const response=await fetchImpl(`${deps.base()}/media/${encodeURIComponent(record.mediaId)}/content`);
        if(response&&response.ok===false)throw new Error('download failed');
        const bytes=typeof response?.arrayBuffer==='function'?new Uint8Array(await response.arrayBuffer()):new TextEncoder().encode(await response.text());
        files.push({name:historyZipEntryName(record,index),data:bytes});
      }catch{failed++;}
    }
    if(!files.length)throw new Error('所选记录没有可下载资源');
    const bytes=buildZip(files);
    const stamp=new Date();
    const pad=n=>String(n).padStart(2,'0');
    const filename=`canvas-history-${stamp.getFullYear()}${pad(stamp.getMonth()+1)}${pad(stamp.getDate())}-${pad(stamp.getHours())}${pad(stamp.getMinutes())}${pad(stamp.getSeconds())}.zip`;
    const blob=new Blob([bytes],{type:'application/zip'});
    const urlApi=globalThis.URL;
    if(urlApi?.createObjectURL){
      const href=urlApi.createObjectURL(blob);
      const link=browserDocument().createElement('a');
      link.href=href;link.download=filename;link.hidden=true;
      s.root.append(link);link.click?.();link.remove();
      setTimeout(()=>urlApi.revokeObjectURL?.(href),1500);
    }
    if(failed)deps.notice(`已打包 ${files.length} 条，另有 ${failed} 条下载失败`);
    else deps.notice(`已打包 ${files.length} 条`);
    return blob;
  }
  async function render(){
    if(!deps.live()||!panel.isConnected)return;
    tabElements.setAttribute('aria-pressed',String(activeTab==='elements'));
    tabHistory.setAttribute('aria-pressed',String(activeTab==='history'));
    panel.dataset.cldActive=activeTab;
    if(activeTab==='elements')paintElements();
    else await paintHistory();
  }
  panel.append(tabs,toolbar,body,pager,attachResizer(panel));
  panel.refresh=()=>render();
  return panel;
}

function mountAssetDrawer(s,deps,{attachResizer}){
  const panel=deps.el('section',null,'cc-assets cc-side-panel cld-drawer cld-assets');
  panel.dataset.cldDrawer='assets';
  const head=deps.el('header');
  const body=deps.el('div',null,'cc-assets-body');
  let tab='project',project='*',kind='',query='',offset=0,batch=false,request=0;
  const picks=new Map();
  const names=ASSET_KIND_NAMES;
  const projectTab=deps.button(s,'项目资产',()=>{tab='project';batch=false;picks.clear();offset=0;return render();});
  const officialTab=deps.button(s,'官方资产',()=>{tab='official';batch=false;picks.clear();offset=0;return render();});
  const storyTab=deps.button(s,'分镜',()=>{tab='storyboard';batch=false;picks.clear();offset=0;return render();});
  const add=deps.el('a','＋','cc-assets-new');
  add.href='/?'+new URLSearchParams({page:'assets',project:s.project});
  deps.bindAttribute(add,'aria-label',deps.msg('asset.create_asset'));
  head.append(projectTab,officialTab,storyTab,add);
  function recovery(){
    if(s.libraryPending){
      const box=deps.el('div',null,'cc-assets-recovery');
      box.append(deps.el('p',s.libraryPending.result?'原引用已保存，等待读回。':'原官方引用回执未确认；本地修改已保留。'),deps.button(s,'恢复原官方引用',()=>deps.libraryReference(null)));
      if(s.libraryPending.rejected)box.append(deps.button(s,'结束已拒绝请求（保留草稿）',()=>{deps.clearLibraryRejected();return render();}));
      body.append(box);
    }
    if(s.projectPending){
      const box=deps.el('div',null,'cc-assets-recovery');
      box.append(deps.el('p',s.projectPending.result?'项目素材已保存，等待读回。':'项目素材引用回执未确认；本地修改已保留。'),deps.button(s,'恢复原项目素材引用',()=>deps.projectReference(null)));
      if(s.projectPending.rejected)box.append(deps.button(s,'结束已拒绝的项目素材请求',()=>{deps.clearProjectRejected();return render();}));
      body.append(box);
    }
  }
  function projectChoices(){
    const available=deps.projects?.()||[{id:s.project,name:'当前项目'}];
    return available.filter(item=>item&&!item.unavailable&&item.id);
  }
  function cardItem(card,form,ownerProject){
    const source=card.record_kind==='blocking'&&card.source&&form.media_id===card.source.media_id?{kind:'blocking',workflow_id:card.source.workflow_id,version_id:card.source.version_id,episode_id:card.source.episode_id,unit_key:card.source.unit_key,media_id:card.source.media_id,spatial_export_id:card.source.spatial_export_id}:form.version_id&&form.media_id?{kind:'asset_form',asset_id:card.id,form_version_id:form.version_id,media_id:form.media_id}:null;
    return {kind:'project',project_id:ownerProject,asset_id:card.record_kind==='blocking'?null:card.id,form_version_id:form.version_id,media_id:form.media_id,source,title:card.name+((card.forms?.length||0)>1?' · '+form.name:''),modality:card.asset_kind==='voice'?'audio':'image',recordKind:card.asset_kind,assetRevision:card.revision||0,formKey:form.form_key||'master',formVersionId:form.version_id||null,assetName:card.name};
  }
  async function writeAsset(path,payload){
    const headers=typeof deps.headers==='function'?deps.headers():{'Content-Type':'application/json'};
    const result=await deps.api(`${deps.base()}${path}`,{method:'POST',headers,body:JSON.stringify({payload,expected_revision:s.revision,idempotency_key:deps.newId()})});
    if(result?.revision!=null)deps.revision(result.revision);
    return result;
  }
  function renameProjectAsset(item){
    const dialog=deps.el('dialog',null,'cld-confirm');
    deps.bindAttribute(dialog,'aria-label','重命名资产');
    const field=deps.input('资产名称',item.assetName||item.title);
    const actions=deps.el('div',null,'cld-confirm-actions');
    actions.append(deps.button(s,'取消',()=>dialog.close()),deps.button(s,'保存',async()=>{
      const name=field.value.trim();
      if(!name)throw new Error('请填写资产名称');
      await writeAsset('/asset-cards',{asset_id:item.asset_id,name,asset_kind:item.recordKind,base_revision:item.assetRevision||0,forms:[{form_key:item.formKey||'master',name:'默认',base_version_id:item.formVersionId||null,media_id:item.media_id}]});
      dialog.close();deps.notice('已保存到资产库');return render();
    }));
    dialog.append(deps.el('p','重命名资产'),field,actions);s.root.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal?.();
  }
  function deleteProjectAsset(item){
    const dialog=deps.el('dialog',null,'cld-confirm');
    deps.bindAttribute(dialog,'aria-label','删除资产');
    const actions=deps.el('div',null,'cld-confirm-actions');
    actions.append(deps.button(s,'取消',()=>dialog.close()),deps.button(s,'删除',async()=>{
      await writeAsset('/asset-cards/batch-recycle',{asset_ids:[item.asset_id],reason:'从画布资产栏删除'});
      dialog.close();deps.notice('已移入回收站');return render();
    }));
    dialog.append(deps.el('p',`确认删除「${item.assetName||item.title}」？资产卡将移入回收站。`),actions);s.root.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal?.();
  }
  function paintProjectCard(item,key){
    const article=deps.el('article',null,'cc-asset-item');
    const cover=deps.el('div',null,'cc-asset-cover');
    const open=deps.button(s,'',()=>deps.projectPreview(item));
    open.className='cc-asset-open';
    deps.bindAttribute(open,'aria-label',deps.msg('gallery.preview',{name:item.title}));
    if(item.media_id){
      const visual=deps.el(item.modality==='audio'?'audio':'img');
      visual.src='/api/v1/projects/'+encodeURIComponent(item.project_id)+'/media/'+encodeURIComponent(item.media_id)+'/content';
      if(item.modality==='audio')visual.controls=true;
      else{deps.bindAttribute(visual,'alt',item.title);visual.addEventListener('error',()=>{visual.hidden=true;cover.append(deps.el('span',deps.msg('gallery.preview_unavailable'),'cc-asset-unavailable'));},{once:true});}
      open.append(visual);
      open.draggable=item.project_id===s.project||!!item.source;
      open.addEventListener('dragstart',event=>deps.dragAsset(event,item));
    }else open.append(deps.el('span',names[item.recordKind]||'资产'));
    cover.append(open,deps.el('small',names[item.recordKind]||'资产','cc-asset-kind'));
    if(batch&&item.media_id){
      const check=deps.input('选择 '+item.title);check.type='checkbox';check.className='cc-asset-check';check.checked=picks.has(key);
      check.addEventListener('change',()=>{check.checked?picks.set(key,item):picks.delete(key);paintBatch();});
      cover.append(check);
    }else{
      const send=deps.button(s,deps.msg('ui.send_to_canvas'),()=>item.project_id===s.project?deps.addProjectForm(item):deps.projectReference(item));
      send.className='cc-asset-send';
      send.disabled=!item.media_id||(item.project_id!==s.project&&!item.source);
      cover.append(send);
    }
    const caption=deps.el('p',item.title);
    if(item.asset_id){
      caption.append(deps.button(s,'重命名',()=>renameProjectAsset(item)),deps.button(s,'删除',()=>deleteProjectAsset(item)));
    }
    if(item.media_id)caption.append(deps.button(s,'加入 Agent 引用',()=>{
      s.agentAttachments=Array.isArray(s.agentAttachments)?s.agentAttachments:[];
      if(!s.agentAttachments.some(row=>row.id===item.media_id))s.agentAttachments.push({id:item.media_id,name:item.assetName||item.title,kind:'asset'});
      s.plgAgentRefs=Array.isArray(s.plgAgentRefs)?s.plgAgentRefs:[];
      s.plgAgentRefs.push({id:item.media_id,name:item.assetName||item.title,kind:'asset'});
      deps.notice('已加入 Agent 引用');
    }));
    article.append(cover,caption);
    return article;
  }
  const list=deps.el('div',null,'cc-asset-grid');
  const paging=deps.el('div',null,'cc-assets-paging');
  const bar=deps.el('div',null,'cc-assets-batch');
  function paintBatch(){
    bar.replaceChildren();
    if(!batch)return;
    bar.append(deps.el('span','已选 '+picks.size+' 项'),deps.button(s,'导入选中',()=>{
      const items=[...picks.values()];
      if(!items.length)throw new Error('请先选择要导入的资产形态');
      if(tab==='official'){
        if(items.length>1)throw new Error('官方资产一次只能引用一条，请先等待上一条读回');
        return deps.libraryReference(items[0]);
      }
      const local=items.filter(item=>item.project_id===s.project&&item.media_id);
      if(!local.length)throw new Error('跨项目素材可逐项发送到画布。');
      if(s.document.nodes.length+local.length>200)throw new Error('画布最多200个节点，请减少本次选择');
      deps.change(()=>{for(const item of local)deps.appendProjectForm(item);});
      if(local.length!==items.length)deps.notice('跨项目素材请逐项发送，本次只导入当前项目的素材');
      picks.clear();batch=false;return render();
    }));
  }
  async function render(){
    if(!deps.live()||!panel.isConnected)return;
    request++;picks.clear();clearTimeout(s.assetSearchTimer);
    body.replaceChildren();
    projectTab.setAttribute('aria-pressed',String(tab==='project'));
    officialTab.setAttribute('aria-pressed',String(tab==='official'));
    storyTab.setAttribute('aria-pressed',String(tab==='storyboard'));
    add.hidden=tab!=='project';
    recovery();
    const filters=deps.el('div',null,'cc-project-asset-filters');
    if(tab!=='official'){
      const projects=deps.input('资产项目',project,'select');
      projects.append(deps.option('*','所有项目'));
      for(const item of projectChoices())projects.append(deps.option(item.id,item.name||item.id));
      if(![...projects.options||[]].some(option=>option.value===project))project=s.project;
      projects.value=project;
      projects.addEventListener('change',()=>{project=projects.value;batch=false;offset=0;render().catch(error=>deps.notice(error.message));});
      filters.append(projects);
    }
    const types=deps.input(deps.msg('asset.asset_type'),kind,'select');
    types.append(deps.option('',deps.msg('common.all')));
    for(const [value,title] of ASSET_KIND_OPTIONS)types.append(deps.option(value,title));
    types.value=kind;
    types.addEventListener('change',()=>{kind=types.value;offset=0;render().catch(error=>deps.notice(error.message));});
    const search=deps.input(deps.msg('ui.search_assets'),query);
    search.type='search';deps.bindAttribute(search,'placeholder','搜索资产...');
    search.addEventListener('input',()=>{query=search.value;clearTimeout(s.assetSearchTimer);s.assetSearchTimer=setTimeout(()=>show().catch(error=>deps.notice(error.message)),250);});
    search.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();clearTimeout(s.assetSearchTimer);show().catch(error=>deps.notice(error.message));}});
    const toggle=deps.button(s,batch?'取消批量':'批量导入画布',()=>{batch=!batch;return render();});
    toggle.classList.add('cld-batch');
    const crossProject=tab!=='official'&&project!=='*'&&project!==s.project;
    toggle.disabled=crossProject;
    if(toggle.disabled)deps.bindAttribute(toggle,'title','跨项目素材可逐项发送到画布。');
    filters.append(types,search,toggle);
    body.append(filters);
    if(crossProject)body.append(deps.el('p','可将固定素材发送至当前画布。','cc-assets-scope-note'));
    body.append(list,paging,bar);
    paintBatch();
    await show(offset);
  }
  async function show(nextOffset=0){
    const read=++request;offset=nextOffset;
    list.replaceChildren(deps.el('p','加载中…','cc-panel-empty'));paging.replaceChildren();
    try{
      if(tab==='official')await showOfficial(read);
      else if(tab==='storyboard')await showStoryboard(read);
      else await showProject(read);
    }catch(error){
      if(!deps.live()||!panel.isConnected||read!==request)return;
      list.replaceChildren(deps.el('p',error.message||'加载失败','cc-panel-empty'));
      throw error;
    }
  }
  async function showProject(read){
    const params=new URLSearchParams({query,asset_kind:kind,...deps.categoryParams(kind),offset:String(offset),limit:'24',favorites:'false'});
    const ids=project==='*'?projectChoices().map(item=>item.id):[project];
    const rows=[];
    let nextOffset=null;
    let revisionValue=null;
    for(const projectId of ids){
      const data=await deps.api('/api/v1/projects/'+encodeURIComponent(projectId)+'/asset-cards?'+params);
      if(!deps.live()||!panel.isConnected||tab!=='project'||read!==request)return;
      if(projectId===s.project&&data?.revision!=null)revisionValue=data.revision;
      for(const card of data?.items||[])rows.push({card,projectId});
      if(data?.next_offset!=null)nextOffset=data.next_offset;
    }
    if(revisionValue!=null)deps.revision(revisionValue);
    list.replaceChildren();
    for(const {card,projectId} of rows){
      const forms=card.forms?.length?card.forms:[{name:'',media_id:card.record_kind==='blocking'?card.preview?.media_id:null,version_id:null}];
      forms.forEach((form,index)=>{
        const owner=card.project_id||projectId;
        const item=cardItem(card,form,owner);
        list.append(paintProjectCard(item,projectId+':'+card.id+':'+(form.form_key||form.version_id||index)));
      });
    }
    if(!list.children.length)list.append(deps.el('p','暂无资产','cc-panel-empty'));
    paintPager({items:rows,next_offset:nextOffset});
  }
  async function showOfficial(read){
    const params=new URLSearchParams({source:'official',order_by:'latest',media_only:'true',query,offset:String(offset),limit:'24'});
    if(kind)params.set('asset_kind',kind);
    const data=await deps.api('/api/v1/asset-center?'+params);
    if(!deps.live()||!panel.isConnected||tab!=='official'||read!==request)return;
    list.replaceChildren();
    for(const row of data.items||[]){
      const member=(row.members||[]).find(item=>!kind||item.modality===(kind==='voice'?'audio':'image'))||row.members?.[0];
      if(!member)continue;
      const article=deps.el('article',null,'cc-asset-item');
      const cover=deps.el('div',null,'cc-asset-cover');
      const open=deps.button(s,'',()=>{});
      open.className='cc-asset-open';
      deps.bindAttribute(open,'aria-label',deps.msg('gallery.preview',{name:row.title||'官方资产'}));
      if(member.preview_url){const visual=deps.el(member.modality==='audio'?'audio':'img');visual.src=member.preview_url;if(member.modality!=='audio')deps.bindAttribute(visual,'alt',row.title||'官方资产');else visual.controls=true;open.append(visual);}
      else open.append(deps.el('span',names[row.official?.asset_kind]||'官方'));
      const selection=()=>deps.librarySelection(row,member);
      open.draggable=true;open.addEventListener('dragstart',event=>deps.dragAsset(event,selection()));
      cover.append(open,deps.el('small','官方','cc-asset-kind'));
      const key=row.version_id+':'+member.member_key;
      if(batch){
        const check=deps.input('选择 '+(row.title||'官方资产'));check.type='checkbox';check.className='cc-asset-check';
        check.addEventListener('change',()=>{if(check.checked){try{picks.set(key,selection());}catch(error){check.checked=false;throw error;}}else picks.delete(key);paintBatch();});
        cover.append(check);
      }else{
        const send=deps.button(s,deps.msg('ui.send_to_canvas'),()=>deps.libraryReference(selection()));
        send.className='cc-asset-send';cover.append(send);
      }
      article.append(cover,deps.el('p',row.title||'官方资产'));list.append(article);
    }
    if(!list.children.length)list.append(deps.el('p','暂无资产','cc-panel-empty'));
    paintPager(data);
  }
  async function showStoryboard(read){
    const projects=project==='*'?projectChoices().map(item=>item.id):[project];
    const rows=[];
    for(const projectId of projects){
      const data=await deps.api('/api/v1/projects/'+encodeURIComponent(projectId)+'/classic-production/storyboard-references?episode_id='+encodeURIComponent(projectId===s.project?s.episode||'':''));
      if(!deps.live()||!panel.isConnected||tab!=='storyboard'||read!==request)return;
      for(const item of data.items||[])rows.push({projectId,item});
    }
    list.replaceChildren();
    const q=query.trim();
    for(const {projectId,item} of rows){
      const images=item.images||[];
      const image=images.find(entry=>entry.selected)||images[0];
      const mediaId=image?.media_id||item.selected_media_id||null;
      const title=item.display_code?item.display_code+' · '+(item.title||image?.name||'分镜'):(item.title||image?.name||'分镜');
      if(q&&!title.includes(q)&&!String(item.serial_number||'').includes(q))continue;
      const card={kind:'project',project_id:projectId,asset_id:null,form_version_id:null,media_id:mediaId,source:null,title,modality:'image',recordKind:'storyboard'};
      if(kind==='voice'||kind==='audio')continue;
      list.append(paintProjectCard(card,projectId+':'+(item.shot_id||title)));
    }
    if(!list.children.length)list.append(deps.el('p','暂无资产','cc-panel-empty'));
  }
  function paintPager(data){
    paging.replaceChildren();
    if(offset)paging.append(deps.button(s,deps.msg('common.previous_page'),()=>show(Math.max(0,offset-24))));
    if(data?.next_offset!=null)paging.append(deps.button(s,deps.msg('common.next_page'),()=>show(data.next_offset)));
    else if((data?.items||[]).length===24)paging.append(deps.button(s,deps.msg('common.next_page'),()=>show(offset+24)));
  }
  panel.append(head,body,attachResizer(panel));
  panel.refresh=()=>render();
  s.assetRefresh=()=>deps.live()&&panel.isConnected?panel.refresh().catch(error=>deps.notice(error.message)):null;
  return panel;
}
