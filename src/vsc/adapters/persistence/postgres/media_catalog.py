"""Read-only media directory from fixed producers and separate current uses.

Classification and scope filtering happen in SQL before count/page. Only a
bounded page is decorated; no generation, sharing, preview creation or writes.
"""
from urllib.parse import urlencode
from math import gcd
import hashlib
import json

from sqlalchemy import and_, case, cast, distinct, exists, func, literal, null, or_, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import Text

from vsc.assets.resource_service import ResourceError, NotFound
from . import schema as S
from .access_control import authority_lock
from .values import clean

CATEGORIES = {'asset_image','shot_image','composite_video','canvas_image','canvas_audio','canvas_video'}
# These are original production purposes/shot slots, not all media references.
ASSET_PURPOSES = {'asset_ref','identity_face','costume','location_master','location_view','prop','image_edit'}
SHOT_IMAGE_PURPOSES = {'first_frame','last_frame','composition','storyboard','image_edit'}
SHOT_VIDEO_PURPOSES = {'video_clip','reference_to_video','motion_transfer','digital_human','video_upgrade'}
SHOT_IMAGE_ROLES = {'first_frame','last_frame','composition','storyboard'}


def _uuid_null(): return cast(null(), UUID(as_uuid=False))
def _text_null(): return cast(null(), Text)


