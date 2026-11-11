import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {createMediaLibrary} from '../../../src/vsc/interfaces/web/static/media-library.js';
import {createProductionPlatform} from '../../../src/vsc/interfaces/web/static/production-platform.js';
import {setLocale} from '../../../src/vsc/interfaces/web/static/i18n.js';

const {Document,Element}=createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const FIXED_NOW='2026-11-11T12:00:00.000Z';

function makeRow(i,overrides={}){
  const projectId=overrides.project_id||'p1';
  const id=overrides.id||'media-'+i;
  const modality=overrides.modality||'image';
  return {
    id,
    project_id:projectId,
    project_name:overrides.project_name||(projectId==='p1'?'项目一':'项目二'),
    episode_id:overrides.episode_id!==undefined?overrides.episode_id:'ep1',
    episode_name:overrides.episode_name!==undefined?overrides.episode_name:'第一集',
    name:overrides.name||`测试资源-${i}`,
    modality,
    category:'category' in overrides?overrides.category:'shot_image',
    category_reason:overrides.category_reason||'shot_generation',
    created_at:'created_at' in overrides?overrides.created_at:'2026-11-10T08:00:00Z',
    updated_at:'2026-11-10T08:00:00Z',
    width:'width' in overrides?overrides.width:1920,
    height:'height' in overrides?overrides.height:1080,
    duration_ms:'duration_ms' in overrides?overrides.duration_ms:(modality==='image'?null:4000),
    content_url:`/api/v1/projects/${projectId}/media/${id}/content`,
    preview_url:'preview_url' in overrides?overrides.preview_url:null,
    poster_url:'poster_url' in overrides?overrides.poster_url:null,
    actions:overrides.actions||{
      source:{available:true,href:`/?project=${projectId}&page=classic-production&scope=shot-${i}&episode=ep1&kind=${modality}`},
      reuse:{available:false,reason_code:'configuration_unavailable'},
      download:{available:true,href:`/api/v1/projects/${projectId}/media/${id}/content?download=true`},
    },
    ...overrides,
  };
}

