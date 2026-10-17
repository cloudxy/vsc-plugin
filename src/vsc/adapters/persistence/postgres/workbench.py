"""Bounded creative workspace queries using one read-only database snapshot."""
from sqlalchemy import text
from .values import checked_id, clean
from vsc.assets.resource_service import Conflict, NotFound

HIERARCHY = ' UNION ALL '.join('SELECT id,parent_id,ordinal FROM '+t+' WHERE project_id=:p' for t in ('episodes','scenes','sequences','shots'))
CTE = '''WITH RECURSIVE hierarchy AS ('''+HIERARCHY+'''),
scope_ids(id) AS (SELECT id FROM creative_objects WHERE project_id=:p AND (CAST(:scope AS uuid) IS NULL OR id=CAST(:scope AS uuid))
 UNION SELECT h.id FROM hierarchy h JOIN scope_ids s ON h.parent_id=s.id),
ancestors(id,parent_id) AS (SELECT id,parent_id FROM hierarchy WHERE id=CAST(:scope AS uuid)
 UNION SELECT h.id,h.parent_id FROM hierarchy h JOIN ancestors a ON a.parent_id=h.id),
scoped_slots AS (SELECT id FROM binding_slots WHERE project_id=:p AND target_object_id IN (SELECT id FROM scope_ids)),
scoped_versions AS (SELECT a.id FROM artifact_versions a WHERE a.project_id=:p AND
 (CAST(:scope AS uuid) IS NULL OR a.project_wide OR EXISTS(SELECT 1 FROM artifact_object_scopes x WHERE x.project_id=:p AND x.artifact_id=a.id
 AND (x.object_id IN (SELECT id FROM scope_ids) OR x.object_id IN (SELECT parent_id FROM ancestors))))),
scoped_instances AS (SELECT id FROM asset_use_instances WHERE project_id=:p AND
 (CAST(:scope AS uuid) IS NULL OR asset_id=CAST(:scope AS uuid) OR shot_id IN (SELECT id FROM scope_ids)
 OR (shot_id IS NULL AND (scene_id IN (SELECT id FROM scope_ids) OR scene_id IN (SELECT parent_id FROM ancestors))))),
scoped_executions AS (SELECT e.id FROM execution_instances e WHERE e.project_id=:p AND (CAST(:scope AS uuid) IS NULL
 OR EXISTS(SELECT 1 FROM execution_shots x WHERE x.project_id=:p AND x.execution_id=e.id AND x.shot_id IN (SELECT id FROM scope_ids))
 OR EXISTS(SELECT 1 FROM execution_participants x WHERE x.project_id=:p AND x.execution_id=e.id AND x.instance_id IN (SELECT id FROM scoped_instances)))),
scoped_cues AS (SELECT c.id FROM sound_cues c WHERE c.project_id=:p AND (CAST(:scope AS uuid) IS NULL
 OR c.scope_object_id IN (SELECT id FROM scope_ids)
 OR EXISTS(SELECT 1 FROM cue_shots x WHERE x.project_id=:p AND x.cue_id=c.id AND x.shot_id IN (SELECT id FROM scope_ids))
 OR c.execution_id IN (SELECT id FROM scoped_executions)))
'''
# Each query has a unique stable ID, readable title, typed refs and searchable attributes.
QUERIES = {
'children': '''SELECT o.id,o.kind,o.display_code,o.title,coalesce(h.ordinal,w.ordinal,0) ordinal,h.parent_id
 FROM creative_objects o LEFT JOIN hierarchy h ON h.id=o.id LEFT JOIN works w ON w.project_id=o.project_id AND w.id=o.id
 WHERE o.project_id=:p AND ((CAST(:scope AS uuid) IS NULL AND (o.kind='work' OR o.kind='asset')) OR h.parent_id=CAST(:scope AS uuid))''',
'shots': '''SELECT o.id,o.id shot_id,o.title,o.display_code,'shot' kind,s.ordinal,s.parent_id sequence_id,q.parent_id scene_id,
 s.duration_ms,(SELECT count(*) FROM shot_line_coverage c WHERE c.project_id=:p AND c.shot_id=s.id) coverage_count,
 (SELECT count(*) FROM binding_slots b WHERE b.project_id=:p AND b.target_object_id=s.id) slot_count,
 (SELECT count(*) FROM current_bindings c JOIN binding_slots b ON b.project_id=c.project_id AND b.id=c.slot_id WHERE c.project_id=:p AND b.target_object_id=s.id) selected_count
 FROM shots s JOIN creative_objects o ON o.project_id=s.project_id AND o.id=s.id JOIN sequences q ON q.project_id=s.project_id AND q.id=s.parent_id
 WHERE s.project_id=:p AND s.id IN (SELECT id FROM scope_ids)''',
'lines': '''SELECT l.id,l.id line_id,l.script_version_id artifact_id,l.scene_id,l.speaker_id asset_id,l.line_key title,
 l.line_kind kind,left(l.text,2000) text,l.text search_text,length(l.text) text_length,length(l.text)>2000 text_truncated,l.ordinal,l.source_sha256,
 (SELECT count(*) FROM shot_line_coverage c WHERE c.project_id=:p AND c.line_id=l.id) coverage_count,
 (SELECT count(*) FROM script_line_dispositions d JOIN current_artifact_versions a ON a.project_id=d.project_id AND a.artifact_id=d.artifact_id WHERE d.project_id=:p AND d.line_id=l.id) decided_disposition_count
 FROM script_lines l WHERE l.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR l.scene_id IN (SELECT id FROM scope_ids)
 OR l.speaker_id=CAST(:scope AS uuid) OR EXISTS(SELECT 1 FROM shot_line_coverage c WHERE c.project_id=:p AND c.line_id=l.id AND c.shot_id IN (SELECT id FROM scope_ids)))''',
'assets': '''SELECT o.id,o.id asset_id,o.title,o.display_code,a.asset_kind kind,
 (SELECT count(*) FROM asset_spec_versions v WHERE v.project_id=:p AND v.asset_id=a.id) version_count,
 (SELECT count(*) FROM asset_use_instances u WHERE u.project_id=:p AND u.asset_id=a.id) use_count
 FROM asset_identities a JOIN creative_objects o ON o.project_id=a.project_id AND o.id=a.id WHERE a.project_id=:p AND
 (CAST(:scope AS uuid) IS NULL OR a.id=CAST(:scope AS uuid)
 OR EXISTS(SELECT 1 FROM asset_use_instances u WHERE u.project_id=:p AND u.asset_id=a.id AND u.id IN (SELECT id FROM scoped_instances))
 OR EXISTS(SELECT 1 FROM state_entity_refs r JOIN state_versions v ON v.project_id=r.project_id AND v.id=r.state_id WHERE r.project_id=:p AND r.asset_id=a.id AND (v.scene_id IN (SELECT id FROM scope_ids) OR v.shot_id IN (SELECT id FROM scope_ids)))
 OR EXISTS(SELECT 1 FROM binding_slots b WHERE b.project_id=:p AND b.identity_asset_id=a.id AND b.id IN (SELECT id FROM scoped_slots)))''',
'instances': '''SELECT u.id,u.artifact_id,u.instance_key,u.label title,u.asset_id,u.spec_version_id,u.scene_id,u.shot_id,u.state_id,u.state,
 'instance' kind,(SELECT count(*) FROM instance_interactions i WHERE i.project_id=:p AND (i.subject_id=u.id OR i.object_id=u.id)) interaction_count
 FROM asset_use_instances u WHERE u.project_id=:p AND u.id IN (SELECT id FROM scoped_instances)''',
'cues': '''SELECT c.id,c.artifact_id,c.cue_key,c.label title,c.cue_kind kind,c.scope_object_id,c.line_id,c.voice_spec_id,c.execution_id,c.subtitle_version_id,c.lipsync_version_id,c.parameters,
 (SELECT count(*) FROM cue_shots x WHERE x.project_id=:p AND x.cue_id=c.id) shot_count,
 (SELECT count(*) FROM cue_slots x WHERE x.project_id=:p AND x.cue_id=c.id) slot_count,
 (SELECT count(*) FROM cue_timeline_items x WHERE x.project_id=:p AND x.cue_id=c.id) timeline_count
 FROM sound_cues c WHERE c.project_id=:p AND c.id IN (SELECT id FROM scoped_cues)''',
'performances': '''SELECT e.id,e.artifact_id,e.execution_key,e.label title,e.domain kind,e.method_artifact_id,e.line_id,e.voice_spec_id,e.parameters,
 (SELECT count(*) FROM execution_shots x WHERE x.project_id=:p AND x.execution_id=e.id) shot_count,
 (SELECT count(*) FROM execution_participants x WHERE x.project_id=:p AND x.execution_id=e.id) participant_count,
 'unverified' capability_status FROM execution_instances e WHERE e.project_id=:p AND e.id IN (SELECT id FROM scoped_executions)''',
'bindings': '''SELECT b.id,b.target_object_id object_id,b.role kind,b.role purpose,b.slot_key title,b.identity_asset_id asset_id,b.variant_spec_id,
 c.media_id,c.id candidate_id,cur.decision_id,CASE WHEN cur.decision_id IS NULL THEN 'unselected' ELSE 'selected' END status,
 (SELECT count(*) FROM binding_candidates bc WHERE bc.project_id=:p AND bc.slot_id=b.id) candidate_count
 FROM binding_slots b LEFT JOIN current_bindings cur ON cur.project_id=b.project_id AND cur.slot_id=b.id
 LEFT JOIN binding_candidates c ON c.project_id=cur.project_id AND c.id=cur.candidate_id
 WHERE b.project_id=:p AND b.id IN (SELECT id FROM scoped_slots)''',
'materials': '''SELECT m.id,m.id media_id,m.name title,m.modality kind,m.blob_id,b.sha256,b.duration_ms,b.size_bytes,
 CASE WHEN EXISTS(SELECT 1 FROM binding_candidates c JOIN current_bindings cb ON cb.project_id=c.project_id AND cb.candidate_id=c.id WHERE c.project_id=:p AND c.media_id=m.id) THEN 'selected'
 WHEN EXISTS(SELECT 1 FROM binding_candidates c WHERE c.project_id=:p AND c.media_id=m.id) THEN 'candidate' ELSE 'unassociated' END status,
 (SELECT count(*) FROM binding_candidates c WHERE c.project_id=:p AND c.media_id=m.id) candidate_count
 FROM media_items m JOIN media_blobs b ON b.id=m.blob_id WHERE m.project_id=:p AND (CAST(:scope AS uuid) IS NULL
 OR EXISTS(SELECT 1 FROM binding_candidates c WHERE c.project_id=:p AND c.media_id=m.id AND c.slot_id IN (SELECT id FROM scoped_slots))
 OR EXISTS(SELECT 1 FROM execution_materials x WHERE x.project_id=:p AND x.media_id=m.id AND x.execution_id IN (SELECT id FROM scoped_executions))
 OR EXISTS(SELECT 1 FROM timeline_item_media t JOIN timeline_items i ON i.project_id=t.project_id AND i.id=t.item_id WHERE t.project_id=:p AND t.media_id=m.id AND i.shot_id IN (SELECT id FROM scope_ids)))''',
'versions': '''SELECT a.id,a.id artifact_id,a.artifact_key title,a.artifact_type kind,a.version,a.sha256,a.stage,a.project_wide,
 CASE d.outcome WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected' WHEN 'revoke' THEN 'revoked' ELSE 'draft' END status
 FROM artifact_versions a LEFT JOIN current_artifact_versions cur ON cur.project_id=a.project_id AND cur.artifact_id=a.id
 LEFT JOIN LATERAL(SELECT outcome FROM artifact_decisions d WHERE d.project_id=a.project_id AND d.artifact_id=a.id ORDER BY decision_sequence DESC LIMIT 1) d ON true
 WHERE a.project_id=:p AND a.id IN (SELECT id FROM scoped_versions)''',
# Relationship rows are separately pageable so large M:N lists never hide in an unbounded card.
'candidates': '''SELECT c.id,c.slot_id,c.media_id,c.spec_version_id artifact_id,s.target_object_id object_id,s.role purpose,m.name title,m.modality kind,CASE WHEN cb.candidate_id=c.id THEN 'selected' WHEN d.outcome='reject' THEN 'rejected' ELSE 'candidate' END status FROM binding_candidates c JOIN binding_slots s ON s.project_id=c.project_id AND s.id=c.slot_id JOIN media_items m ON m.project_id=c.project_id AND m.id=c.media_id LEFT JOIN current_bindings cb ON cb.project_id=c.project_id AND cb.slot_id=c.slot_id LEFT JOIN LATERAL(SELECT outcome FROM binding_decisions x WHERE x.project_id=c.project_id AND x.candidate_id=c.id ORDER BY decision_sequence DESC LIMIT 1) d ON true WHERE c.project_id=:p AND c.slot_id IN (SELECT id FROM scoped_slots)''',
'coverage': '''SELECT c.id,c.coverage_version_id artifact_id,c.shot_id,c.line_id,c.start_char,c.end_char,'coverage' kind,'剧本覆盖' title FROM shot_line_coverage c WHERE c.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR c.shot_id IN (SELECT id FROM scope_ids))''',
'states': '''SELECT s.id,s.artifact_id,s.scene_id,s.shot_id,s.location_id asset_id,s.source_sha256,'state' kind,'场镜状态' title FROM state_versions s WHERE s.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR s.shot_id IN (SELECT id FROM scope_ids) OR (s.shot_id IS NULL AND (s.scene_id IN (SELECT id FROM scope_ids) OR s.scene_id IN (SELECT parent_id FROM ancestors))))''',
'voices': '''SELECT b.id,b.character_id asset_id,b.voice_spec_id,b.scope_version_id artifact_id,v.voice_id,v.reference_media_id media_id,'voice' kind,o.title
 FROM character_voice_bindings b JOIN voice_spec_versions v ON v.project_id=b.project_id AND v.id=b.voice_spec_id JOIN creative_objects o ON o.project_id=b.project_id AND o.id=b.character_id
 WHERE b.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR b.character_id=CAST(:scope AS uuid) OR EXISTS(SELECT 1 FROM script_lines l LEFT JOIN shot_line_coverage c ON c.project_id=l.project_id AND c.line_id=l.id WHERE l.project_id=:p AND l.speaker_id=b.character_id AND (l.scene_id IN (SELECT id FROM scope_ids) OR c.shot_id IN (SELECT id FROM scope_ids))))''',
'interactions': '''SELECT i.id,i.artifact_id,i.subject_id,i.object_id,i.relation kind,i.relation title,i.hand,i.parameters FROM instance_interactions i WHERE i.project_id=:p AND (i.subject_id IN (SELECT id FROM scoped_instances) OR i.object_id IN (SELECT id FROM scoped_instances))''',
'dispositions': '''SELECT d.id,d.artifact_id,d.line_id,d.disposition kind,d.reason title,EXISTS(SELECT 1 FROM current_artifact_versions a WHERE a.project_id=d.project_id AND a.artifact_id=d.artifact_id) approved_current FROM script_line_dispositions d JOIN script_lines l ON l.project_id=d.project_id AND l.id=d.line_id WHERE d.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR l.scene_id IN (SELECT id FROM scope_ids))''',
}
for name,table,owner,key,scope in [
 ('cue_shots','cue_shots','cue_id','shot_id','scoped_cues'),('cue_slots','cue_slots','cue_id','slot_id','scoped_cues'),
 ('cue_timeline_items','cue_timeline_items','cue_id','item_id','scoped_cues'),
 ('execution_shots','execution_shots','execution_id','shot_id','scoped_executions'),
 ('execution_participants','execution_participants','execution_id','instance_id','scoped_executions'),
 ('execution_materials','execution_materials','execution_id','media_id','scoped_executions'),
 ('execution_slots','execution_slots','execution_id','slot_id','scoped_executions')]:
    target_table={'shot_id':'creative_objects','slot_id':'binding_slots','item_id':'timeline_items','instance_id':'asset_use_instances','media_id':'media_items'}[key]
    label={'shot_id':"t.display_code || ' · ' || t.title",'slot_id':"t.role || ' · ' || t.slot_key",'item_id':"t.track_key || ' #' || t.ordinal",'instance_id':'t.label','media_id':'t.name'}[key]
    QUERIES[name] = "SELECT r.*, '%s' kind, %s title FROM %s r JOIN %s t ON t.project_id=r.project_id AND t.id=r.%s WHERE r.project_id=:p AND r.%s IN (SELECT id FROM %s)" % (name,label,table,target_table,key,owner,scope)