class ProjectMediaCatalog:
    def __init__(self, store, configuration):
        self.store, self.configuration = store, configuration

    def _readable_projects(self, conn):
        return self.store._access_project_query(conn, 'read')

    @staticmethod
    def _objects():
        e, sc, sq, sh = S.episodes, S.scenes, S.sequences, S.shots
        edges = union_all(*(select(t.c.project_id, t.c.parent_id, t.c.id.label('child_id'))
            for t in (e, sc, sq, sh))).cte('media_object_edges')
        states = S.management_object_states
        hidden = select(states.c.project_id, states.c.object_id).where(states.c.state != 'active').cte('media_hidden_objects', recursive=True)
        hidden = hidden.union(select(edges.c.project_id, edges.c.child_id)
            .join(hidden, and_(edges.c.project_id == hidden.c.project_id, edges.c.parent_id == hidden.c.object_id)))
        object_episodes = union_all(
            select(e.c.project_id, e.c.id.label('object_id'), e.c.id.label('episode_id')),
            select(sc.c.project_id, sc.c.id, sc.c.parent_id),
            select(sq.c.project_id, sq.c.id, sc.c.parent_id).join(sc, and_(sc.c.project_id == sq.c.project_id, sc.c.id == sq.c.parent_id)),
            select(sh.c.project_id, sh.c.id, sc.c.parent_id).join(sq, and_(sq.c.project_id == sh.c.project_id, sq.c.id == sh.c.parent_id))
                .join(sc, and_(sc.c.project_id == sq.c.project_id, sc.c.id == sq.c.parent_id))
        ).cte('media_object_episodes')
        objects = select(object_episodes).where(~exists(select(1).where(hidden.c.project_id == object_episodes.c.project_id,
            hidden.c.object_id == object_episodes.c.object_id))).cte('media_active_object_episodes')
        return hidden, object_episodes, objects

    @staticmethod
    def _canvas_jobs(allowed):
        j, run, prep, ci, wi = S.generation_jobs, S.creative_canvas_runs, S.creative_canvas_preparations, S.canvas_generation_inputs, S.workbench_run_inputs
        canvas_jobs = union_all(
            select(j.c.project_id, j.c.id.label('job_id'), run.c.version_id, run.c.node_key, run.c.created_at, literal(0).label('priority'))
                .join(run, and_(run.c.project_id == j.c.project_id, run.c.artifact_id == j.c.run_version_id)),
            select(prep.c.project_id, prep.c.job_id, prep.c.version_id, prep.c.node_key, prep.c.created_at, literal(1))
                .where(prep.c.job_id.is_not(None)),
            select(j.c.project_id, j.c.id, ci.c.version_id, ci.c.node_key, ci.c.created_at, literal(2))
                .join(wi, and_(wi.c.project_id == j.c.project_id, wi.c.run_version_id == j.c.run_version_id, wi.c.shot_id == j.c.shot_id))
                .join(ci, and_(ci.c.project_id == wi.c.project_id, ci.c.draft_version_id == wi.c.draft_version_id))
        ).cte('media_canvas_producers')
        ranked = select(canvas_jobs, func.row_number().over(partition_by=(canvas_jobs.c.project_id, canvas_jobs.c.job_id),
            order_by=(canvas_jobs.c.priority, canvas_jobs.c.created_at, canvas_jobs.c.version_id, canvas_jobs.c.node_key)).label('rank'))\
            .where(canvas_jobs.c.project_id.in_(allowed)).cte('media_canvas_producer_rank')
        return select(ranked).where(ranked.c.rank == 1).cte('media_canvas_producer')

    @staticmethod
    def _references(allowed, hidden, objects, cj):
        bc, bs = S.binding_candidates, S.binding_slots
        bindings = select(bc.c.project_id, bc.c.media_id, objects.c.episode_id, bs.c.target_object_id.label('target_id'),
            _uuid_null().label('canvas_id'), literal('binding').label('source_type'), bc.c.created_at.label('touched_at'))\
            .join(bs, and_(bs.c.project_id == bc.c.project_id, bs.c.id == bc.c.slot_id))\
            .join(objects, and_(objects.c.project_id == bs.c.project_id, objects.c.object_id == bs.c.target_object_id))
        jobs, outputs, inputs = S.generation_jobs, S.job_outputs, S.job_input_media
        j_cv, j_ver = S.creative_canvases.alias('job_canvases'), S.creative_canvas_versions.alias('job_canvas_versions')
        job_canvas_active = and_(~exists(select(1).where(hidden.c.project_id == jobs.c.project_id,
            hidden.c.object_id == j_cv.c.episode_id)), ~exists(select(1).where(
                S.management_canvas_states.c.project_id == jobs.c.project_id,
                S.management_canvas_states.c.canvas_id == j_cv.c.id,
                S.management_canvas_states.c.state != 'active')))
        job_refs = []
        for table, kind in ((outputs, 'job_output'), (inputs, 'job_input')):
            job_refs.append(select(jobs.c.project_id, table.c.media_id,
                func.coalesce(j_cv.c.episode_id, objects.c.episode_id).label('episode_id'),
                case((cj.c.job_id.is_not(None), _uuid_null()), else_=func.coalesce(jobs.c.shot_id, jobs.c.asset_id)).label('target_id'),
                j_cv.c.id.label('canvas_id'), literal(kind).label('source_type'), jobs.c.updated_at.label('touched_at'))
                .join(table, and_(table.c.project_id == jobs.c.project_id, table.c.job_id == jobs.c.id))
                .outerjoin(cj, and_(cj.c.project_id == jobs.c.project_id, cj.c.job_id == jobs.c.id))
                .outerjoin(j_ver, and_(j_ver.c.project_id == cj.c.project_id, j_ver.c.id == cj.c.version_id))
                .outerjoin(j_cv, and_(j_cv.c.project_id == j_ver.c.project_id, j_cv.c.id == j_ver.c.canvas_id))
                .outerjoin(objects, and_(objects.c.project_id == jobs.c.project_id, objects.c.object_id == jobs.c.shot_id))
                .where(~exists(select(1).where(hidden.c.project_id == jobs.c.project_id,
                    hidden.c.object_id == func.coalesce(jobs.c.shot_id, jobs.c.asset_id))),
                    or_(cj.c.job_id.is_(None), job_canvas_active)))
        canvases, nodes, versions = S.creative_canvases, S.creative_canvas_nodes, S.creative_canvas_versions
        canvas_from = canvases.join(versions, and_(versions.c.project_id == canvases.c.project_id,
            versions.c.id == canvases.c.current_version_id)).join(nodes, and_(nodes.c.project_id == canvases.c.project_id,
                nodes.c.version_id == versions.c.id))
        canvas_active = and_(~exists(select(1).where(hidden.c.project_id == canvases.c.project_id,
            hidden.c.object_id == canvases.c.episode_id)), ~exists(select(1).where(
                S.management_canvas_states.c.project_id == canvases.c.project_id,
                S.management_canvas_states.c.canvas_id == canvases.c.id,
                S.management_canvas_states.c.state != 'active')))
        canvas_media = select(canvases.c.project_id, nodes.c.media_id, canvases.c.episode_id, _uuid_null().label('target_id'),
            canvases.c.id.label('canvas_id'), literal('canvas').label('source_type'), versions.c.created_at.label('touched_at'))\
            .select_from(canvas_from).where(nodes.c.media_id.is_not(None), canvas_active)
        canvas_jobs = select(canvases.c.project_id, outputs.c.media_id, canvases.c.episode_id, _uuid_null().label('target_id'),
            canvases.c.id.label('canvas_id'), literal('canvas').label('source_type'), versions.c.created_at.label('touched_at'))\
            .select_from(canvas_from.join(outputs, and_(outputs.c.project_id == nodes.c.project_id, outputs.c.job_id == nodes.c.job_id)))\
            .where(nodes.c.job_id.is_not(None), canvas_active)
        assets, forms, fv = S.episode_assets, S.episode_asset_forms, S.episode_asset_form_versions
        episode_assets = select(assets.c.project_id, fv.c.media_id, assets.c.episode_id, assets.c.episode_id.label('target_id'),
            _uuid_null().label('canvas_id'), literal('episode_asset').label('source_type'), fv.c.created_at.label('touched_at'))\
            .join(forms, and_(forms.c.project_id == assets.c.project_id, forms.c.episode_asset_id == assets.c.id))\
            .join(fv, and_(fv.c.project_id == forms.c.project_id, fv.c.id == forms.c.current_version_id))\
            .where(fv.c.media_id.is_not(None), ~exists(select(1).where(hidden.c.project_id == assets.c.project_id,
                hidden.c.object_id == assets.c.episode_id)))
        refs = union_all(bindings, *job_refs, canvas_media, canvas_jobs, episode_assets).cte('media_original_references')
        return select(refs).where(refs.c.project_id.in_(allowed)).cte('media_visible_references')

    @staticmethod
    def _producers(allowed, hidden, objects, cj):
        """Fixed output provenance wins over later usage or asset/shot references."""
        j,o,m,v,cv = S.generation_jobs,S.job_outputs,S.media_items,S.creative_canvas_versions,S.creative_canvases
        def active_object(project,identifier):
            return ~exists(select(1).where(hidden.c.project_id==project,hidden.c.object_id==identifier))
        def fields(project,media,category,kind,at,key,priority=1,episode=None,target=None,canvas=None,version=None,node=None,job=None,asset=None,form=None,active=None,asset_kind=None):
            values=(project,media,category,kind,at,cast(key,Text),literal(priority),episode if episode is not None else _uuid_null(),
                target if target is not None else _uuid_null(),canvas if canvas is not None else _uuid_null(),
                version if version is not None else _uuid_null(),node if node is not None else _text_null(),job if job is not None else _uuid_null(),
                asset if asset is not None else _uuid_null(),form if form is not None else _uuid_null(),active if active is not None else literal(True),
                asset_kind if asset_kind is not None else _text_null())
            names=('project_id','media_id','category','kind','created_at','evidence_id','priority','episode_id','target_id','canvas_id','canvas_version_id','node_key','source_job_id','asset_id','form_version_id','active','asset_kind')
            return [value.label(name) for name,value in zip(names,values)]
        canvas_active=and_(active_object(j.c.project_id,cv.c.episode_id),~exists(select(1).where(
            S.management_canvas_states.c.project_id==j.c.project_id,S.management_canvas_states.c.canvas_id==cv.c.id,S.management_canvas_states.c.state!='active')))
        category=case((and_(cj.c.job_id.is_not(None),m.c.modality.in_(['image','audio','video'])),literal('canvas_')+m.c.modality),
            (and_(j.c.asset_id.is_not(None),m.c.modality=='image',j.c.purpose.in_(ASSET_PURPOSES)),literal('asset_image')),
            (and_(j.c.shot_id.is_not(None),m.c.modality=='image',j.c.purpose.in_(SHOT_IMAGE_PURPOSES)),literal('shot_image')),
            (and_(j.c.shot_id.is_not(None),m.c.modality=='video',j.c.purpose.in_(SHOT_VIDEO_PURPOSES)),literal('composite_video')),else_=_text_null())
        generated=select(*fields(j.c.project_id,o.c.media_id,category,
            case((cj.c.job_id.is_not(None),literal('canvas_generation')),(j.c.asset_id.is_not(None),literal('asset_generation')),else_=literal('shot_generation')),
            j.c.created_at,j.c.id,priority=0,episode=func.coalesce(cv.c.episode_id,objects.c.episode_id),target=func.coalesce(j.c.shot_id,j.c.asset_id),
            canvas=cv.c.id,version=cj.c.version_id,node=cj.c.node_key,job=j.c.id,asset=j.c.asset_id,
            active=and_(active_object(j.c.project_id,func.coalesce(j.c.shot_id,j.c.asset_id)),or_(cj.c.job_id.is_(None),canvas_active)),asset_kind=S.asset_identities.c.asset_kind))\
            .join(o,and_(o.c.project_id==j.c.project_id,o.c.job_id==j.c.id))\
            .join(m,and_(m.c.project_id==o.c.project_id,m.c.id==o.c.media_id))\
            .outerjoin(cj,and_(cj.c.project_id==j.c.project_id,cj.c.job_id==j.c.id))\
            .outerjoin(v,and_(v.c.project_id==cj.c.project_id,v.c.id==cj.c.version_id))\
            .outerjoin(cv,and_(cv.c.project_id==v.c.project_id,cv.c.id==v.c.canvas_id))\
            .outerjoin(objects,and_(objects.c.project_id==j.c.project_id,objects.c.object_id==j.c.shot_id))\
            .outerjoin(S.asset_identities,and_(S.asset_identities.c.project_id==j.c.project_id,S.asset_identities.c.id==j.c.asset_id))\
            .where(j.c.status=='succeeded',j.c.project_id.in_(allowed))
        f,fv,a=S.asset_card_forms,S.asset_card_form_versions,S.asset_identities
        asset_forms=select(*fields(f.c.project_id,fv.c.media_id,literal('asset_image'),literal('asset_form'),fv.c.created_at,fv.c.id,
            target=f.c.asset_id,asset=f.c.asset_id,form=fv.c.id,active=active_object(f.c.project_id,f.c.asset_id),asset_kind=a.c.asset_kind))\
            .join(fv,and_(fv.c.project_id==f.c.project_id,fv.c.form_id==f.c.id)).join(a,and_(a.c.project_id==f.c.project_id,a.c.id==f.c.asset_id))\
            .join(m,and_(m.c.project_id==fv.c.project_id,m.c.id==fv.c.media_id)).where(m.c.modality=='image',f.c.project_id.in_(allowed))
        ea,ef,ev=S.episode_assets,S.episode_asset_forms,S.episode_asset_form_versions
        episode_forms=select(*fields(ea.c.project_id,ev.c.media_id,literal('asset_image'),literal('episode_asset_form'),ev.c.created_at,ev.c.id,
            episode=ea.c.episode_id,target=ea.c.episode_id,asset=ea.c.id,form=ev.c.id,active=active_object(ea.c.project_id,ea.c.episode_id),asset_kind=ea.c.asset_kind))\
            .join(ef,and_(ef.c.project_id==ea.c.project_id,ef.c.episode_asset_id==ea.c.id)).join(ev,and_(ev.c.project_id==ef.c.project_id,ev.c.form_id==ef.c.id))\
            .join(m,and_(m.c.project_id==ev.c.project_id,m.c.id==ev.c.media_id)).where(m.c.modality=='image',ea.c.project_id.in_(allowed))
        bc,bs=S.binding_candidates,S.binding_slots
        binding_category=case((and_(m.c.modality=='image',bs.c.role.in_(SHOT_IMAGE_ROLES)),literal('shot_image')),
            (and_(m.c.modality=='video',bs.c.role=='video_take'),literal('composite_video')),else_=_text_null())
        bindings=select(*fields(bc.c.project_id,bc.c.media_id,binding_category,literal('shot_binding'),bc.c.created_at,bc.c.id,
            episode=objects.c.episode_id,target=bs.c.target_object_id,active=active_object(bc.c.project_id,bs.c.target_object_id)))\
            .join(bs,and_(bs.c.project_id==bc.c.project_id,bs.c.id==bc.c.slot_id)).join(S.shots,and_(S.shots.c.project_id==bs.c.project_id,S.shots.c.id==bs.c.target_object_id))\
            .join(m,and_(m.c.project_id==bc.c.project_id,m.c.id==bc.c.media_id)).join(objects,and_(objects.c.project_id==bs.c.project_id,objects.c.object_id==bs.c.target_object_id))\
            .where(binding_category.is_not(None),bc.c.project_id.in_(allowed))
        all_producers=union_all(generated,asset_forms,episode_forms,bindings).cte('media_producer_candidates')
        ranked_priority=select(all_producers,func.min(all_producers.c.priority).over(partition_by=(all_producers.c.project_id,all_producers.c.media_id)).label('best_priority')).cte('media_producer_priority')
        preferred=select(ranked_priority).where(ranked_priority.c.priority==ranked_priority.c.best_priority).cte('media_preferred_producers')
        stats=select(preferred.c.project_id,preferred.c.media_id,func.count(distinct(preferred.c.category)).label('categories')).group_by(preferred.c.project_id,preferred.c.media_id).cte('media_producer_stats')
        ranked=select(preferred,func.row_number().over(partition_by=(preferred.c.project_id,preferred.c.media_id),
            order_by=(preferred.c.created_at,preferred.c.evidence_id,preferred.c.kind)).label('rank')).cte('media_producer_rank')
        return select(ranked,case((and_(ranked.c.priority==1,stats.c.categories>1),_text_null()),else_=ranked.c.category).label('resolved_category'),
            case((and_(ranked.c.priority==1,stats.c.categories>1),literal('ambiguous_source')),(ranked.c.category.is_(None),literal('unclassified_producer')),else_=literal('fixed_evidence')).label('category_reason'))\
            .join(stats,and_(stats.c.project_id==ranked.c.project_id,stats.c.media_id==ranked.c.media_id)).where(ranked.c.rank==1).cte('media_resolved_producers')

    def search(self, filters, *, media_id=None, detail=False):
        media,projects,life,blob=S.media_items,S.projects,S.media_lifecycle_decisions,S.media_blobs
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            authority_lock(conn)
            allowed=self._readable_projects(conn).where(~exists(select(1).where(S.management_project_states.c.project_id==projects.c.id,S.management_project_states.c.state!='active')))
            if filters['project_id']:
                self.store._access_require(conn,filters['project_id'],'read')
                allowed=allowed.where(projects.c.id==filters['project_id'])
            if filters['episode_id']:
                self.store._one(conn,S.episodes,filters['project_id'],filters['episode_id'])
            allowed=allowed.cte('media_readable_projects');allowed_ids=select(allowed.c.id)
            hidden,objects,active_objects=self._objects();cj=self._canvas_jobs(allowed_ids)
            refs=self._references(allowed_ids,hidden,active_objects,cj)
            producer=self._producers(allowed_ids,hidden,objects,cj)
            latest=select(life.c.project_id,life.c.media_id,life.c.id,life.c.outcome,
                func.row_number().over(partition_by=(life.c.project_id,life.c.media_id),order_by=life.c.decision_sequence.desc()).label('rank'))\
                .where(life.c.project_id.in_(allowed_ids)).cte('media_lifecycle_ranked')
            recycled=exists(select(1).select_from(latest.join(S.media_recycle_actions,and_(S.media_recycle_actions.c.project_id==latest.c.project_id,S.media_recycle_actions.c.decision_id==latest.c.id)))\
                .where(latest.c.project_id==media.c.project_id,latest.c.media_id==media.c.id,latest.c.rank==1,latest.c.outcome=='deprecate'))
            query=select(media,projects.c.name.label('project_name'),blob.c.width,blob.c.height,blob.c.duration_ms,producer.c.resolved_category.label('category'),producer.c.category_reason)\
                .join(projects,projects.c.id==media.c.project_id).join(blob,blob.c.id==media.c.blob_id)\
                .outerjoin(producer,and_(producer.c.project_id==media.c.project_id,producer.c.media_id==media.c.id)).where(media.c.project_id.in_(allowed_ids),~recycled)
            if media_id:query=query.where(media.c.id==media_id)
            if filters['episode_id']:
                query=query.where(or_(exists(select(1).where(refs.c.project_id==media.c.project_id,refs.c.media_id==media.c.id,refs.c.episode_id==filters['episode_id'])),
                    and_(producer.c.active.is_(True),producer.c.episode_id==filters['episode_id'])))
            if filters.get('category'):query=query.where(producer.c.resolved_category==filters['category'])
            if filters['modality']:query=query.where(media.c.modality==filters['modality'])
            if filters['query']:
                pattern='%'+filters['query'].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
                query=query.where(media.c.name.ilike(pattern,escape='\\'))
            if filters['created_after']:query=query.where(media.c.created_at>=filters['created_after'])
            if filters['created_before']:query=query.where(media.c.created_at<filters['created_before'])
            total=conn.scalar(select(func.count()).select_from(query.subquery()))
            if not total or filters['offset']>=total:
                return {'items':[],'total':total,'offset':filters['offset'],'limit':filters['limit'],'next_offset':None}
            ref_stats=select(refs.c.project_id,refs.c.media_id,func.max(refs.c.touched_at).label('reference_updated_at'),func.count(distinct(refs.c.episode_id)).label('episode_count'),
                func.min(cast(refs.c.episode_id,Text)).label('single_episode_id')).group_by(refs.c.project_id,refs.c.media_id).subquery()
            life_updated=select(life.c.project_id,life.c.media_id,func.max(life.c.created_at).label('lifecycle_updated_at')).where(life.c.project_id.in_(allowed_ids)).group_by(life.c.project_id,life.c.media_id).subquery()
            updated_at=func.greatest(media.c.created_at,ref_stats.c.reference_updated_at,life_updated.c.lifecycle_updated_at).label('updated_at')
            query=query.outerjoin(ref_stats,and_(ref_stats.c.project_id==media.c.project_id,ref_stats.c.media_id==media.c.id))\
                .outerjoin(life_updated,and_(life_updated.c.project_id==media.c.project_id,life_updated.c.media_id==media.c.id)).add_columns(updated_at,ref_stats.c.episode_count,ref_stats.c.single_episode_id)
            sort_at=updated_at if filters['order']=='updated_desc' else media.c.created_at
            rows=[dict(r) for r in conn.execute(query.order_by(sort_at.desc(),media.c.project_id,media.c.id).offset(filters['offset']).limit(filters['limit'])).mappings()]
            keys=[(r['project_id'],r['id']) for r in rows]
            producers={(r['project_id'],r['media_id']):dict(r) for r in conn.execute(select(producer).where(tuple_(producer.c.project_id,producer.c.media_id).in_(keys))).mappings()}
            # Only a bounded set of current uses for this page; no unbounded JSON.
            ranked_refs=select(refs,func.row_number().over(partition_by=(refs.c.project_id,refs.c.media_id),order_by=(refs.c.touched_at.desc(),refs.c.source_type,refs.c.target_id,refs.c.canvas_id)).label('rank')).where(tuple_(refs.c.project_id,refs.c.media_id).in_(keys)).subquery()
            uses={}
            for r in conn.execute(select(ranked_refs).where(ranked_refs.c.rank<=20)).mappings():uses.setdefault((r['project_id'],r['media_id']),[]).append(dict(r))
            episode_ids={(r['project_id'],r['single_episode_id']) for r in rows if r['episode_count']==1}
            episode_ids.update((r['project_id'],r['episode_id']) for r in producers.values() if r['active'] and r['episode_id'])
            episode_names={(r['project_id'],r['id']):r['title'] for r in conn.execute(select(S.creative_objects.c.project_id,S.creative_objects.c.id,S.creative_objects.c.title).where(tuple_(S.creative_objects.c.project_id,S.creative_objects.c.id).in_(episode_ids))).mappings()} if episode_ids else {}
            renditions={}
            rd,loc=S.media_renditions,S.blob_locations
            for r in conn.execute(select(rd.c.project_id,rd.c.media_id,rd.c.purpose).where(tuple_(rd.c.project_id,rd.c.media_id).in_(keys),
                rd.c.purpose.in_(['thumbnail','poster','proxy_video','waveform']),exists(select(1).where(loc.c.blob_id==rd.c.blob_id,loc.c.storage=='local',loc.c.available.is_(True))))).mappings():
                renditions.setdefault((r['project_id'],r['media_id']),set()).add(r['purpose'])
            editable=set(conn.execute(self.store._access_project_query(conn,'edit').where(S.projects.c.id.in_({r['project_id'] for r in rows}))).scalars())
            items=[]
            for row in rows:
                key=row['project_id'],row['id'];fixed=producers.get(key);references=uses.get(key,[])
                item=self._item(row,fixed,references,episode_names,renditions.get(key,set()),filters['episode_id'])
                if fixed and fixed['active'] and fixed['kind']=='shot_generation' and row['category'] in {'shot_image','composite_video'} and row['project_id'] in editable and self.configuration:
                    try:configuration=self.configuration(row['project_id'],fixed['target_id'],row['id'])
                    except ResourceError:configuration=None
                    if configuration and configuration.get('available') and configuration.get('source_job_id')==fixed['source_job_id'] and configuration.get('configuration_source')=='fixed_workbench_draft':
                        href='/?'+urlencode(dict(page='classic-production',project=row['project_id'],scope=fixed['target_id'],kind=row['modality'],reuse_media=row['id']))
                        item['reuse_href']=href;item['actions']['reuse']={'available':True,'kind':'classic_fixed_draft','href':href}
                if detail:item.update(self._metadata(conn,row,fixed))
                items.append(item)
            following=filters['offset']+len(items)
            return clean(dict(items=items,total=total,offset=filters['offset'],limit=filters['limit'],next_offset=following if following<total else None))

    @staticmethod
    def _source(fixed):
        source={k:fixed[k] for k in ('kind','project_id','episode_id','canvas_id','canvas_version_id','node_key','source_job_id','asset_id','form_version_id') if fixed.get(k) is not None}
        if fixed['kind'] in {'shot_generation','shot_binding'}:source['shot_id']=fixed['target_id']
        return source

    @staticmethod
    def _href(source,modality):
        params=dict(project=source['project_id'])
        if source.get('canvas_id'):params.update(page='creative-canvas',task_target=source['canvas_id'])
        elif source.get('shot_id'):params.update(page='classic-production' if modality in {'image','video'} else 'workbench',scope=source['shot_id'])
        elif source.get('asset_id') or source['kind'] in {'episode_asset','episode_asset_usage'}:params.update(page='assets',scope=source.get('asset_id') or source.get('episode_id') or source.get('target_id'))
        else:params.update(page='workbench',scope=source.get('target_id'))
        if source.get('episode_id'):params['episode']=source['episode_id']
        if params['page']=='classic-production':params['kind']=modality
        return '/?'+urlencode({k:v for k,v in params.items() if v is not None})

    def _item(self,row,fixed,uses,episode_names,renditions,episode_filter):
        base='/api/v1/projects/'+row['project_id']+'/media/'+row['id']
        item={k:row[k] for k in ('id','project_id','project_name','name','modality','created_at','updated_at','category','width','height','duration_ms')}
        source=None;producer=None;reason='source_unknown'
        if fixed:
            if fixed['active'] and row['category_reason']!='ambiguous_source':source=producer=self._source(fixed)
            else:reason='source_inactive' if not fixed['active'] else 'ambiguous_source'
        elif uses:
            use=uses[0];source={k:use[k] for k in ('project_id','episode_id','canvas_id','target_id') if use[k] is not None};source['kind']=use['source_type']+'_usage'
            if use['source_type'] in {'job_output','job_input','binding'} and use['target_id']:source['shot_id']=use['target_id']
        episode_id=episode_filter or (row['single_episode_id'] if row['episode_count']==1 else None)
        if not row['episode_count'] and fixed and fixed['active']:episode_id=fixed['episode_id']
        href=self._href(source,row['modality']) if source else None
        preview_purpose='thumbnail' if row['modality']=='image' else 'proxy_video' if row['modality']=='video' else None
        item.update(category_reason=row['category_reason'] or 'unknown_source',episode_id=episode_id,episode_name=episode_names.get((row['project_id'],episode_id)),
            episode_count=row['episode_count'] or (1 if episode_id else 0),content_url=base+'/content',
            preview_url=base+'/preview?purpose='+preview_purpose if preview_purpose in renditions else None,
            poster_url=base+'/preview?purpose=poster' if 'poster' in renditions else base+'/preview?purpose=waveform' if 'waveform' in renditions else None,
            source=source,producer=producer,source_href=href,reuse_href=None,source_job_id=producer.get('source_job_id') if producer else None,
            usages=[{**{k:u[k] for k in ('project_id','episode_id','target_id','canvas_id') if u[k] is not None},'kind':u['source_type']} for u in uses],
            actions=dict(source=dict(available=bool(source),**({'href':href} if source else {'reason_code':reason})),
                reuse=dict(available=False,reason_code='configuration_unavailable'),download=dict(available=True,href=base+'/content?download=true')))
        return item

    def _metadata(self,conn,row,fixed):
        width,height=row['width'],row['height']
        ratio=(str(width//gcd(width,height))+':'+str(height//gcd(width,height))) if width and height else None
        result=dict(prompt=None,model=None,aspect_ratio=ratio,resolution_label=None,asset_kind=None)
        if not fixed or not fixed['active'] or row['category_reason']=='ambiguous_source':return result
        result['asset_kind']=fixed['asset_kind']
        if not fixed['source_job_id']:return result
        job=self.store._one(conn,S.generation_jobs,row['project_id'],fixed['source_job_id'])
        request=job['request_payload'];document=None
        # Prefer the original typed fixed draft, never current canvas text/defaults.
        pin=conn.execute(select(S.workbench_run_inputs).where(S.workbench_run_inputs.c.project_id==row['project_id'],S.workbench_run_inputs.c.run_version_id==job['run_version_id'],S.workbench_run_inputs.c.shot_id==job['shot_id'])).mappings().first() if job['shot_id'] else None
        if pin:
            artifact=self.store._one(conn,S.artifact_versions,row['project_id'],pin['draft_version_id'])
            if artifact['sha256']==pin['draft_sha256'] and hashlib.sha256(bytes(artifact['document'])).hexdigest()==pin['draft_sha256']:
                document=json.loads(bytes(artifact['document']))
        config=document if isinstance(document,dict) else request.get('logical_request',request) if isinstance(request.get('logical_request'),dict) else request
        prompt=config.get('prompt')
        if isinstance(prompt,str):result['prompt']=prompt[:50000]
        params=config.get('params')
        resolution=params.get('resolution') if isinstance(params,dict) else None
        if isinstance(resolution,(str,int)) and not isinstance(resolution,bool) and len(str(resolution))<=32:result['resolution_label']=str(resolution)
        model=conn.execute(select(S.provider_models.c.id,S.provider_models.c.model_key,S.provider_models.c.enabled,S.providers.c.enabled.label('provider_enabled'))
            .join(S.providers,S.providers.c.id==S.provider_models.c.provider_id).where(S.provider_models.c.id==job['model_id'])).mappings().first()
        if model:result['model']=dict(id=model['id'],name=model['model_key'],version=job['model_version'],available=bool(model['enabled'] and model['provider_enabled']))
        return result

    def detail(self,project_id,media_id):
        filters=dict(project_id=project_id,episode_id=None,modality=None,category=None,query='',created_after=None,created_before=None,order='created_desc',offset=0,limit=1)
        result=self.search(filters,media_id=media_id,detail=True)
        if not result['items']:raise NotFound('媒资不在当前可读目录中')
        return result['items'][0]