function setup({rows,count=3,api,projects,episodes,navigate,now=FIXED_NOW}={}){
  setLocale('zh-cn',{persist:false});
  const document=new Document(''),root=document.createElement('section');
  const docListeners=new Map();
  document.hidden=false;
  document.addEventListener=(type,fn)=>{if(!docListeners.has(type))docListeners.set(type,new Set());docListeners.get(type).add(fn);};
  document.removeEventListener=(type,fn)=>{docListeners.get(type)?.delete(fn);};
  document.dispatchVisibility=hidden=>{document.hidden=hidden;for(const fn of [...(docListeners.get('visibilitychange')||[])])fn({type:'visibilitychange'});};
  document.listenerCount=type=>docListeners.get(type)?.size||0;
  document.body.append(root);
  globalThis.document=document;
  if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
  const winListeners=new Map();
  globalThis.window={
    innerWidth:1414,innerHeight:762,
    addEventListener(type,fn){if(!winListeners.has(type))winListeners.set(type,new Set());winListeners.get(type).add(fn);},
    removeEventListener(type,fn){winListeners.get(type)?.delete(fn);},
    dispatchKey(key){for(const fn of [...(winListeners.get('keydown')||[])])fn({key,preventDefault(){}});},
    listenerCount(type){return winListeners.get(type)?.size||0;},
  };
  const session={actor:'human',identityId:'id-1',workspaceId:'ws-1',csrf:'csrf',writeAvailable:true};
  const dataset=rows||Array.from({length:count},(_,i)=>makeRow(i));
  const calls=[],notices=[],navigations=[];
  const ctx={
    session:()=>session,
    now:()=>now,
    notice:text=>notices.push(String(text)),
    navigate:async(...args)=>{navigations.push(args);await navigate?.(...args);},
    projects:projects||(async()=>({items:[{id:'p1',name:'项目一',storage_policy:'postgres-series-v1'},{id:'p2',name:'项目二',storage_policy:'postgres-series-v1'}]})),
    episodes:episodes||(async p=>({items:[{id:p==='p1'?'ep1':'ep2',title:p==='p1'?'第一集':'第二项目首集'}]})),
    api:async(url,options={})=>{
      const call={url,options};calls.push(call);
      if(api){const custom=await api(call);if(custom!==undefined)return custom;}
      if(url.startsWith('/api/v1/project-media?')){
        const q=new URLSearchParams(url.split('?')[1]),start=Number(q.get('offset')||0),lim=Number(q.get('limit')||20);
        const filtered=dataset.filter(r=>(!q.get('project_id')||r.project_id===q.get('project_id'))&&(!q.get('episode_id')||r.episode_id===q.get('episode_id'))&&(!q.get('category')||r.category===q.get('category')));
        const slice=filtered.slice(start,start+lim);
        return {items:slice,total:filtered.length,offset:start,limit:lim,next_offset:start+slice.length<filtered.length?start+slice.length:null};
      }
      const detailMatch=url.match(/^\/api\/v1\/projects\/([^/]+)\/media\/([^/]+)\/catalog-detail$/);
      if(detailMatch){
        const [,pid,mid]=detailMatch.map(decodeURIComponent);
        const found=dataset.find(r=>r.project_id===pid&&r.id===mid);
        if(!found)throw Object.assign(new Error('not found'),{status:404});
        return {...found,prompt:'固定提示词 '+found.id,model:{id:'m1',name:'seedream-v3',version:'2.1',available:true},aspect_ratio:'16:9',resolution_label:'2K'};
      }
      throw new Error('unexpected route '+url);
    },
  };
  const library=createMediaLibrary(root,ctx);
  return {
    document,root,ctx,library,session,dataset,calls,notices,navigations,
    lists:()=>calls.filter(c=>c.url.startsWith('/api/v1/project-media?')),
    details:()=>calls.filter(c=>c.url.includes('/catalog-detail')),
    mutations:()=>calls.filter(c=>c.options.method&&c.options.method!=='GET'),
  };
}

test('initial load uses limit=20 without free-text search or sort controls and performs zero writes',async()=>{
  const h=setup({count:5});
  await h.library.load();
  const q=new URLSearchParams(h.lists()[0].url.split('?')[1]);
  assert.equal(q.get('offset'),'0');
  assert.equal(q.get('limit'),'20');
  assert.equal(q.has('query'),false);
  assert.equal(q.has('order'),false);
  assert.equal(h.root.querySelectorAll('input').length,0);
  const selects=h.root.querySelector('.ml-filters').querySelectorAll('select');
  assert.equal(selects.length,3);
  assert.equal(selects[1].disabled,true);
  assert.deepEqual(selects[2].options.map(o=>o.value),['','asset_image','shot_image','composite_video','canvas_image','canvas_audio','canvas_video']);
  assert.equal(h.root.querySelectorAll('.ml-card').length,5);
  assert.ok(h.root.querySelector('.ml-total').textContent.includes('共 5 个资源'));
  assert.equal(h.mutations().length,0);
  h.library.suspend();
});

test('limit=20 continuation deduplicates by project_id:id, preserves rows on continuation failure and retries same offset',async()=>{
  let failContinuation=true;
  const rows=Array.from({length:41},(_,i)=>makeRow(i,{project_id:i%2===0?'p1':'p2'}));
  const h=setup({
    rows,
    api:async call=>{
      if(call.url.includes('offset=20')&&failContinuation){
        failContinuation=false;
        throw new Error('continuation offline');
      }
    },
  });
  await h.library.load();
  assert.equal(h.root.querySelectorAll('.ml-card').length,20);
  await h.library.loadMore();
  assert.equal(h.root.querySelectorAll('.ml-card').length,20);
  assert.ok(h.root.textContent.includes('continuation offline'));
  await h.root.querySelector('.ml-retry').click();
  assert.equal(h.root.querySelectorAll('.ml-card').length,40);
  const secondBatchUrl=h.lists().filter(c=>c.url.includes('offset=20'))[1].url;
  assert.equal(new URLSearchParams(secondBatchUrl.split('?')[1]).get('limit'),'20');
  await h.library.loadMore();
  assert.equal(h.root.querySelectorAll('.ml-card').length,41);
  assert.ok(h.root.textContent.includes('没有更多资源了'));
  h.library.suspend();
});

