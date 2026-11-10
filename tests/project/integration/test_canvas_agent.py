"""Fixed Agent roles/plans consume original canvas, artifact and run commands."""
import importlib.util
import os
import unittest
import uuid
from copy import deepcopy
from support.fixtures.resource_store import ResourceStoreFixture

HAS_DB=all(importlib.util.find_spec(n) for n in ("sqlalchemy","psycopg","alembic"))


class PlanningFixture:
    name="synthetic-plan-only"
    def __init__(self,plan):self.plan=plan;self.calls=0;self.packets=[]
    def available(self):return True
    def generate(self,packet,turn,skill):
        self.calls+=1;self.packets.append(packet)
        return self.plan(packet,turn,skill) if callable(self.plan) else deepcopy(self.plan)


def plan(kind="append_text",text="合成可编辑文字",questions=None,source=""):
    return {"message":"合成工程操作计划","questions":questions or [],"action":{"kind":kind,"title":"建议节点","text":text,"source_node_id":source}}


@unittest.skipUnless(HAS_DB and os.environ.get("VSC_TEST_DATABASE_URL"),"requires configured isolated PostgreSQL")
class CanvasAgentTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.canvas=self.write("create_creative_canvas",{"title":"Agent工程画布","document":{"nodes":[{"id":"prompt","type":"text","text":"固定输入"}],"edges":[]}})
    def turn(self,**extra):
        current=self.service.get_creative_canvas(self.p,self.canvas["id"])
        payload=dict(canvas_id=self.canvas["id"],canvas_revision=current["canvas_revision"],message="合成规划请求",skill_id="vsc-script",node_ids=["prompt"],model_ids=[]);payload.update(extra)
        return self.write("create_canvas_agent_turn",payload)
    def execute(self,turn,proposal):
        self.service.canvas_agent_backend=PlanningFixture(proposal)
        result=self.service.execute_canvas_agent_turn(self.p,turn["id"]);self.rev=self.service.get_project(self.p)["revision"];return result
    def decide(self,turn,outcome="confirm",**kw):return self.write("decide_canvas_agent_turn",{"turn_id":turn["id"],"outcome":outcome,"reason":"合成工程明确决定"},**kw)

    def test_mv_skill_uses_installed_direction_materials_and_original_text_consumer(self):
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.production.canvas_agent import SKILLS
        catalog = SKILLS["ai-mv-production"]
        self.assertEqual(catalog["source_skill"], "vsc-direct")
        self.assertEqual(catalog["role"], "director")
        turn = self.turn(skill_id="ai-mv-production", message="根据已选音乐和歌词规划镜头节奏，先补问缺失信息。")
        ready = self.execute(turn, plan(text="合成 MV 分镜计划：0–4 秒建立场景。"))
        self.assertEqual(ready["status"], "planned")
        self.assertEqual(self.service.canvas_agent_backend.packets[0]["role"]["id"], "director")
        result = self.decide(turn)
        self.assertFalse(result["provider_submitted"])
        document = self.service.get_creative_canvas(self.p, self.canvas["id"])["document"]
        self.assertEqual(document["nodes"][-1]["text"], "合成 MV 分镜计划：0–4 秒建立场景。")
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(select(func.count()).select_from(S.generation_jobs)).scalar_one(), 0)

    def test_clarify_reply_reject_confirm_original_role_returns_and_fixed_nodes(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.project.role_runtime import validate_packet
        first=self.turn();question=self.execute(first,plan("none","",["请明确需要的语气。"]));self.assertEqual(question["status"],"needs_input")
        second=self.turn(session_id=first["session_id"],parent_turn_id=first["id"])
        ready=self.execute(second,plan());self.assertEqual(ready["status"],"planned")
        packet=self.service.canvas_agent_backend.packets[0];self.assertFalse(validate_packet(packet));self.assertEqual(packet["role"]["id"],"screenwriter")
        self.assertEqual(ready["previous_plan"]["questions"],["请明确需要的语气。"])
        self.decide(second,"reject");self.assertEqual(len(self.service.get_creative_canvas(self.p,self.canvas["id"])["document"]["nodes"]),1)
        third=self.turn(session_id=first["session_id"],parent_turn_id=second["id"]);self.execute(third,plan(text="确认后保存的文字"))
        revision=self.rev;confirmed=self.decide(third,idempotency_key="confirm-once")
        replay=self.service.decide_canvas_agent_turn(self.p,{"turn_id":third["id"],"outcome":"confirm","reason":"合成工程明确决定"},actor="test-human",expected_revision=revision,idempotency_key="confirm-once")
        self.assertEqual(replay,confirmed);self.assertFalse(confirmed["provider_submitted"])
        document=self.service.get_creative_canvas(self.p,self.canvas["id"])["document"]
        self.assertEqual(document["nodes"][-1]["text"],"确认后保存的文字")
        with self.engine.connect() as conn:
            for table in (S.dispatch_consumptions,S.dispatch_returns):self.assertEqual(conn.execute(select(func.count()).select_from(table).where(table.c.project_id==self.p)).scalar_one(),3)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p)).scalar_one(),0)

    def test_unknown_does_not_retry_stop_discards_late_result_and_stale_plan_preserves_draft(self):
        from vsc.assets.resource_service import ResourceError,Conflict
        def unknown(*args):raise ResourceError("synthetic timeout","canvas_agent_submission_unknown")
        turn=self.turn();self.execute(turn,unknown);backend=self.service.canvas_agent_backend
        self.assertEqual(self.service.execute_canvas_agent_turn(self.p,turn["id"])["status"],"submission_unknown");self.assertEqual(backend.calls,1)
        self.decide(turn,"stop")
        late=self.turn()
        def stopped(*args):
            self.decide(late,"stop");return plan(text="迟到结果不能应用")
        self.assertEqual(self.execute(late,stopped)["status"],"stopped")
        self.assertEqual(len(self.service.get_creative_canvas(self.p,self.canvas["id"])["document"]["nodes"]),1)
        ready=self.turn();self.execute(ready,plan());current=self.service.get_creative_canvas(self.p,self.canvas["id"])
        document=current["document"];document["nodes"][0]["text"]="他人修订"
        self.write("save_creative_canvas",{"canvas_id":self.canvas["id"],"canvas_revision":current["canvas_revision"],"title":"修订","document":document})
        with self.assertRaises(Conflict):self.decide(ready)
        self.assertEqual(self.service.get_creative_canvas(self.p,self.canvas["id"])["document"]["nodes"][0]["text"],"他人修订")

    def test_auto_text_media_reference_and_sealed_input_validation(self):
        from sqlalchemy import insert,select
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        turn=self.turn(mode="auto_drafts");self.assertEqual(self.execute(turn,plan())["status"],"applied")
        media=self.media();canvas=self.service.get_creative_canvas(self.p,self.canvas["id"]);doc=canvas["document"];doc["nodes"].append({"id":"image","type":"image","media_id":media})
        self.write("save_creative_canvas",{"canvas_id":self.canvas["id"],"canvas_revision":canvas["canvas_revision"],"document":doc})
        current=self.service.get_creative_canvas(self.p,self.canvas["id"])
        ref=self.write("create_canvas_agent_turn",{"canvas_id":self.canvas["id"],"canvas_revision":current["canvas_revision"],"message":"复用这张已选图片","skill_id":"vsc-assets","node_ids":["image"]})
        self.execute(ref,plan("reuse_media","",source="image"));done=self.decide(ref);self.assertTrue(done["output_version_id"])
        self.assertEqual(self.service.get_creative_canvas(self.p,self.canvas["id"])["document"]["nodes"][-1]["media_id"],media)
        with self.engine.connect() as conn:row=dict(conn.execute(select(S.canvas_agent_refs).where(S.canvas_agent_refs.c.turn_id==ref["id"])).mappings().one())
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(insert(S.canvas_agent_refs).values(dict(row,node_key="prompt")))
        with self.assertRaises(ResourceError):self.turn(node_ids=["missing"])

    def test_video_plan_creates_original_pending_run_without_generation_or_approval(self):
        from sqlalchemy import insert,select,func
        from vsc.adapters.persistence.postgres import schema as S
        objects=self.hierarchy();self.artifact(objects=[objects["shot"]]);self.artifact("state","scene-state",[objects["scene"]],{"state_versions":[{"scene_id":objects["scene"]}]})
        image=self.media();self.select(self.candidate(objects["shot"],image))
        provider,model="agent_"+uuid.uuid4().hex,str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider,name="synthetic nonexecuting",modality="video",base_url="https://example.invalid",auth_ref="none",enabled=True,rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model,provider_id=provider,model_key="synthetic-agent",modality="video",model_version="1",capabilities={"purposes":["video_clip"],"first_frame":True},default_params={},cost_rule={},enabled=True))
        doc={"nodes":[{"id":"prompt","type":"text","text":"固定输入"},{"id":"image","type":"image","media_id":image},{"id":"video","type":"video"}],"edges":[{"id":"p","source":"prompt","target":"video","port":"prompt"},{"id":"i","source":"image","target":"video","port":"first_frame"}]}
        self.write("save_creative_canvas",{"canvas_id":self.canvas["id"],"canvas_revision":1,"document":doc})
        self.write("configure_commerce_plan",{"base_version_id":None,"metering_enabled":True,"document":dict(plan_key="synthetic",title="隔离工程计价",amount_minor=100,currency="TST",credits=100,bucket_kind="credit",validity_days=2,checkout_minutes=10,purposes=["video_clip"],rates=[dict(model_id=model,unit="video_seconds",credits_per_unit=10)],refund_policy="unused_order_only",max_concurrent_jobs=1,invoice_enabled=False,seat_limit=3,watermark_required=False,renewal_policy="manual_from_payment")})
        authorization={"mode":"new_batch","reason":"隔离工程批次"}
        turn=self.turn(skill_id="vsc-direct",model_ids=[model],target_node_id="video",shot_id=objects["shot"],execution_settings={"commerce_account_actor":None,"duration_ms":5000,"execution_policy":{"version":"bounded-v1","first_draft_due_at":"2099-01-01T00:00:00Z","stop_submitting_at":"2099-01-01T01:00:00Z","max_attempts_per_purpose":3,"max_repair_rounds":1,"authorization":authorization}})
        self.execute(turn,plan("prepare_video_run",""))
        from unittest.mock import patch
        original=self.service.list_models('video');adapter=patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':[dict(m,adapter_available=True) for m in original]});adapter.start();self.addCleanup(adapter.stop)
        preview=self.service.preview_canvas_agent_run(self.p,turn["id"])
        self.assertTrue(preview["commerce_quote"]["enabled"])
        self.assertIsNone(preview["commerce_quote"]["commerce_charge"]["account_actor"])
        self.assertEqual(sum(preview["commerce_quote"]["commerce_charge"]["max_credits_by_operation"].values()),50)
        self.assertEqual(preview["artifact"]["document"]["execution_policy"]["authorization"],authorization)
        done=self.decide(turn)
        self.assertTrue(done["needs_approval"]);self.assertFalse(done["provider_submitted"])
        artifact=self.service.get_artifact_version(self.p,done["run_artifact_id"])
        self.assertEqual(artifact["artifact_type"],"production-run")
        import json
        document=json.loads(artifact["document"])
        self.assertEqual(document["execution_policy"]["authorization"],authorization)
        self.assertEqual(document["commerce_charge"],preview["commerce_quote"]["commerce_charge"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p)).scalar_one(),0)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.artifact_decisions).where(S.artifact_decisions.c.project_id==self.p,S.artifact_decisions.c.artifact_id==done["run_artifact_id"])).scalar_one(),0)

    def test_fixed_template_favorite_copy_history_and_cross_project_media_gate(self):
        from vsc.assets.resource_service import ResourceError
        template=self.write("publish_canvas_template",{"canvas_id":self.canvas["id"],"canvas_revision":1,"title":"固定文字模板"})
        self.write("favorite_canvas_template",{"template_id":template["id"],"active":True})
        self.assertTrue(self.service.list_canvas_templates(self.p,"test-human")["items"][0]["favorite"])
        current=self.service.get_creative_canvas(self.p,self.canvas["id"]);doc=current["document"];doc["nodes"][0]["text"]="后续修改"
        self.write("save_creative_canvas",{"canvas_id":self.canvas["id"],"canvas_revision":1,"document":doc})
        copied=self.write("copy_canvas_template",{"template_id":template["id"]})
        copy=self.service.get_creative_canvas(self.p,copied["id"]);self.assertEqual(copy["document"]["nodes"][0]["text"],"固定输入");self.assertEqual(copy["runs"],[])
        self.assertTrue(all(n["job_id"] is None for n in copy["document"]["nodes"]))
        media=self.media();doc["nodes"].append({"id":"image","type":"image","media_id":media})
        self.write("save_creative_canvas",{"canvas_id":self.canvas["id"],"canvas_revision":2,"document":doc})
        mixed=self.write("publish_canvas_template",{"canvas_id":self.canvas["id"],"canvas_revision":3,"title":"含素材模板"})
        other=self.service.create_project({"name":"copy target","profile_snapshot":{"profile_id":"vsc.synthetic","version":"1","stages":[]}},actor="test-human")
        with self.assertRaises(ResourceError):self.service.copy_canvas_template(other["id"],{"source_project_id":self.p,"template_id":mixed["id"]},expected_revision=0,idempotency_key="missing-media-map",actor="test-human")
        result=self.service.copy_canvas_template(other["id"],{"source_project_id":self.p,"template_id":template["id"]},expected_revision=0,idempotency_key="pure-text-copy",actor="test-human")
        self.assertFalse(result["provider_submitted"])