QUERIES['jobs'] = """SELECT j.id,j.shot_id,j.asset_id,j.purpose,j.status,j.modality kind,j.purpose title,j.model_version,
 (SELECT count(*) FROM job_outputs o WHERE o.project_id=:p AND o.job_id=j.id) output_count,
 (SELECT count(*) FROM job_outputs o WHERE o.project_id=:p AND o.job_id=j.id AND NOT EXISTS(
 SELECT 1 FROM binding_candidates bc JOIN media_reviews mr ON mr.project_id=bc.project_id AND mr.candidate_id=bc.id WHERE bc.project_id=:p AND bc.media_id=o.media_id)) unreviewed_output_count
 FROM generation_jobs j WHERE j.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR j.shot_id IN (SELECT id FROM scope_ids) OR j.asset_id IN (SELECT id FROM scope_ids))"""
QUERIES['quality_observations'] = """SELECT o.id,o.artifact_id,o.job_id,o.media_id,o.method_artifact_id,o.criteria_artifact_id,o.result status,
 o.defect_code kind,o.observation title,o.position,o.effort_seconds,o.wait_seconds,o.cost_amount,o.cost_unit,o.cost_basis,j.shot_id,j.asset_id,j.purpose
 FROM quality_observations o JOIN generation_jobs j ON j.project_id=o.project_id AND j.id=o.job_id
 WHERE o.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR j.shot_id IN (SELECT id FROM scope_ids) OR j.asset_id IN (SELECT id FROM scope_ids))"""