test('project change clears episode filter immediately and discards stale episode responses',async()=>{
  const slowP1=deferred(),startedP1=deferred();
  const h=setup({
    rows:[makeRow(0,{project_id:'p1',episode_id:'ep1'}),makeRow(1,{project_id:'p2',episode_id:'ep2'})],
    episodes:async p=>{
      if(p==='p1'){startedP1.resolve();return slowP1.promise;}
      return {items:[{id:'ep2',title:'项目二剧集'}]};
    },
  });
  await h.library.load();
  const [projectSel,episodeSel]=h.root.querySelector('.ml-filters').querySelectorAll('select');
  projectSel.value='p1';
  const p1Change=projectSel.dispatch('change');
  await startedP1.promise;
  projectSel.value='p2';
  await projectSel.dispatch('change');
  slowP1.resolve({items:[{id:'stale-ep',title:'旧剧集'}]});
  await p1Change;
  assert.equal(episodeSel.disabled,false);
  assert.equal(episodeSel.value,'');
  assert.equal(episodeSel.options.some(o=>o.value==='stale-ep'),false);
  assert.equal(episodeSel.options.some(o=>o.value==='ep2'),true);
  episodeSel.value='ep2';
  await episodeSel.dispatch('change');
  const lastQuery=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);
  assert.equal(lastQuery.get('project_id'),'p2');
  assert.equal(lastQuery.get('episode_id'),'ep2');
  h.library.suspend();
});

test('six categories and dual-month date picker shortcuts, two-click ordering and clear button send exact ISO bounds',async()=>{
  const h=setup({rows:[makeRow(0,{category:'canvas_image'})]});
  await h.library.load();
  const categorySel=h.root.querySelector('.ml-filter-category');
  categorySel.value='canvas_image';
  await categorySel.dispatch('change');
  assert.equal(new URLSearchParams(h.lists().at(-1).url.split('?')[1]).get('category'),'canvas_image');

  await h.root.querySelector('.ml-date-trigger').click();
  assert.equal(h.root.querySelector('.ml-date-popover').hidden,false);
  assert.equal(h.root.querySelectorAll('.ml-month-panel').length,2);
  const shortcuts=h.root.querySelectorAll('.ml-shortcut');
  assert.deepEqual(shortcuts.map(b=>b.dataset.shortcut),['today','yesterday','day_before','this_month','last_month']);
  await shortcuts.find(b=>b.dataset.shortcut==='last_month').click();
  assert.equal(h.root.querySelector('.ml-date-popover').hidden,true);
  const shortcutParams=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);
  assert.equal(shortcutParams.get('created_after'),new Date(2026,9,1,0,0,0,0).toISOString());
  assert.equal(shortcutParams.get('created_before'),new Date(2026,10,1,0,0,0,0).toISOString());

  // Re-open and pick reversed dates (15th then 5th) -> auto-ordered [2026-10-05, 2026-10-15].
  await h.root.querySelector('.ml-date-trigger').click();
  const days=h.root.querySelectorAll('.ml-day');
  await days.find(b=>b.dataset.date==='2026-10-15').click();
  assert.equal(h.root.querySelector('.ml-date-popover').hidden,false);
  await days.find(b=>b.dataset.date==='2026-10-05').click();
  assert.equal(h.root.querySelector('.ml-date-popover').hidden,true);
  const rangeParams=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);
  assert.equal(rangeParams.get('created_after'),new Date(2026,9,5,0,0,0,0).toISOString());
  assert.equal(rangeParams.get('created_before'),new Date(2026,9,16,0,0,0,0).toISOString());

  await h.root.querySelector('.ml-date-clear').click();
  const clearedParams=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);
  assert.equal(clearedParams.has('created_after'),false);
  assert.equal(clearedParams.has('created_before'),false);
  h.library.suspend();
});