@unittest.skipUnless(HAS_DB and os.environ.get('VSC_TEST_DATABASE_URL'),'requires isolated PostgreSQL')
class CanvasMultiActionTests(ResourceStoreFixture,unittest.TestCase):
    turn=CanvasAgentTests.turn
    execute=CanvasAgentTests.execute
    decide=CanvasAgentTests.decide
    def setUp(self):
        super().setUp();self.canvas=self.write('create_creative_canvas',{'title':'多操作合成画布','document':{'nodes':[{'id':'prompt','type':'text','text':'固定输入'}],'edges':[]}})
    def test_manual_each_operation_and_auto_text_do_not_create_media_jobs(self):
        turn=self.turn();multi=dict(message='两项顺序操作',questions=[],actions=[plan(text='第一项')['action'],plan(text='第二项')['action']]);self.execute(turn,multi)
        first=self.decide(turn);self.assertEqual(first['status'],'planned');self.assertEqual(len(self.service.get_creative_canvas(self.p,self.canvas['id'])['document']['nodes']),2)
        original=self.service.get_canvas_agent_turn(self.p,turn['id']);self.assertEqual(len(original['action_results']),1)
        second=self.decide(turn);self.assertEqual(second['status'],'applied');self.assertEqual(len(self.service.get_creative_canvas(self.p,self.canvas['id'])['document']['nodes']),3)
        auto=self.turn(mode='auto_drafts');result=self.execute(auto,multi);self.assertEqual(result['status'],'applied');self.assertEqual(len(result['action_results']),2);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)


