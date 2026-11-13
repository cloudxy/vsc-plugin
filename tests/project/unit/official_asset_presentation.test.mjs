import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
const doc=new Document('');doc.documentElement=doc.createElement('html');
doc.removeEventListener=()=>{};
globalThis.document=doc;
Object.defineProperty(Element.prototype,'style',{get(){return this._style??={};}});
Object.defineProperty(Element.prototype,'isConnected',{get(){return doc.body.contains(this);}});
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;for(const fn of this.listeners.get('close')||[])fn();};
const local=new Map();
globalThis.window={location:{protocol:'http:',hostname:'127.0.0.1'},localStorage:{getItem:k=>local.get(k)||null,setItem:(k,v)=>local.set(k,v),removeItem:k=>local.delete(k)}};
globalThis.sessionStorage={getItem:()=>null,setItem(){},removeItem(){}};
globalThis.history={replaceState(){},pushState(){}};
const observers=[];
globalThis.IntersectionObserver=class{
 constructor(callback){this.callback=callback;observers.push(this);}
 observe(node){this.node=node;}
 unobserve(){}
 disconnect(){this.disconnected=true;}
 fire(){this.callback([{isIntersecting:true,target:this.node}]);}
};
const {createAssetCenter}=await import('../../../src/vsc/interfaces/web/static/asset-center.js');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
const button=(root,label)=>root.querySelectorAll('button').find(n=>n.textContent===label);
const select=(root,label)=>root.querySelectorAll('select').find(n=>n.getAttribute('aria-label')===label);
const official=i=>({id:'o'+i,version_id:'v'+i,title:'官方资产'+i,source:'official',official:{asset_kind:'character'},catalog:{tags:[]},allowed_purposes:['identity_face'],members:[{member_key:'main',modality:'image',preview_url:'/fixture/'+i+'.png'}]});
async function mount(kind,handler){
 globalThis.location={search:'?kind='+kind};
 const root=doc.createElement('main');doc.body.append(root);const requests=[];
 const center=createAssetCenter(root,{session:()=>({actor:'presentation',csrf:'csrf'}),projects:()=>[],notice(){},api:async url=>{
  if(url.includes('/auth/status'))return {};
  requests.push(url);return handler(url,new URL(url,'http://fixture').searchParams);
 }},{source:'official',workbench:true});
 await center.load();await settle();
 return {root,center,requests,cleanup(){center.suspend();root.remove();}};
}

test('official scrolling serializes requests, preserves cards on failure and explicitly retries the same cursor',async()=>{
 let fail=true,release;
 const view=await mount('',async(_url,q)=>{
  const offset=Number(q.get('offset')||0);
  if(offset===24){await new Promise(resolve=>{release=resolve;});if(fail){fail=false;throw Error('offline');}}
  const end=Math.min(offset+24,50);
  return {items:Array.from({length:end-offset},(_,i)=>official(offset+i)),total:50,next_offset:end<50?end:null};
 });
 const observer=observers.at(-1),cards=()=>view.root.querySelectorAll('.center-card');
 assert.equal(cards().length,24);assert.equal(button(view.root,'下一页'),undefined);
 observer.fire();observer.fire();await settle();assert.equal(view.requests.length,2);
 assert.equal(view.root.querySelector('.center-load-more').hidden,true);
 release();await settle();assert.equal(cards().length,24);
 assert.match(view.root.querySelector('.center-load-status').textContent,/加载失败/);
 observer.fire();await settle();assert.equal(view.requests.length,2,'intersection cannot retry an error loop');
 const retry=button(view.root,'重试加载');assert.equal(retry.hidden,false);
 const retrying=retry.onclick();await settle();release();await retrying;
 assert.equal(cards().length,48);assert.equal(new URL(view.requests.at(-1),'http://fixture').searchParams.get('offset'),'24');
 observer.fire();await settle();assert.equal(cards().length,50);
 assert.match(view.root.querySelector('.center-load-status').textContent,/已显示全部 50/);
 assert.equal(observer.disconnected,true);view.cleanup();
});

test('an old append response cannot enter the newly selected official category',async()=>{
 let finish;
 const view=await mount('',async(_url,q)=>{
  if(q.get('asset_kind')==='location')return {items:[{...official('scene'),official:{asset_kind:'location'}}],total:1,next_offset:null};
  if(q.get('offset')==='24')return new Promise(resolve=>{finish=()=>resolve({items:[official('late')],total:25,next_offset:null});});
  return {items:[official('initial')],total:25,next_offset:24};
 });
 const oldObserver=observers.at(-1);oldObserver.fire();await settle();
 await button(view.root,'场景').onclick();assert.equal(oldObserver.disconnected,true);
 finish();await settle();
 assert.equal(view.root.querySelectorAll('.center-card').length,1);
 assert.match(view.root.querySelector('.center-card').textContent,/官方资产scene/);
 assert.doesNotMatch(view.root.textContent,/官方资产late/);view.cleanup();
});