QUERIES['method_evaluations'] = """SELECT e.id,e.artifact_id,e.method_artifact_id,e.trial_run_id,e.baseline_media_id,e.output_media_id media_id,e.criteria_artifact_id,
 e.result status,e.environment_sha256,'method_evaluation' kind,a.artifact_key title
 FROM method_evaluations e JOIN artifact_versions a ON a.project_id=e.project_id AND a.id=e.method_artifact_id
 WHERE e.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR e.artifact_id IN (SELECT id FROM scoped_versions))"""
QUERIES['script_status'] = """SELECT d.scope_key id,d.scope_key title,'script_draft' kind,
 CASE WHEN d.submitted_artifact_id IS NULL THEN 'editing'
      WHEN cur.artifact_id IS NOT NULL THEN 'approved'
      WHEN (SELECT x.outcome FROM artifact_decisions x WHERE x.project_id=d.project_id AND x.artifact_id=d.submitted_artifact_id
            ORDER BY x.decision_sequence DESC LIMIT 1)='reject' THEN 'rejected'
      ELSE 'pending_confirmation' END status,
 d.draft_revision,d.updated_at,d.updated_by,d.base_artifact_id,d.submitted_artifact_id,
 (SELECT count(*) FROM script_notes n WHERE n.project_id=d.project_id) note_count
 FROM script_drafts d LEFT JOIN current_artifact_versions cur ON cur.project_id=d.project_id AND cur.artifact_id=d.submitted_artifact_id
 WHERE d.project_id=:p"""

