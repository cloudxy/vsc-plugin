"""Application consumers for versioned episode planning and original production drafts."""
from copy import deepcopy
import json
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.production.quotes import fingerprint
from vsc.production.intelligent_production import DEFINITION,ROUTES,TEMPLATES,normalize_document,normalize_unit,GrokBuildIntelligentPlanner,execute_planning


class IntelligentProductionServiceMixin:
    def intelligent_options(self,p):
        from vsc.production.resource_settings import ResourceSettings
        tree=self.get_project_tree(p);backend=getattr(self,'intelligent_planner',None) or GrokBuildIntelligentPlanner()
        return dict(definition=deepcopy(DEFINITION),routes=ROUTES,templates=deepcopy(TEMPLATES),nodes=tree['nodes'],models=ResourceSettings(self.store).list()['configurations'],host_available=backend.available(),media=self.list_resources(p,limit=200)['items'],revision=tree['revision'])
    def list_intelligent_workflows(self,p,episode_id=None):return self.store.list_intelligent_workflows(p,episode_id)
    def get_intelligent_workflow(self,p,identifier,version_id=None):
        result=self.store.get_intelligent_workflow(p,identifier,version_id)
        for row in result['selected_media']:
            row['url']='/api/v1/projects/'+p+'/media/'+row['media_id']+'/content'
        result['warnings']=self._intelligent_warnings(result['state'])
        result['episode_assets']=self.list_episode_assets(p,result['workflow']['episode_id'])['items']
        result['working_selections']=self.list_working_selections(p,episode_id=result['workflow']['episode_id'])['items']
        return result
    @staticmethod
    def _intelligent_warnings(state):
        output=[]
        for u in state['units']:
            if u['segments'] and max(s['end_ms'] for s in u['segments'])!=u['duration_ms']:output.append(dict(unit_key=u['unit_key'],code='duration_mismatch',message='分段脚本总时长与目标时长不一致'))
        return output
    def create_intelligent_workflow(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.create_intelligent_workflow(p,payload,**kw)
    def preview_intelligent_change(self,p,payload):
        if not isinstance(payload,dict) or set(payload)!={'workflow_id','base_version_id','state'}:raise ResourceError('修改预览需要固定基线与完整草稿')
        current=self.get_intelligent_workflow(p,payload['workflow_id'])
        if current['version']['id']!=payload['base_version_id']:raise Conflict('流程已有新版本，请保稿后比较')
        state=payload['state']
        if not isinstance(state,dict) or set(state)!={'document','source_artifact_id','template_artifact_id','route','blocking_mode','assets','units','dependencies','media'}:raise ResourceError('流程状态字段不完整')
        if any(not isinstance(state[k],list) for k in ('assets','units','dependencies','media')):raise ResourceError('资产、单元、依赖和媒体必须为列表')
        normalize_document(state['document']);[normalize_unit(u) for u in state['units']]
        old={u['unit_key']:u for u in current['state']['units']};new={u['unit_key']:u for u in state['units']}
        changes=[dict(unit_key=k,change='removed' if k not in new else 'changed') for k,u in old.items() if new.get(k)!=u]
        impacted={r['unit_key'] for r in changes}
        inputs_changed=any(current['state'][k]!=state[k] for k in ('document','route','blocking_mode','assets','dependencies','media'))
        if inputs_changed:impacted.update(old)
        result=dict(revision=current['revision'],changes=changes,inputs_changed=inputs_changed,retained_selected_media=[m for m in current['state']['media'] if m['unit_key'] in impacted],retained_runs=[r for r in current['runs'] if r['unit_key'] in impacted],warnings=self._intelligent_warnings(state),original_media_deleted=False)
        result['sha256']=fingerprint(dict(request=payload,impact=result));return result
    def save_intelligent_workflow(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.save_intelligent_workflow(p,payload,build_preview=self.preview_intelligent_change,**kw)
    def create_intelligent_task(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.create_intelligent_task(p,payload,**kw)
    def get_intelligent_task(self,p,identifier):return self.store.get_intelligent_task(p,identifier)
    def execute_intelligent_task(self,p,identifier):
        self.authorize_access(p,'execute');return execute_planning(self,p,identifier)
    def decide_intelligent_task(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.decide_intelligent_task(p,payload,**kw)

    def _compile_intelligent_drafts(self,p,payload):
        from vsc.production.resource_settings import ResourceSettings
        current=self.get_intelligent_workflow(p,payload['workflow_id']);state=current['state'];keys=payload.get('unit_keys');purpose=payload.get('purpose')
        model=next((m for m in ResourceSettings(self.store).list()['configurations'] if m['id']==payload.get('model_id')),None)
        if current['version']['id']!=payload.get('version_id'):raise Conflict('运行准备需要当前固定版本')
        if not isinstance(keys,list) or not 1<=len(keys)<=200 or len(set(keys))!=len(keys) or purpose not in {'blocking','lineart','video'}:raise ResourceError('请选择唯一单元及真实用途')
        by_key={u['unit_key']:u for u in state['units']}
        if any(k not in by_key for k in keys):raise ResourceError('所选单元不存在')
        output=[]
        for key in keys:
            unit=by_key[key];gaps=[];references=[]
            def gap(code,message):gaps.append(dict(code=code,message=message))
            if unit['skip_reason']:gap('unit_skipped','该单元已明确跳过；先回补才会制作')
            if not unit['shot_id']:gap('original_shot_required','先导入或映射原镜头')
            if purpose=='blocking' and unit['kind']!='blocking' or purpose in {'lineart','video'} and unit['kind']!='shot':gap('unit_purpose_mismatch','单元与运行用途不匹配')
            if purpose=='blocking' and state['blocking_mode']=='3d':gap('spatial_export_required','三维站位请进入原导演台，保存场景并导出实际截图')
            if purpose=='video' and any(w['unit_key']==key for w in self._intelligent_warnings(state)):gap('duration_mismatch','请核对逐段时间与目标时长后保存')
            for dep in [d for d in current['dependency_inputs'] if d['unit_key']==key]:
                if not dep['selected']:gap('anchor_not_selected','依赖首图尚无固定工作图片；选图保存后刷新依赖引用')
                for media in dep['selected']:references.append(dict(role='reference_image',media_id=media['media_id'],**({'episode_asset_form_version_id':media['episode_asset_form_version_id']} if media.get('episode_asset_form_version_id') else {})))
            for media in [m for m in state['media'] if m['unit_key']==key]:
                if purpose in {'blocking','lineart'}:
                    if media['purpose'] in {'reference_image','blocking','first_frame'}:references.append(dict(role='reference_image',media_id=media['media_id'],**({'episode_asset_form_version_id':media['episode_asset_form_version_id']} if media.get('episode_asset_form_version_id') else {})))
                else:
                    role=unit['lineart_purpose'] if media['purpose']=='lineart' else 'first_frame' if media['purpose']=='first_frame' else 'reference_image'
                    if role!='none':references.append(dict(role=role,media_id=media['media_id'],**({'episode_asset_form_version_id':media['episode_asset_form_version_id']} if media.get('episode_asset_form_version_id') else {})))
            references=list({(r['role'],r['media_id']):r for r in references}.values())
            if purpose!='video':mode='image';run_purpose='keyframe'
            else:
                mode='multi' if state['route']=='multi_reference_video' else 'single' if state['route']=='storyboard_video' else 'multi' if len(references)>1 else 'single' if any(r['role']=='first_frame' for r in references) else 'text'
                if mode=='single' and not any(r['role']=='first_frame' for r in references):gap('first_frame_required','分镜画面路线需要明确工作首帧，不能把任意参考静默当首帧')
                if mode=='text' and references:gap('reference_role_required','单张参考请明确首帧用途，或补齐多参考路线')
                run_purpose='video_clip'
            choices=('keyframe','shot_keyframe','first_frame','ref') if purpose!='video' else ('reference_to_video','image_to_video','video_clip','i2v') if mode=='multi' else ('image_to_video','video_clip','i2v') if mode!='text' else ('text_to_video','video_clip')
            if model:run_purpose=next((name for name in choices if name in model['capabilities'].get('purposes',[])),run_purpose)
            description=unit['description']
            if purpose=='lineart':description='绘制分镜网格线稿；保持以下逐段叙事与参考空间关系。\n'+description
            if unit['segments']:description+='\n'+'\n'.join(f"{s['start_ms']/1000:g}–{s['end_ms']/1000:g}秒：{s['text']}" for s in unit['segments'])
            document=dict(shot_id=unit['shot_id'],mode=mode,purpose=run_purpose,model_id=payload.get('model_id',''),prompt=description,duration_ms=unit['duration_ms'],width=payload.get('width',1080),height=payload.get('height',1920),count=payload.get('count',1),params=payload.get('params',{}),references=references)
            if not gaps:document=self._classic_document(p,document)
            output.append(dict(unit_key=key,document=document,gaps=gaps))
        return output
    def prepare_intelligent_drafts(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.prepare_intelligent_drafts(p,payload,compile_drafts=self._compile_intelligent_drafts,**kw)
    def preview_intelligent_runs(self,p,payload):
        if not isinstance(payload,dict) or set(payload)-{'workflow_id','version_id','purpose','items','execution_policy','commerce_account_actor'}:raise ResourceError('批量预览字段无效')
        workflow=self.get_intelligent_workflow(p,payload['workflow_id'])
        if payload['version_id']!=workflow['version']['id']:raise Conflict('流程版本改变，请重新准备')
        rows=payload.get('items')
        if not isinstance(rows,list) or not 1<=len(rows)<=200:raise ResourceError('请选择已准备的单元草稿')
        items=[];seen=set()
        for row in rows:
            if set(row)!={'unit_key','draft_artifact_id'} or row['unit_key'] in seen:raise ResourceError('批量项目标识无效')
            seen.add(row['unit_key']);artifact=self.get_artifact_version(p,row['draft_artifact_id'])
            expected='intelligent-classic:'+payload['version_id']+':'+row['unit_key']+':'+payload['purpose']
            if artifact['artifact_key']!=expected or artifact['artifact_type']!='classic-production-draft':raise ResourceError('草稿不属于此固定单元和用途')
            request=dict(draft_version_id=row['draft_artifact_id'],execution_policy=payload['execution_policy'])
            if 'commerce_account_actor' in payload:request['commerce_account_actor']=payload['commerce_account_actor']
            preview=self.preview_classic_run(p,request);items.append(dict(row,preview=preview))
        revision=self.get_project(p)['revision']
        if revision!=workflow['revision'] or any(i['preview']['revision']!=revision for i in items):raise Conflict('预览期间项目发生改变')
        result=dict(items=items,ready=all(i['preview']['ready'] for i in items),revision=revision,provider_submitted=False)
        result['sha256']=fingerprint(dict(request=payload,result=result));return result
    def propose_intelligent_runs(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.propose_intelligent_runs(p,payload,build_preview=self.preview_intelligent_runs,**kw)
    def copy_intelligent_unit(self,p,payload,**kw):
        self._validate_write(payload,**kw);return self.store.copy_intelligent_unit(p,payload,**kw)

    def preview_intelligent_missing_assets(self,p,payload):
        from vsc.production.canvas_execution import preview_request
        current=self.get_intelligent_workflow(p,payload.get('workflow_id'))
        if current['version']['id']!=payload.get('version_id'):raise Conflict('缺图准备需要当前固定版本')
        rows=self.store.intelligent_asset_inputs(p,current['version']['id']);items=[]
        for row in rows:
            if row['asset_kind']=='voice':
                items.append(dict(asset_key=row['asset_key'],ready=False,gaps=[dict(code='voice_adapter_required',message='音色沿原声音能力；不能用图片任务替代')]));continue
            context=self.compile_asset_context(p,row['asset_id'],'identity_ref',spec_version_id=row['spec_id'])
            if context['media']:
                items.append(dict(asset_key=row['asset_key'],status='already_selected',ready=False,gaps=[]));continue
            prompt='制作该固定资产形态的独立参考图。\n'+json.dumps(context.get('semantic_inputs') or row['specification'],ensure_ascii=False)
            result=preview_request(self,p,target=dict(asset_id=row['asset_id'],spec_version_id=row['spec_id']),purpose='identity_ref',modality='image',prompt=prompt,model_ids=[payload.get('model_id')],logical={},execution_policy=payload.get('execution_policy'),billing={k:payload[k] for k in ['commerce_account_actor'] if k in payload},key='intelligent-asset:'+current['version']['id']+':'+row['asset_key'])
            items.append(dict(asset_key=row['asset_key'],**result))
        result=dict(workflow_id=current['workflow']['id'],version_id=current['version']['id'],episode_id=current['workflow']['episode_id'],items=items,revision=current['revision'])
        result['sha256']=fingerprint(result);return result

    def propose_intelligent_missing_assets(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.propose_intelligent_missing_assets(p,payload,build_preview=self.preview_intelligent_missing_assets,**kw)

    def advance_intelligent_runs(self,p,payload,actor):
        from vsc.production.canvas_execution import advance_runs
        current=self.get_intelligent_workflow(p,payload.get('workflow_id'))
        if current['version']['id']!=payload.get('version_id'):raise Conflict('请重新核对当前流程版本')
        # The original bounded runtime continues already started, approved jobs.
        return advance_runs(self,p,[r['run_artifact_id'] for r in current['runs']+current.get('asset_runs',[])],actor)