const pose=i=>({id:'p'+i,体系:'标准系',分类:'站姿',姿势名称:'姿势'+i,姿势编号:'P'+i,角度:'正面',缩略图:'thumbs/'+i+'.png',原图:'img/'+i+'.png'});
test('reference groups load 60 manually, single view starts at 96 and filters reset to 60',async()=>{
 const before=observers.length;let fail=false;
 const view=await mount('pose',async(_url,q)=>{
  const start=Number(q.get('offset')),limit=Number(q.get('limit')),end=Math.min(start+limit,170);
  if(start&&fail){fail=false;throw Error('offline');}
  return {items:Array.from({length:end-start},(_,i)=>q.get('view')==='single'?pose(start+i):{key:'g'+(start+i),name:'姿势组'+(start+i),items:[pose(start+i)]}),total:170,next_offset:end<170?end:null,systems:[{name:'标准系',count:170}],angles:['正面'],categories:['站姿']};
 });
 const cards=()=>view.root.querySelectorAll('.ref-card');
 assert.equal(observers.length,before,'reference libraries never auto-load');
 assert.equal(cards().length,60);assert.ok(button(view.root,'加载更多（剩余 110 组）'));
 fail=true;await button(view.root,'加载更多（剩余 110 组）').onclick();
 assert.equal(cards().length,60);assert.ok(button(view.root,'重试加载'));
 await button(view.root,'重试加载').onclick();assert.equal(cards().length,120);
 assert.equal(new URL(view.requests.at(-1),'http://fixture').searchParams.get('offset'),'60');
 await button(view.root,'加载更多（剩余 50 组）').onclick();assert.equal(cards().length,170);
 assert.equal(view.root.querySelector('.costume-more'),null);
 assert.match(view.root.querySelector('.ref-load-complete').textContent,/已显示全部 170 组/);
 const mode=select(view.root,'视图');mode.value='single';await mode.onchange();
 assert.equal(cards().length,96);assert.equal(new URL(view.requests.at(-1),'http://fixture').searchParams.get('limit'),'96');
 await button(view.root,'加载更多（剩余 74 张）').onclick();assert.equal(cards().length,156);
 assert.equal(new URL(view.requests.at(-1),'http://fixture').searchParams.get('limit'),'60');
 const angle=select(view.root,'全部角度');angle.value='正面';await angle.onchange();
 assert.equal(cards().length,60);const q=new URL(view.requests.at(-1),'http://fixture').searchParams;
 assert.equal(q.get('offset'),'0');assert.equal(q.get('limit'),'60');assert.equal(q.get('angle'),'正面');view.cleanup();
});

test('drawer switches the displayed member and hides destructive controls without management permission',async()=>{
 const row=official('gallery');row.members.push({...row.members[0],member_key:'backup',preview_url:'/backup.png'});
 const view=await mount('',async url=>url.includes('/official-gallery')?{...row,can_manage_media:false}:url.includes('/o')?{...row,can_manage_media:false}:{items:[row],total:1,next_offset:null});
 await view.root.querySelector('.center-preview').onclick();await settle();
 const drawer=view.root.querySelector('.official-detail-drawer');assert.ok(drawer);
 const members=drawer.querySelectorAll('.official-drawer-member'),thumbs=drawer.querySelectorAll('.official-drawer-thumb');
 assert.equal(thumbs.length,2);assert.equal(members.filter(n=>!n.hidden).length,1);
 await thumbs[1].onclick();assert.equal(members[0].hidden,true);assert.equal(members[1].hidden,false);
 assert.equal(thumbs[1].getAttribute('aria-pressed'),'true');
 assert.equal(members[1].querySelector('img').src,'/backup.png');
 assert.equal(drawer.querySelector('.official-drawer-delete'),null);view.cleanup();
});

test('costume and portrait remaining counts use their own units and stop at completion',async()=>{
 for(const [kind,unit]of [['costume','套'],['portrait','张']]){
  const view=await mount(kind,async(_url,q)=>{
   const start=Number(q.get('offset')),end=Math.min(start+Number(q.get('limit')),61);
   return {items:Array.from({length:end-start},(_,i)=>({id:'r'+(start+i),服装名称:'服装'+i,标题:'人像'+i,缩略图:'thumbs/'+i+'.png'})),total:61,next_offset:end<61?end:null,categories:[],tops:[],sources:[],tags:[],sections:[],hair_lengths:[],hair_styles:[]};
  });
  await button(view.root,`加载更多（剩余 1 ${unit}）`).onclick();
  assert.equal(view.root.querySelectorAll('.ref-card').length,61);
  assert.equal(view.root.querySelector('.ref-load-complete').textContent,`已显示全部 61 ${unit}`);view.cleanup();
 }
});

test('initial failure leaves a visible retry state instead of a permanent loading label',async()=>{
 let fail=true;
 const view=await mount('',async()=>{if(fail){fail=false;throw Error('offline');}return {items:[official('recovered')],total:1,next_offset:null};});
 assert.equal(view.root.querySelector('.center-count').textContent,'加载失败');
 assert.equal(view.root.querySelector('.center-grid').getAttribute('aria-busy'),'false');
 await button(view.root,'重新读取').onclick();assert.equal(view.root.querySelectorAll('.center-card').length,1);view.cleanup();
});