QUERIES['cue_timeline_items'] = """SELECT r.id,r.cue_id,r.item_id,t.timeline_id,t.track_key,t.offset_frame,t.duration_frames,t.shot_id,v.fps_num,v.fps_den,
 t.track_key || ' #' || t.ordinal title,'cue_timeline_items' kind FROM cue_timeline_items r JOIN timeline_items t ON t.project_id=r.project_id AND t.id=r.item_id
 JOIN timeline_versions v ON v.project_id=t.project_id AND v.id=t.timeline_id WHERE r.project_id=:p AND r.cue_id IN (SELECT id FROM scoped_cues)"""
QUERIES['timeline_media'] = """SELECT m.id,m.media_id,m.item_id,m.binding_decision_id,m.blob_id,m.blob_sha256,m.role purpose,m.source_in_frame,m.source_out_frame,
 t.timeline_id,t.track_key,t.offset_frame,t.duration_frames,t.shot_id,t.envelope,v.fps_num,v.fps_den,i.name title,i.modality kind
 FROM timeline_item_media m JOIN timeline_items t ON t.project_id=m.project_id AND t.id=m.item_id
 JOIN timeline_versions v ON v.project_id=t.project_id AND v.id=t.timeline_id JOIN media_items i ON i.project_id=m.project_id AND i.id=m.media_id
 WHERE m.project_id=:p AND (CAST(:scope AS uuid) IS NULL OR t.shot_id IN (SELECT id FROM scope_ids) OR EXISTS(SELECT 1 FROM cue_timeline_items c WHERE c.project_id=:p AND c.item_id=t.id AND c.cue_id IN (SELECT id FROM scoped_cues)))"""