@unittest.skipUnless(HAS_DB and os.environ.get('VSC_TEST_DATABASE_URL'),'requires isolated PostgreSQL')
class CanvasRoutingAutoTests(ResourceStoreFixture,unittest.TestCase):
    turn=CanvasAgentTests.turn
    execute=CanvasAgentTests.execute
    decide=CanvasAgentTests.decide

    def setUp(self):
        from unittest.mock import patch
        super().setUp()
        self.canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'prompt','type':'text','text':'合成固定输入'}],'edges':[]}})
        self.models=[]
        for index in range(3):
            provider='synthetic_route_'+uuid.uuid4().hex
            self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
            model=self.service.register_model(dict(provider_id=provider,model_key='route-'+str(index),model_version='offline',modality='image',capabilities={'purposes':['first_frame'],'reference_media':index>0}),actor='test-admin')
            self.models.append(dict(model,enabled=True,adapter_available=True))
        fixture=patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':self.models});fixture.start();self.addCleanup(fixture.stop)
        self.policy=dict(version='bounded-v1',first_draft_due_at='2099-01-01T00:00:00Z',stop_submitting_at='2099-01-01T01:00:00Z',max_attempts_per_purpose=3,max_repair_rounds=1,authorization={'mode':'new_batch','reason':'合成隔离自动范围'})

    def proposal(self,source='',pairs=1):
        return dict(message='合成固定媒体计划',questions=[],actions=[action for _ in range(pairs) for action in [plan('create_image_node','合成构图',source=source)['action'],plan('prepare_run','')['action']]])

    def media_turn(self,automatic=False,source='',pairs=1,scope=None,**settings):
        if source:
            current=self.service.get_creative_canvas(self.p,self.canvas['id']);doc=current['document'];doc['nodes'].append({'id':source,'type':'image','media_id':self.media('合成固定参考')})
            self.write('save_creative_canvas',dict(canvas_id=self.canvas['id'],canvas_revision=current['canvas_revision'],document=doc))
        execution=dict(execution_policy=self.policy,**settings)
        if automatic:execution['auto_media']=scope or dict(max_jobs=1,max_images=1,max_video_ms=0,max_credits=0,stop_submitting_at=self.policy['stop_submitting_at'])
        turn=self.turn(skill_id='image-generation',model_ids=[m['id'] for m in self.models],node_ids=['prompt']+([source] if source else []),mode='auto_drafts' if automatic else 'manual',execution_settings=execution)
        return turn,self.execute(turn,self.proposal(source,pairs))

    def generate_manual(self,source='reference'):
        turn,_=self.media_turn(source=source);self.decide(turn)
        preview=self.service.preview_canvas_agent_run(self.p,turn['id']);self.assertTrue(preview['ready'],preview)
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
        result=self.write('decide_canvas_agent_turn',dict(turn_id=turn['id'],outcome='confirm',reason='合成明确报价确认',preview_sha256=preview['preview_sha256']))
        canvas=self.service.get_creative_canvas(self.p,self.canvas['id']);step=next(s for s in canvas['execution_steps'] if s['run_artifact_id']==result['run_artifact_id'])
        return turn,preview,step

    def test_capability_order_is_pinned_and_failed_working_fallback_creates_original_job(self):
        import json
        from vsc.assets.resource_service import Conflict,ResourceError
        turn,preview,step=self.generate_manual()
        original=[m['id'] for m in self.models];self.assertEqual(self.service.get_canvas_agent_turn(self.p,turn['id'])['model_ids'],original)
        self.assertEqual(preview['routing']['original_model_ids'],original);self.assertEqual(preview['routing']['model_ids'],original[1:])
        self.assertEqual(preview['routing']['candidates'][0]['code'],'model_capability_mismatch');self.assertIn('参考',preview['routing']['candidates'][0]['message'])
        self.assertEqual(step['model_ids'],original[1:]);self.assertEqual(self.service.get_generation_job(self.p,step['jobs'][0]['id'])['model_id'],original[1])
        run=json.loads(self.service.get_artifact_version(self.p,step['run_artifact_id'])['document']);self.assertEqual(run['canvas_model_routing']['sha256'],preview['routing']['sha256'])
        draft=json.loads(self.service.get_artifact_version(self.p,run['workbench_draft']['id'])['document']);draft['references']=[]
        forged=self.write('create_artifact',dict(artifact_key='synthetic-forged-canvas-source',artifact_type='classic-production-draft',document=draft,object_ids=[draft['shot_id']],dependency_ids=[preview['routing']['id']]))
        with self.assertRaises(ResourceError) as unbound:self.service.preview_canvas_work_generation(self.p,dict(draft_version_id=forged['id'],execution_policy=self.policy))
        self.assertEqual(unbound.exception.code,'canvas_input_missing')
        self.write('update_generation_job',dict(job_id=step['jobs'][0]['id'],status='failed',raw_response={'synthetic':'definite no-submit failure'}))
        fallback=self.service.preview_canvas_fallback(self.p,step['id']);self.assertTrue(fallback['ready'],fallback);self.assertEqual(fallback['model_ids'],original[2:])
        self.assertEqual(fallback['artifact']['document']['workbench_draft'],run['workbench_draft']);self.assertFalse(fallback['needs_approval'])
        made=self.write('propose_canvas_fallback',dict(step_id=step['id'],preview_sha256=fallback['preview_sha256']),idempotency_key='fixed-fallback')
        self.assertFalse(made['needs_approval']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],2)
        successor=next(s for s in self.service.get_creative_canvas(self.p,self.canvas['id'])['execution_steps'] if s['source_step_id']==step['id'])
        self.assertEqual(self.service.get_generation_job(self.p,successor['jobs'][0]['id'])['model_id'],original[2]);self.assertTrue(self.service.get_artifact_version(self.p,successor['run_artifact_id'])['approved'])
        with self.assertRaises(Conflict):self.write('propose_canvas_fallback',dict(step_id=step['id'],preview_sha256=fallback['preview_sha256']))
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],2)

    def test_unknown_keeps_original_model_and_task_without_successor(self):
        from vsc.assets.resource_service import ResourceError
        _,_,step=self.generate_manual();job=step['jobs'][0]['id']
        self.write('update_generation_job',dict(job_id=job,status='submission_unknown',raw_response={'synthetic':'response unavailable'}))
        with self.assertRaises(ResourceError) as caught:self.service.preview_canvas_fallback(self.p,step['id'])
        self.assertEqual(caught.exception.code,'canvas_fallback_not_terminal')
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1);self.assertEqual(self.service.get_generation_job(self.p,job)['model_id'],self.models[1]['id'])

    def test_explicit_auto_scope_counts_unknown_and_stops_before_next_quote(self):
        from sqlalchemy import select
        from unittest.mock import patch
        from vsc.adapters.persistence.postgres import schema as S
        original_preview=self.service.preview_canvas_agent_run
        def preview_with_unknown_original(project_id,turn_id):
            current=self.service.list_generation_jobs(self.p)['items']
            if current and current[0]['status']=='created':
                self.rev=self.service.get_project(self.p)['revision']
                self.write('update_generation_job',dict(job_id=current[0]['id'],status='submission_unknown',raw_response={'synthetic':'unknown before next quote'}))
            return original_preview(project_id,turn_id)
        with patch.object(self.service,'preview_canvas_agent_run',side_effect=preview_with_unknown_original):turn,result=self.media_turn(automatic=True,pairs=2)
        self.assertEqual(result['status'],'planned',result);self.assertEqual(len(result['action_results']),3,result)
        self.assertIn('任务数上限',result['error']);jobs=self.service.list_generation_jobs(self.p)['items'];self.assertEqual(len(jobs),1)
        with self.engine.connect() as conn:
            approval=conn.execute(select(S.artifact_decisions).where(S.artifact_decisions.c.project_id==self.p,S.artifact_decisions.c.artifact_id==jobs[0]['run_version_id'])).mappings().one()
            self.assertIn(turn['id'],approval['reason']);self.assertIn('有界自动媒体',approval['reason'])
        self.assertEqual(jobs[0]['status'],'submission_unknown')
        again=self.service.execute_canvas_agent_turn(self.p,turn['id']);self.rev=self.service.get_project(self.p)['revision']
        self.assertEqual(again['error'],result['error']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)
        self.decide(turn,'stop');self.assertEqual(self.service.execute_canvas_agent_turn(self.p,turn['id'])['status'],'stopped');self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)

    def test_commercial_quote_and_expired_scope_create_no_tasks(self):
        from vsc.assets.resource_service import ResourceError
        self.write('configure_commerce_plan',{'base_version_id':None,'metering_enabled':True,'document':dict(plan_key='synthetic',title='隔离工程计价',amount_minor=100,currency='TST',credits=100,bucket_kind='credit',validity_days=2,checkout_minutes=10,purposes=['first_frame'],rates=[dict(model_id=m['id'],unit='images',credits_per_unit=10) for m in self.models],refund_policy='unused_order_only',max_concurrent_jobs=1,invoice_enabled=False,seat_limit=3,watermark_required=False,renewal_policy='manual_from_payment')})
        _,result=self.media_turn(automatic=True,commerce_account_actor=None)
        self.assertEqual(len(result['action_results']),1,result);self.assertIn('商业额度上限',result['error']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
        scope=dict(max_jobs=1,max_images=1,max_video_ms=0,max_credits=0,stop_submitting_at='2000-01-01T00:00:00Z')
        with self.assertRaises(ResourceError) as caught:self.media_turn(automatic=True,scope=scope)
        self.assertEqual(caught.exception.code,'canvas_auto_expired');self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_auto_original_worker_returns_decoded_image_once_without_per_action_confirmation(self):
        import tempfile
        from support.fixtures.media import production_media
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.production.resource_worker import ResourceWorker
        from vsc.production.providers import GeneratedAsset,JobHandle,JobStatus
        with tempfile.TemporaryDirectory(prefix='vsc-canvas-auto-worker-') as directory:
            self.service.storage=LocalStorage(directory);self.addCleanup(setattr,self.service,'storage',None)
            content=production_media()['png'];requests=[]
            class Adapter:
                def submit(self,request):
                    requests.append(request);return JobHandle('isolated','isolated',None,{'synthetic':True})
                def poll(self,handle):return JobStatus('succeeded',raw=handle.raw)
                def parse_result(self,raw):return [GeneratedAsset('image',inline_bytes=content)]
            self.write('configure_budget',{'limits':{'remote_jobs':1,'images':1},'reason':'隔离自动执行验证额度'})
            turn,result=self.media_turn(automatic=True)
            self.assertEqual(result['status'],'applied',result);self.assertEqual(len(result['action_results']),2)
            worker=ResourceWorker(self.service,lambda *_:Adapter());finished=worker.run_once(self.p)
            self.assertEqual(finished['status'],'succeeded',finished);self.assertEqual(len(requests),1)
            self.assertIsNone(worker.run_once(self.p));self.assertEqual(len(requests),1)
            self.service.execute_canvas_agent_turn(self.p,turn['id'])
            canvas=self.service.get_creative_canvas(self.p,self.canvas['id']);node=next(n for n in canvas['document']['nodes'] if n['id']=='agent-'+turn['id']+'-0')
            self.assertEqual(node['job_id'],finished['id']);self.assertTrue(node['media_id'])
            media=self.service.get_media(self.p,node['media_id']);self.assertEqual(media['modality'],'image');self.assertGreater(media['width'],0)
            self.service.execute_canvas_agent_turn(self.p,turn['id'])
            again=self.service.get_creative_canvas(self.p,self.canvas['id']);self.assertEqual(again['canvas_revision'],canvas['canvas_revision']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)
