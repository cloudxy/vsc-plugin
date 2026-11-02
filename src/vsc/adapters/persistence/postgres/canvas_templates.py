"""Transactional copies of fixed templates using original domain authorities."""
from copy import deepcopy
import json
from sqlalchemy import select,insert,func
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.production.creative_tools import normalize_draft,DRAFT_TYPE,FORMAT,TOOLS
from . import schema as S
from .values import checked_id,new_id,digest,clean

class CanvasTemplatesRepository:
    def __init__(self,store):self.store=store
    def __getattr__(self,name):return getattr(self.store,name)
    def _plan(self,c,target,payload):
        source=checked_id(payload['source_project_id']);self._access_require(c,source,'read');self._access_require(c,target,'edit')
        template=self._one(c,S.canvas_templates,source,payload['template_id']);version=self._one(c,S.creative_canvas_versions,source,template['version_id']);canvas=self._one(c,S.creative_canvases,source,version['canvas_id']);doc=self._canvas_document(c,source,version)
        if digest({'title':version['title'],'document':doc})!=version['sha256']:raise Conflict('固定模板摘要不符')
        media=set();domains={};episodes=set()
        if canvas['episode_id']:episodes.add(canvas['episode_id'])
        for node in doc['nodes']:
            if node['media_id']:media.add(node['media_id'])
            if not node.get('domain_version_id'):continue
            kind='spatial' if node['type'] in {'spatial','director'} else 'edit' if node['type']=='edit' else 'tool';key=(kind,node['domain_version_id'])
            if key in domains:continue
            if kind=='spatial':
                fixed=self._one(c,S.spatial_scene_versions,source,key[1]);obj=self._one(c,S.spatial_scenes,source,fixed['spatial_scene_id']);body=self._spatial_document(c,source,fixed);ep=obj['episode_id'];media.update(x['media_id'] for x in body['objects'] if x['media_id'])
            elif kind=='edit':
                fixed=self._one(c,S.edit_revisions,source,key[1]);obj=self._one(c,S.edit_workspaces,source,fixed['workspace_id']);body=deepcopy(fixed['document']);ep=obj['episode_id'];media.update(x['media_id'] for track in ('clips','audio') for x in body[track])
            else:
                fixed=self._one(c,S.artifact_versions,source,key[1]);obj=fixed
                if fixed['artifact_type']!=DRAFT_TYPE:raise ResourceError('加工节点未固定原工具草稿')
                body=json.loads(bytes(fixed['document']));ep=body['input']['episode_id'];media.update(x['media_id'] for x in body['media'])
            if ep:episodes.add(ep)
            domains[key]=dict(kind=kind,fixed=fixed,obj=obj,document=body,episode_id=ep)
        chosen=payload.get('episode_id')
        if chosen:
            self._one(c,S.episodes,target,chosen)
            if len(episodes)>1:raise ResourceError('此模板包含多集工具，请选择自动新建对应分集')
            if any(d['kind']=='edit' for d in domains.values()) and c.scalar(select(S.edit_workspaces.c.id).where(S.edit_workspaces.c.project_id==target,S.edit_workspaces.c.episode_id==chosen)):raise Conflict('目标分集已有剪辑稿，请选择新建对应分集，避免覆盖原稿')
        items=[]
        for mid in sorted(media):
            from .copy_lineage import assert_copy_source
            item=self._media(c,source,mid);rights=assert_copy_source(self.store,c,source,mid)
            if rights and rights['outcome'] not in {'owned','licensed','unknown'}:raise ResourceError('模板素材权利已限制，不能复制')
            items.append(dict(id=mid,name=item.get('name') or item['modality'],modality=item['modality'],sha256=item['sha256']))
        return dict(source=source,template=template,version=version,canvas=canvas,document=doc,media=items,domains=domains,episodes=episodes)
    def preview(self,p,payload):
        with self.engine.connect() as c:
            plan=self._plan(c,p,payload);return clean(dict(title=plan['template']['title'],source_version=plan['version']['version'],source_sha256=plan['version']['sha256'],media=plan['media'],domain_counts={kind:sum(d['kind']==kind for d in plan['domains'].values()) for kind in ('spatial','tool','edit')},new_episode_count=0 if payload.get('episode_id') else len(plan['episodes']),node_count=len(plan['document']['nodes']),revision=self._project(c,p)['revision']))
    def media_ids(self,source,template_id):
        # Read-only fixed dependency walk; target=source only requires the source read grant.
        with self.engine.connect() as c:
            t=self._one(c,S.canvas_templates,source,template_id);v=self._one(c,S.creative_canvas_versions,source,t['version_id']);doc=self._canvas_document(c,source,v);ids={n['media_id'] for n in doc['nodes'] if n['media_id']}
            for n in doc['nodes']:
                ver=n.get('domain_version_id')
                if not ver:continue
                if n['type'] in {'spatial','director'}:ids.update(x['media_id'] for x in self._spatial_document(c,source,self._one(c,S.spatial_scene_versions,source,ver))['objects'] if x['media_id'])
                elif n['type']=='edit':
                    body=self._one(c,S.edit_revisions,source,ver)['document'];ids.update(x['media_id'] for track in ('clips','audio') for x in body[track])
                else:ids.update(x['media_id'] for x in json.loads(bytes(self._one(c,S.artifact_versions,source,ver)['document']))['media'])
            return sorted(ids)
    def copy(self,p,payload,actor,**kw):
        source=checked_id(payload['source_project_id'])
        def work(c,project):
            plan=self._plan(c,p,payload);media_map={};episode_map={};domain_map={};copy_id=new_id();canvas_id=new_id()
            def new_object(kind,parent,title):
                table=S.episodes if kind=='episode' else S.scenes
                ordinal=c.scalar(select(func.coalesce(func.max(table.c.ordinal),-1)).where(table.c.project_id==p,table.c.parent_id==parent))+1
                return self._create_object(c,project,dict(kind=kind,parent_id=parent,ordinal=ordinal,display_code=('EP-' if kind=='episode' else 'SC-')+new_id()[:8],title=title))['id']
            work_id=c.scalar(select(S.works.c.id).where(S.works.c.project_id==p).order_by(S.works.c.ordinal).limit(1))
            if plan['episodes'] and not payload.get('episode_id') and not work_id:
                work_id=self._create_object(c,project,dict(kind='work',display_code='WK-'+new_id()[:8],title=payload['title'],ordinal=0))['id']
            for old in sorted(plan['episodes']):
                name=self._one(c,S.creative_objects,source,old)['title'];episode_map[old]=payload.get('episode_id') or new_object('episode',work_id,(name or '模板分集')+' · 副本')
            def copied_media(mid):
                if not mid:return None
                if mid not in media_map:
                    item=self._media(c,source,mid);rights=self._latest(c,S.rights_decisions,source,'media_id',mid);location=next((x for x in item['locations'] if x['available']),None)
                    if not location:raise ResourceError('模板素材没有可用副本')
                    row=self._register_media(c,project,dict(item,id=new_id(),storage=location['storage'],object_key=location['object_key'],rights=rights['outcome'] if rights else 'unknown',rights_scope=rights['scope'] if rights else {'purposes':[]},rights_expires_at=rights['expires_at'] if rights else None,source={'kind':'canvas-template-copy','content':{'source_project_id':source,'template_id':plan['template']['id'],'source_media_id':mid,'sha256':item['sha256']}}),actor);media_map[mid]=dict(id=row['id'],blob_id=item['blob_id'],sha256=item['sha256'])
                return media_map[mid]['id']
            for item in plan['media']:copied_media(item['id'])
            internal=dict(actor=actor,expected_revision=project['revision'],idempotency_key='template-copy-internal',_transaction=(c,project))
            for key,d in plan['domains'].items():
                episode=episode_map.get(d['episode_id']) or payload.get('episode_id');body=deepcopy(d['document']);kind=d['kind']
                if kind=='spatial':
                    for item in body['objects']:item['media_id']=copied_media(item['media_id'])
                    scene_id=new_object('scene',episode,d['fixed']['title']) if d['obj']['mode']=='blocking' else None
                    saved=self.create_spatial_scene(p,dict(mode=d['obj']['mode'],episode_id=episode,scene_id=scene_id,title=d['fixed']['title'],description=d['fixed']['description'],document=body),**internal);domain_map[key]=(saved['id'],saved['version_id'])
                elif kind=='edit':
                    from .editor_workspace import EditorWorkspaceRepository
                    for track in ('clips','audio'):
                        for item in body[track]:
                            item['media_id']=copied_media(item['media_id']);item['id']=new_id()
                            for field in ('shot_id','working_selection_version_id','decision_id','annotation_id'):item.pop(field,None)
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
            canvas=dict(id=canvas_id,episode_id=payload.get('episode_id') or episode_map.get(plan['canvas']['episode_id']));c.execute(insert(S.creative_canvases).values(project_id=p,created_by=actor,**canvas))
            result=self._insert_canvas_version(c,project,canvas,dict(title=payload['title'],document=doc),actor)
            c.execute(insert(S.canvas_template_copies).values(project_id=p,id=copy_id,source_project_id=source,template_id=plan['template']['id'],canvas_id=canvas_id,created_by=actor))
            for old,new in media_map.items():c.execute(insert(S.template_copy_media).values(project_id=p,id=new_id(),copy_id=copy_id,source_project_id=source,source_media_id=old,target_media_id=new['id'],blob_id=new['blob_id'],sha256=new['sha256']))
            for (kind,old),(_,new) in domain_map.items():c.execute(insert(S.template_copy_domains).values(project_id=p,id=new_id(),copy_id=copy_id,source_project_id=source,**{'source_'+kind+'_version_id':old,'target_'+kind+'_version_id':new}))
            return dict(result,copy_id=copy_id,source_version_id=plan['version']['id'],media_count=len(media_map),domain_count=len(domain_map),episode_ids=list(episode_map.values()),provider_submitted=False)
        from .copy_lineage import source_projects_for_copy
        with self.engine.connect() as c:related=source_projects_for_copy(c,source)
        return self._mutate(p,'copy_fixed_canvas_template',payload,actor=actor,callback=work,_related_projects=related,**kw)