OVERVIEW = ('script_status','children','shots','lines','assets','instances','cues','performances','bindings','materials','versions','jobs')


def query_workbench(store,project_id,*,object_id=None,section='overview',query='',limit=24,offset=0,revision=None,
                    kind=None,status=None,purpose=None,version=None,association=None,entity_id=None):
    p=checked_id(project_id)
    params=dict(p=p,scope=checked_id(object_id) if object_id else None,query='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%',
        kind=kind,status=status,purpose=purpose,version=version,association=association,entity=entity_id)
    names=OVERVIEW if section=='overview' else (section,)
    with store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn,conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        project=store._project(conn,p)
        if revision is not None and revision!=project['revision']:
            raise Conflict('工作台快照已变化，请刷新','workbench_revision_changed')
        scope=store._one(conn,S_OBJECTS(),p,object_id) if object_id else None
        ancestors=[dict(r) for r in conn.execute(text(CTE+'''SELECT o.id,o.kind,o.title,o.display_code FROM creative_objects o
          WHERE o.project_id=:p AND o.id IN (SELECT parent_id FROM ancestors) ORDER BY CASE o.kind WHEN 'work' THEN 0 WHEN 'episode' THEN 1 WHEN 'scene' THEN 2 ELSE 3 END'''),params).mappings()]
        sections,summary={},{}
        # Project landing is an aggregate navigation view, not a full inventory scan.
        # Concrete collection pages are still available with all filters and stable pagination.
        if section=='overview' and not object_id and not any((query,kind,status,purpose,version,association,entity_id)):
            tables={'shots':'shots','lines':'script_lines','assets':'asset_identities','instances':'asset_use_instances',
                'cues':'sound_cues','performances':'execution_instances','bindings':'binding_slots','materials':'media_items',
                'versions':'artifact_versions','jobs':'generation_jobs'}
            counts=conn.execute(text(' UNION ALL '.join("SELECT '%s' section,count(*) total FROM %s WHERE project_id=:p"%(key,table) for key,table in tables.items())),params).mappings()
            for row in counts:
                total=row['total'];name=row['section'];summary[name]=total
                sections[name]=dict(items=[],scope_total=total,filtered_total=total,total=total,loaded_count=0,
                    truncated=total>0,next_offset=0 if total else None,load_on_demand=True)
            names=('children',)
        for name in names:
            if name=='materials':
                sections[name]=material_page(conn,store,p,params,min(limit,6) if section=='overview' else limit,offset)
                summary[name]=sections[name]['scope_total']
                continue
            sql=QUERIES[name]
            envelope=CTE+', rows AS NOT MATERIALIZED ('+sql+'''), raw AS NOT MATERIALIZED (SELECT to_jsonb(r) body FROM rows r), data AS NOT MATERIALIZED (
              SELECT raw.body || CASE WHEN raw.body ? 'artifact_id' THEN jsonb_build_object(
                'version_status',CASE d.outcome WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected' WHEN 'revoke' THEN 'revoked' ELSE 'draft' END,
                'current',cur.artifact_id IS NOT NULL,'owner_version',a.version,'owner_sha256',a.sha256)
                ELSE '{}'::jsonb END body FROM raw
              LEFT JOIN artifact_versions a ON a.project_id=:p AND a.id=CAST(raw.body->>'artifact_id' AS uuid)
              LEFT JOIN current_artifact_versions cur ON cur.project_id=a.project_id AND cur.artifact_id=a.id
              LEFT JOIN LATERAL(SELECT outcome FROM artifact_decisions d WHERE d.project_id=a.project_id AND d.artifact_id=a.id ORDER BY decision_sequence DESC LIMIT 1) d ON true) '''
            condition="""WHERE (:query='%%' OR body->>'title' ILIKE :query OR body->>'display_code' ILIKE :query OR body->>'text' ILIKE :query OR body->>'search_text' ILIKE :query OR body->>'id' ILIKE :query)
              AND (CAST(:kind AS text) IS NULL OR body->>'kind'=:kind) AND (CAST(:status AS text) IS NULL OR body->>'status'=:status OR body->>'version_status'=:status OR (:status='current' AND body->>'current'='true'))
              AND (CAST(:purpose AS text) IS NULL OR body->>'purpose'=:purpose) AND (CAST(:version AS text) IS NULL OR body->>'version'=:version OR body->>'artifact_id'=:version)
              AND (CAST(:association AS text) IS NULL OR (:association='unassociated' AND body->>'status'='unassociated') OR (:association='associated' AND body->>'status'<>'unassociated'))
              AND (CAST(:entity AS text) IS NULL OR body->>'id'=:entity OR body->>'cue_id'=:entity OR body->>'execution_id'=:entity OR body->>'line_id'=:entity OR body->>'asset_id'=:entity OR body->>'object_id'=:entity OR body->>'slot_id'=:entity OR body->>'media_id'=:entity OR body->>'subject_id'=:entity OR body->>'item_id'=:entity OR body->>'timeline_id'=:entity)"""
            count=conn.execute(text(envelope+'SELECT (SELECT count(*) FROM data) scope_total,count(*) filtered_total FROM data '+condition),params).mappings().one()
            take=min(limit,6) if section=='overview' else limit
            page=[r[0] for r in conn.execute(text(envelope+"SELECT body - 'search_text' FROM data "+condition+" ORDER BY CASE WHEN body->>'kind'='work' THEN -1 WHEN body->>'current'='true' OR body->>'status'='selected' THEN 0 ELSE 1 END,coalesce((body->>'ordinal')::int,0),body->>'title',body->>'id' LIMIT :limit OFFSET :offset"),dict(params,limit=take,offset=offset))]
            if name=='lines' and page:
                enrich_line_coverage(conn,p,page)
            if name in ('materials','candidates') and page:
                media_ids=[row['media_id'] for row in page]
                previews=store._renditions(conn,p,media_ids)
                for row in page:
                    row['renditions']=[{k:v[k] for k in ('id','purpose','sha256','mime_type','size_bytes')} for v in previews if str(v['media_id'])==str(row['media_id'])]
                    row['modality']=row['kind']
            loaded=len(page); total=count['filtered_total']; more=offset+loaded<total
            sections[name]=dict(items=page,**count,total=total,loaded_count=loaded,truncated=more,next_offset=offset+loaded if more else None)
            summary[name]=count['scope_total']
        gaps=[]
        if section=='overview':
            for name,message in [('lines','未登记可查询的固定剧本行/镜头覆盖'),('instances','未登记资产使用实例；不能据此推断场镜无人或无道具'),('cues','未登记声音Cue；不能视为有意静默')]:
                if not summary[name]:gaps.append(dict(code='missing_'+name,message=message))
        return clean(dict(project_id=p,revision=project['revision'],scope=scope,ancestors=ancestors,summary=summary,sections=sections,gaps=gaps,
            warnings=['关系来自登记的固定版本；历史与草稿不等于当前采用。缺少关系不证明不受影响。'],read_only=True,snapshot='repeatable_read'))


