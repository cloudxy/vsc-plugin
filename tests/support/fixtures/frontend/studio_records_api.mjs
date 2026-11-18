import {resolveRecordProvenance} from '../../../../src/vsc/interfaces/web/static/character-studio-ai.js';

// In-memory simulation of the PostgreSQL-backed `/api/v1/character-studio/records` and
// `/api/v1/character-studio/media/*` HTTP contract for fast Node.js frontend unit tests;
// real SQL constraints + dated disk layout are verified in PostgreSQL integration tests.
function parseDataImage(raw){
 const m=/^data:(image\/[a-z0-9.+-]+)(;base64)?,([\s\S]*)$/i.exec(String(raw||''));
 if(!m)return null;
 const mime=m[1].toLowerCase();
 const ext=({'image/png':'png','image/jpeg':'jpg','image/jpg':'jpg','image/webp':'webp','image/gif':'gif','image/avif':'avif'})[mime]||'png';
 const bin=m[2]?Buffer.from(m[3],'base64'):Buffer.from(decodeURIComponent(m[3]),'latin1');
 return {mime,ext,bytes:new Uint8Array(bin)};
}

export function createStudioRecordsServer(initial=[],control={}){
 const mediaMap=new Map();
 let seq=0;

 function sanitizeSnapshot(snap,day,stem){
  if(!snap||typeof snap!=='object')return {};
  let refIdx=0;
  function walk(val,key=''){
   if(/(api[_-]?key|secret|token|authorization|password)/i.test(key))return undefined;
   if(typeof val==='string'){
    const parsed=parseDataImage(val);
    if(parsed){
     const refPath=`${day}/refs/${stem}_ref${++refIdx}.${parsed.ext}`;
     mediaMap.set(refPath,{mime:parsed.mime,bytes:parsed.bytes});
     return `/api/v1/character-studio/media/${refPath}`;
    }
    return val;
   }
   if(Array.isArray(val))return val.map(item=>walk(item)).filter(v=>v!==undefined);
   if(val&&typeof val==='object'){
    const out={};
    for(const [k,v]of Object.entries(val)){
     const next=walk(v,k);
     if(next!==undefined)out[k]=next;
    }
    return out;
   }
   return val;
  }
  return walk(snap);
 }

 function normalizeRecord(raw,idx=0){
  const id=String(raw.id||`rec-${++seq}-${idx}`);
  const createdAt=Number(raw.createdAt??raw.created_at??(Date.now()+idx));
  const info=resolveRecordProvenance(raw);
  const day=new Date(createdAt).toISOString().slice(0,10);
  const cleanId=id.replace(/[^a-zA-Z0-9_-]/g,'').slice(0,12)||`r${++seq}`;
  const stem=`${day.replace(/-/g,'')}_${cleanId}`;
  const rawImg=String(raw.imageUrl||raw.image_url||'');
  const parsed=parseDataImage(rawImg);
  const extFromUrl=/\.(png|jpe?g|webp|gif|avif)(?:[?#]|$)/i.exec(rawImg)?.[1]?.toLowerCase()?.replace('jpeg','jpg');
  const ext=parsed?.ext||extFromUrl||'png';
  const imagePath=raw.imagePath||`${day}/${stem}.${ext}`;
  const promptPath=raw.promptPath||`${day}/${stem}.txt`;
  if(parsed)mediaMap.set(imagePath,{mime:parsed.mime,bytes:parsed.bytes});
  else if(!mediaMap.has(imagePath))mediaMap.set(imagePath,{mime:`image/${ext==='jpg'?'jpeg':ext}`,bytes:new Uint8Array([137,80,78,71])});
  const imageUrl=rawImg&&!rawImg.startsWith('data:image/')&&rawImg.startsWith('/api/v1/character-studio/media/')
   ?rawImg
   :`/api/v1/character-studio/media/${imagePath}`;
  return {
   id,
   createdAt,
   imagePath,
   promptPath,
   storageDisplayPath:`assets/ai-generate-image/${imagePath}`,
   promptDisplayPath:`assets/ai-generate-image/${promptPath}`,
   imageUrl,
   provider:raw.provider||info.provider,
   model:raw.model!==undefined?raw.model:info.model,
   upstreamModel:raw.upstreamModel||raw.upstream_model||info.upstreamModel||'',
   method:raw.method!==undefined?raw.method:info.method,
   methodLabel:raw.methodLabel||raw.method_label||info.methodLabel||'',
   endpoint:raw.endpoint!==undefined?raw.endpoint:info.endpoint||'',
   prompt:raw.prompt||'',
   recipeSummary:raw.recipeSummary??raw.recipe_summary??'',
   snapshot:sanitizeSnapshot(raw.snapshot||{},day,stem),
   publication:raw.publication?structuredClone(raw.publication):null,
  };
 }

 let rows=initial.map((r,idx)=>normalizeRecord(r,idx));
 const norm=v=>String(v||'').toLocaleLowerCase().replace(/[_-]+/g,'-');

 async function handle(url,options={}){
  const method=String(options.method||'GET').toUpperCase();
  const parsed=new URL(url,'http://localhost');
  if(!parsed.pathname.startsWith('/api/v1/character-studio/records'))return undefined;
  if(control.failAll)throw new Error(control.failMessage||'数据库服务不可用');
  if(method==='GET'&&parsed.pathname==='/api/v1/character-studio/records'){
   if(control.failRead)throw new Error(control.failMessage||'无法从数据库读取合成记录');
   if(control.holdRead)await control.holdRead;
   const q=(parsed.searchParams.get('q')||'').trim().toLocaleLowerCase(),nq=norm(q);
   const fk=parsed.searchParams.get('filter_key')||'';
   const offset=Number(parsed.searchParams.get('offset')||0),limit=Number(parsed.searchParams.get('limit')||20);
   const ordered=[...rows].sort((a,b)=>b.createdAt-a.createdAt);
   const facetMap=new Map();
   for(const r of ordered){
    const info=resolveRecordProvenance(r);
    const cur=facetMap.get(info.filterKey);
    if(cur)cur.count+=1;
    else facetMap.set(info.filterKey,{key:info.filterKey,provider:info.provider,model:info.model,method:info.method,methodLabel:info.methodLabel,count:1});
   }
   const filtered=ordered.filter(r=>{
    const info=resolveRecordProvenance(r);
    if(fk&&info.filterKey!==fk)return false;
    if(!q)return true;
    return [r.recipeSummary,r.prompt,info.model,info.upstreamModel,info.method,info.methodLabel,info.endpoint,info.providerShort,info.providerName,info.provider]
     .some(v=>{const s=String(v||'').toLocaleLowerCase();return s.includes(q)||(nq&&norm(s).includes(nq));});
   });
   const items=filtered.slice(offset,offset+limit);
   return {
    items:structuredClone(items),
    total:filtered.length,
    overall_total:rows.length,
    offset,
    limit,
    next_offset:offset+limit<filtered.length?offset+limit:null,
    facets:[...facetMap.values()],
   };
  }
  if(method==='POST'&&parsed.pathname==='/api/v1/character-studio/records'){
   if(control.failWrite)throw new Error(control.failMessage||'写入数据库失败');
   const body=typeof options.body==='string'?JSON.parse(options.body):(options.body||{});
   const existing=body.id?rows.find(x=>x.id===body.id):null;
   if(existing)return {record:structuredClone(existing)};
   const rec=normalizeRecord(body,rows.length);
   rows=[rec,...rows];
   return {record:structuredClone(rec)};
  }
  const pubMatch=parsed.pathname.match(/^\/api\/v1\/character-studio\/records\/([^/]+)\/publication$/);
  if(method==='PATCH'&&pubMatch){
   if(control.failWrite||control.failPublicationWrite)throw new Error(control.failMessage||'数据库更新回执失败');
   const id=decodeURIComponent(pubMatch[1]);
   const idx=rows.findIndex(x=>x.id===id);
   if(idx<0)throw new Error('合成记录不存在');
   const body=typeof options.body==='string'?JSON.parse(options.body):(options.body||{});
   const prevActor=rows[idx].publication?.actor,nextActor=body.publication?.actor;
   if(prevActor&&nextActor&&prevActor!==nextActor)throw new Error('这次入库由另一账号发起，请切回原账号继续，不能复用另一身份的回执');
   rows[idx]={...rows[idx],publication:structuredClone(body.publication)};
   return {record:structuredClone(rows[idx])};
  }
  const itemMatch=parsed.pathname.match(/^\/api\/v1\/character-studio\/records\/([^/]+)$/);
  if(method==='DELETE'&&itemMatch){
   if(control.failWrite||control.failDelete)throw new Error(control.failMessage||'删除记录失败');
   const id=decodeURIComponent(itemMatch[1]);
   const found=rows.find(x=>x.id===id);
   if(found)mediaMap.delete(found.imagePath);
   rows=rows.filter(x=>x.id!==id);
   return {deleted:true,id};
  }
  if(method==='DELETE'&&parsed.pathname==='/api/v1/character-studio/records'){
   if(control.failWrite||control.failDelete)throw new Error(control.failMessage||'清空记录失败');
   const count=rows.length;rows=[];mediaMap.clear();
   return {deleted_count:count};
  }
  return undefined;
 }

 function createFetch(fallbackFetch){
  return async(url,options={})=>{
   const str=String(url||'');
   if(str.startsWith('/api/v1/character-studio/media/')){
    const sub=str.slice('/api/v1/character-studio/media/'.length).split('?')[0];
    const media=mediaMap.get(sub);
    if(!media)return new Response('Not Found',{status:404});
    return new Response(media.bytes,{status:200,headers:{'Content-Type':media.mime}});
   }
   if(str.startsWith('/api/v1/character-studio/records')){
    try{
     const data=await handle(str,options);
     return new Response(JSON.stringify(data??{}),{status:200,headers:{'Content-Type':'application/json'}});
    }catch(error){
     return new Response(JSON.stringify({detail:error?.message||String(error)}),{status:500,headers:{'Content-Type':'application/json'}});
    }
   }
   if(typeof fallbackFetch==='function')return fallbackFetch(url,options);
   throw new Error('Unhandled fetch '+str);
  };
 }

 return {
  handle,
  createFetch,
  normalizeRecord,
  get rows(){return rows;},
  setRows(next){mediaMap.clear();rows=next.map((r,i)=>normalizeRecord(r,i));},
  control,
 };
}
