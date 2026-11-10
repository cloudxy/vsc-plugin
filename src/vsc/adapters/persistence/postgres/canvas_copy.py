"""One fixed-document clone engine for templates and direct canvas copies.

The caller owns the locked mutation, source identity and immutable lineage rows.
No provider, approval, execution or template publication is created here.
"""
from copy import deepcopy
import hashlib
import json
from sqlalchemy import select, insert, func
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.production.creative_tools import normalize_draft, DRAFT_TYPE, FORMAT, TOOLS
from . import schema as S
from .values import checked_id, new_id, digest, clean


def domain_kind(node):
    return 'spatial' if node['type'] in {'spatial','director'} else 'edit' if node['type']=='edit' else 'tool'


def tool_input_media(body):
    value = normalize_draft(body['input'])
    return {value[field] for field in ('source_media_id','audio_media_id','voice_media_id','replacement_media_id') if value.get(field)} | set(value.get('visual_media_ids', []))


class FixedCanvasClone:
    def __init__(self, store): self.store = store
    def __getattr__(self, name): return getattr(self.store, name)

    def plan_fixed(self, c, target, canvas, version, episode_id, *, direct=False):
        from .project_management import management_canvas_guard, management_object_guard, management_project_guard
        source = canvas['project_id']
        if version['canvas_id'] != canvas['id']:
            raise ResourceError('固定版本不属于源画布', 'canvas_copy_source_mismatch')
        self._access_require(c, source, 'read')
        self._access_require(c, source, 'read', 'canvas_version', version['id'])
        self._access_require(c, target, 'edit')
        management_canvas_guard(c, source, canvas['id'])
        management_project_guard(c, target)
        doc = self._canvas_document(c, source, version)
        if digest({'title':version['title'], 'document':doc}) != version['sha256']:
            raise Conflict('固定画布摘要不符', 'canvas_integrity_mismatch')
        media, domains, episodes, media_pins = set(), {}, set(), {}
        if canvas['episode_id']: episodes.add(canvas['episode_id'])
        for node in doc['nodes']:
            if node['media_id']: media.add(node['media_id'])
            if direct and node['job_id']:
                job = self._one(c, S.generation_jobs, source, node['job_id'])
                if not node['media_id'] and job['status'] not in {'succeeded','failed','cancelled'}:
                    raise ResourceError('源节点任务尚未结束，请完成或停止任务并保存结果', 'canvas_copy_job_pending')
                if not node['media_id'] and (job['status']=='succeeded' or c.scalar(select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id==source, S.job_outputs.c.job_id==job['id']).limit(1))):
                    raise ResourceError('请先将所选结果放回节点并保存，再复制画布', 'canvas_copy_output_selection_required')
            if not node.get('domain_version_id'): continue
            kind = domain_kind(node); key = (kind, node['domain_version_id'])
            if kind == 'spatial':
                fixed = self._one(c, S.spatial_scene_versions, source, key[1])
                obj = self._one(c, S.spatial_scenes, source, fixed['spatial_scene_id'])
                if obj['id'] != node['domain_object_id'] or obj['mode'] != ('blocking' if node['type']=='director' else 'previs'):
                    raise ResourceError('场景版本与节点类型不符', 'canvas_domain_scope')
                body = self._spatial_document(c, source, fixed); ep = obj['episode_id']
                media.update(x['media_id'] for x in body['objects'] if x['media_id'])
                if obj['scene_id']: management_object_guard(c, source, obj['scene_id'])
            elif kind == 'edit':
                fixed = self._one(c, S.edit_revisions, source, key[1]); obj = self._one(c, S.edit_workspaces, source, fixed['workspace_id'])
                if obj['id'] != node['domain_object_id']: raise ResourceError('剪辑版本不属于此工作区', 'canvas_domain_scope')
                body = deepcopy(fixed['document']); ep = obj['episode_id']
                if digest(body) != fixed['sha256']:
                    raise Conflict('固定剪辑版本摘要不符', 'canvas_copy_domain_integrity')
                media.update(x['media_id'] for track in ('clips','audio') for x in body[track])
            else:
                fixed = self._one(c, S.artifact_versions, source, key[1]); obj = fixed
                if fixed['artifact_type'] != DRAFT_TYPE or node['domain_object_id'] != fixed['id']:
                    raise ResourceError('加工节点未固定原工具草稿', 'canvas_domain_scope')
                if hashlib.sha256(bytes(fixed['document'])).hexdigest() != fixed['sha256']:
                    raise Conflict('固定工具草稿摘要不符', 'canvas_copy_domain_integrity')
                body = json.loads(bytes(fixed['document'])); ep = body['input']['episode_id']
                media.update(x['media_id'] for x in body['media'])
                # Pins and actual input slots both belong to the fixed graph.
                # A manually registered draft must not add unverified media
                # later, after the locked plan's rights/byte verification.
                media.update(tool_input_media(body))
                for pin in body['media']:
                    media_pins.setdefault(pin['media_id'], set()).add(pin['sha256'])
            if ep:
                self._one(c, S.episodes, source, ep); management_object_guard(c, source, ep); episodes.add(ep)
            if canvas['episode_id'] and ep != canvas['episode_id']:
                raise ResourceError('工具对象不属于源画布分集', 'canvas_domain_scope')
            domains[key] = dict(kind=kind, fixed=fixed, obj=obj, document=body, episode_id=ep)
        if episode_id:
            self._one(c, S.episodes, target, episode_id); management_object_guard(c, target, episode_id)
            if len(episodes)>1:
                raise ResourceError('源画布包含多个分集的工具，请拆分画布后复制' if direct else '此模板包含多集工具，请选择自动新建对应分集', 'canvas_copy_multiple_episodes')
            edits = sum(d['kind']=='edit' for d in domains.values())
            if edits>1: raise ResourceError('源画布包含多个固定剪辑版本，请拆分画布后复制', 'canvas_copy_multiple_edits')
            if edits and c.scalar(select(S.edit_workspaces.c.id).where(S.edit_workspaces.c.project_id==target, S.edit_workspaces.c.episode_id==episode_id)):
                raise Conflict('目标分集已有剪辑稿，请选择其他分集，避免覆盖原稿', 'canvas_copy_edit_exists')
        elif episodes:
            work_id = c.scalar(select(S.works.c.id).where(S.works.c.project_id==target).order_by(S.works.c.ordinal).limit(1))
            if work_id: management_object_guard(c, target, work_id)
        if direct and source==target and canvas['episode_id']==episode_id:
            raise ResourceError('同集副本请使用原复制入口', 'canvas_copy_same_episode')
        items = []
        from .copy_lineage import assert_copy_source
        for mid in sorted(media):
            item = self._media(c, source, mid); assert_copy_source(self.store, c, source, mid)
            if any(sha != item['sha256'] for sha in media_pins.get(mid, ())):
                raise Conflict('工具草稿媒体摘要与固定字节不符', 'canvas_copy_media_pin_mismatch')
            items.append(dict(id=mid, name=item.get('name') or item['modality'], modality=item['modality'], sha256=item['sha256']))
        return dict(source=source, version=version, canvas=canvas, document=doc, media=items, domains=domains, episodes=episodes)

    def clone_plan(self, c, project, plan, episode_id, title, actor, *, source_kind, source_ref):
        p, source = project['id'], plan['source']
        media_map, episode_map, domain_map = {}, {}, {}
        planned_media = {item['id'] for item in plan['media']}
        canvas_id = new_id()
        def new_object(kind,parent,title):
            table=S.episodes if kind=='episode' else S.scenes
            ordinal=c.scalar(select(func.coalesce(func.max(table.c.ordinal),-1)).where(table.c.project_id==p,table.c.parent_id==parent))+1
            return self._create_object(c,project,dict(kind=kind,parent_id=parent,ordinal=ordinal,display_code=('EP-' if kind=='episode' else 'SC-')+new_id()[:8],title=title))['id']
        work_id=c.scalar(select(S.works.c.id).where(S.works.c.project_id==p).order_by(S.works.c.ordinal).limit(1))
        if plan['episodes'] and not episode_id and not work_id:
            work_id=self._create_object(c,project,dict(kind='work',display_code='WK-'+new_id()[:8],title=title,ordinal=0))['id']
        for old in sorted(plan['episodes']):
            name=self._one(c,S.creative_objects,source,old)['title'];episode_map[old]=episode_id or new_object('episode',work_id,(name or '模板分集')+' · 副本')
        def copied_media(mid):
            if not mid:return None
            if mid not in planned_media:
                raise Conflict('媒体依赖未进入固定复制计划', 'canvas_copy_unplanned_media')
            if mid not in media_map:
                item=self._media(c,source,mid);rights=self._latest(c,S.rights_decisions,source,'media_id',mid);location=next((x for x in item['locations'] if x['available']),None)
                if not location:raise ResourceError('模板素材没有可用副本')
                row=self._register_media(c,project,dict(item,id=new_id(),storage=location['storage'],object_key=location['object_key'],rights=rights['outcome'] if rights else 'unknown',rights_scope=rights['scope'] if rights else {'purposes':[]},rights_expires_at=rights['expires_at'] if rights else None,source={'kind':source_kind,'content':dict(source_ref,source_project_id=source,source_media_id=mid,sha256=item['sha256'])}),actor);media_map[mid]=dict(id=row['id'],blob_id=item['blob_id'],sha256=item['sha256'])
            return media_map[mid]['id']
        for item in plan['media']:copied_media(item['id'])
        internal=dict(actor=actor,expected_revision=project['revision'],idempotency_key='template-copy-internal',_transaction=(c,project))
        for key,d in plan['domains'].items():
            episode=episode_map.get(d['episode_id']) or episode_id;body=deepcopy(d['document']);kind=d['kind']
            if kind=='spatial':
                for item in body['objects']:item['media_id']=copied_media(item['media_id'])
                scene_id=new_object('scene',episode,d['fixed']['title']) if d['obj']['mode']=='blocking' else None
                saved=self.create_spatial_scene(p,dict(mode=d['obj']['mode'],episode_id=episode,scene_id=scene_id,title=d['fixed']['title'],description=d['fixed']['description'],document=body),**internal);domain_map[key]=(saved['id'],saved['version_id'])
            elif kind=='edit':
                from .editor_workspace import EditorWorkspaceRepository
                for track in ('clips','audio'):
                    for item in body[track]:
                        item['media_id']=copied_media(item['media_id']);item['id']=new_id()
                        for field in ('shot_id','working_selection_version_id','source_job_id','decision_id','annotation_id','cue_id','binding_decision_id'):item.pop(field,None)
                saved=EditorWorkspaceRepository(self.store).save(p,dict(episode_id=episode,edit_revision=0,document=body),**internal);domain_map[key]=(saved['id'],saved['edit_version_id'])
            else:
                value=body['input'];value['episode_id']=episode;value['shot_id']='';value['script_line_ids']=[]
                for field in ('source_media_id','audio_media_id','voice_media_id','replacement_media_id'):value[field]=copied_media(value.get(field)) or ''
                value['visual_media_ids']=[copied_media(x) for x in value.get('visual_media_ids',[])];value=normalize_draft(value)
                pins=[dict(pin,media_id=copied_media(pin['media_id'])) for pin in body['media']]
                saved=self._create_artifact(c,project,dict(artifact_key='canvas-tool:'+new_id(),artifact_type=DRAFT_TYPE,stage='production',document=dict(format=FORMAT,input=value,media=pins,blocked_reason=TOOLS[value['tool']][3],generated=False),object_ids=[episode]));domain_map[key]=(saved['id'],saved['id'])
        doc=deepcopy(plan['document']);nodes={n['id']:'node-'+new_id() for n in doc['nodes']}
        for n in doc['nodes']:
            n['id']=nodes[n['id']];n['job_id']=None;n['media_id']=copied_media(n['media_id'])
            if n.get('domain_version_id'):
                kind='spatial' if n['type'] in {'spatial','director'} else 'edit' if n['type']=='edit' else 'tool';n['domain_object_id'],n['domain_version_id']=domain_map[(kind,n['domain_version_id'])]
        for e in doc['edges']:e.update(id='edge-'+new_id(),source=nodes[e['source']],target=nodes[e['target']])
        canvas=dict(id=canvas_id,episode_id=episode_id or episode_map.get(plan['canvas']['episode_id']));c.execute(insert(S.creative_canvases).values(project_id=p,created_by=actor,**canvas))
        result=self._insert_canvas_version(c,project,canvas,dict(title=title,document=doc),actor)
        return dict(result=result, media_map=media_map, domain_map=domain_map, episode_map=episode_map)


