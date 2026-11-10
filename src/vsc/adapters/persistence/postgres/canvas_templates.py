"""Template identity/receipt adapter over the shared fixed-canvas clone."""
import json
from sqlalchemy import insert
from . import schema as S
from .values import checked_id,new_id,clean
from .canvas_copy import FixedCanvasClone, tool_input_media


class CanvasTemplatesRepository(FixedCanvasClone):
    def _plan(self,c,target,payload):
        source=checked_id(payload['source_project_id'])
        self._access_require(c,source,'read');self._access_require(c,target,'edit')
        template=self._one(c,S.canvas_templates,source,payload['template_id'])
        version=self._one(c,S.creative_canvas_versions,source,template['version_id'])
        canvas=self._one(c,S.creative_canvases,source,version['canvas_id'])
        return dict(self.plan_fixed(c,target,canvas,version,payload.get('episode_id')),template=template)

    def preview(self,p,payload):
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            plan=self._plan(c,p,payload)
            return clean(dict(title=plan['template']['title'],source_version=plan['version']['version'],source_sha256=plan['version']['sha256'],media=plan['media'],domain_counts={kind:sum(d['kind']==kind for d in plan['domains'].values()) for kind in ('spatial','tool','edit')},new_episode_count=0 if payload.get('episode_id') else len(plan['episodes']),node_count=len(plan['document']['nodes']),revision=self._project(c,p)['revision']))

    def media_ids(self,source,template_id):
        # Read-only fixed dependency walk; no destination or source edit grant.
        with self.engine.connect() as c:
            t=self._one(c,S.canvas_templates,source,template_id);v=self._one(c,S.creative_canvas_versions,source,t['version_id']);doc=self._canvas_document(c,source,v);ids={n['media_id'] for n in doc['nodes'] if n['media_id']}
            for n in doc['nodes']:
                ver=n.get('domain_version_id')
                if not ver:continue
                if n['type'] in {'spatial','director'}:ids.update(x['media_id'] for x in self._spatial_document(c,source,self._one(c,S.spatial_scene_versions,source,ver))['objects'] if x['media_id'])
                elif n['type']=='edit':
                    body=self._one(c,S.edit_revisions,source,ver)['document'];ids.update(x['media_id'] for track in ('clips','audio') for x in body[track])
                else:
                    body=json.loads(bytes(self._one(c,S.artifact_versions,source,ver)['document']))
                    ids.update(x['media_id'] for x in body['media']);ids.update(tool_input_media(body))
            return sorted(ids)

    def copy(self,p,payload,actor,**kw):
        source=checked_id(payload['source_project_id'])
        def work(c,project):
            plan=self._plan(c,p,payload);copy_id=new_id()
            cloned=self.clone_plan(c,project,plan,payload.get('episode_id'),payload['title'],actor,
                source_kind='canvas-template-copy',source_ref={'template_id':plan['template']['id']})
            result=cloned['result'];canvas_id=result['id'];media_map=cloned['media_map'];domain_map=cloned['domain_map'];episode_map=cloned['episode_map']
            c.execute(insert(S.canvas_template_copies).values(project_id=p,id=copy_id,source_project_id=source,template_id=plan['template']['id'],canvas_id=canvas_id,created_by=actor))
            for old,new in media_map.items():c.execute(insert(S.template_copy_media).values(project_id=p,id=new_id(),copy_id=copy_id,source_project_id=source,source_media_id=old,target_media_id=new['id'],blob_id=new['blob_id'],sha256=new['sha256']))
            for (kind,old),(_,new) in domain_map.items():c.execute(insert(S.template_copy_domains).values(project_id=p,id=new_id(),copy_id=copy_id,source_project_id=source,**{'source_'+kind+'_version_id':old,'target_'+kind+'_version_id':new}))
            return dict(result,copy_id=copy_id,source_version_id=plan['version']['id'],media_count=len(media_map),domain_count=len(domain_map),episode_ids=list(episode_map.values()),provider_submitted=False)
        from .copy_lineage import source_projects_for_copy
        with self.engine.connect() as c:related=source_projects_for_copy(c,source)
        return self._mutate(p,'copy_fixed_canvas_template',payload,actor=actor,callback=work,_related_projects=related,**kw)