def S_OBJECTS():
    from .schema import creative_objects
    return creative_objects


def material_page(conn,store,p,params,limit,offset):
    """Filter/count on base columns; compute costly usage summaries only for page IDs."""
    base=QUERIES['materials']
    where=base[base.index(' WHERE m.project_id'):]
    source=' FROM media_items m JOIN media_blobs b ON b.id=m.blob_id'+where
    selected="EXISTS(SELECT 1 FROM binding_candidates c JOIN current_bindings cb ON cb.project_id=c.project_id AND cb.candidate_id=c.id WHERE c.project_id=:p AND c.media_id=m.id)"
    associated="EXISTS(SELECT 1 FROM binding_candidates c WHERE c.project_id=:p AND c.media_id=m.id)"
    filters=""" AND (:query='%%' OR m.name ILIKE :query OR m.id::text ILIKE :query)
      AND (CAST(:kind AS text) IS NULL OR m.modality=:kind)
      AND (CAST(:entity AS text) IS NULL OR m.id::text=:entity OR EXISTS(SELECT 1 FROM binding_candidates c JOIN binding_slots s ON s.project_id=c.project_id AND s.id=c.slot_id WHERE c.project_id=:p AND c.media_id=m.id AND (s.id::text=:entity OR s.target_object_id::text=:entity OR s.identity_asset_id::text=:entity)))
      AND (CAST(:purpose AS text) IS NULL OR EXISTS(SELECT 1 FROM binding_candidates c JOIN binding_slots s ON s.project_id=c.project_id AND s.id=c.slot_id WHERE c.project_id=:p AND c.media_id=m.id AND s.role=:purpose))
      AND (CAST(:version AS text) IS NULL OR EXISTS(SELECT 1 FROM binding_candidates c WHERE c.project_id=:p AND c.media_id=m.id AND c.spec_version_id::text=:version))"""
    if params['status']:
        filters+=' AND '+({'selected':selected,'candidate':associated+' AND NOT '+selected,'unassociated':'NOT '+associated}.get(params['status'],'false'))
    if params['association']:
        filters+=' AND '+('NOT ' if params['association']=='unassociated' else '')+associated
    total=conn.execute(text(CTE+'SELECT count(*)'+source),params).scalar_one()
    filtered=conn.execute(text(CTE+'SELECT count(*)'+source+filters),params).scalar_one()
    ids=[str(r[0]) for r in conn.execute(text(CTE+'SELECT m.id'+source+filters+' ORDER BY m.name,m.id LIMIT :limit OFFSET :offset'),dict(params,limit=limit,offset=offset))]
    page=[]
    if ids:
        from sqlalchemy import bindparam
        stmt=text(CTE+base+' AND m.id IN :ids ORDER BY m.name,m.id').bindparams(bindparam('ids',expanding=True))
        page=[dict(r) for r in conn.execute(stmt,dict(params,ids=ids)).mappings()]
        previews=store._renditions(conn,p,ids)
        for row in page:
            row['modality']=row['kind']
            row['renditions']=[{k:v[k] for k in ('id','purpose','sha256','mime_type','size_bytes')} for v in previews if str(v['media_id'])==str(row['media_id'])]
    more=offset+len(page)<filtered
    return dict(items=page,scope_total=total,filtered_total=filtered,total=filtered,loaded_count=len(page),truncated=more,next_offset=offset+len(page) if more else None)