class DirectCanvasCopiesRepository(FixedCanvasClone):
    def _plan(self, c, p, payload):
        source = payload['source_project_id']
        self._access_require(c, source, 'read')
        canvas = self._one(c, S.creative_canvases, source, payload['source_canvas_id'])
        version = self._one(c, S.creative_canvas_versions, source, payload['source_version_id'])
        if version['sha256'] != payload['source_sha256']:
            raise Conflict('请求摘要与固定源版本不符', 'canvas_copy_sha_mismatch')
        return self.plan_fixed(c, p, canvas, version, payload['episode_id'], direct=True)

    def preview(self, p, payload):
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            from .access_control import authority_lock
            authority_lock(c)
            plan = self._plan(c, p, payload)
            return clean(dict(revision=self._project(c,p)['revision'], source_project_id=plan['source'],
                source_canvas_id=plan['canvas']['id'], source_version_id=plan['version']['id'],
                source_sha256=plan['version']['sha256'], episode_id=payload['episode_id'],
                media_count=len(plan['media']), domain_count=len(plan['domains']), node_count=len(plan['document']['nodes']), provider_submitted=False))

    def copy(self, p, payload, actor, verify_media, **kw):
        source = payload['source_project_id']
        def work(c, project):
            plan = self._plan(c, p, payload)
            # Receipt lookup, authority/graph locks and target revision precede
            # all source validation and byte reads. No nested read session.
            for item in plan['media']:
                verify_media(source, item['id'], item['sha256'], self._media(c, source, item['id']))
            cloned = self.clone_plan(c, project, plan, payload['episode_id'], payload['title'], actor,
                source_kind='canvas-direct-copy', source_ref=dict(source_canvas_id=plan['canvas']['id'], source_version_id=plan['version']['id']))
            result = cloned['result']; copy_id = new_id()
            c.execute(insert(S.canvas_direct_copies).values(project_id=p, id=copy_id,
                canvas_id=result['id'], canvas_version_id=result['version_id'], source_project_id=source,
                source_canvas_id=plan['canvas']['id'], source_version_id=plan['version']['id'],
                command_key=kw['idempotency_key'], created_by=actor))
            for old, new in cloned['media_map'].items():
                c.execute(insert(S.canvas_direct_copy_media).values(project_id=p,id=new_id(),copy_id=copy_id,
                    source_project_id=source,source_media_id=old,target_media_id=new['id'],blob_id=new['blob_id'],sha256=new['sha256']))
            for (kind, old), (_, new) in cloned['domain_map'].items():
                c.execute(insert(S.canvas_direct_copy_domains).values(project_id=p,id=new_id(),copy_id=copy_id,
                    source_project_id=source,**{'source_'+kind+'_version_id':old,'target_'+kind+'_version_id':new}))
            return dict(result,copy_id=copy_id,source_project_id=source,source_canvas_id=plan['canvas']['id'],
                source_version_id=plan['version']['id'],episode_id=payload['episode_id'],
                media_count=len(cloned['media_map']),domain_count=len(cloned['domain_map']),provider_submitted=False)
        return self._mutate(p, 'copy_direct_canvas', payload, actor=actor, callback=work,
            _related_projects=(source,), **kw)
