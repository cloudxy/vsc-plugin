"""Creative inputs and MV imports use original artifacts, objects and receipts."""
import json
from sqlalchemy import select, func, insert

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.production.creative_tools import DRAFT_TYPE, compile_mv
from . import schema as S
from .values import checked_id, clean, new_id, digest, CURRENT_REVISION


class CreativeToolsRepository:
    def __init__(self, store):
        self.store = store

    def workspace_identity(self,actor):
        from .access_control import authority_lock
        from vsc.assets.access_control import denied
        with self.store.engine.begin() as conn:
            authority_lock(conn);principal,person,_=self.store._access_principal(conn)
            if not principal or not person or principal.api_key_id or person['actor']!=actor:denied('独立工具需要已登录成员身份')
            return person['id']

    def ensure_workspace(self,p,identity,actor):
        import uuid
        work_id=str(uuid.uuid5(uuid.UUID(p),'creative-tools-work'));episode_id=str(uuid.uuid5(uuid.UUID(p),'creative-tools-scope'))
        def work(conn,project):
            if project['profile_snapshot'].get('workspace_kind')!='creative-tools':raise ResourceError('不是独立工具范围')
            self.store._create_object(conn,project,dict(id=work_id,kind='work',display_code='TOOLS',title='工具内容'))
            self.store._create_object(conn,project,dict(id=episode_id,kind='episode',parent_id=work_id,ordinal=0,display_code='TOOL-SCOPE',title='工具内容'))
            return {'id':p,'episode_id':episode_id,'standalone':True}
        result=self.store._mutate(p,'initialize_creative_tools',{'identity_id':identity},expected_revision=CURRENT_REVISION,
            idempotency_key='creative-tools-scope:'+identity,actor=actor,callback=work)
        # A receipt confirms the original initialization, not that its current
        # workspace is still usable. Reopening must preserve explicit recycle.
        from .access_control import authority_lock
        from .project_management import management_object_guard
        with self.store.engine.begin() as conn:
            authority_lock(conn)
            project=self.store._project(conn,p,lock=True)
            self.store._access_require(conn,p,'read')
            management_object_guard(conn,p,episode_id)
            return dict(result,revision=project['revision'])

    def _import_plan(self,conn,project,payload,storage):
        from .project_management import management_object_guard,management_project_guard
        from .media_recycle import recycled_ids
        from vsc.assets.access_control import denied
        required={'source_project_id','source_artifact_id','source_media_id','sha256','episode_id','audio_purpose'}
        if not isinstance(payload,dict) or set(payload)!=required:raise ResourceError('导入需要固定输出、摘要、目标集和音轨用途')
        principal,person,_=self.store._access_principal(conn)
        if not principal or not person or principal.api_key_id:denied('导入需要真实成员会话')
        p=project['id'];source=checked_id(payload['source_project_id']);episode=checked_id(payload['episode_id'])
        if p==source:raise ResourceError('请选择另一个目标项目')
        if project['profile_snapshot'].get('workspace_kind') in {'text-tools','creative-tools'}:raise ResourceError('目标请选择影视项目中的实际一集')
        self.store._access_require(conn,p,'edit');self.store._access_require(conn,source,'read')
        management_project_guard(conn,source);management_object_guard(conn,p,episode);self.store._one(conn,S.episodes,p,episode)
        artifact=self.store._one(conn,S.artifact_versions,source,checked_id(payload['source_artifact_id']))
        if artifact['artifact_type'] not in {'local-tool-output','creative-tool-output'}:raise ResourceError('只能导入已登记的工具输出')
        document=json.loads(artifact['document']);management_object_guard(conn,source,document['episode_id'])
        member=next((row for row in document['outputs'] if row['id']==payload['source_media_id']),None)
        if not member or member['sha256']!=payload['sha256']:raise Conflict('所选媒体不属于固定输出或摘要不符','tool_import_source_changed')
        media=self.store._media(conn,source,member['id'])
        if media['sha256']!=payload['sha256']:raise Conflict('源字节摘要已改变','tool_import_source_changed')
        if conn.execute(select(S.media_items.c.id).where(S.media_items.c.project_id==source,S.media_items.c.id==media['id'],S.media_items.c.id.in_(recycled_ids(source)))).first():raise ResourceError('源素材已回收')
        lifecycle=self.store._latest(conn,S.media_lifecycle_decisions,source,'media_id',media['id'])
        rights=self.store._latest(conn,S.rights_decisions,source,'media_id',media['id'])
        if lifecycle and lifecycle['outcome']=='deprecate' or rights and rights['outcome'] not in {'owned','licensed','unknown'}:raise ResourceError('源素材已停用或权利受限')
        location=next((row for row in media['locations'] if row['storage']=='local' and row['available']),None)
        if storage is None or not location:raise ResourceError('需要受控本机字节')
        storage.verify(location['object_key'],media['sha256'])
        if payload['audio_purpose'] not in {'music','ambience','sfx','dialogue_dry'}:raise ResourceError('音轨用途需为音乐、环境、音效或对白')
        prior=conn.execute(select(S.creative_tool_imports).where(S.creative_tool_imports.c.project_id==p,S.creative_tool_imports.c.episode_id==episode,
            S.creative_tool_imports.c.source_project_id==source,S.creative_tool_imports.c.source_artifact_id==artifact['id'],S.creative_tool_imports.c.source_media_id==media['id'])).mappings().first()
        workspace=conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id==p,S.edit_workspaces.c.episode_id==episode)).mappings().first()
        return dict(source=source,artifact=artifact,media=media,location=location,episode_id=episode,workspace=dict(workspace) if workspace else None,prior=dict(prior) if prior else None)

    def preview_import(self,project_id,payload,*,storage):
        from .access_control import authority_lock
        with self.store.engine.begin() as conn:
            authority_lock(conn);project=self.store._project(conn,project_id);plan=self._import_plan(conn,project,payload,storage)
            return clean(dict(project_id=project_id,revision=project['revision'],preview_sha256=digest({'request':payload,'target_revision':project['revision']}),
                source_name=plan['media']['name'],sha256=plan['media']['sha256'],episode_id=plan['episode_id'],
                rights='unknown',existing_media_id=plan['prior']['media_id'] if plan['prior'] else None,
                action='加入目标集剪辑工作稿；音轨从集起点开始，可在剪辑调整。权利待确认，不自动选片或批准'))

    def import_output(self,project_id,payload,*,storage,**kw):
        from copy import deepcopy
        from vsc.post.edit_workspace import FORMAT
        from .editor_workspace import EditorWorkspaceRepository
        if not isinstance(payload,dict) or set(payload)!={'request','preview_sha256'}:raise ResourceError('先预览固定输出及目标集')
        request=payload['request'];source=checked_id(request.get('source_project_id'))
        def work(conn,project):
            plan=self._import_plan(conn,project,request,storage)
            if plan['prior']:
                version=conn.execute(select(S.edit_revisions.c.id).join(S.edit_revision_media,
                    (S.edit_revision_media.c.project_id==S.edit_revisions.c.project_id)&(S.edit_revision_media.c.edit_version_id==S.edit_revisions.c.id)).where(
                    S.edit_revisions.c.project_id==project['id'],S.edit_revisions.c.workspace_id==plan['workspace']['id'],
                    S.edit_revision_media.c.media_id==plan['prior']['media_id']).order_by(S.edit_revisions.c.version).limit(1)).scalar_one()
                return dict(plan['prior'],already_imported=True,edit_version_id=version)
            if payload['preview_sha256']!=digest({'request':request,'target_revision':project['revision']}):raise Conflict('目标剪辑或项目已变化，请重新预览','tool_import_stale')
            media=plan['media'];location=plan['location'];p=project['id']
            reused=conn.execute(select(S.creative_tool_imports.c.media_id).where(S.creative_tool_imports.c.project_id==p,
                S.creative_tool_imports.c.source_project_id==source,S.creative_tool_imports.c.source_artifact_id==plan['artifact']['id'],S.creative_tool_imports.c.source_media_id==media['id']).limit(1)).scalar_one_or_none()
            if reused:
                from .media_recycle import recycled_ids
                if conn.execute(select(S.media_items.c.id).where(S.media_items.c.project_id==p,S.media_items.c.id==reused,S.media_items.c.id.in_(recycled_ids(p)))).first():raise ResourceError('此输出在目标项目已回收，请先恢复原媒体')
            registered={'id':reused} if reused else self.store._register_media(conn,project,dict(media,id=new_id(),storage='local',object_key=location['object_key'],rights='unknown',
                source={'kind':'creative-tool-import','content':{'source_project_id':source,'source_artifact_id':plan['artifact']['id'],
                    'source_artifact_sha256':plan['artifact']['sha256'],'source_media_id':media['id'],'sha256':media['sha256']}}),kw['actor'])
            current=plan['workspace'];document=deepcopy(self.store._one(conn,S.edit_revisions,p,current['current_version_id'])['document']) if current else dict(format=FORMAT,width=720,height=1280,fps=24,clips=[],audio=[],captions=[])
            clip=dict(id='import-'+registered['id'],media_id=registered['id'],in_frame=0,out_frame=max(1,int((media.get('duration_ms') or 2000)*document['fps']/1000)),volume=1,muted=False)
            if media['modality']=='audio':clip.update(at_frame=0,purpose=request['audio_purpose']);document['audio'].append(clip)
            else:document['clips'].append(clip)
            edit=EditorWorkspaceRepository(self.store).save(p,dict(episode_id=plan['episode_id'],edit_revision=current['revision'] if current else 0,document=document),_transaction=(conn,project),**kw)
            row=dict(project_id=p,id=new_id(),episode_id=plan['episode_id'],media_id=registered['id'],source_project_id=source,
                source_artifact_id=plan['artifact']['id'],source_media_id=media['id'],blob_id=media['blob_id'],sha256=media['sha256'])
            conn.execute(insert(S.creative_tool_imports).values(**row))
            return dict(row,already_imported=False,edit_version_id=edit['edit_version_id'])
        return self.store._mutate(project_id,'import_creative_output',payload,callback=work,_related_projects=(source,),**kw)

    def _lyrics_read(self,conn,project,identifier):
        from datetime import datetime,timezone,timedelta
        row=self.store._one(conn,S.artifact_versions,project['id'],checked_id(identifier))
        if row['artifact_type']!='lyrics-request':raise ResourceError('需要原歌词创作尝试')
        data=json.loads(row['document'])
        result=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project['id'],S.artifact_versions.c.artifact_key=='lyrics-result:'+identifier)).mappings().first()
        status=json.loads(result['document'])['status'] if result else 'submission_unknown' if row['created_at']+timedelta(seconds=180)<datetime.now(timezone.utc) else 'running'
        return clean(dict(data,id=identifier,kind='lyrics',status=status,result_version_id=result['id'] if result else None,result=json.loads(result['document']) if result else None,revision=project['revision']))

    def lyrics_result(self,p,identifier):
        with self.store.engine.connect() as conn:return self._lyrics_read(conn,self.store._project(conn,p),identifier)

    def music_results(self,p,episode):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p)
            rows=conn.execute(select(S.artifact_versions).join(S.artifact_object_scopes,(S.artifact_object_scopes.c.project_id==S.artifact_versions.c.project_id)&(S.artifact_object_scopes.c.artifact_id==S.artifact_versions.c.id)).where(S.artifact_versions.c.project_id==p,S.artifact_object_scopes.c.object_id==episode,S.artifact_versions.c.artifact_type.in_(['lyrics-request','music-analysis'])).order_by(S.artifact_versions.c.created_at.desc())).mappings()
            return clean([self._lyrics_read(conn,project,row['id']) if row['artifact_type']=='lyrics-request' else dict(json.loads(row['document']),id=row['id'],kind='beats',status='completed',result_version_id=row['id']) for row in rows])

    def start_lyrics(self,p,payload,*,caller,backend,**kw):
        from vsc.bootstrap import repository_root
        from vsc.project.role_runtime import bind_packet
        import hashlib
        def work(conn,project):
            row=self.store._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']))
            if row['artifact_type']!=DRAFT_TYPE:raise ResourceError('请保存歌词工具输入')
            saved=json.loads(row['document']);value=saved['input']
            if value['tool']!='lyrics' or not value['prompt'].strip():raise ResourceError('歌词创作需要明确主题或创作要求')
            requests=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_type=='lyrics-request').order_by(S.artifact_versions.c.created_at.desc())).mappings()
            for old in requests:
                previous=json.loads(old['document'])
                if previous['draft_version_id']!=row['id']:continue
                state=self._lyrics_read(conn,project,old['id'])
                if state['status'] in {'running','submission_unknown'} or not payload['new_attempt']:return dict(id=old['id'],caller=None)
                break
            skill='vsc-sound';role='music-supervisor';sha=hashlib.sha256((repository_root()/'skills'/skill/'SKILL.md').read_bytes()).hexdigest();identifier=new_id()
            packet=bind_packet(dict(context_id='lyrics-'+identifier,project={'project_id':p},revision=project['revision'],role=self.store._role(role),task=value['prompt'],inputs=[],approved_memories=[],scope=value['episode_id'],parent_brief={'content':json.dumps(dict(draft_version_id=row['id'],draft_sha256=row['sha256'],skill_sha256=sha)),'persistence':'context_file_only_not_long_term_memory'},rules=['仅对固定文本创作歌词建议，不生成演唱、不批准。','不得调用工具或媒体供应商。']),host='grok-build-lyrics',actor=kw['actor'],ownership=[])
            internal=dict(actor=kw['actor'],expected_revision=project['revision'],idempotency_key='lyrics-internal',_transaction=(conn,project))
            dispatch=self.store.create_role_dispatch(p,{'packet':packet},**internal)
            self.store.consume_role_dispatch(p,dict(dispatch_id=dispatch['dispatch_id'],instance_id=packet['dispatch']['instance_id'],role_id=role,context_sha256=packet['context_sha256'],packet=packet),**internal)
            data=dict(draft_version_id=row['id'],draft_sha256=row['sha256'],episode_id=value['episode_id'],dispatch_id=dispatch['dispatch_id'],skill_id=skill,skill_sha256=sha,backend=backend,created_by=kw['actor'])
            artifact=self.store._create_artifact(conn,project,dict(id=identifier,artifact_key='lyrics-request:'+identifier,artifact_type='lyrics-request',stage='production',document=data,dependency_ids=[row['id']],object_ids=[value['episode_id']]))
            return dict(id=artifact['id'],caller=caller)
        return self.store._mutate(p,'start_creative_lyrics',payload,callback=work,**kw)

    def finish_lyrics(self,p,identifier,result,error):
        request=self.lyrics_result(p,identifier)
        def work(conn,project):
            prior=self._lyrics_read(conn,project,identifier)
            if prior['result_version_id']:return dict(id=identifier)
            data=dict(request_id=identifier,draft_version_id=request['draft_version_id'],status='completed' if result is not None else 'submission_unknown' if error=='lyrics_submission_unknown' else 'failed',error=error,suggestion=result)
            artifact=self.store._create_artifact(conn,project,dict(artifact_type='lyrics-result',artifact_key='lyrics-result:'+identifier,stage='production',document=data,dependency_ids=[request['draft_version_id']],object_ids=[request['episode_id']]))
            packet=self.store._one(conn,S.role_dispatches,p,request['dispatch_id'])['packet'];d=packet['dispatch']
            returned=dict(role_id=d['role_id'],role_sha256=d['role_sha256'],context_id=packet['context_id'],context_sha256=packet['context_sha256'],dispatch_id=d['id'],instance_id=d['instance_id'],result_refs=[dict(kind='artifact',id=artifact['id'],sha256=artifact['sha256'])],memory_proposals=[])
            self.store.return_role_dispatch(p,dict(dispatch_id=d['id'],instance_id=d['instance_id'],role_id=d['role_id'],context_sha256=packet['context_sha256'],result=returned,return_key='lyrics:'+identifier,closed=True),actor=request['created_by'],expected_revision=project['revision'],idempotency_key='lyrics-return',_transaction=(conn,project))
            return dict(id=identifier)
        self.store._mutate(p,'finish_creative_lyrics',dict(request_id=identifier,result=result,error=error),callback=work,actor=request['created_by'],expected_revision=CURRENT_REVISION,idempotency_key='lyrics-finish:'+identifier)
        return self.lyrics_result(p,identifier)

    def analyze_music(self,p,payload,*,build,**kw):
        def work(conn,project):
            row=self.store._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']))
            if row['artifact_type']!=DRAFT_TYPE:raise ResourceError('分析需要保存的MV稿')
            saved=json.loads(row['document']);value=saved['input']
            if value['tool']!='mv' or not value['audio_media_id']:raise ResourceError('MV节拍分析需要固定音乐素材')
            key='music-analysis:'+row['id']+':'+str(payload['beats_per_segment'])
            prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:return dict(id=prior['id'],**json.loads(prior['document']),already_analyzed=True)
            media,gaps=self.store._usable(conn,p,value['audio_media_id'],'music')
            if [g for g in gaps if g!='technical_check_missing']:raise ResourceError('音乐素材当前不可用')
            pin=next(r for r in saved['media'] if r['role']=='audio')
            if pin['sha256']!=media['sha256'] or pin['duration_ms']!=media.get('duration_ms'):raise Conflict('音乐素材固定摘要或时长不符')
            analysis=build(media,payload['beats_per_segment'])
            if abs(analysis['decoded_duration_ms']-media['duration_ms'])>100:raise ResourceError('音频实测与登记时长差超过100ms，请先核对媒体')
            analysis['segments'][-1]['end_ms']=media['duration_ms']
            data=dict(draft_version_id=row['id'],audio_media_id=media['id'],audio_sha256=media['sha256'],source_duration_ms=media['duration_ms'],analysis=analysis)
            saved=self.store._create_artifact(conn,project,dict(artifact_type='music-analysis',artifact_key=key,stage='production',document=data,dependency_ids=[row['id']],object_ids=[value['episode_id']]))
            return dict(id=saved['id'],**data,already_analyzed=False)
        return self.store._mutate(p,'analyze_creative_music',payload,callback=work,**kw)

    def accept_music_result(self,p,payload,*,build,**kw):
        def work(conn,project):
            result=self.store._one(conn,S.artifact_versions,p,checked_id(payload['result_version_id']));data=json.loads(result['document'])
            if result['artifact_type'] not in {'lyrics-result','music-analysis'}:raise ResourceError('需要歌词或节拍建议结果')
            source=self.store._one(conn,S.artifact_versions,p,data['draft_version_id']);saved=json.loads(source['document']);value=saved['input']
            latest=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==source['artifact_key']).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            if latest!=payload['base_draft_id'] or latest!=source['id']:raise Conflict('人工稿已经改变；建议只供比较，不覆盖','music_result_stale')
            if result['artifact_type']=='lyrics-result':
                if data['status']!='completed':raise ResourceError('这次歌词尝试没有可接受结果')
                value.update(lyrics=data['suggestion']['lyrics'],title=data['suggestion']['title'] or value['title'])
            else:value['segments']=data['analysis']['segments']
            document=build(p,value)
            return self.store._create_artifact(conn,project,dict(artifact_type=DRAFT_TYPE,artifact_key=source['artifact_key'],stage='production',document=document,supersedes_id=source['id'],object_ids=[value['episode_id']]))
        return self.store._mutate(p,'accept_creative_music_result',payload,callback=work,**kw)

    def _mv_edit_plan(self,conn,project,payload):
        from vsc.post.edit_workspace import FORMAT,validate_edit
        if not isinstance(payload,dict) or set(payload)-{'draft_version_id','visual_segments'} or 'draft_version_id' not in payload:raise ResourceError('MV剪辑需固定已导入镜头计划的草稿')
        p=project['id'];artifact=self.store._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']))
        if artifact['artifact_type']!=DRAFT_TYPE:raise ResourceError('需要工具草稿')
        saved=json.loads(artifact['document']);value=saved['input']
        imported=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key=='mv-import:'+artifact['id'])).mappings().first()
        if value['tool']!='mv' or not imported:raise ResourceError('先保存并导入此固定MV稿的原镜头计划')
        plan=json.loads(imported['document'])['plan'];mapping=payload.get('visual_segments',value['params'].get('visual_segments'))
        if not isinstance(mapping,list) or len(mapping)!=len(plan['shots']):raise ResourceError('请为每个MV段落明确选择已有图片或视频，不自动补占位画面')
        fps=24;clips=[];pins=[]
        for index,(shot,item) in enumerate(zip(plan['shots'],mapping)):
            if not isinstance(item,dict) or set(item)!={'media_id','in_ms'} or type(item['in_ms'])is not int or item['in_ms']<0:raise ResourceError('MV视觉段落需媒体与非负剪入毫秒')
            media=self.store._media(conn,p,checked_id(item['media_id']))
            generated=conn.execute(select(S.job_outputs.c.media_id).join(S.generation_jobs,(S.generation_jobs.c.project_id==p)&(S.generation_jobs.c.id==S.job_outputs.c.job_id)).where(S.job_outputs.c.project_id==p,S.job_outputs.c.media_id==media['id'],S.generation_jobs.c.shot_id==shot['shot_id'],S.generation_jobs.c.status=='succeeded')).first()
            if media['modality'] not in {'image','video'} or media['id'] not in value['visual_media_ids'] and not generated:raise ResourceError('画面须来自本稿参考或此镜头成功候选')
            if media['modality']=='video' and (not media.get('duration_ms') or item['in_ms']+shot['duration_ms']>media['duration_ms']):raise ResourceError('选中视频不足以覆盖段落，不能静默循环')
            if media['modality']=='image' and item['in_ms']:raise ResourceError('静态图片剪入点须为0')
            pin=next((r for r in saved['media'] if r['media_id']==media['id']),None)
            if not generated and (not pin or pin['sha256']!=media['sha256']):raise Conflict('MV视觉素材固定摘要不符')
            # Cumulative rounding preserves the full music duration across short segments.
            length=round(shot['end_ms']*fps/1000)-round(shot['start_ms']*fps/1000)
            if length<1:raise ResourceError('MV段落短于一帧，请合并后重试')
            start=round(item['in_ms']*fps/1000)
            clips.append(dict(id='mv-'+str(index),shot_id=shot['shot_id'],media_id=media['id'],in_frame=start,out_frame=start+length,volume=1,muted=True));pins.append(dict(media_id=media['id'],sha256=media['sha256']))
        audio=self.store._media(conn,p,plan['audio_media_id'])
        if audio['sha256']!=plan['audio_sha256']:raise Conflict('MV音频SHA不符')
        document=dict(format=FORMAT,width=720,height=1280,fps=fps,clips=clips,audio=[dict(id='mv-music',media_id=audio['id'],purpose='music',in_frame=0,out_frame=round(plan['audio_duration_ms']*fps/1000),at_frame=0,volume=1)],captions=[])
        validate_edit(document)
        current=conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id==p,S.edit_workspaces.c.episode_id==value['episode_id'])).mappings().first()
        return dict(draft_version_id=artifact['id'],shot_plan_id=imported['id'],episode_id=value['episode_id'],edit_revision=current['revision'] if current else 0,document=document,media_pins=pins+[dict(media_id=audio['id'],sha256=audio['sha256'])],previous_document=self.store._one(conn,S.edit_revisions,p,current['current_version_id'])['document'] if current else None)

    def preview_mv_edit(self,p,payload):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);plan=self._mv_edit_plan(conn,project,payload)
            return clean(dict(plan=plan,preview_sha256=digest(plan),revision=project['revision']))

    def apply_mv_edit(self,p,payload,**kw):
        from .editor_workspace import EditorWorkspaceRepository
        def work(conn,project):
            plan=self._mv_edit_plan(conn,project,payload['request'])
            if digest(plan)!=payload['preview_sha256']:raise Conflict('原剪辑或固定MV素材已变，请重新预览')
            return EditorWorkspaceRepository(self.store).save(p,{k:plan[k] for k in ['episode_id','edit_revision','document']},_transaction=(conn,project),**kw)
        return self.store._mutate(p,'apply_creative_mv_edit',payload,callback=work,**kw)

    def outputs(self, project_id, episode_id):
        with self.store.engine.connect() as conn:
            p = self.store._project(conn, project_id)["id"]
            rows = conn.execute(select(S.artifact_versions).join(S.artifact_object_scopes,
                (S.artifact_object_scopes.c.project_id == S.artifact_versions.c.project_id) &
                (S.artifact_object_scopes.c.artifact_id == S.artifact_versions.c.id)).where(
                S.artifact_versions.c.project_id == p, S.artifact_versions.c.artifact_type.in_(["local-tool-output","creative-tool-output"]),
                S.artifact_object_scopes.c.object_id == episode_id).order_by(S.artifact_versions.c.created_at.desc())).mappings()
            return clean([dict(json.loads(row["document"]), id=row["id"]) for row in rows])

    def process_local(self, project_id, payload, *, build, **kw):
        from vsc.post.local_media_tools import LOCAL_TOOLS, RECIPE
        def work(conn, project):
            p = project["id"]
            artifact = self.store._one(conn, S.artifact_versions, p, checked_id(payload["draft_version_id"]))
            if artifact["artifact_type"] != DRAFT_TYPE:
                raise ResourceError("本机加工需要工具草稿")
            saved = json.loads(artifact["document"])
            value = saved["input"]
            if value["tool"] not in LOCAL_TOOLS|{'music_mix'} or not value["source_media_id"]:
                raise ResourceError("本机加工类型或源视频缺失")
            key = "local-tool-output:" + artifact["id"]
            previous = conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == p,
                S.artifact_versions.c.artifact_key == key)).mappings().first()
            if previous:
                return dict(json.loads(previous["document"]), id=previous["id"], already_processed=True)
            if value['tool']=='music_mix':
                from .workbench_generation import working_media
                media,gaps=working_media(self.store,conn,p,value['source_media_id'],'video_take')
            else:media, gaps = self.store._usable(conn, p, value["source_media_id"], "video_take")
            gaps = [gap for gap in gaps if gap != "technical_check_missing"]
            if gaps:
                raise ResourceError("源视频不可加工：" + ", ".join(gaps), "local_source_unusable")
            pin = next((row for row in saved["media"] if row["role"] == "source"), None)
            if not pin or media["sha256"] != pin["sha256"] or media.get("duration_ms") != pin["duration_ms"]:
                raise Conflict("固定源媒体已改变", "tool_source_changed")
            replacement=None
            if value['tool']=='segment_remake':
                replacement,gaps=self.store._usable(conn,p,checked_id(value.get('replacement_media_id')),'video_take')
                if [gap for gap in gaps if gap!='technical_check_missing']:raise ResourceError('替换片当前不可用','local_replacement_unusable')
                pin=next((r for r in saved['media'] if r['role']=='replacement'),None)
                if not pin or pin['sha256']!=replacement['sha256'] or pin['duration_ms']!=replacement.get('duration_ms'):raise Conflict('固定替换片已变化')
            if value['tool']=='music_mix':
                from .workbench_generation import working_media
                replacement,gaps=working_media(self.store,conn,p,checked_id(value.get('audio_media_id')),'music')
                if gaps:raise ResourceError('配乐音频当前不可用','music_audio_unusable')
                pin=next((r for r in saved['media'] if r['role']=='audio'),None)
                if not pin or pin['sha256']!=replacement['sha256'] or pin['duration_ms']!=replacement.get('duration_ms'):raise Conflict('固定配乐音频已变化')
            built, receipt = build(value, media, replacement)
            outputs = []
            for item in built:
                record = self.store._register_media(conn, project, dict(item["media"], rights="unknown", source={
                    "kind": "local-media-tool", "content": {"draft_version_id": artifact["id"], "draft_sha256": artifact["sha256"],
                    "source_media_id": media["id"], "source_sha256": media["sha256"], "receipt": receipt}}), kw["actor"])
                outputs.append({**record, "media_id": record["id"], "role": item["role"], "modality": item["media"]["modality"], "name": item["media"]["name"]})
            operation = self.store.create_media_operation(p, dict(operation_type=value["tool"], recipe_version=RECIPE,
                tool="ffmpeg", tool_version=receipt["ffmpeg_version"], parameters={"draft_version_id": artifact["id"], "draft_sha256": artifact["sha256"],
                    "params": value["params"], "ranges": value["ranges"]}, execution=receipt,
                inputs=[{"media_id": media["id"], "role": "source"}]+([{'media_id':replacement['id'],'role':'music' if value['tool']=='music_mix' else 'replacement','start_ms':value['audio_in_ms'] if value['tool']=='music_mix' else value['params'].get('replacement_in_ms',0)}] if replacement else []), outputs=outputs), _transaction=(conn, project), **kw)
            result = dict(tool=value["tool"], episode_id=value["episode_id"], draft_version_id=artifact["id"], source_media_id=media["id"],
                source_sha256=media["sha256"], operation_id=operation["id"], outputs=outputs, receipt=receipt)
            output = self.store._create_artifact(conn, project, dict(artifact_key=key, artifact_type="local-tool-output", stage="production",
                document=result, dependency_ids=[artifact["id"]], object_ids=[value["episode_id"]]))
            return dict(result, id=output["id"], already_processed=False)
        return self.store._mutate(project_id, "process_creative_tool_local", payload, callback=work, **kw)

    def use_output(self, project_id, payload, **kw):
        from copy import deepcopy
        from vsc.post.edit_workspace import FORMAT
        from .editor_workspace import EditorWorkspaceRepository
        def work(conn, project):
            p = project["id"]
            artifact = self.store._one(conn, S.artifact_versions, p, checked_id(payload.get("output_version_id")))
            if artifact["artifact_type"] not in {"local-tool-output","creative-tool-output"}:
                raise ResourceError("需要本机加工的固定输出")
            output = json.loads(artifact["document"])
            if payload.get("media_id") not in {row["id"] for row in output["outputs"]}:
                raise ResourceError("所选媒体不属于加工输出")
            media = self.store._media(conn, p, payload["media_id"])
            target, episode = payload.get("target"), output["episode_id"]
            selected=next(row for row in output['outputs'] if row['id']==media['id'])
            if selected.get('role')=='depth_intermediate' and target!='canvas':raise ResourceError('深度中间视频仅供查看或来源图，不作为最终候选或剪辑','depth_intermediate_only')
            if target == "candidate":
                shot = checked_id(payload.get("shot_id"))
                if shot not in self.store._descendant_ids(conn, p, episode):
                    raise ResourceError("候选镜头不属于输出所在集")
                self.store._one(conn, S.shots, p, shot)
                role = "composition" if media["modality"] == "image" else "video_take" if media["modality"] == "video" else payload.get("audio_purpose")
                if media["modality"] == "audio" and role not in {"music", "ambience", "sfx"}:
                    raise ResourceError("音频候选须明确音乐、环境或音效用途")
                binding = dict(target_object_id=shot, role=role, media_id=media["id"], slot_key="local-tool:"+media["id"])
                if media["modality"] == "audio":
                    binding["track_key"] = binding["slot_key"]
                return self.store.propose_binding(p, binding, _transaction=(conn, project), **kw)
            if target == "canvas":
                canvas, version = self.store._canvas_version(conn, project, payload.get("canvas_id"))
                if canvas["episode_id"] != episode or version["version"] != payload.get("canvas_revision"):
                    raise Conflict("目标画布范围或版本已变化")
                document = self.store._canvas_document(conn, p, version)
                if output['tool']=='depth_motion':
                    original=self.store._one(conn,S.artifact_versions,p,output['draft_version_id'])
                    value=json.loads(original['document'])['input']
                    depth=next(row for row in output['outputs'] if row['role']=='depth_intermediate')
                    final=next(row for row in output['outputs'] if row['role']=='generated_video')
                    nodes=[('source',value['source_media_id'],'原始动作视频',None,0,0),('character',value['visual_media_ids'][0],'人物图',None,300,240),
                           ('depth',depth['id'],'灰度深度中间视频',depth['job_id'],300,0),('final',final['id'],'最终人物视频',final['job_id'],600,0)]
                    prefix='depth-'+artifact['id']+'-';existing={node['id'] for node in document['nodes']}
                    for key,identifier,title,job,x,y in nodes:
                        item=self.store._media(conn,p,identifier)
                        if prefix+key not in existing:document['nodes'].append(dict(id=prefix+key,type=item['modality'],title=title,x=x,y=y,media_id=identifier,job_id=job,group='深度动作 '+artifact['id'][:8],params={}))
                    edges={edge['id'] for edge in document['edges']}
                    for index,(source,target) in enumerate([('source','depth'),('depth','final'),('character','final')]):
                        identifier=prefix+'edge-'+str(index)
                        if identifier not in edges:document['edges'].append(dict(id=identifier,source=prefix+source,target=prefix+target,port='derived_from'))
                    return self.store.save_creative_canvas(p,dict(canvas_id=canvas['id'],canvas_revision=version['version'],title=version['title'],document=document),_transaction=(conn,project),**kw)
                source = next(row for row in output["outputs"] if row["id"] == media["id"])
                document["nodes"].append(dict(id="local-"+new_id(), type=media["modality"], title=media["name"],
                    x=40, y=40+40*len(document["nodes"]), media_id=media["id"], job_id=source.get("job_id"),
                    params={"operation_id": output["operation_id"]} if output.get("operation_id") else {}))
                return self.store.save_creative_canvas(p, dict(canvas_id=canvas["id"], canvas_revision=version["version"],
                    title=version["title"], document=document), _transaction=(conn, project), **kw)
            if target == "editing":
                current = conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id == p,
                    S.edit_workspaces.c.episode_id == episode)).mappings().first()
                if payload.get("edit_revision") != (current["revision"] if current else 0):
                    raise Conflict("剪辑稿已改变，请重新读取")
                document = deepcopy(self.store._one(conn, S.edit_revisions, p, current["current_version_id"])["document"]) if current else {
                    "format": FORMAT, "width": 720, "height": 1280, "fps": 24, "clips": [], "audio": [], "captions": []}
                fps = document["fps"]
                clip = dict(id="local-"+media["id"], media_id=media["id"], in_frame=0,
                    out_frame=max(1, round((media.get("duration_ms") or 2000)*fps/1000)), volume=1, muted=False)
                if media["modality"] == "audio":
                    if payload.get('audio_purpose','music') not in {'music','ambience','sfx','dialogue_dry'}:raise ResourceError('请明确音轨用途')
                    clip.update(at_frame=0, purpose=payload.get("audio_purpose", "music"))
                    document["audio"].append(clip)
                else:
                    document["clips"].append(clip)
                return EditorWorkspaceRepository(self.store).save(p, dict(episode_id=episode,
                    edit_revision=payload["edit_revision"], document=document), _transaction=(conn, project), **kw)
            raise ResourceError("选择候选、画布或剪辑目标")
        return self.store._mutate(project_id, "use_creative_tool_output", payload, callback=work, **kw)

    def list(self, project_id, episode_id):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            self.store._one(conn, S.episodes, project["id"], checked_id(episode_id))
            rows = conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == project["id"],
                S.artifact_versions.c.artifact_type == DRAFT_TYPE,
                S.artifact_versions.c.artifact_key.like("creative-tool:" + episode_id + ":%"))
                .order_by(S.artifact_versions.c.version)).mappings()
            latest = {}
            for row in rows:
                if row["artifact_key"] != "creative-tool:"+episode_id+":"+json.loads(row["document"])["input"]["tool"]:continue
                latest[row["artifact_key"]] = dict(id=row["id"], version=row["version"], sha256=row["sha256"],
                    document=json.loads(row["document"]), created_at=row["created_at"])
            return clean(dict(items=list(latest.values()), revision=project["revision"]))

    def save(self, project_id, payload, *, build, **kw):
        def work(conn, project):
            document = build(project_id, payload["document"])
            value = document["input"]
            key = "creative-tool:" + value["episode_id"] + ":" + value["tool"]
            current = conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id == project["id"],
                S.artifact_versions.c.artifact_key == key).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            if (str(current) if current else None) != payload["base_draft_id"]:
                raise Conflict("此工具已有新草稿；请保留输入并读取比较", "tool_draft_conflict")
            dependencies=[]
            if payload.get('origin_draft_id'):
                origin=self.store._one(conn,S.artifact_versions,project['id'],checked_id(payload['origin_draft_id']))
                original=json.loads(origin['document'])['input']
                if origin['artifact_type']!=DRAFT_TYPE or original['tool']!=value['tool'] or original['source_media_id']!=value['source_media_id'] or original['episode_id']!=value['episode_id']:raise ResourceError('工具来源与画布固定输入不符','tool_origin_mismatch')
                dependencies=[origin['id']]
            return self.store._create_artifact(conn, project, dict(artifact_type=DRAFT_TYPE, artifact_key=key,
                stage="production", document=document, object_ids=[value["episode_id"]], supersedes_id=current,dependency_ids=dependencies))
        return self.store._mutate(project_id, "save_creative_tool_draft", payload, callback=work, **kw)

    def working_input(self,p,draft_id):
        with self.store.engine.connect() as conn:
            self.store._one(conn,S.artifact_versions,p,checked_id(draft_id))
            row=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key=='tool-work:'+draft_id)).mappings().first()
            if not row:raise ResourceError('先固定此工具的生成输入','tool_work_input_required')
            return clean(dict(row))

    def prepare_work(self,p,payload,**kw):
        import uuid
        from vsc.assets.classic_production import normalize_draft
        from vsc.production.creative_tools import TOOLS
        def work(conn,project):
            artifact=self.store._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']))
            if artifact['artifact_type']!=DRAFT_TYPE:raise ResourceError('需要固定工具草稿')
            value=json.loads(artifact['document'])['input'];tool=value['tool']
            if tool not in {'music_description','music_lyrics','instrumental','ambience','sfx','speech','music_mix','depth_motion'}:raise ResourceError('此工具没有工作生成适配器','tool_adapter_unavailable')
            if tool=='music_lyrics' and any(value.get(field) for field in ('source_media_id','audio_media_id','visual_media_ids','script_line_ids','voice_media_id','speaker','replacement_media_id')):
                raise ResourceError('歌词演唱只接受固定歌词与风格，不会静默忽略参考媒体或音色','song_inputs_unsupported')
            if tool=='music_mix':
                if not value['source_media_id']:raise ResourceError('先选择配乐的源视频，再生成完整音乐','music_source_required')
                source=self.store._media(conn,p,checked_id(value['source_media_id']))
                if source['modality']!='video' or not source.get('duration_ms') or not 0<=value['music_start_ms']<value['music_end_ms']<=source['duration_ms']:
                    raise ResourceError('配乐使用区间须位于已核验的源视频内','music_range_invalid')
            key='tool-work:'+artifact['id'];prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:return dict(draft_version_id=prior['id'],tool_draft_id=artifact['id'])
            shot=value['shot_id']
            if not shot:
                parent=value['episode_id'];self.store._one(conn,S.episodes,p,parent)
                for kind in ('scene','sequence','shot'):
                    identity=str(uuid.uuid5(uuid.UUID(p),'tool-work:'+value['episode_id']+':'+tool+':'+kind))
                    if not conn.execute(select(S.creative_objects.c.id).where(S.creative_objects.c.project_id==p,S.creative_objects.c.id==identity)).first():
                        table={'scene':S.scenes,'sequence':S.sequences,'shot':S.shots}[kind];ordinal=conn.scalar(select(func.coalesce(func.max(table.c.ordinal),-1)+1).where(table.c.project_id==p,table.c.parent_id==parent))
                        self.store._create_object(conn,project,dict(id=identity,kind=kind,parent_id=parent,ordinal=ordinal,display_code='TOOL-'+kind.upper()+'-'+identity[:8],title='独立声音工作范围' if kind!='shot' else '声音工作请求'))
                    parent=identity
                shot=parent
            prompt=value['prompt'].strip()
            if tool=='depth_motion':
                if not value['source_media_id'] or len(value['visual_media_ids'])!=1 or not value['depth_model_id'] or not prompt or value['audio_media_id'] or value['script_line_ids'] or value['voice_media_id']:
                    raise ResourceError('深度动作须固定源视频、唯一人物图、两个模型及最终画面要求','depth_motion_inputs')
                refs=[]
                for role,identifier,modality in [('operation_source',value['source_media_id'],'video'),('character',value['visual_media_ids'][0],'image')]:
                    media=self.store._media(conn,p,checked_id(identifier))
                    if media['modality']!=modality:raise ResourceError('深度动作源媒体类型不匹配','depth_motion_inputs')
                    refs.append(dict(role=role,media_id=media['id'],sha256=media['sha256']))
                document=normalize_draft(dict(shot_id=shot,mode='depth_motion',purpose='reference_to_video',model_id=value['model_id'],prompt=prompt,
                    duration_ms=value['duration_ms'],references=refs,tool_settings=dict(value['params'],depth_model_id=value['depth_model_id'])))
                created=self.store._create_artifact(conn,project,dict(artifact_key=key,artifact_type='classic-production-draft',stage='workspace',document=document,dependency_ids=[artifact['id']],object_ids=[shot]))
                self.store._project_classic_draft_media(conn,project,created,document)
                return dict(draft_version_id=created['id'],tool_draft_id=artifact['id'],shot_id=shot)
            if tool!='speech':prompt='\n'.join(v for v in [prompt,value['style'].strip(),'仅使用乐器与非人声音色，不含歌词和演唱人声。' if tool in {'instrumental','music_mix'} else ''] if v)
            if not prompt:raise ResourceError('请输入实际生成内容')
            document=normalize_draft(dict(shot_id=shot,mode='audio_speech' if tool=='speech' else 'audio_song' if tool=='music_lyrics' else 'audio',purpose='music' if tool=='music_mix' else TOOLS[tool][2],model_id=value['model_id'],prompt=prompt,duration_ms=max(1,value['duration_ms']),params=value['params'],references=[],**({'tool_settings':{'speaker':value['speaker']}} if tool=='speech' else {'lyrics':value['lyrics']} if tool=='music_lyrics' else {})))
            created=self.store._create_artifact(conn,project,dict(artifact_key=key,artifact_type='classic-production-draft',stage='workspace',document=document,dependency_ids=[artifact['id']],object_ids=[shot]))
            self.store._project_classic_draft_media(conn,project,created,document)
            return dict(draft_version_id=created['id'],tool_draft_id=artifact['id'],shot_id=shot)
        return self.store._mutate(p,'prepare_creative_tool_work',payload,callback=work,**kw)

    def generate_work(self,p,payload,*,preview,work_preview,**kw):
        def work(conn,project):
            fixed=preview(p,payload['request'])
            if not fixed.get('ready') or fixed['preview_sha256']!=payload['preview_sha256']:raise Conflict('生成报价已变化，请核对当前固定输入','tool_quote_changed')
            depth=fixed.get('artifact',{}).get('document',{}).get('working_dependency_contract')=='depth-motion/v1'
            result=self.store.generate_workbench(p,dict(request=payload['request'] if depth else fixed['work_request'],preview_sha256=fixed['preview_sha256']),build_preview=preview if depth else work_preview,_transaction=(conn,project),**{k:v for k,v in kw.items() if k!='_transaction'})
            return dict(result,tool_draft_id=payload['request']['draft_version_id'])
        return self.store._mutate(p,'generate_creative_tool_work',payload,callback=work,**kw)

    def work_runs(self,p,episode):
        with self.store.engine.connect() as conn:
            result=[]
            drafts=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_type==DRAFT_TYPE,S.artifact_versions.c.artifact_key.like('creative-tool:'+episode+':%')).order_by(S.artifact_versions.c.created_at.desc())).mappings()
            for draft in drafts:
                work=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key=='tool-work:'+draft['id'])).scalar()
                if not work:continue
                runs=conn.execute(select(S.workbench_run_inputs.c.run_version_id).where(S.workbench_run_inputs.c.project_id==p,S.workbench_run_inputs.c.draft_version_id==work)).scalars()
                for run in runs:
                    jobs=[dict(j) for j in conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==p,S.generation_jobs.c.run_version_id==run)).mappings()]
                    for job in jobs:
                        job['outputs']=[dict(o) for o in conn.execute(select(S.job_outputs).where(S.job_outputs.c.project_id==p,S.job_outputs.c.job_id==job['id'])).mappings()]
                    result.append(dict(tool_draft_id=draft['id'],run_version_id=run,tool=json.loads(draft['document'])['input']['tool'],jobs=jobs))
            return clean(result)

    def resolve_generated_music(self,p,payload,**kw):
        def work(conn,project):
            artifact=self.store._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']))
            if artifact['artifact_type']!=DRAFT_TYPE:raise ResourceError('需要固定配乐输入')
            saved=json.loads(artifact['document']);value=saved['input']
            if value['tool']!='music_mix':raise ResourceError('仅配乐操作可接续混合')
            run=self.store._one(conn,S.artifact_versions,p,checked_id(payload['run_version_id']))
            working=conn.execute(select(S.workbench_run_inputs.c.draft_version_id).where(S.workbench_run_inputs.c.project_id==p,S.workbench_run_inputs.c.run_version_id==run['id'])).scalar()
            if not working:raise ResourceError('配乐须使用原工作生成运行')
            fixed=self.store._one(conn,S.artifact_versions,p,working)
            if fixed['artifact_key']!='tool-work:'+artifact['id']:raise ResourceError('生成运行不属于这份配乐输入','music_run_scope')
            media_id=checked_id(payload['audio_media_id'])
            found=conn.execute(select(S.job_outputs.c.media_id).join(S.generation_jobs,(S.generation_jobs.c.project_id==p)&(S.generation_jobs.c.id==S.job_outputs.c.job_id)).where(S.job_outputs.c.project_id==p,S.job_outputs.c.media_id==media_id,S.generation_jobs.c.run_version_id==run['id'],S.generation_jobs.c.status=='succeeded')).first()
            if not found:raise ResourceError('完整配乐尚未在原任务成功登记','music_output_pending')
            media=self.store._media(conn,p,media_id)
            if media['modality']!='audio':raise ResourceError('需要完整音频结果')
            key='creative-tool:'+value['episode_id']+':music-resolved:'+artifact['id']+':'+media_id
            prior=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).scalar()
            if prior:return {'draft_version_id':prior}
            value['audio_media_id']=media_id;saved['media']=[r for r in saved['media'] if r['role']!='audio']+[dict(role='audio',media_id=media_id,sha256=media['sha256'],duration_ms=media['duration_ms'])]
            result=self.store._create_artifact(conn,project,dict(artifact_key=key,artifact_type=DRAFT_TYPE,stage='workspace',document=saved,dependency_ids=[artifact['id'],run['id']],object_ids=[value['episode_id']]))
            return {'draft_version_id':result['id']}
        return self.store._mutate(p,'resolve_creative_music_output',payload,callback=work,**kw)

    def publish_work_outputs(self,p,payload,**kw):
        def work(conn,project):
            run=self.store._one(conn,S.artifact_versions,p,checked_id(payload['run_version_id']))
            fixed_id=conn.execute(select(S.workbench_run_inputs.c.draft_version_id).where(S.workbench_run_inputs.c.project_id==p,S.workbench_run_inputs.c.run_version_id==run['id'])).scalar()
            if not fixed_id:raise ResourceError('需要原工具工作运行')
            fixed=self.store._one(conn,S.artifact_versions,p,fixed_id)
            if not fixed['artifact_key'].startswith('tool-work:'):raise ResourceError('运行不属于声音工具')
            source=self.store._one(conn,S.artifact_versions,p,fixed['artifact_key'][len('tool-work:'):]);value=json.loads(source['document'])['input'];key='tool-generated-output:'+run['id']
            prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:return dict(json.loads(prior['document']),id=prior['id'])
            jobs=conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==p,S.generation_jobs.c.run_version_id==run['id'])).mappings().all()
            if not jobs or len(jobs)!=len(json.loads(run['document'])['series_batch']['jobs']) or any(j['status']!='succeeded' for j in jobs):raise ResourceError('原任务尚未全部完成','tool_output_pending')
            outputs=[]
            for job in jobs:
                for identifier in conn.execute(select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id==p,S.job_outputs.c.job_id==job['id'])).scalars():
                    media=self.store._media(conn,p,identifier);outputs.append({k:media[k] for k in ('id','name','modality','sha256')}|{'media_id':identifier,'role':'depth_intermediate' if job['purpose']=='depth' else 'generated_'+job['modality'],'job_id':job['id']})
            result=dict(tool=value['tool'],episode_id=value['episode_id'],draft_version_id=source['id'],run_version_id=run['id'],outputs=outputs,receipt={'source':'original-generation-jobs','job_ids':[j['id'] for j in jobs]})
            artifact=self.store._create_artifact(conn,project,dict(artifact_type='creative-tool-output',artifact_key=key,stage='workspace',document=result,dependency_ids=[source['id'],run['id']],object_ids=[value['episode_id']]))
            return dict(result,id=artifact['id'])
        return self.store._mutate(p,'publish_creative_tool_outputs',payload,callback=work,**kw)

    def import_mv(self, project_id, payload, *, service, **kw):
        def work(conn, project):
            artifact, saved = service._fixed_creative_tool(project_id, payload["draft_version_id"])
            value = saved["input"]
            if value["tool"] != "mv" or not value["audio_media_id"]:
                raise ResourceError("需要保存的 MV 与完整音乐输入", "mv_audio_required")
            key = "mv-import:" + artifact["id"]
            prior = conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == project["id"],
                S.artifact_versions.c.artifact_key == key)).mappings().first()
            if prior:
                result = json.loads(prior["document"])
                return dict(id=prior["id"], shot_ids=result["shot_ids"], scene_id=result["scene_id"], already_imported=True)
            try:
                plan = compile_mv(value, self.store._media(conn, project["id"], value["audio_media_id"]))
            except ValueError as error:
                raise ResourceError(str(error), "invalid_mv_plan") from error
            # Every source is read in this same project-locked transaction.
            for pin in saved["media"]:
                media = self.store._media(conn, project["id"], pin["media_id"])
                if media["sha256"] != pin["sha256"] or media.get("duration_ms") != pin["duration_ms"]:
                    raise Conflict("MV 固定素材已改变", "tool_source_changed")
            ordinal = conn.execute(select(func.coalesce(func.max(S.scenes.c.ordinal), -1)).where(
                S.scenes.c.project_id == project["id"], S.scenes.c.parent_id == value["episode_id"])).scalar_one() + 1
            suffix = new_id().replace("-", "")[:12]
            scene = self.store._create_object(conn, project, dict(kind="scene", display_code="MV-SC-" + suffix,
                title=value["title"] or "MV 镜头计划", ordinal=ordinal, parent_id=value["episode_id"]))
            sequence = self.store._create_object(conn, project, dict(kind="sequence", display_code="MV-SQ-" + suffix,
                title="音乐段落", ordinal=0, parent_id=scene["id"]))
            shots = []
            for index, shot in enumerate(plan["shots"]):
                created = self.store._create_object(conn, project, dict(kind="shot", display_code="MV-" + suffix + "-%03d" % (index + 1),
                    title=shot["title"], ordinal=index, parent_id=sequence["id"], duration_ms=shot["duration_ms"]))
                shot["shot_id"] = created["id"]
                shots.append(created["id"])
            result = dict(plan=plan, source_draft_id=artifact["id"], source_draft_sha256=artifact["sha256"],
                          scene_id=scene["id"], shot_ids=shots)
            registered = self.store._create_artifact(conn, project, dict(artifact_type="shot-plan", artifact_key=key,
                stage="production", document=result, object_ids=shots))
            return dict(id=registered["id"], scene_id=scene["id"], shot_ids=shots, already_imported=False, approved=False)
        return self.store._mutate(project_id, "import_creative_mv", payload, callback=work, **kw)

    def mv_workspace(self,p,draft_id):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);artifact=self.store._one(conn,S.artifact_versions,p,checked_id(draft_id))
            imported=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key=='mv-import:'+artifact['id'])).mappings().first()
            if not imported:raise ResourceError('先导入固定MV镜头计划','mv_plan_missing')
            value=json.loads(artifact['document'])['input'];plan=json.loads(imported['document'])['plan'];shots=[]
            for shot in plan['shots']:
                jobs=[dict(j) for j in conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==p,S.generation_jobs.c.shot_id==shot['shot_id']).order_by(S.generation_jobs.c.created_at.desc())).mappings()]
                ids=set(value['visual_media_ids'])
                for job in jobs:
                    if job['status']=='succeeded':ids.update(conn.execute(select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id==p,S.job_outputs.c.job_id==job['id'])).scalars())
                shots.append(dict(shot,candidates=[self.store._media(conn,p,i) for i in sorted(ids)],jobs=jobs))
            return clean(dict(draft_version_id=artifact['id'],plan_id=imported['id'],shots=shots,revision=project['revision']))

    def prepare_mv_shot(self,p,payload,**kw):
        from vsc.assets.classic_production import normalize_draft
        def work(conn,project):
            artifact=self.store._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']));saved=json.loads(artifact['document']);value=saved['input']
            imported=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key=='mv-import:'+artifact['id'])).mappings().first()
            if value['tool']!='mv' or not imported:raise ResourceError('先导入固定MV镜头计划')
            shot=next((r for r in json.loads(imported['document'])['plan']['shots'] if r['shot_id']==payload['shot_id']),None)
            if not shot:raise ResourceError('镜头不属于此MV计划')
            model=conn.execute(select(S.provider_models).where(S.provider_models.c.id==checked_id(payload['model_id']))).mappings().one_or_none()
            if not model or model['modality'] not in {'image','video'} or not model['enabled']:raise ResourceError('请选择实际图像或视频模型')
            refs=[];reference=payload.get('reference_media_id')
            if reference:
                if reference not in value['visual_media_ids']:raise ResourceError('参考须属于本稿固定输入')
                media=self.store._media(conn,p,checked_id(reference))
                if media['modality']!='image':raise ResourceError('首帧参考需要图片')
                refs=[dict(role='reference_image' if model['modality']=='image' else 'first_frame',media_id=reference,sha256=media['sha256'])]
            mode='image' if model['modality']=='image' else 'single' if refs else 'text';preferred='first_frame' if mode=='image' else 'image_to_video' if refs else 'text_to_video';purposes=model['capabilities'].get('purposes',[])
            purpose=preferred if preferred in purposes else 'video_clip' if 'video_clip' in purposes else preferred
            doc=normalize_draft(dict(mode=mode,shot_id=shot['shot_id'],model_id=model['id'],purpose=purpose,prompt='\n'.join(x for x in [shot['prompt'],value['style']] if x),duration_ms=shot['duration_ms'],references=refs))
            result=self.store._create_artifact(conn,project,dict(artifact_type='classic-production-draft',artifact_key='mv-work:'+imported['id']+':'+shot['shot_id'],stage='workspace',document=doc,dependency_ids=[artifact['id'],imported['id']],object_ids=[shot['shot_id']]))
            self.store._project_classic_draft_media(conn,project,result,doc)
            return dict(draft_version_id=result['id'],shot_id=shot['shot_id'])
        return self.store._mutate(p,'prepare_creative_mv_shot',payload,callback=work,**kw)

    def propose(self, project_id, payload, *, preview, **kw):
        def work(conn, project):
            value = preview(project_id, payload["request"])
            if not value["ready"]:
                raise ResourceError("工具尚有输入或能力缺口", "tool_not_ready")
            if value["preview_sha256"] != payload["preview_sha256"]:
                raise Conflict("输入或报价已改变，请重新预览", "tool_preview_changed")
            return self.store._create_artifact(conn, project, value["artifact"])
        return self.store._mutate(project_id, "propose_creative_tool_run", payload, callback=work, **kw)