test('unknown dimensions, unknown duration and null category never fabricate badges or 00:00 values',async()=>{
  const h=setup({
    rows:[
      makeRow(0,{modality:'video',category:null,width:null,height:null,duration_ms:null,actions:{source:{available:false,reason_code:'ambiguous_source'},reuse:{available:false,reason_code:'configuration_unavailable'},download:{available:false,reason_code:'media_unavailable'}}}),
      makeRow(1,{modality:'audio',category:'canvas_audio',width:null,height:null,duration_ms:0}),
    ],
  });
  await h.library.load();
  const cards=h.root.querySelectorAll('.ml-card');
  assert.equal(cards[0].querySelector('.ml-duration'),null);
  assert.equal(cards[0].querySelector('.ml-badge'),null);
  assert.equal(cards[0].querySelector('.ml-dimensions'),null);
  assert.equal(cards[0].querySelector('.ml-card-actions'),null);
  assert.equal(cards[0].textContent.includes('00:00'),false);
  assert.equal(cards[0].textContent.includes('null'),false);
  assert.equal(cards[1].querySelector('.ml-duration'),null);
  assert.equal(cards[1].querySelector('.ml-badge').textContent,'画布音频');
  h.library.suspend();
});

test('source and classic_fixed_draft reuse follow backend actions per row project_id without faking asset/canvas reuse or shares',async()=>{
  const h=setup({
    rows:[
      makeRow(0,{
        id:'shot-img',project_id:'p2',category:'shot_image',
        actions:{
          source:{available:true,href:'/?project=p2&page=classic-production&scope=shot-22&episode=ep2&kind=image'},
          reuse:{available:true,kind:'classic_fixed_draft',href:'/?page=classic-production&project=p2&scope=shot-22&kind=image&reuse_media=shot-img'},
          download:{available:true,href:'/api/v1/projects/p2/media/shot-img/content?download=true'},
        },
      }),
      makeRow(1,{
        id:'asset-img',project_id:'p1',category:'asset_image',
        actions:{
          source:{available:true,href:'/?project=p1&page=assets&scope=asset-7'},
          reuse:{available:false,reason_code:'configuration_unavailable'},
          download:{available:true,href:'/api/v1/projects/p1/media/asset-img/content?download=true'},
        },
      }),
      makeRow(2,{
        id:'canvas-vid',project_id:'p2',modality:'video',category:'canvas_video',
        actions:{
          source:{available:true,href:'/?project=p2&page=creative-canvas&task_target=cv-9&episode=ep2'},
          reuse:{available:false,reason_code:'configuration_unavailable'},
          download:{available:true,href:'/api/v1/projects/p2/media/canvas-vid/content?download=true'},
        },
      }),
    ],
  });
  await h.library.load();
  const cards=h.root.querySelectorAll('.ml-card');
  assert.ok(cards[0].querySelector('.ml-action-reuse'));
  assert.equal(cards[1].querySelector('.ml-action-reuse'),null);
  assert.equal(cards[2].querySelector('.ml-action-reuse'),null);

  await cards[0].querySelector('.ml-action-reuse').click();
  assert.deepEqual(h.navigations[0],['classic-production','shot-22','p2',{kind:'image',reuse_media:'shot-img'}]);

  await cards[2].querySelector('.ml-action-source').click();
  assert.deepEqual(h.navigations[1],['creative-canvas',null,'p2',{task_target:'cv-9',episode:'ep2'}]);
  assert.equal(h.mutations().length,0);
  h.library.suspend();
});