def enrich_line_coverage(conn,p,page):
    """Explicit character gaps against current fixed coverage; bounded evidence per line."""
    from sqlalchemy import bindparam
    ids=[row['id'] for row in page]
    stmt=text("""SELECT * FROM (SELECT c.line_id,c.shot_id,c.coverage_version_id,c.start_char,c.end_char,
       count(*) OVER(PARTITION BY c.line_id) total,
       row_number() OVER(PARTITION BY c.line_id ORDER BY c.start_char,c.end_char,c.id) n
       FROM shot_line_coverage c JOIN current_artifact_versions a ON a.project_id=c.project_id AND a.artifact_id=c.coverage_version_id
       WHERE c.project_id=:p AND c.line_id IN :ids) rows WHERE n<=32""").bindparams(bindparam('ids',expanding=True))
    grouped={}
    for span in conn.execute(stmt,dict(p=p,ids=ids)).mappings():grouped.setdefault(str(span['line_id']),[]).append(dict(span))
    stmt=text("""SELECT * FROM (SELECT d.line_id,d.artifact_id,d.disposition,d.reason,
       row_number() OVER(PARTITION BY d.line_id ORDER BY d.id) n FROM script_line_dispositions d
       JOIN current_artifact_versions a ON a.project_id=d.project_id AND a.artifact_id=d.artifact_id
       WHERE d.project_id=:p AND d.line_id IN :ids) rows WHERE n<=4""").bindparams(bindparam('ids',expanding=True))
    dispositions={}
    for row in conn.execute(stmt,dict(p=p,ids=ids)).mappings():dispositions.setdefault(str(row['line_id']),[]).append(dict(row))
    for row in page:
        spans=grouped.get(row['id'],[]);total=spans[0]['total'] if spans else 0;clipped=total>len(spans)
        end=0;missing=[]
        if not clipped:
            for span in spans:
                if span['start_char']>end:missing.append([end,span['start_char']])
                end=max(end,span['end_char'])
            if end<row['text_length']:missing.append([end,row['text_length']])
        row.update(current_coverage_count=total,coverage_truncated=clipped,
            uncovered_ranges=None if clipped else missing,approved_dispositions=dispositions.get(row['id'],[]),
            current_coverage=[{k:span[k] for k in ('shot_id','coverage_version_id','start_char','end_char')} for span in spans])
