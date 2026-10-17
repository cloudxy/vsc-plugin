"""Large synthetic read workload, restricted to random test schemas.

Bulk SQL bypasses authoring APIs for speed; these are synthetic query fixtures,
not imported project evidence. API/approval behavior is tested separately.
"""
import uuid,hashlib
from sqlalchemy import text


def scale_id(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,'vsc-scale:'+value))


def seed_workbench_scale(engine):
    uid=scale_id
    p=uid('project')
    with engine.begin() as c:
      schema=c.execute(text('SELECT current_schema()')).scalar_one()
      if not schema.startswith('vsc_test_'):raise ValueError('scale fixture requires isolated vsc_test_ schema')
      c.execute(text("SET statement_timeout='240s'"))
      c.execute(text("INSERT INTO projects(id,name,profile,storage_policy,profile_snapshot) VALUES(:p,'Synthetic 60 episode scale','vsc.synthetic','postgres-series-v1','{}')"),{'p':p})
      def objects(kind,n,parent_kind=None,per_parent=None):
       rows=[dict(p=p,id=uid(kind+str(i)),kind=kind,code=kind+str(i),title='Synthetic '+kind+' '+str(i),ordinal=(i%per_parent if parent_kind else i),parent=uid(parent_kind+str(i//per_parent)) if parent_kind else None) for i in range(n)]
       c.execute(text('INSERT INTO creative_objects(project_id,id,kind,display_code,title) VALUES(:p,:id,:kind,:code,:title)'),rows)
       table={'work':'works','episode':'episodes','scene':'scenes','sequence':'sequences','shot':'shots'}[kind]
       c.execute(text('INSERT INTO '+table+'(project_id,id,ordinal'+(',parent_id' if parent_kind else '')+') VALUES(:p,:id,:ordinal'+(',:parent' if parent_kind else '')+')'),rows)
      objects('work',1);objects('episode',60,'work',60);objects('scene',1200,'episode',20);objects('sequence',1200,'scene',1);objects('shot',12000,'sequence',10)
      c.execute(text("INSERT INTO media_blobs(id,sha256,size_bytes,mime_type,duration_ms) SELECT md5('blob'||g)::uuid,encode(sha256(convert_to('synthetic'||g,'UTF8')),'hex'),1024,'video/mp4',5000 FROM generate_series(0,49999) g"))
      c.execute(text("INSERT INTO media_items(project_id,id,blob_id,name,modality,registered_by) SELECT :p,md5('media'||g)::uuid,md5('blob'||g)::uuid,'Synthetic clip '||g,'video','synthetic-fixture' FROM generate_series(0,49999) g"),{'p':p})
      slots=[dict(p=p,id=uid('slot'+str(i)),shot=uid('shot'+str(i))) for i in range(12000)]
      c.execute(text("INSERT INTO binding_slots(project_id,id,target_object_id,role,slot_key) VALUES(:p,:id,:shot,'video_take','main')"),slots)
      # 20 independent candidates per shot: 240,000 typed relations, reused media across scopes.
      c.execute(text("INSERT INTO binding_candidates(project_id,id,slot_id,media_id,proposer) SELECT :p,md5('candidate'||s.id||n)::uuid,s.id,md5('media'||((row_number() over(order by s.id,n)-1)%50000))::uuid,'synthetic' FROM binding_slots s CROSS JOIN generate_series(1,20) n WHERE s.project_id=:p"),{'p':p})
      raw=b'{"synthetic":true}'
      c.execute(text("INSERT INTO artifact_versions(project_id,id,artifact_key,version,artifact_type,stage,document,mime_type,sha256,project_wide,parser_version) VALUES(:p,:id,'synthetic-script',1,'screenplay','script',:doc,'application/json',:sha,true,'synthetic-v1')"),dict(p=p,id=uid('script'),doc=raw,sha=hashlib.sha256(raw).hexdigest()))
      lines=[dict(p=p,id=uid('line'+str(i)),script=uid('script'),scene=uid('scene'+str(i//10)),key='L'+str(i),n=i,sha=hashlib.sha256(raw).hexdigest()) for i in range(12000)]
      c.execute(text("INSERT INTO script_lines(project_id,id,script_version_id,scene_id,line_key,line_kind,text,ordinal,source_sha256) VALUES(:p,:id,:script,:scene,:key,'action','Synthetic action',:n,:sha)"),lines)
      c.execute(text("INSERT INTO shot_line_coverage(project_id,id,coverage_version_id,shot_id,line_id,start_char,end_char) VALUES(:p,:id,:script,:shot,:line,0,10)"),[dict(p=p,id=uid('coverage'+str(i)),script=uid('script'),shot=uid('shot'+str(i)),line=uid('line'+str(i))) for i in range(12000)])
      c.execute(text("INSERT INTO sound_cues(project_id,id,artifact_id,scope_object_id,cue_key,label,cue_kind,parameters) VALUES(:p,:id,:art,:scope,:key,:key,'ambience','{}')"),[dict(p=p,id=uid('cue'+str(i)),art=uid('script'),scope=uid('scene'+str(i)),key='AMBIENCE'+str(i)) for i in range(1200)])
      c.execute(text("INSERT INTO cue_shots(project_id,id,cue_id,shot_id) VALUES(:p,:id,:cue,:shot)"),[dict(p=p,id=uid('cq'+str(i)),cue=uid('cue'+str(i//10)),shot=uid('shot'+str(i))) for i in range(12000)])
      c.execute(text("INSERT INTO creative_objects(project_id,id,kind,display_code,title) VALUES(:p,:id,'asset',:code,:code)"),[dict(p=p,id=uid('asset'+str(i)),code='Shared asset '+str(i)) for i in range(100)])
      c.execute(text("INSERT INTO asset_identities(project_id,id,asset_kind) VALUES(:p,:id,'prop')"),[dict(p=p,id=uid('asset'+str(i))) for i in range(100)])
      c.execute(text("INSERT INTO asset_use_instances(project_id,id,artifact_id,asset_id,scene_id,shot_id,instance_key,label,state) VALUES(:p,:id,:art,:asset,:scene,:shot,:key,:key,'{}')"),[dict(p=p,id=uid('instance'+str(i)),art=uid('script'),asset=uid('asset'+str(i%100)),scene=uid('scene'+str(i//10)),shot=uid('shot'+str(i)),key='Use '+str(i)) for i in range(12000)])
      c.execute(text("INSERT INTO artifact_versions(project_id,id,artifact_key,version,artifact_type,stage,document,mime_type,sha256,project_wide,parser_version) VALUES(:p,:id,'synthetic-script',2,'screenplay','script',:doc,'application/json',:sha,true,'synthetic-v1')"),dict(p=p,id=uid('script2'),doc=raw,sha=hashlib.sha256(raw).hexdigest()))
      c.execute(text('ANALYZE'))
    return p
