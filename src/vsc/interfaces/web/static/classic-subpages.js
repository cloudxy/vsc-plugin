import {msg,setText,bindAttribute,option as localizedOption} from './i18n.js';

const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const setStyle=(node,css)=>{if(node.style&&typeof node.style==='object'){for(const part of css.split(';')){const [k,v]=part.split(':');if(k&&v)node.style[k.trim().replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v.trim();}}node.setAttribute?.('style',css);};
const emptyGraphic=()=>{const s=el('span',null,'classic-empty-graphic');s.setAttribute('aria-hidden','true');s.innerHTML='<svg viewBox="0 0 120 120" fill="none"><rect x="22" y="26" width="76" height="68" rx="10" fill="#1d1d1d" stroke="#48484c" stroke-width="2"/><circle cx="46" cy="50" r="8" stroke="#8e8d92" stroke-width="1.8"/><path d="M28 80l18-18 15 13 14-16 17 21" stroke="#74ff53" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';return s;};

export const BATCH_STORYBOARD_RE=/^\d+\.(png|jpg|jpeg)$/i;
export function validateStoryboardBatchFilename(name){
  const trimmed=String(name||'').trim();
  if(!BATCH_STORYBOARD_RE.test(trimmed)){
    return {valid:false,error:`文件名格式不正确：${name}。文件名必须为数字.png/jpg/jpeg 格式，如 1.png、2.jpg、3.JPEG 等`};
  }
  const stem=trimmed.slice(0,trimmed.lastIndexOf('.'));
  return {valid:true,ordinal:Number.parseInt(stem,10),filename:trimmed};
}

export function klingWeightedLength(text){
  let units=0;
  for(const ch of Array.from(String(text||''))){
    units+=(ch.codePointAt(0)<=127)?(11/26):1;
  }
  return units;
}

export async function openPromptRecommendationDialog(root,ctx,projectId,onPickTag){
  const dialog=el('dialog',null,'classic-upload-dialog classic-prompt-recommend-dialog');
  bindAttribute(dialog,'aria-label','提示词推荐库');
  const header=el('header');
  const closeBtn=el('button','×');closeBtn.type='button';bindAttribute(closeBtn,'aria-label',msg('common.close'));
  closeBtn.addEventListener('click',()=>{if(dialog.close)dialog.close();else dialog.open=false;dialog.remove();});
  header.append(el('h2','提示词推荐库'),closeBtn);
  const search=el('input');search.type='search';bindAttribute(search,'placeholder','搜索景别、运镜、光影、风格词…');bindAttribute(search,'aria-label','搜索推荐提示词');
  const tabs=el('nav',null,'classic-recommend-tabs');
  const list=el('div',null,'classic-recommend-tags');
  const status=el('p','正在读取推荐词库…','hint');
  dialog.append(header,search,tabs,list,status);
  root.append(dialog);
  dialog.addEventListener('close',()=>dialog.remove());
  if(dialog.showModal)dialog.showModal();else dialog.open=true;
  let categories=[],activeCategory='';
  function draw(){
    tabs.replaceChildren();list.replaceChildren();
    const q=search.value.trim().toLocaleLowerCase();
    for(const cat of categories){
      const tab=el('button',cat.label);tab.type='button';
      tab.setAttribute('aria-pressed',String(cat.id===activeCategory));
      tab.addEventListener('click',()=>{activeCategory=cat.id;draw();});
      tabs.append(tab);
    }
    const chosen=categories.filter(c=>q||!activeCategory||c.id===activeCategory);
    let count=0;
    for(const cat of chosen){
      for(const tag of (cat.items||cat.tags||[])){
        const text=typeof tag==='string'?tag:(tag.text||tag.label||'');
        if(!text||(q&&!text.toLocaleLowerCase().includes(q)&&!(cat.label||'').toLocaleLowerCase().includes(q)))continue;
        count++;
        const chip=el('button',text,'classic-recommend-chip');chip.type='button';
        chip.dataset.tagText=text;
        chip.addEventListener('click',()=>{onPickTag(text);setText(status,`已插入提示词：${text}`);});
        list.append(chip);
      }
    }
    if(!count)list.append(el('p','没有匹配的推荐提示词','hint'));
    else setText(status,`共 ${count} 个可用提示词标签，点击即可插入输入框`);
  }
  try{
    const data=await ctx.api('/api/v1/projects/'+encodeURIComponent(projectId)+'/classic-production/prompt-recommendations');
    categories=data.categories||[];
    activeCategory=categories[0]?.id||'';
    search.addEventListener('input',draw);
    draw();
  }catch(err){
    setText(status,err.message||'提示词推荐库读取失败');
  }
  return dialog;
}

export async function mountStoryboardReferencePicker(host,ctx,currentProjectId,onPick){
  host.replaceChildren();
  const bar=el('div',null,'classic-frame-filters classic-storyboard-picker-bar');
  const projectSelect=el('select'),episodeSelect=el('select');
  bindAttribute(projectSelect,'aria-label','分镜来源项目');
  bindAttribute(episodeSelect,'aria-label','分镜来源剧集');
  setStyle(projectSelect,'width:200px;flex:0 0 200px');
  setStyle(episodeSelect,'width:200px;flex:0 0 200px');
  bar.append(projectSelect,episodeSelect);
  const grid=el('div',null,'classic-frame-grid');
  const status=el('p','','classic-upload-status');
  host.append(bar,grid,status);

  let reqNo=0;
  async function loadItems(sourceProjectId,episodeId=''){
    const r=++reqNo;
    if(!sourceProjectId){grid.replaceChildren();return;}
    const qs=new URLSearchParams(episodeId?{episode_id:episodeId}:{});
    try{
      const data=await ctx.api('/api/v1/projects/'+encodeURIComponent(sourceProjectId)+'/classic-production/storyboard-references'+(qs.toString()?'?'+qs:''));
      if(r!==reqNo)return;
      episodeSelect.replaceChildren();
      const episodes=data.episodes||[];
      if(!episodes.length)episodeSelect.append(localizedOption('','暂无剧集'));
      for(const ep of episodes)episodeSelect.append(localizedOption(ep.id,ep.title||ep.display_code||ep.id));
      const chosenEp=data.episode_id||data.selected_episode_id||'';
      if(chosenEp&&episodes.some(ep=>ep.id===chosenEp))episodeSelect.value=chosenEp;
      grid.replaceChildren();
      const flat=[];
      for(const shot of data.items||[]){
        if(Array.isArray(shot.images)){
          for(const img of shot.images)flat.push({shot_id:shot.shot_id,ordinal:shot.serial_number||shot.ordinal||1,shot_title:shot.title||shot.shot_title||'',media_id:img.media_id,candidate_id:img.candidate_id,name:img.name,sha256:img.sha256});
        }else if(shot.media_id){
          flat.push(shot);
        }
      }
      for(const item of flat){
        const card=el('button',null,'classic-frame-card');card.type='button';
        card.dataset.shotId=item.shot_id;card.dataset.mediaId=item.media_id;
        const img=el('img');
        img.src='/api/v1/projects/'+encodeURIComponent(sourceProjectId)+'/media/'+encodeURIComponent(item.media_id)+'/content';
        img.alt=item.shot_title||String(item.ordinal||'');
        img.addEventListener('error',()=>{img.hidden=true;});
        card.append(img,el('span',`#${item.ordinal} ${item.shot_title||item.name||''}`.trim()));
        card.addEventListener('click',async()=>{
          try{await onPick(sourceProjectId,item);}
          catch(err){setText(status,err.message);}
        });
        grid.append(card);
      }
      if(!grid.querySelector('.classic-frame-card')){
        grid.append(el('p','当前剧集暂无已选用的分镜图','hint'));
      }
    }catch(err){
      if(r===reqNo)setText(status,err.message||'读取分镜参考失败');
    }
  }

  const projectsResp=await ctx.api('/api/v1/projects');
  const projects=(Array.isArray(projectsResp)?projectsResp:projectsResp.items||[]).filter(p=>!p.unavailable);
  for(const p of projects)projectSelect.append(localizedOption(p.id,p.name||p.id));
  if(projects.some(p=>p.id===currentProjectId))projectSelect.value=currentProjectId;
  projectSelect.addEventListener('change',()=>loadItems(projectSelect.value,''));
  episodeSelect.addEventListener('change',()=>loadItems(projectSelect.value,episodeSelect.value));
  await loadItems(projectSelect.value,'');
}

export function createStoryboardRepaint(root,ctx){
  let active=false,epoch=0,fullscreenCleanup=null;
  const base=p=>'/api/v1/projects/'+encodeURIComponent(p);

  function stop(){
    active=false;epoch++;
    fullscreenCleanup?.();fullscreenCleanup=null;
  }

  function renderMissingGuard(scope){
    root.replaceChildren();
    root.className='classic-subpage classic-repaint-page';
    const crumb=el('header',null,'classic-subpage-header');
    const backLink=el('button','← 分镜','classic-subpage-back');backLink.type='button';
    backLink.addEventListener('click',()=>ctx.navigate('storyboard',scope?.episodeId||null));
    crumb.append(backLink,el('span','/','classic-subpage-sep'),el('h1','局部重绘'));
    const card=el('section',null,'classic-repaint-guard');
    card.append(
      emptyGraphic(),
      el('p','缺少有效的重绘任务参数，请从分镜页面重新进入。','classic-repaint-guard-text'),
      (()=>{
        const btn=el('button','返回分镜','classic-repaint-back classic-primary');
        btn.type='button';
        btn.addEventListener('click',()=>ctx.navigate('storyboard',scope?.episodeId||null));
        return btn;
      })(),
    );
    root.append(crumb,card);
  }

  async function load(scope={}){
    stop();active=true;const n=epoch;
    const urlParams=globalThis.location?.search?new URLSearchParams(location.search):new URLSearchParams();
    const projectId=scope.projectId||urlParams.get('project_id')||urlParams.get('project')||'';
    const shotId=scope.shotId||scope.objectId||urlParams.get('shot_id')||urlParams.get('shot')||'';
    const mediaId=scope.mediaId||scope.repaintMediaId||urlParams.get('media_id')||urlParams.get('media')||'';
    if(!projectId||!shotId||!mediaId){
      renderMissingGuard(scope);
      return true;
    }
    root.replaceChildren(el('p','正在加载局部重绘编辑器…','hint'));
    root.className='classic-subpage classic-repaint-page';
    try{
      const [classicData,mediaResp]=await Promise.all([
        ctx.api(base(projectId)+'/classic-production?shot_id='+encodeURIComponent(shotId)),
        ctx.api(base(projectId)+'/media/'+encodeURIComponent(mediaId)),
      ]);
      if(!active||n!==epoch)return false;
      if(classicData.revision!=null)ctx.setRevision(classicData.revision,projectId);
      const raw=mediaResp.media||mediaResp;
      if(raw.modality!=='image'){
        renderMissingGuard(scope);
        return false;
      }
      const w=Math.max(1,Number(raw.width)||1024),h=Math.max(1,Number(raw.height)||1024);
      let tool='brush',brushSize=24,eraserSize=28,zoom=1,panX=0,panY=0,drawing=null,panStart=null;
      let baseDraftId=(classicData.drafts||[]).find(d=>(d.document?.mode||d.mode)==='image_inpaint')?.id||null;
      const operations=[],redo=[];

      root.replaceChildren();
      const crumb=el('header',null,'classic-subpage-header');
      const backBtn=el('button','← 分镜','classic-subpage-back');backBtn.type='button';
      backBtn.addEventListener('click',()=>ctx.navigate('storyboard',classicData.episode_id||scope.episodeId||null));
      crumb.append(backBtn,el('span','/','classic-subpage-sep'),el('h1','局部重绘'),el('span',raw.name||mediaId,'hint'));

      const body=el('div',null,'classic-repaint-layout');
      const stageShell=el('section',null,'classic-repaint-stage-shell');
      const stageViewport=el('div',null,'classic-repaint-viewport');
      const canvasStack=el('div',null,'classic-repaint-stack');
      const baseCanvas=el('canvas',null,'classic-repaint-base');baseCanvas.width=w;baseCanvas.height=h;
      const maskCanvas=el('canvas',null,'classic-repaint-mask');maskCanvas.width=w;maskCanvas.height=h;
      bindAttribute(maskCanvas,'aria-label','局部重绘蒙版画布');
      canvasStack.append(baseCanvas,maskCanvas);
      stageViewport.append(canvasStack);

      const sourceImg=el('img');
      sourceImg.crossOrigin='use-credentials';
      sourceImg.src=base(projectId)+'/media/'+encodeURIComponent(mediaId)+'/content';

      const applyTransform=()=>{
        setStyle(canvasStack,`transform:translate(${panX}px,${panY}px) scale(${zoom.toFixed(2)});transform-origin:center center`);
        setText(zoomBadge,`${Math.round(zoom*100)}%`);
      };

      const paintBase=()=>{
        const g=baseCanvas.getContext?.('2d');if(!g)return;
        g.clearRect(0,0,w,h);
        try{g.drawImage(sourceImg,0,0,w,h);}catch{}
      };
      sourceImg.addEventListener('load',paintBase);

      const drawStroke=(g,op)=>{
        const pts=op.points.map(([px,py])=>[px*w,py*h]);
        const lw=Math.max(2,op.width*Math.min(w,h));
        g.save();
        g.lineCap='round';g.lineJoin='round';g.lineWidth=lw;
        if(op.tool==='eraser'){
          g.globalCompositeOperation='destination-out';
          g.strokeStyle='rgba(0,0,0,1)';
        }else{
          g.globalCompositeOperation='source-over';
          g.strokeStyle='rgba(116, 255, 83, 0.58)';
        }
        g.beginPath();
        const first=pts[0]||[0,0];
        g.moveTo(first[0],first[1]);
        for(const p of pts)g.lineTo(p[0],p[1]);
        if(pts.length===1)g.lineTo(first[0]+0.1,first[1]+0.1);
        g.stroke();
        g.restore();
      };

      let undoBtn=null,redoBtn=null,clearBtn=null;
      const paintMask=()=>{
        if(undoBtn)undoBtn.disabled=!operations.length;
        if(redoBtn)redoBtn.disabled=!redo.length;
        if(clearBtn)clearBtn.disabled=!operations.length;
        const g=maskCanvas.getContext?.('2d');if(!g)return;
        g.clearRect(0,0,w,h);
        for(const op of operations)drawStroke(g,op);
        if(drawing)drawStroke(g,drawing);
      };

      const toPoint=e=>{
        const r=maskCanvas.getBoundingClientRect?.()||{left:0,top:0,width:w,height:h};
        return [
          Math.max(0,Math.min(1,(e.clientX-r.left)/(r.width||1))),
          Math.max(0,Math.min(1,(e.clientY-r.top)/(r.height||1))),
        ];
      };

      maskCanvas.onpointerdown=e=>{
        e.preventDefault?.();
        maskCanvas.setPointerCapture?.(e.pointerId);
        if(tool==='pan'){
          panStart={x:e.clientX-panX,y:e.clientY-panY};
          return;
        }
        const sizePx=tool==='eraser'?eraserSize:brushSize;
        drawing={
          id:crypto.randomUUID(),
          tool:tool==='eraser'?'eraser':'mask',
          points:[toPoint(e)],
          color:'#ffffff',
          width:sizePx/Math.min(w,h),
          text:'',
        };
        paintMask();
      };
      maskCanvas.onpointermove=e=>{
        if(panStart){
          panX=e.clientX-panStart.x;panY=e.clientY-panStart.y;
          applyTransform();
          return;
        }
        if(!drawing)return;
        if(drawing.points.length<4000)drawing.points.push(toPoint(e));
        paintMask();
      };
      maskCanvas.onpointerup=()=>{
        panStart=null;
        if(!drawing)return;
        operations.push(drawing);drawing=null;redo.length=0;paintMask();
      };
      maskCanvas.onpointercancel=()=>{panStart=null;drawing=null;paintMask();};
      stageViewport.addEventListener('wheel',e=>{
        e.preventDefault?.();
        const delta=(e.deltaY||0)<0?0.15:-0.15;
        zoom=Math.max(0.5,Math.min(4,zoom+delta));
        applyTransform();
      });

      const toolbar=el('nav',null,'classic-repaint-toolbar');
      bindAttribute(toolbar,'aria-label','局部重绘工具栏');
      const toolBtns={};
      const selectTool=next=>{
        tool=next;
        for(const [k,b]of Object.entries(toolBtns))b.setAttribute('aria-pressed',String(k===tool));
      };
      for(const [k,label]of [['brush','画笔'],['eraser','擦除'],['pan','拖动']]){
        const b=el('button',label,'classic-repaint-tool');b.type='button';
        b.dataset.tool=k;
        b.setAttribute('aria-pressed',String(k===tool));
        b.addEventListener('click',()=>selectTool(k));
        toolBtns[k]=b;toolbar.append(b);
      }
      const sizeInput=el('input');sizeInput.type='range';sizeInput.min='4';sizeInput.max='80';sizeInput.value=String(brushSize);
      bindAttribute(sizeInput,'aria-label','笔刷大小');
      sizeInput.addEventListener('input',()=>{
        if(tool==='eraser')eraserSize=Number(sizeInput.value);
        else brushSize=Number(sizeInput.value);
      });
      const zoomBadge=el('span','100%','classic-repaint-zoom');
      undoBtn=el('button','撤销');undoBtn.type='button';undoBtn.disabled=true;
      undoBtn.addEventListener('click',()=>{if(operations.length){redo.push(operations.pop());paintMask();}});
      redoBtn=el('button','重做');redoBtn.type='button';redoBtn.disabled=true;
      redoBtn.addEventListener('click',()=>{if(redo.length){operations.push(redo.pop());paintMask();}});
      clearBtn=el('button','清空蒙版');clearBtn.type='button';clearBtn.disabled=true;
      clearBtn.addEventListener('click',()=>{operations.length=0;redo.length=0;paintMask();});
      const fullBtn=el('button','全屏');fullBtn.type='button';
      fullBtn.addEventListener('click',()=>{
        stageShell.classList.toggle('is-fullscreen');
        setText(fullBtn,stageShell.classList.contains('is-fullscreen')?'退出全屏':'全屏');
      });
      toolbar.append(sizeInput,zoomBadge,undoBtn,redoBtn,clearBtn,fullBtn);
      stageShell.append(stageViewport,toolbar);

      const panel=el('form',null,'classic-repaint-panel');
      panel.append(el('h2','重绘设置'));
      const inpaintModels=(classicData.models||[]).filter(m=>m.modality==='image'&&(m.capabilities?.image_operations||[]).includes('inpaint'));
      const modelSelect=el('select');bindAttribute(modelSelect,'aria-label','局部重绘模型');
      modelSelect.append(localizedOption('','默认局部重绘配置'));
      for(const m of inpaintModels)modelSelect.append(localizedOption(m.id,m.name||m.model_key||m.id));
      if(inpaintModels[0])modelSelect.value=inpaintModels[0].id;
      const modelWrap=el('label','模型');modelWrap.append(modelSelect);

      const refSelect=el('select');bindAttribute(refSelect,'aria-label','参考图（可选）');
      refSelect.append(localizedOption('','不使用额外参考图'));
      for(const item of (classicData.media||[]).filter(x=>x.modality==='image'&&x.id!==mediaId)){
        refSelect.append(localizedOption(item.id,item.name||item.id));
      }
      const refWrap=el('label','参考图（可选）');refWrap.append(refSelect);

      const promptInput=el('textarea');promptInput.rows=5;promptInput.maxLength=5000;
      bindAttribute(promptInput,'aria-label','局部重绘提示词');
      bindAttribute(promptInput,'placeholder','描述涂抹区域需要重绘的内容，例如：换成古风斗笠、修复手部细节…');
      const promptWrap=el('label','重绘提示词（必填）');promptWrap.append(promptInput);

      const countSelect=el('select');bindAttribute(countSelect,'aria-label','生成张数');
      for(const c of [1,2,3,4])countSelect.append(localizedOption(String(c),`${c} 张`));
      const countWrap=el('label','生成张数');countWrap.append(countSelect);

      const status=el('p','','classic-repaint-status');status.setAttribute('role','status');
      const submitBtn=el('button','开始生成','classic-primary classic-repaint-submit');submitBtn.type='submit';
      const resultList=el('div',null,'classic-repaint-results');

      async function postClassic(action,payload){
        const sess=ctx.session();
        if(!sess.actor||!sess.writable)throw new Error('请先建立可写会话');
        const res=await ctx.api(base(projectId)+'/classic-production/'+action,{
          method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':sess.csrf},
          body:JSON.stringify({payload,expected_revision:sess.revision,idempotency_key:crypto.randomUUID()}),
        });
        if(res.revision!=null)ctx.setRevision(res.revision,projectId);
        return res;
      }

      async function loadResults(){
        const cand=await ctx.api(base(projectId)+'/working-candidates?'+new URLSearchParams({shot_id:shotId,output_kind:'image',limit:'12'}));
        if(!active||n!==epoch)return;
        resultList.replaceChildren(el('h3','当前镜头图片结果'));
        for(const item of cand.items||[]){
          const row=el('div',null,'classic-repaint-result-card');
          const img=el('img');img.src=base(projectId)+'/media/'+encodeURIComponent(item.media_id)+'/content';img.alt=item.name||item.media_id;
          row.append(img,el('span',(item.selected?'✓ 当前分镜 · ':'')+(item.name||item.media_id)));
          resultList.append(row);
        }
      }

      panel.addEventListener('submit',async e=>{
        e.preventDefault();
        try{
          if(!operations.some(op=>op.tool==='mask'))throw new Error('请先使用画笔涂抹需要局部重绘的区域');
          if(!promptInput.value.trim())throw new Error('请输入局部重绘提示词');
          submitBtn.disabled=true;
          setText(status,'正在固定蒙版与保存局部重绘任务草稿…');
          const editDoc={
            format:'vsc.reference-edit/v1',
            id:crypto.randomUUID(),
            source_media_id:mediaId,
            source_sha256:raw.sha256,
            source_modality:'image',
            time_ms:0,
            width:w,
            height:h,
            description:promptInput.value.trim(),
            operations:operations.map(op=>({...op})),
            brightness:1,
            saturation:1,
            grid:{rows:1,columns:1},
          };
          const savedEdit=await postClassic('reference-edits',{shot_id:shotId,mode:'image_inpaint',document:editDoc,base_edit_id:null});
          const exported=await postClassic('reference-exports',{edit_version_id:savedEdit.id});
          const inpaintMask=(exported.outputs||[]).find(o=>o.role==='inpaint-mask');
          if(!inpaintMask)throw new Error('未能导出有效局部重绘蒙版');
          const refs=[
            {role:'operation_source',media_id:mediaId,sha256:raw.sha256},
            {role:'operation_mask',media_id:inpaintMask.media_id,sha256:inpaintMask.sha256},
          ];
          const chosenRefMedia=refSelect.value?(classicData.media||[]).find(x=>x.id===refSelect.value):null;
          if(chosenRefMedia){
            refs.push({role:'reference_image',media_id:chosenRefMedia.id,sha256:chosenRefMedia.sha256});
          }
          const finalPrompt=promptInput.value.trim()+(chosenRefMedia?`\n[[ref:${chosenRefMedia.id}]]`:'');
          const draftDoc={
            shot_id:shotId,
            mode:'image_inpaint',
            model_id:modelSelect.value||'',
            purpose:'image_edit',
            prompt:finalPrompt,
            duration_ms:5000,
            width:w,
            height:h,
            count:Number(countSelect.value)||1,
            params:{},
            references:refs,
            tool_settings:{
              ...(classicData.modes?.image_inpaint?.tool_defaults||{}),
              mask_media_id:inpaintMask.media_id,
              mask_sha256:inpaintMask.sha256,
              mask_export_id:exported.id,
            },
          };
          const savedDraft=await postClassic('drafts',{document:draftDoc,base_draft_id:baseDraftId});
          baseDraftId=savedDraft.id;
          setText(status,`局部重绘蒙版与草稿已保存（v${savedDraft.version}），遮罩媒体 ${inpaintMask.media_id} 已登记。`);
          ctx.notice('局部重绘蒙版与任务草稿已保存');
          await loadResults();
        }catch(err){
          setText(status,err.message||'局部重绘保存失败');
          ctx.notice(err.message||'局部重绘保存失败');
        }finally{
          if(active&&n===epoch)submitBtn.disabled=false;
        }
      });

      panel.append(modelWrap,refWrap,promptWrap,countWrap,submitBtn,status,resultList);
      body.append(stageShell,panel);
      root.append(crumb,body);
      applyTransform();
      paintBase();
      paintMask();
      await loadResults();
      return {
        drawMaskStroke(points=[[0.25,0.25],[0.65,0.65]]){
          operations.push({id:crypto.randomUUID(),tool:'mask',points,color:'#ffffff',width:brushSize/Math.min(w,h),text:''});
          redo.length=0;paintMask();
        },
      };
    }catch(err){
      if(active&&n===epoch){
        renderMissingGuard(scope);
        ctx.notice(err.message);
      }
      return false;
    }
  }

  return {load,suspend:stop};
}

export function createVideoReview(root,ctx){
  let active=false,epoch=0,activeVideo=null;
  const base=p=>'/api/v1/projects/'+encodeURIComponent(p);

  function stop(){
    active=false;epoch++;
    if(activeVideo){
      activeVideo.pause?.();
      activeVideo.removeAttribute?.('src');
      activeVideo.load?.();
      activeVideo=null;
    }
  }

  async function load(scope={}){
    stop();active=true;const n=epoch;
    const urlParams=globalThis.location?.search?new URLSearchParams(location.search):new URLSearchParams();
    const projectId=scope.projectId||urlParams.get('project_id')||urlParams.get('project')||'';
    const episodeId=scope.episodeId||urlParams.get('episode_id')||urlParams.get('episode')||'';
    const shotId=scope.shotId||scope.objectId||urlParams.get('shot_id')||'';
    if(!projectId){
      root.replaceChildren(el('p','请先选择要审片的作品项目','hint'));
      return false;
    }
    root.className='classic-subpage classic-video-review-page';
    root.replaceChildren(el('p','正在读取剧集审片台…','hint'));
    try{
      const qs=new URLSearchParams({
        ...(episodeId?{episode_id:episodeId}:{}),
        ...(shotId?{shot_id:shotId}:{}),
      });
      const data=await ctx.api(base(projectId)+'/classic-production/video-review'+(qs.toString()?'?'+qs:''));
      if(!active||n!==epoch)return false;
      if(data.revision!=null)ctx.setRevision(data.revision,projectId);

      const resolvedEpisodeId=data.episode_id||episodeId||null;
      const rawClips=data.clips||data.items||[];
      const items=rawClips.map(it=>({
        ...it,
        has_video:Boolean(it.media_id&&(it.has_video!==false)),
        submission_id:it.pending_submission_id??it.submission_id??null,
        review_status:it.latest_outcome||it.review_status||'unreviewed',
      }));
      const playableIndices=items.map((it,idx)=>it.has_video?idx:-1).filter(idx=>idx>=0);
      let currentIndex=playableIndices[0]??0;
      const checkedMediaIds=new Set(items.filter(it=>it.has_video&&it.media_id).map(it=>it.media_id));

      root.replaceChildren();
      const header=el('header',null,'classic-subpage-header');
      const backBtn=el('button','← 视频','classic-subpage-back');backBtn.type='button';
      backBtn.addEventListener('click',()=>ctx.navigate('video',resolvedEpisodeId));
      header.append(backBtn,el('span','/','classic-subpage-sep'),el('h1',data.episode_title||'当前剧集'));

      const grid=el('div',null,'classic-video-review-grid');
      const leftCard=el('section',null,'classic-video-review-card classic-video-review-list-card');
      const rightCard=el('section',null,'classic-video-review-card classic-video-review-player-card');

      const leftHead=el('div',null,'classic-video-review-card-head');
      leftHead.append(el('h2','所有视频片段'),el('span',`${playableIndices.length}/${items.length} 可预览`,'hint'));
      leftCard.append(leftHead);

      const clipList=el('div',null,'classic-video-review-clips');
      leftCard.append(clipList);

      const rightHead=el('div',null,'classic-video-review-card-head');
      rightHead.append(el('h2','视频预览'));
      rightCard.append(rightHead);

      const playerBody=el('div',null,'classic-video-review-player-body');
      rightCard.append(playerBody);

      function renderRight(){
        if(activeVideo){
          activeVideo.pause?.();
          activeVideo=null;
        }
        playerBody.replaceChildren();
        const current=items[currentIndex];
        if(!items.length||!playableIndices.length||!current?.has_video){
          const empty=el('div',null,'classic-video-review-empty');
          empty.append(emptyGraphic(),el('p','暂无数据'));
          playerBody.append(empty);
          return;
        }
        const video=el('video',null,'classic-video-review-screen');
        video.controls=true;video.preload='metadata';
        video.src=base(projectId)+'/media/'+encodeURIComponent(current.media_id)+'/content';
        activeVideo=video;
        let isPlaying=false;

        const transport=el('div',null,'classic-video-review-transport');
        const playToggle=el('button','▶ 播放片段','classic-video-review-play');playToggle.type='button';
        const posLabel=el('span',`第 ${currentIndex+1}/${items.length} 段 · ${current.shot_title||current.shot_id}`,'hint');
        const nextPlayable=()=>{
          const pos=playableIndices.indexOf(currentIndex);
          return pos>=0&&pos+1<playableIndices.length?playableIndices[pos+1]:null;
        };

        const commentWrap=el('div',null,'classic-video-review-comment-box');
        const comment=el('textarea',null,'classic-video-review-comment');
        comment.rows=3;
        const placeholderText=`第${currentIndex+1}段视频 审核意见（视频播放暂停才能填写）`;
        bindAttribute(comment,'placeholder',placeholderText);
        bindAttribute(comment,'aria-label',placeholderText);

        const decisionSelect=el('select');
        bindAttribute(decisionSelect,'aria-label','审核结论');
        for(const [val,label]of [['rework','继续整改'],['pass','审核通过'],['reject','淘汰重做']]){
          decisionSelect.append(localizedOption(val,label));
        }

        const submitReviewBtn=el('button','提交审核意见','classic-primary');submitReviewBtn.type='button';
        const markReadBtn=el('button','标记已阅');markReadBtn.type='button';
        markReadBtn.disabled=!ctx.session().actor||!ctx.session().writable||!(current.reviews||[]).length;
        const reviewStatus=el('p','','hint');reviewStatus.setAttribute('role','status');

        const syncPauseGate=()=>{
          const isPaused=!isPlaying&&video.paused!==false;
          comment.disabled=!isPaused;
          submitReviewBtn.disabled=!isPaused||!ctx.session().actor||!ctx.session().writable;
          setText(playToggle,isPaused?'▶ 播放片段':'⏸ 暂停以填写审核意见');
          setText(reviewStatus,isPaused?'当前已暂停，可填写该段视频审核意见。':'视频播放中，审核意见输入框已锁定，暂停后可填写。');
        };

        playToggle.addEventListener('click',()=>{
          if(isPlaying||video.paused===false){
            isPlaying=false;
            video.pause?.();
            syncPauseGate();
          }else{
            isPlaying=true;
            video.play?.().catch(()=>{isPlaying=false;syncPauseGate();});
            syncPauseGate();
          }
        });
        video.addEventListener('play',()=>{isPlaying=true;syncPauseGate();});
        video.addEventListener('playing',()=>{isPlaying=true;syncPauseGate();});
        video.addEventListener('pause',()=>{isPlaying=false;syncPauseGate();});
        video.addEventListener('ended',()=>{
          isPlaying=false;syncPauseGate();
          const nxt=nextPlayable();
          if(nxt!=null){
            currentIndex=nxt;
            renderLeft();
            renderRight();
          }
        });

        submitReviewBtn.addEventListener('click',async()=>{
          if(isPlaying||video.paused===false){
            ctx.notice('请先暂停视频后再提交审核意见');
            return;
          }
          const sess=ctx.session();
          const note=comment.value.trim()||(decisionSelect.value==='pass'?'审片台审核通过':'');
          const outcomeMap={rework:'needs_changes',pass:'pass',reject:'fail'};
          const outcome=outcomeMap[decisionSelect.value]||'needs_changes';
          if(outcome!=='pass'&&!comment.value.trim()){
            ctx.notice('继续整改或淘汰时请填写具体审核意见');
            return;
          }
          if(current.submission_id){
            const committed=await ctx.api(base(projectId)+'/team-review/commit',{
              method:'POST',
              headers:{'Content-Type':'application/json','X-CSRF-Token':sess.csrf},
              body:JSON.stringify({
                payload:{submission_id:current.submission_id,outcome,reason:note},
                expected_revision:sess.revision,
                idempotency_key:crypto.randomUUID(),
              }),
            });
            if(committed.revision!=null)ctx.setRevision(committed.revision,projectId);
          }else{
            const recorded=await ctx.api(base(projectId)+'/reviews',{
              method:'POST',
              headers:{'Content-Type':'application/json','X-CSRF-Token':sess.csrf},
              body:JSON.stringify({
                payload:{
                  candidate_id:current.candidate_id,
                  reviewer_type:'human',
                  criteria_version:'video-review-v1',
                  outcome,
                  reason:note,
                  evidence:{media_id:current.media_id,shot_id:current.shot_id},
                },
                expected_revision:sess.revision,
                idempotency_key:crypto.randomUUID(),
              }),
            });
            if(recorded.revision!=null)ctx.setRevision(recorded.revision,projectId);
          }
          ctx.notice('审核意见已记录');
          await load(scope);
        });

        markReadBtn.addEventListener('click',async()=>{
          const sess=ctx.session();
          const res=await ctx.api(base(projectId)+'/team-review/mark-read',{
            method:'POST',
            headers:{'Content-Type':'application/json','X-CSRF-Token':sess.csrf},
            body:JSON.stringify({
              payload:{candidate_id:current.candidate_id||null,media_id:current.media_id,shot_id:current.shot_id||null,submission_id:current.submission_id||null,note:'审片台确认已阅'},
              expected_revision:sess.revision,
              idempotency_key:crypto.randomUUID(),
            }),
          });
          if(res.revision!=null)ctx.setRevision(res.revision,projectId);
          ctx.notice('已标记为已阅');
          await load(scope);
        });

        transport.append(playToggle,posLabel);
        const actionRow=el('div',null,'classic-video-review-actions');
        actionRow.append(decisionSelect,submitReviewBtn,markReadBtn);
        commentWrap.append(comment,actionRow,reviewStatus);

        const history=el('details',null,'classic-video-review-history');
        const reviews=current.reviews||[];
        history.append(el('summary',`历史审核意见 (${reviews.length})`));
        if(!reviews.length){
          history.append(el('p','暂无历史审核意见','hint'));
        }else{
          for(const rev of reviews){
            const decisionLabel=({pass:'通过',needs_changes:'待整改',fail:'淘汰'})[rev.outcome||rev.decision]||(rev.outcome||rev.decision||'审阅');
            history.append(el('p',`${decisionLabel}${rev.read_ack?' · 已阅':''} · ${rev.created_by||rev.actor||'审阅人'}：${rev.reason||rev.note||'（无备注）'}`,'classic-video-review-history-item'));
          }
        }
        syncPauseGate();
        playerBody.append(video,transport,commentWrap,history);
      }

      function renderLeft(){
        clipList.replaceChildren();
        if(!items.length){
          const empty=el('div',null,'classic-video-review-empty');
          empty.append(emptyGraphic(),el('p','暂无数据'));
          clipList.append(empty);
          return;
        }
        for(const [idx,item]of items.entries()){
          const row=el('div',null,'classic-video-review-clip'+(idx===currentIndex?' is-active':''));
          row.dataset.shotId=item.shot_id;
          if(item.has_video&&item.media_id){
            const cb=el('input');cb.type='checkbox';cb.checked=checkedMediaIds.has(item.media_id);
            bindAttribute(cb,'aria-label',`勾选下载第${idx+1}段视频`);
            cb.addEventListener('change',()=>{
              if(cb.checked)checkedMediaIds.add(item.media_id);
              else checkedMediaIds.delete(item.media_id);
            });
            row.append(cb);
          }
          const openBtn=el('button',`#${idx+1} ${item.shot_title||item.shot_id}`,'classic-video-review-clip-open');
          openBtn.type='button';
          openBtn.disabled=!item.has_video;
          openBtn.addEventListener('click',()=>{
            currentIndex=idx;
            renderLeft();
            renderRight();
          });
          const badgeText=item.has_video?({pass:'已通过',needs_changes:'待整改',rework:'待整改',fail:'淘汰',reject:'淘汰',pending:'待审',unreviewed:'未审阅',unsubmitted:'未提审'})[item.review_status]||item.review_status:'无视频';
          row.append(openBtn,el('span',badgeText,'classic-video-review-badge'));
          clipList.append(row);
        }
      }

      renderLeft();
      renderRight();
      grid.append(leftCard,rightCard);

      const footer=el('footer',null,'classic-video-review-footer');
      const downloadBtn=el('button','下载选中视频片段','classic-video-review-download classic-primary');
      downloadBtn.type='button';
      downloadBtn.addEventListener('click',()=>{
        if(!checkedMediaIds.size){
          ctx.notice('请先勾选至少 1 个可下载的视频片段');
          return;
        }
        const dlQs=new URLSearchParams({
          scope:'selected',
          ...(resolvedEpisodeId?{episode_id:resolvedEpisodeId}:{}),
          media_ids:[...checkedMediaIds].join(','),
        });
        const a=el('a');
        a.href=base(projectId)+'/classic-production/video-download?'+dlQs.toString();
        a.download='selected-review-videos.zip';
        a.click?.();
      });
      footer.append(downloadBtn);
      root.append(header,grid,footer);
      return true;
    }catch(err){
      if(active&&n===epoch){
        root.replaceChildren(el('p',err.message||'审片台加载失败','hint'));
      }
      return false;
    }
  }

  return {load,suspend:stop};
}

export function createFcpPortal(root,ctx){
  let cleanup=null;
  function suspend(){
    cleanup?.();cleanup=null;
  }
  async function load(scope={}){
    suspend();
    const locale=String(scope.locale||'en').toLowerCase();
    root.replaceChildren();
    root.className='classic-subpage fcp-portal-page';
    const frame=el('iframe',null,'fcp-portal-frame');
    frame.src='/api/v1/fcp-embed/'+encodeURIComponent(locale);
    bindAttribute(frame,'title',`SkyReels Overseas FCP Portal (${locale})`);
    const expectedOrigin=globalThis.window?.location?.origin||globalThis.location?.origin||'';
    const sendAuth=()=>{
      const sess=ctx.session?.()||{};
      if(!expectedOrigin)return;
      frame.contentWindow?.postMessage?.({
        type:'fcp-auth-state',
        authenticated:Boolean(sess.actor),
        actor:sess.actor||null,
        locale,
      },expectedOrigin);
    };
    frame.addEventListener('load',sendAuth);
    const onMessage=event=>{
      if(expectedOrigin&&event?.origin!==expectedOrigin)return;
      if(frame.contentWindow&&event?.source!==frame.contentWindow)return;
      const msgData=event?.data;
      if(!msgData||typeof msgData!=='object')return;
      if(msgData.type==='fcp-request-auth')sendAuth();
      else if(msgData.type==='fcp-navigate-home')ctx.navigate('home',null);
      else if(msgData.type==='fcp-close-home')ctx.navigate('projects',null);
      else if(msgData.type==='fcp-home-popup-blocked')ctx.notice('浏览器拦截了新窗口，请在当前工作台继续操作。');
      else if(msgData.type==='fcp-action'&&msgData.action==='login')ctx.openSessionDialog?.();
    };
    globalThis.window?.addEventListener?.('message',onMessage);
    cleanup=()=>globalThis.window?.removeEventListener?.('message',onMessage);
    root.append(frame);
    return true;
  }
  return {load,suspend};
}
