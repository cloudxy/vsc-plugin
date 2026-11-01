"""Explicit use of approved takes; the original timeline freezer owns adoption."""
import json
from sqlalchemy import select, insert, and_
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.production.handoffs import _cues
from vsc.post.edit_workspace_handoff import timeline_document
from . import schema as S
from .editor_workspace import EditorWorkspaceRepository
from .values import checked_id, clean, digest, new_id


class EditorHandoffRepository:
    def __init__(self,store):self.store=store

    def _options(self,conn,project,version_id):
        p=project['id'];version=dict(self.store._one(conn,S.edit_revisions,p,checked_id(version_id)))
        workspace=self.store._one(conn,S.edit_workspaces,p,version['workspace_id'])
        episode=workspace['episode_id'];scope=self.store._descendant_ids(conn,p,episode)
        fixed=EditorWorkspaceRepository(self.store)._inputs(conn,p,version['id'],usable=True)
        selected,plans=[],[]
        query=select(S.artifact_versions).join(S.current_artifact_versions,and_(
            S.current_artifact_versions.c.project_id==p,S.current_artifact_versions.c.artifact_id==S.artifact_versions.c.id))
        query=query.where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_type.in_(
            ['vsc.selected_takes','selected-takes','vsc.sound_plan','sound-plan','vsc.sound_cue_sheet','sound-cue-sheet']))
        for row in conn.execute(query).mappings():
            ids=set(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                S.artifact_object_scopes.c.project_id==p,S.artifact_object_scopes.c.artifact_id==row['id'])).scalars())
            if not row['project_wide'] and not scope.intersection(ids):continue
            if not self.store._artifact_approved(conn,p,row['id']):continue
            document=json.loads(row['document'])
            value=dict(id=row['id'],title=row['artifact_key'],sha256=row['sha256'],document=document)
            if row['artifact_type'] in {'vsc.selected_takes','selected-takes'}:selected.append(value)
            else:value['cues']=_cues(document);plans.append(value)
        members=[]
        for row in fixed:
            candidates=conn.execute(select(S.binding_decisions.c.id,S.binding_slots.c.role,S.binding_slots.c.target_object_id)
                .select_from(S.binding_candidates.join(S.current_bindings,and_(S.current_bindings.c.project_id==p,
                    S.current_bindings.c.candidate_id==S.binding_candidates.c.id))
                .join(S.binding_decisions,and_(S.binding_decisions.c.project_id==p,S.binding_decisions.c.id==S.current_bindings.c.decision_id))
                .join(S.binding_slots,and_(S.binding_slots.c.project_id==p,S.binding_slots.c.id==S.binding_decisions.c.slot_id)))
                .where(S.binding_candidates.c.project_id==p,S.binding_candidates.c.media_id==row['media_id'])).mappings().all()
            members.append(dict(row,decisions=[dict(c) for c in candidates]))
        return dict(project_id=p,revision=project['revision'],episode_id=episode,version=version,
            selected_takes=selected,sound_plans=plans,members=members)

    def options(self,p,version):
        with self.store.engine.connect() as conn:
            result=self._options(conn,self.store._project(conn,p),version)
            handoffs=[]
            for row in conn.execute(select(S.edit_timeline_handoffs).where(S.edit_timeline_handoffs.c.project_id==result['project_id'],
                S.edit_timeline_handoffs.c.edit_version_id==version)).mappings():
                timeline=conn.execute(select(S.timeline_versions.c.id).where(S.timeline_versions.c.project_id==result['project_id'],
                    S.timeline_versions.c.artifact_id==row['artifact_id'])).scalar_one_or_none()
                handoffs.append(dict(artifact_id=row['artifact_id'],approved=self.store._artifact_approved(conn,result['project_id'],row['artifact_id']),timeline_id=timeline))
            return clean(dict(result,handoffs=handoffs))

    def _proposal(self,conn,project,payload):
        options=self._options(conn,project,payload['edit_version_id']);p=project['id']
        selected=next((row for row in options['selected_takes'] if row['id']==payload['selected_takes_id']),None)
        if selected is None:raise ResourceError('先选择当前集有效且已批准的选片清单','edit_selected_takes_required')
        assignments=payload.get('assignments');members={row['clip_key']:row for row in options['members']}
        if not isinstance(assignments,dict) or set(assignments)!=set(members):raise ResourceError('须为每个剪辑片段明确原选片与采用决定','edit_mapping_required')
        choices={row['id']:row for row in selected['document'].get('items',[])}
        shots=self.store._projection_id_map(conn,p)['shot'];fixed={}
        for key,ref in assignments.items():
            if not isinstance(ref,dict) or set(ref)-{'selected_item_id','binding_decision_id','sound_plan_id','cue_id','audio_role','reuse_reason'}:
                raise ResourceError('片段映射包含无效字段','edit_mapping_required')
            member=members[key];choice=choices.get(ref.get('selected_item_id'))
            decision=next((d for d in member['decisions'] if d['id']==ref.get('binding_decision_id')),None)
            if not choice or not decision or choice.get('media',{}).get('sha256')!=member['blob_sha256']:
                raise ResourceError('原选片、采用决定和固定剪辑媒体不一致','edit_selection_mismatch')
            shot=shots.get(choice.get('shot_id'))
            if member['track']=='clips' and (not shot or member.get('shot_id')!=shot):
                raise ResourceError('画面片段须明确其原镜头，且与选片归属一致','edit_selection_mismatch')
            self.store._validate_fixed_decision(conn,p,self.store._one(conn,S.binding_decisions,p,decision['id']),member['media_id'],shot)
            if member['track']=='audio' and (member['modality']!='audio' or choice.get('purpose') not in {'dialogue','narration','music','ambience','sfx'}):
                raise ResourceError('正式声音轨需要已登记并按声音用途采用的独立音频','edit_audio_selection_required')
            fixed[key]=dict(ref,modality=member['modality'])
        try:document=timeline_document(p,options['episode_id'],options['version'],selected,fixed,{row['id']:row for row in options['sound_plans']})
        except (ValueError,KeyError,TypeError) as error:raise ResourceError(str(error),'edit_handoff_invalid') from error
        dependencies=[selected['id']]+[row['id'] for row in document['sound_plans']]
        artifact=dict(artifact_key='edit-timeline-'+options['episode_id'],artifact_type='vsc.timeline',
            document=document,dependency_ids=dependencies,object_ids=[options['episode_id']])
        return dict(revision=project['revision'],artifact=artifact,preview_sha256=digest(artifact),needs_approval=True)

    def preview(self,p,payload):
        with self.store.engine.connect() as conn:return clean(self._proposal(conn,self.store._project(conn,p),payload))

    def propose(self,p,payload,**kw):
        def work(conn,project):
            result=self._proposal(conn,project,payload['request'])
            if result['preview_sha256']!=payload['preview_sha256']:raise Conflict('时间线输入已改变，请重新预览','edit_handoff_stale')
            artifact=self.store._create_artifact(conn,project,result['artifact'])
            conn.execute(insert(S.edit_timeline_handoffs).values(project_id=project['id'],id=new_id(),
                edit_version_id=payload['request']['edit_version_id'],artifact_id=artifact['id']))
            return dict(artifact_id=artifact['id'],sha256=artifact['sha256'],needs_approval=True)
        return self.store._mutate(p,'propose_edit_timeline',payload,callback=work,**kw)

    def frozen_payload(self,p,artifact_id):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);p=project['id']
            relation=conn.execute(select(S.edit_timeline_handoffs).where(S.edit_timeline_handoffs.c.project_id==p,
                S.edit_timeline_handoffs.c.artifact_id==checked_id(artifact_id))).mappings().first()
            if relation is None:raise ResourceError('没有此时间线与剪辑稿的固定关系','edit_handoff_missing')
            artifact=self.store._one(conn,S.artifact_versions,p,artifact_id);document=json.loads(artifact['document'])
            version=self.store._one(conn,S.edit_revisions,p,relation['edit_version_id'])
            workspace=self.store._one(conn,S.edit_workspaces,p,version['workspace_id'])
            return dict(artifact_id=artifact_id,episode_id=workspace['episode_id'],selected_media=document['edit_handoff']['selected_media'])