test('image viewer sequences images only, uses per-row project_id, aborts stale detail fetches and restores focus',async()=>{
  const firstDetail=deferred(),firstStarted=deferred();
  let abortedFirst=false;
  const h=setup({
    rows:[
      makeRow(0,{id:'img-1',project_id:'p1',modality:'image',category:'asset_image',width:1024,height:1024}),
      makeRow(1,{id:'vid-mid',project_id:'p1',modality:'video',category:'composite_video',duration_ms:5000}),
      makeRow(2,{id:'aud-mid',project_id:'p2',modality:'audio',category:'canvas_audio',duration_ms:8000}),
      makeRow(3,{id:'img-2',project_id:'p2',modality:'image',category:'canvas_image',width:1920,height:1080}),
    ],
    api:async call=>{
      if(call.url==='/api/v1/projects/p1/media/img-1/catalog-detail'){
        call.options.signal.addEventListener('abort',()=>{abortedFirst=true;});
        firstStarted.resolve();
        return firstDetail.promise;
      }
    },
  });
  await h.library.load();
  const cards=h.root.querySelectorAll('.ml-card');
  const firstOpenBtn=cards[0].querySelector('.ml-open');
  await firstOpenBtn.click();
  await firstStarted.promise;

  const viewer=h.document.querySelector('.ml-image-viewer');
  assert.ok(viewer);
  assert.equal(viewer.querySelector('.ml-viewer-counter').textContent,'1 / 2');

  // Step next -> skips video and audio, jumps straight to img-2 in p2, and aborts img-1 detail request!
  await viewer.querySelector('.ml-viewer-next').click();
  assert.equal(abortedFirst,true);
  firstDetail.resolve({id:'img-1',project_id:'p1',content_url:'/api/v1/projects/p1/media/img-1/content',prompt:'不应显示的旧详情',actions:{}});
  await Promise.resolve();

  assert.equal(viewer.querySelector('.ml-viewer-counter').textContent,'2 / 2');
  assert.equal(h.details().at(-1).url,'/api/v1/projects/p2/media/img-2/catalog-detail');
  assert.ok(viewer.querySelector('.ml-viewer-sidebar').textContent.includes('固定提示词 img-2'));
  assert.equal(viewer.querySelector('.ml-viewer-sidebar').textContent.includes('不应显示的旧详情'),false);

  // Fold and unfold 360px sidebar.
  await viewer.querySelector('.ml-viewer-fold').click();
  assert.equal(viewer.querySelector('.ml-viewer-sidebar').hidden,true);
  await viewer.querySelector('.ml-viewer-fold').click();
  assert.equal(viewer.querySelector('.ml-viewer-sidebar').hidden,false);

  await viewer.querySelector('.ml-viewer-close').click();
  assert.equal(h.document.querySelector('.ml-image-viewer'),null);
  assert.equal(h.document.activeElement,firstOpenBtn);
  assert.equal(globalThis.window.listenerCount('keydown'),0);
  h.library.suspend();
});

test('standalone AV preview pauses/unloads player and cleans up listeners and controllers on close and suspend',async()=>{
  let failOnce=true;
  const h=setup({
    rows:[makeRow(0,{id:'vid-1',project_id:'p2',modality:'video',category:'composite_video',duration_ms:7000})],
    api:async call=>{
      if(call.url.endsWith('/catalog-detail')&&failOnce){
        failOnce=false;
        throw new Error('detail timeout');
      }
    },
  });
  await h.library.load();
  const openBtn=h.root.querySelector('.ml-open');
  await openBtn.click();
  const avDialog=h.document.querySelector('.ml-av-dialog');
  assert.ok(avDialog);
  assert.ok(avDialog.querySelector('.ml-viewer-sidebar'));
  assert.equal(h.document.querySelector('.ml-image-viewer'),null);
  const player=avDialog.querySelector('.ml-av-player');
  let paused=0,loaded=0;
  player.pause=()=>{paused++;};
  player.load=()=>{loaded++;};

  // Visibility change pauses active player when hidden.
  h.document.dispatchVisibility(true);
  assert.equal(paused,1);
  h.document.dispatchVisibility(false);
  assert.equal(paused,1);

  // Detail retry works cleanly.
  assert.ok(avDialog.textContent.includes('detail timeout'));
  await avDialog.querySelector('.ml-detail-retry').click();
  assert.ok(avDialog.textContent.includes('固定提示词 vid-1'));

  h.library.suspend();
  assert.equal(paused,2);
  assert.equal(loaded,1);
  assert.equal(player.getAttribute('src'),null);
  assert.equal(h.document.querySelector('.ml-av-dialog'),null);
  assert.equal(globalThis.window.listenerCount('keydown'),0);
  assert.equal(h.document.listenerCount('visibilitychange'),0);
});

test('identity change discards in-flight list responses and locale toggle translates UI labels without refetching',async()=>{
  const pendingList=deferred(),started=deferred();
  let intercept=false;
  const h=setup({
    rows:[makeRow(0,{name:'小橘原始立绘',category:'asset_image'})],
    api:async call=>{
      if(call.url.startsWith('/api/v1/project-media?')&&intercept){
        started.resolve();
        return pendingList.promise;
      }
    },
  });
  await h.library.load();
  const callsBeforeLocale=h.calls.length;
  setLocale('en',{persist:false});
  assert.equal(h.root.querySelector('.ml-badge').textContent,'Three-view');
  assert.ok(h.root.querySelector('.ml-total').textContent.includes('1 resources in total'));
  assert.equal(h.root.querySelector('.ml-title').textContent,'小橘原始立绘');
  assert.equal(h.calls.length,callsBeforeLocale);
  setLocale('zh-cn',{persist:false});
  assert.equal(h.root.querySelector('.ml-badge').textContent,'三视图');

  intercept=true;
  const reloadPromise=h.library.reload();
  await started.promise;
  h.session.identityId='other-user';
  pendingList.resolve({items:[makeRow(9,{name:'串号资源'})],total:1,offset:0,limit:20,next_offset:null});
  assert.equal(await reloadPromise,false);
  assert.equal(h.root.textContent.includes('串号资源'),false);
  h.library.suspend();
});

test('production-platform media tab wires createMediaLibrary, filters non-postgres projects and suspends cleanly',async()=>{
  const document=new Document(''),host=document.createElement('main');
  document.body.append(host);
  globalThis.document=document;
  const calls=[];
  const platform=createProductionPlatform(host,{
    projects:()=>[],
    session:()=>({actor:'human',identityId:'id-1',workspaceId:'ws-1',csrf:'csrf',writeAvailable:true}),
    notice:()=>{},
    navigate:async()=>{},
    api:async url=>{
      calls.push(url);
      if(url==='/api/v1/projects')return {items:[
        {id:'pg-1',name:'正式项目',storage_policy:'postgres-series-v1',unavailable:false},
        {id:'legacy-1',name:'旧镜像项目',storage_policy:'legacy-json',unavailable:false},
      ]};
      if(url.startsWith('/api/v1/project-media?'))return {items:[makeRow(0,{project_id:'pg-1',category:'shot_image'})],total:1,offset:0,limit:20,next_offset:null};
      throw new Error('unexpected '+url);
    },
  });
  await platform.load({page:'projects',tab:'media'});
  assert.ok(host.classList.contains('platform-media'));
  assert.ok(host.textContent.includes('展开查看所有项目中的图片、视频、音频和文本资源,可按项目继续筛选'));
  assert.equal(host.querySelector('.project-toolbar').querySelector('.ml-total').textContent,'共 1 个资源');
  const projectOptions=host.querySelector('.ml-filter-project').options.map(o=>o.value);
  assert.deepEqual(projectOptions,['','pg-1']);
  assert.equal(host.querySelectorAll('.ml-card').length,1);
  platform.suspend();
  assert.equal(host.querySelector('.ml-total'),null);
});
