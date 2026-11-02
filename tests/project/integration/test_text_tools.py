"""Real fixed-draft consumers, host boundaries, exports and isolated media checks."""
import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import zipfile
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.text_tools import COMMON,DEFAULTS,normalize_document,group_mapping
from vsc.assets.resource_service import ResourceError,Conflict

class FixedHost:
    name='synthetic-text-host/v1'
    def __init__(self):self.calls=[];self.fail=False
    def available(self):return True
    def generate(self,tool,action,document,references,*,materials=None):
        self.calls.append((tool,action,deepcopy(document),deepcopy(references)))
        if self.fail:raise ResourceError('synthetic failure','text_host_failed')
        if action=='terms':return {'terms':[{'source':'阿叶','target':'Aya','aliases':'小叶'}],'translation_characters':[{'source':'阿叶','target':'Aya','aliases':'小叶','kind':'主角','description':'固定文本人物'}]}
        if action=='analyze':return {'analysis':'固定文本行分析','category':'短剧','channel':'家庭','card_start_line':1,'card_end_line':2}
        if action=='score':return {'analysis':'显式标准分析','scores':[{'key':r['key'],'score':3,'evidence':'第一场固定证据','reason':'依据所给标准'} for r in document['criteria']]}
        if action=='observe':return {'observations':document['observations']}
        return {action if action not in {'translate','localize'} else 'body':'建议结果，尚未接受'}

@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class TextToolTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-text-tool-test-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.service.storage=LocalStorage(self.root/'storage');self.service.text_tool_host=FixedHost()

    def draft(self,tool,**changes):return {**deepcopy(COMMON),**deepcopy(DEFAULTS[tool]),**changes}

    def test_bounded_text_batch_original_attempts_manual_protection_and_translation_completion(self):
        baseline=self.save('novel',self.draft('novel',source_text='第1章 起点\n离家\n第2章 归来\n回家',synopsis='回家',core_setting='小城',chapter_end=2,target_episodes=2))
        plan=self.write('create_novel_plan',{'unit_id':baseline['unit_id'],'version_id':baseline['id'],'episodes':[dict(title='第一集',chapter_start=1,chapter_end=1,outline='离家'),dict(title='第二集',chapter_start=2,chapter_end=2,outline='归来')]})
        first=self.service.get_text_tool(self.p,plan['episodes'][0]['unit_id']);manual=self.save('novel',dict(first['document'],body='保护的人工正文'),dict(unit_id=first['id'],id=first['current_version_id']))
        batch=self.write('create_text_batch',dict(tool='novel',action='body',unit_ids=[r['unit_id'] for r in plan['episodes']],auto_accept=True,overwrite=False,qa_unit_id=baseline['unit_id']))
        for _ in range(4):result=self.write('process_text_batch',{'batch_id':batch['id']})
        self.assertEqual(result['status'],'completed');self.assertEqual([r['status'] for r in result['items']],['skipped','completed','completed'])
        self.assertEqual(len(self.service.text_tool_host.calls),2)
        self.assertEqual(self.service.get_text_tool(self.p,manual['unit_id'])['document']['body'],'保护的人工正文')
        qa=self.service.get_text_tool_attempt(self.p,result['items'][-1]['attempt_id']);self.assertEqual(len(qa['references']),2)
        translation=self.save('translation',self.draft('translation',body='Proofread line.',proofread=True,target_language='English'))
        complete=self.write('set_translation_stage',{'unit_id':translation['unit_id'],'version_id':translation['id'],'stage':'complete'})
        self.assertTrue(self.service.get_text_tool(self.p,translation['unit_id'])['locked'])
        with self.assertRaises(Conflict):self.save('translation',translation['document'],dict(unit_id=translation['unit_id'],id=complete['id']))
        opened=self.write('set_translation_stage',{'unit_id':translation['unit_id'],'version_id':complete['id'],'stage':'draft'})
        self.assertFalse(self.service.get_text_tool(self.p,translation['unit_id'])['locked'])

    def test_batch_unknown_and_failure_never_resubmit_original_task(self):
        one=self.save('scoring',self.draft('scoring',source_text='第一行\n第二行'))
        batch=self.write('create_text_batch',dict(tool='scoring',action='analyze',unit_ids=[one['unit_id']],auto_accept=False))
        host=self.service.text_tool_host
        def unknown(*args):host.calls.append(args);raise ResourceError('unknown','text_submission_unknown')
        host.generate=unknown
        first=self.write('process_text_batch',{'batch_id':batch['id']});second=self.write('process_text_batch',{'batch_id':batch['id']})
        self.assertEqual(first['items'][0]['attempt_id'],second['items'][0]['attempt_id']);self.assertEqual(len(host.calls),1)
        self.write('stop_text_batch',{'batch_id':batch['id']});self.write('process_text_batch',{'batch_id':batch['id']});self.assertEqual(len(host.calls),1)

    def test_text_fixed_member_sets_reject_late_append_and_incomplete_commit(self):
        from sqlalchemy import insert,select,update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        baseline=self.save('novel',self.draft('novel',source_text='第1章 起点\n出门',synopsis='出门',core_setting='小城',chapter_end=1,target_episodes=1))
        plan=self.write('create_novel_plan',dict(unit_id=baseline['unit_id'],version_id=baseline['id'],episodes=[dict(title='第一集',chapter_start=1,chapter_end=1,outline='出门')]))
        extra=self.save('novel',self.draft('novel',body='独立参考'))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.text_tool_novel_episodes).values(project_id=self.p,id=str(uuid.uuid4()),plan_id=plan['id'],unit_id=extra['unit_id'],ordinal=2,chapter_start=1,chapter_end=1))
        child=self.service.get_text_tool(self.p,plan['episodes'][0]['unit_id'])
        target={'unit_id':child['id'],'id':child['current_version_id']}
        started=self.store.start_text_tool_attempt(self.p,dict(unit_id=target['unit_id'],input_version_id=target['id'],action='body',new_attempt=True),backend='isolated-seal-test',caller='fixed-caller',expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor='test-human');self.rev=started['revision']
        self.assertEqual(len(self.service.get_text_tool_attempt(self.p,started['id'])['references']),1)
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.text_tool_attempt_inputs).values(project_id=self.p,id=str(uuid.uuid4()),attempt_id=started['id'],version_id=extra['id'],ordinal=2))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(update(S.text_tool_attempts).where(S.text_tool_attempts.c.project_id==self.p,S.text_tool_attempts.c.id==started['id']).values(input_count=3))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.text_tool_attempts).values(project_id=self.p,id=str(uuid.uuid4()),unit_id=extra['unit_id'],input_version_id=extra['id'],action='body',backend='isolated-seal-test',status='running',input_count=1,created_by='test-human'))
        batch=self.write('create_text_batch',dict(tool='novel',action='body',unit_ids=[extra['unit_id']],auto_accept=False,overwrite=True))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.text_tool_batch_items).values(project_id=self.p,id=str(uuid.uuid4()),batch_id=batch['id'],unit_id=baseline['unit_id'],input_version_id=baseline['id'],ordinal=1,action='body',status='pending'))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(update(S.text_tool_batches).where(S.text_tool_batches.c.project_id==self.p,S.text_tool_batches.c.id==batch['id']).values(item_count=2))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.text_tool_batches).values(project_id=self.p,id=str(uuid.uuid4()),tool='novel',action='body',auto_accept=False,status='ready',item_count=1,created_by='test-human'))
        for _ in range(2):completed=self.write('process_text_batch',dict(batch_id=batch['id']))
        self.assertEqual(completed['status'],'completed');self.assertEqual(len(completed['items']),1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(S.text_tool_attempts.c.input_count).where(S.text_tool_attempts.c.project_id==self.p,S.text_tool_attempts.c.id==started['id'])),2)
        self.assertEqual(len(self.store.get_novel_plan(self.p,baseline['unit_id'])['episodes']),1)

    def test_text_migration_empty_downgrade_and_fact_refusal(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from support.fixtures.postgres import isolated_postgres
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        with isolated_postgres(TEST_URL) as engine:
            cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
            with engine.begin() as conn:
                cfg.attributes['connection']=conn;command.downgrade(cfg,'0035_canvas_product_flow')
                self.assertIsNone(conn.execute(text("SELECT to_regclass('text_tool_batches')")).scalar_one())
                command.upgrade(cfg,'head')
            service=ResourceService(PostgresResourceStore(engine=engine))
            project=service.create_project({'name':'migration fixture','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')
            draft=service.save_text_tool(project['id'],dict(tool='novel',group_key='g',unit_key='u',title='fixture',ordinal=0,episode_id=None,base_version_id=None,document=self.draft('novel',source_text='第1章 起点\n出门',synopsis='归来',core_setting='小城',chapter_end=1,target_episodes=1)),expected_revision=0,idempotency_key=uuid.uuid4().hex,actor='test-human')
            plan=service.create_novel_plan(project['id'],dict(unit_id=draft['unit_id'],version_id=draft['id'],episodes=[dict(title='一集',chapter_start=1,chapter_end=1,outline='出门')]),expected_revision=draft['revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
            with engine.connect() as conn:
                cfg.attributes['connection']=conn
                with self.assertRaises(IntegrityError) as failure:
                    with conn.begin():command.downgrade(cfg,'0035_canvas_product_flow')
                self.assertEqual(failure.exception.orig.sqlstate,'23514')
                self.assertEqual(conn.execute(text('SELECT count(*) FROM text_tool_novel_plans')).scalar_one(),1)
            service.create_text_batch(project['id'],dict(tool='novel',action='body',unit_ids=[plan['episodes'][0]['unit_id']],auto_accept=False),expected_revision=plan['revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
            with engine.connect() as conn:
                cfg.attributes['connection']=conn
                with self.assertRaises(IntegrityError) as failure:
                    with conn.begin():command.downgrade(cfg,'0036_text_product_flow')
                self.assertEqual(failure.exception.orig.sqlstate,'23514')
                self.assertEqual(conn.execute(text('SELECT count(*) FROM text_tool_batches')).scalar_one(),1)

    def test_media_understanding_qc_suggestion_decisions_and_embedded_evidence(self):
        import hashlib
        from vsc.production.media_understanding import GrokFrameUnderstanding
        media,path=self.video('semantic.mp4',2);calls=[]
        class MediaHost:
            name='synthetic-source-media-recorder';basis='source_media';capabilities={'observe','subtitle_semantics','visual_quality','audiovisual','content'}
            def available(self):return True
            def analyze(self,request,actual):
                self_hash=hashlib.sha256(actual.read_bytes()).hexdigest()
                if self_hash!=request['media']['sha256']:raise AssertionError('wrong media bytes')
                calls.append(deepcopy(request))
                if request['action']=='observe':return {'observations':[{'start_ms':0,'end_ms':900,'kind':'action','text':'合成工程观察，非模型质量证据'}]}
                return {'issues':[{'rule':request['checks'][0],'start_ms':100,'end_ms':900,'code':'synthetic_typo','severity':'warning','message':'合成字幕建议','evidence':'固定源帧100ms','original_subtitle':'错字','suggested_subtitle':'正字'}]}
        self.service.media_understanding_host=MediaHost()
        saved=self.save('breakdown',self.draft('breakdown',media_id=media,understanding_mode='deep'))
        run=self.write('run_text_tool',{'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'observe'})
        self.assertEqual(run['status'],'completed');accepted=self.accept(run,saved);self.assertEqual(accepted['document']['observation_basis'],'source_media')
        qc=self.save('qc',self.draft('qc',videos=[{'media_id':media,'name':'','sha256':''}],subtitles=[{'filename':'semantic.vtt','text':'WEBVTT\n\n00:00.100 --> 00:00.900\n错字\n'}],checks=['subtitle_semantics']))
        run=self.write('run_text_tool',{'unit_id':qc['unit_id'],'input_version_id':qc['id'],'action':'check'});self.assertEqual(run['status'],'completed');qc=self.accept(run,qc)
        self.assertEqual(calls[-1]['subtitles']['cues'][0]['text'],'错字')
        self.write('decide_text_issue',{'version_id':qc['id'],'issue_index':0,'decision':'fixed','reason':'已核对合成字幕'})
        evidence=self.write('capture_text_tool_evidence',{'version_id':qc['id'],'issue_index':0})
        fixed=self.write('freeze_text_review_report',{'version_id':qc['id']});raw=self.service.text_tool_export(self.p,fixed['id'],'xlsx')[0]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn('xl/media/evidence1.png',archive.namelist());self.assertTrue(archive.read('xl/media/evidence1.png').startswith(b'\x89PNG'));self.assertIn('已核对合成字幕',archive.read('xl/worksheets/sheet1.xml').decode())
        corrected=self.write('apply_text_issue_subtitle',{'unit_id':qc['unit_id'],'version_id':qc['id'],'issue_index':0,'subtitle_filename':'semantic.vtt'})
        doc=corrected['document'];self.assertIn('正字',doc['subtitles'][-1]['text']);self.assertIn('错字',doc['subtitles'][0]['text']);self.assertEqual(doc['check_ranges'][0]['start_ms'],100)
        self.assertEqual(self.service.text_tool_export(self.p,fixed['id'],'xlsx')[0],raw)
        canvas=self.write('create_creative_canvas',{'title':'理解来源','document':{'nodes':[{'id':'source','type':'video','media_id':media,'title':'视频','x':0,'y':0}],'edges':[]}})
        request={'unit_id':saved['unit_id'],'version_id':accepted['id'],'canvas_id':canvas['id'],'canvas_revision':canvas['canvas_revision'],'source_node_id':'source','dimension':'storyboard'}
        preview=self.service.preview_breakdown_canvas(self.p,request);linked=self.write('apply_breakdown_canvas',{'request':request,'preview_sha256':preview['preview_sha256']});self.assertEqual(linked['added_count'],1)
        self.assertEqual(len(self.service.get_creative_canvas(self.p,canvas['id'])['document']['edges']),1)

    def test_multiformat_subtitles_and_actual_grok_frame_payload(self):
        from vsc.post.subtitle_formats import normalize_subtitle
        from vsc.post.subtitles import SubtitleError
        import hashlib
        samples={'srt':'1\n00:00:00,100 --> 00:00:00,900\n台词\n','vtt':'WEBVTT\n\n00:00.100 --> 00:00.900 align:start\n台词\n','ass':'[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.10,0:00:00.90,Default,,0,0,0,,台词','ssa':'[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: Marked=0,0:00:00.10,0:00:00.90,Default,,0,0,0,,台词','txt':'[00:00.100-00:00.900] 台词'}
        for kind,text_ in samples.items():
            with self.subTest(kind=kind):self.assertEqual(normalize_subtitle('a.'+kind,text_,duration=1,require_timing=True)['cues'][0],dict(start_ms=100,end_ms=900,text='台词'))
        with self.assertRaises(SubtitleError):normalize_subtitle('a.txt','无时码文本',require_timing=True)
        media,path=self.video('frame-input.mp4',1)
        from vsc.production.media_understanding import GrokFrameUnderstanding
        captured=[]
        def runner(command,**kw):
            blocks=json.loads(Path(command[command.index('--prompt-file')+1]).read_text());pictures=[b for b in blocks if b['type']=='image'];captured.extend(pictures)
            self.assertTrue(pictures);self.assertTrue(all(base64.b64decode(b['data']).startswith(b'\xff\xd8') for b in pictures));self.assertTrue(all(b['mimeType']=='image/jpeg' for b in pictures))
            return subprocess.CompletedProcess(command,0,stdout=json.dumps({'observations':[{'start_ms':0,'end_ms':900,'kind':'action','text':'test fixture'}]}),stderr='')
        request={'request_id':'offline-test','action':'observe','media':{'id':media,'duration_ms':1000,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},'mode':'light','start_ms':0,'end_ms':1000}
        result=GrokFrameUnderstanding(runner=runner).analyze(request,path);self.assertEqual(len(captured),2);self.assertEqual(result['observations'][0]['kind'],'action')

    def test_novel_product_plan_real_ranges_shared_baseline_qa_batch_and_replay(self):
        objects=self.hierarchy()
        source='第1章 起点\n阿叶出门。\n第2章 归来\n阿叶回来。\n第3章 尾声\n阿叶告别。'
        baseline=self.save('novel',self.draft('novel',source_text=source,synopsis='离家后归来',core_setting='当代小城',characters=[{'name':'阿叶','description':'同一个人'}],chapter_start=1,chapter_end=2,target_episodes=2))
        episodes=[dict(title='离家',chapter_start=1,chapter_end=1,outline='出门'),dict(title='回家',chapter_start=2,chapter_end=2,outline='归来')]
        request={'unit_id':baseline['unit_id'],'version_id':baseline['id'],'episodes':episodes}
        plan=self.write('create_novel_plan',request);self.assertEqual(self.write('create_novel_plan',request)['id'],plan['id'])
        saved=[]
        for row in plan['episodes']:
            unit=self.service.get_text_tool(self.p,row['unit_id']);doc=unit['document']
            self.assertNotIn('尾声',doc['source_text']);self.assertEqual(doc['core_setting'],'当代小城')
            self.assertEqual(doc['source_text'].count('章'),1)
            draft=self.save('novel',dict(doc,body=row['title']+'正文'),{'unit_id':unit['id'],'id':unit['current_version_id']},title=row['title'])
            saved.append(draft)
        child=self.service.get_text_tool(self.p,saved[0]['unit_id'])
        with self.assertRaises(Conflict):self.save('novel',dict(child['document'],core_setting='擅改共享设定'),saved[0])
        with self.assertRaises(Conflict):self.save('novel',dict(child['document'],novel_baseline_version_id=''),saved[0])
        with self.assertRaises(Conflict):self.write('save_text_tool',{**{k:child[k] for k in ('tool','group_key','unit_key','title','episode_id')},'unit_id':child['id'],'ordinal':99,'base_version_id':child['current_version_id'],'document':child['document']})
        run=self.write('run_text_tool',{'unit_id':saved[0]['unit_id'],'input_version_id':saved[0]['id'],'action':'qa_notes'})
        self.assertEqual(run['status'],'completed');refs=self.service.get_text_tool_attempt(self.p,run['id'])['references']
        self.assertEqual({r['id'] for r in refs},{plan['plan_version_id'],*[row['id'] for row in saved]})
        self.assertNotIn('第2章',self.service.text_tool_host.calls[-1][2]['source_text'])
        revised=self.save('novel',dict(saved[1]['document'],body='归来修订正文'),saved[1],title='回家')
        with self.assertRaises(Conflict):self.accept(run,saved[0])
        request={'plan_id':plan['id'],'work_id':objects['work'],'code_prefix':'NOV-'}
        preview=self.service.preview_novel_batch_import(self.p,request)
        result=self.write('import_novel_batch',{'request':request,'preview_sha256':preview['preview_sha256']})
        again=self.write('import_novel_batch',{'request':request,'preview_sha256':preview['preview_sha256']})
        self.assertTrue(again['already_imported']);self.assertEqual(len(result['episodes']),2)
        for item in result['episodes']:
            self.assertFalse(item['automatic_approval'])
            self.assertIn('正文',self.service.store.get_script_draft(self.p,item['episode_id'])['content']['body'])
        bad=deepcopy(episodes);bad[1]['chapter_end']=3
        with self.assertRaises(ResourceError):self.write('create_novel_plan',{'unit_id':baseline['unit_id'],'version_id':baseline['id'],'episodes':bad})

    def test_translation_product_ranges_role_terms_residuals_and_source_exports(self):
        first=self.save('translation',self.draft('translation',target_language='English',episode_number=1,body='Aya leaves.',proofread=True))
        third=self.save('translation',self.draft('translation',target_language='English',episode_number=3,body='Aya returns.',proofread=True))
        base=self.draft('translation',translation_mode='incremental',episode_number=2,target_language='English',source_text='阿叶回来',body='Aya 回来',reference_version_ids=[first['id']],translation_characters=[{'source':'阿叶','target':'Aya','aliases':'小叶','kind':'主角','description':'来自小城'}])
        saved=self.save('translation',base)
        unit=self.service.get_text_tool(self.p,saved['unit_id']);self.assertEqual(unit['residuals'][0]['line'],1)
        self.assertEqual(self.service.text_tool_export(self.p,saved['id'],'txt',view='source')[0].decode(),'阿叶回来')
        bilingual=self.service.text_tool_export(self.p,saved['id'],'txt',view='bilingual')[0].decode();self.assertIn('阿叶回来',bilingual);self.assertIn('Aya 回来',bilingual)
        source_json=json.loads(self.service.text_tool_export(self.p,saved['id'],'json',view='source')[0]);self.assertEqual(source_json['units'][0]['source_text'],'阿叶回来');self.assertNotIn('body',source_json['units'][0])
        for changes in [{'reference_version_ids':[]},{'reference_version_ids':[third['id']]},{'reference_version_ids':[first['id'],third['id']]},{'episode_number':1}]:
            with self.subTest(changes=changes),self.assertRaises(ResourceError):self.save('translation',dict(base,**changes))

    def test_scoring_line_boundary_multiple_fixed_runs_and_immutable_exports(self):
        saved=self.save('scoring',self.draft('scoring',source_text='开场\n冲突\n结尾',card_start_line=1,card_end_line=2,criteria=[{'key':'cause','label':'因果','max_score':5,'weight':1}]))
        request={'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'score','new_attempt':True}
        first=self.write('run_text_tool',request);second=self.write('run_text_tool',request)
        adopted=self.accept(second,saved)
        document=json.loads(self.service.text_tool_export(self.p,adopted['id'],'json')[0]);self.assertEqual(len(document['runs']),2)
        self.assertEqual(document['card']['text'],'开场\n冲突');self.assertEqual({r['id'] for r in document['runs']},{first['id'],second['id']})
        before=self.service.text_tool_export(self.p,adopted['id'],'csv')[0]
        self.write('run_text_tool',dict(request,input_version_id=adopted['id']))
        self.assertEqual(self.service.text_tool_export(self.p,adopted['id'],'csv')[0],before)
        stale=dict(adopted['document'],source_text='变更\n冲突\n结尾')
        with self.assertRaises(ResourceError) as error:self.save('scoring',stale,adopted)
        self.assertEqual(error.exception.code,'scoring_card_stale')
        stale['card_source_sha256']='';self.save('scoring',stale,adopted)

    def test_analysis_and_terms_are_comparable_patches_with_old_draft_protection(self):
        translation=self.save('translation',self.draft('translation',source_text='阿叶又名小叶',target_language='English'))
        terms=self.write('run_text_tool',{'unit_id':translation['unit_id'],'input_version_id':translation['id'],'action':'terms'})
        self.assertEqual(terms['status'],'completed');self.assertEqual(self.service.get_text_tool(self.p,translation['unit_id'])['document']['terms'],[])
        accepted=self.accept(terms,translation);self.assertEqual(accepted['document']['translation_characters'][0]['kind'],'主角')
        score=self.save('scoring',self.draft('scoring',source_text='第一行\n第二行\n第三行'))
        analysis=self.write('run_text_tool',{'unit_id':score['unit_id'],'input_version_id':score['id'],'action':'analyze'})
        accepted=self.accept(analysis,score);self.assertEqual(accepted['document']['category'],'短剧');self.assertEqual(accepted['document']['card_end_line'],2)
        changed=self.save('scoring',dict(accepted['document'],review_decision='keep',review_reason='人工判断'),accepted)
        with self.assertRaises(Conflict):self.accept(analysis,changed)

    def save(self,tool,document,old=None,title='测试单元',episode=None):
        unit=self.service.get_text_tool(self.p,old['unit_id']) if old else None
        payload={'tool':tool,'group_key':unit['group_key'] if unit else 'test','unit_key':unit['unit_key'] if unit else uuid.uuid4().hex,
            'title':title,'ordinal':unit['ordinal'] if unit else 0,'episode_id':episode,'document':document,
            'unit_id':unit['id'] if unit else None,'base_version_id':old['id'] if old else None}
        return self.write('save_text_tool',payload)

    def accept(self,run,saved):return self.write('accept_text_tool_result',{'attempt_id':run['id'],'base_version_id':saved['id']})

    def video(self,name='a.mp4',duration=3):
        if not shutil.which('ffmpeg'):self.skipTest('requires real ffmpeg')
        path=self.root/name
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=128x128:rate=24','-t',str(duration),'-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True,capture_output=True)
        with path.open('rb') as file:upload=self.service.storage.stage_upload(file,name)
        value=self.write('register_media',{'staged_upload':upload['staged_upload'],'name':name,'rights':'owned','source':{'kind':'test-owned','content':'synthetic testsrc2'}})
        return value['id'],path

    def overseas_fixture(self):
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        objects=self.hierarchy();source,_=self.video('overseas-source.mp4',4)
        self.artifact(objects=[objects['shot']]);self.artifact('state','scene-state',[objects['scene']],{'state_versions':[{'scene_id':objects['scene']}]})
        from vsc.post.local_media_tools import frame
        picture=self.root/'overseas-frame.png';frame(self.root/'overseas-source.mp4',picture,'first')
        with picture.open('rb') as stream:upload=self.service.storage.stage_upload(stream,picture.name)
        image=self.write('register_media',{'staged_upload':upload['staged_upload'],'rights':'owned','source':{'kind':'synthetic','content':'testsrc2 frame'}})['id']
        self.write('record_media_check',{'media_id':image,'checker':'test-probe','criteria_version':'1','outcome':'pass'})
        self.select(self.candidate(objects['shot'],image))
        preset=next(r for r in PRESETS if r['id']=='xai-grok-imagine-video');settings={k:v for k,v in preset.items() if k not in {'id','label'}}
        settings.update(enabled=True,model_version='offline-overseas');model=ResourceSettings(self.store).save(settings,'test-human')['id']
        groups=[dict(key='g1',source_start_ms=0,source_end_ms=2000,target_duration_ms=1000,shot_id=objects['shot'],first_frame_media_id=image),dict(key='g2',source_start_ms=2000,source_end_ms=4000,target_duration_ms=2000,shot_id=objects['shot'],first_frame_media_id=image)]
        segments=[dict(key='s1',group='g1',source_start_ms=0,source_end_ms=2000,target_start_ms=0,target_end_ms=1000,source_text='人工观察：合成图案，无故事事实',entity_keys='a,b',scene_key='park',localized_text='First synthetic pattern.'),dict(key='s2',group='g2',source_start_ms=2000,source_end_ms=4000,target_start_ms=0,target_end_ms=2000,source_text='人工观察：同一合成图案继续',entity_keys='b',scene_key='park2',localized_text='Second pattern.')]
        entities=[dict(key='a',kind='character',name='角色甲'),dict(key='b',kind='character',name='角色甲另称'),dict(key='park',kind='scene',name='测试场景'),dict(key='park2',kind='scene',name='同场别称')]
        saved=self.save('overseas',self.draft('overseas',source_media_id=source,target_language='English',understanding='人工观察，不宣称视觉模型识别',body='Localized synthetic sequence.',groups=groups,segments=segments,entities=entities),episode=objects['episode'])
        return objects,source,model,saved

    def overseas_confirm(self,saved,episode):
        first=self.write('stage_overseas_baseline',{'unit_id':saved['unit_id'],'version_id':saved['id'],'phase':'understanding'})
        self.write('decide_artifact',{'artifact_id':first['id'],'reason':'隔离测试操作者确认人工观察内容'})
        saved=self.save('overseas',dict(saved['document'],understanding_version_id=first['id']),saved,episode=episode)
        second=self.write('stage_overseas_baseline',{'unit_id':saved['unit_id'],'version_id':saved['id'],'phase':'localization'})
        self.write('decide_artifact',{'artifact_id':second['id'],'reason':'隔离测试操作者确认固定理解与改写'})
        return saved,first,second

    def overseas_policy(self):
        from datetime import datetime,timedelta,timezone
        now=datetime.now(timezone.utc)
        return dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=45)).isoformat(),stop_submitting_at=(now+timedelta(minutes=60)).isoformat(),max_attempts_per_purpose=3,max_repair_rounds=1)

    def test_overseas_uid_merge_impact_original_confirmation_and_revision_lineage(self):
        objects,source,model,saved=self.overseas_fixture();saved,understanding,localization=self.overseas_confirm(saved,objects['episode'])
        original=self.service.get_artifact_version(self.p,understanding['id'])['document']
        request={'unit_id':saved['unit_id'],'version_id':saved['id'],'source_key':'b','target_key':'a'}
        preview=self.service.preview_overseas_merge(self.p,request)
        self.assertEqual([r['segment_key'] for r in preview['plan']['impact']['affected_segments']],['s1','s2'])
        merged=self.write('merge_overseas_entities',{'request':request,'preview_sha256':preview['preview_sha256']})
        read=self.service.get_text_tool(self.p,saved['unit_id']);self.assertEqual([r['entity_keys'] for r in read['document']['segments']],['a','a']);self.assertEqual(read['document']['understanding_version_id'],'')
        self.assertEqual(self.service.get_artifact_version(self.p,understanding['id'])['document'],original)
        with self.assertRaises(Conflict):self.write('merge_overseas_entities',{'request':request,'preview_sha256':preview['preview_sha256']})
        request.update(version_id=merged['id'],source_key='park2',target_key='park')
        preview=self.service.preview_overseas_merge(self.p,request);merged=self.write('merge_overseas_entities',{'request':request,'preview_sha256':preview['preview_sha256']})
        read=self.service.get_text_tool(self.p,saved['unit_id']);self.assertEqual([r['scene_key'] for r in read['document']['segments']],['park','park'])
        self.assertEqual([(r['source_start_ms'],r['source_end_ms']) for r in read['document']['segments']],[(0,2000),(2000,4000)])
        invalid=deepcopy(read['document']);invalid['entities']=[e for e in invalid['entities'] if e['key']!='a']
        with self.assertRaises(ResourceError):self.save('overseas',invalid,dict(id=merged['id'],unit_id=saved['unit_id']),episode=objects['episode'])
        revised=self.write('stage_overseas_baseline',{'unit_id':saved['unit_id'],'version_id':merged['id'],'phase':'understanding'})
        self.assertEqual(self.service.get_artifact_version(self.p,revised['id'])['supersedes_id'],understanding['id'])
        self.write('decide_artifact',{'artifact_id':revised['id'],'reason':'明确批准合并后的新理解'})
        next_=self.save('overseas',dict(read['document'],understanding_version_id=revised['id'],body='Revised localization.'),dict(id=merged['id'],unit_id=saved['unit_id']),episode=objects['episode'])
        localized=self.write('stage_overseas_baseline',{'unit_id':saved['unit_id'],'version_id':next_['id'],'phase':'localization'})
        artifact=self.service.get_artifact_version(self.p,localized['id']);self.assertEqual(artifact['dependency_ids'],[revised['id']]);self.assertEqual(artifact['supersedes_id'],localization['id'])
        self.assertFalse(artifact['approved']);self.assertTrue(self.service.get_artifact_version(self.p,localization['id'])['approved'])

    def test_overseas_original_group_run_unknown_guard_candidates_and_editor(self):
        from vsc.production.bounded import preview_batch,execute_batch
        objects,source,model,saved=self.overseas_fixture();saved,understanding,localized=self.overseas_confirm(saved,objects['episode'])
        self.write('configure_budget',{'limits':{'remote_jobs':10,'video_seconds':30},'reason':'合成工程无外部调用'})
        prepare={'unit_id':saved['unit_id'],'version_id':saved['id'],'localization_version_id':localized['id'],'group_key':'g1','settings':{'mode':'single','model_id':model},'attempt_key':str(uuid.uuid4()),'new_attempt':False}
        fixed=self.write('prepare_overseas_group',prepare)
        self.assertEqual(self.write('prepare_overseas_group',prepare)['id'],fixed['id'])
        request={'group_draft_id':fixed['id'],'execution_policy':self.overseas_policy()}
        preview=self.service.preview_overseas_group_run(self.p,request);self.assertTrue(preview['ready'],preview.get('gaps'))
        self.assertEqual(preview['generation_quote']['native_units']['video_seconds'],1)
        proposed=self.write('propose_overseas_group_run',{'request':request,'preview_sha256':preview['preview_sha256']})
        self.assertFalse(self.service.get_artifact_version(self.p,proposed['id'])['approved']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
        with self.assertRaises(Conflict):self.write('prepare_overseas_group',dict(prepare,attempt_key=str(uuid.uuid4()),new_attempt=True))
        self.write('decide_artifact',{'artifact_id':proposed['id'],'reason':'明确批准合成原分组制作包'})
        original=preview_batch(self.service,self.p,{'run_version_id':proposed['id']});self.assertEqual(original['ready_count'],1,original)
        queued=execute_batch(self.service,self.p,{'run_version_id':proposed['id']},'test-human');self.rev=self.service.get_project(self.p)['revision'];self.assertEqual(queued['created_count'],1,queued)
        job=queued['tasks'][0]['job_id'];self.write('update_generation_job',{'job_id':job,'status':'submission_unknown'})
        with self.assertRaises(Conflict) as error:self.write('prepare_overseas_group',dict(prepare,attempt_key=str(uuid.uuid4()),new_attempt=True))
        self.assertEqual(error.exception.code,'overseas_run_unsettled');self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)
        self.write('update_generation_job',{'job_id':job,'status':'succeeded','outputs':[{'media_id':source}], 'recovery_evidence':{'source':'offline-fixture','note':'合成素材回执，不代表云调用'}})
        chosen=self.write('select_overseas_candidate',{'unit_id':saved['unit_id'],'version_id':saved['id'],'group_draft_id':fixed['id'],'job_id':job,'media_id':source,'candidate_in_ms':500})
        doc=self.service.get_text_tool(self.p,saved['unit_id'])['document'];self.assertEqual(doc['groups'][0]['candidate_in_ms'],500);self.assertEqual(doc['groups'][1]['candidate_media_id'],'')
        # A second group remains independent, including its nonzero source offset.
        next_group=dict(prepare,version_id=chosen['id'],group_key='g2',base_classic_draft_id=fixed['classic_draft_id'],attempt_key=str(uuid.uuid4()))
        second=self.write('prepare_overseas_group',next_group);request2=dict(request,group_draft_id=second['id']);preview2=self.service.preview_overseas_group_run(self.p,request2)
        run2=self.write('propose_overseas_group_run',{'request':request2,'preview_sha256':preview2['preview_sha256']});self.write('decide_artifact',{'artifact_id':run2['id'],'reason':'合成第二组'})
        batch=execute_batch(self.service,self.p,{'run_version_id':run2['id']},'test-human');self.rev=self.service.get_project(self.p)['revision'];self.assertEqual(batch['created_count'],1,batch)
        job2=batch['tasks'][0]['job_id'];self.write('update_generation_job',{'job_id':job2,'status':'submitted','external_task_id':'offline-'+job2});self.write('update_generation_job',{'job_id':job2,'status':'succeeded','outputs':[{'media_id':source}]})
        chosen2=self.write('select_overseas_candidate',{'unit_id':saved['unit_id'],'version_id':chosen['id'],'group_draft_id':second['id'],'job_id':job2,'media_id':source,'candidate_in_ms':1500})
        current=self.service.get_text_tool(self.p,saved['unit_id']);self.assertEqual(current['mapping'][1]['group_start_ms'],0);self.assertEqual(current['document']['groups'][0]['candidate_media_id'],source)
        request={'unit_id':saved['unit_id'],'version_id':chosen2['id'],'episode_id':objects['episode']};preview=self.service.preview_text_tool_import(self.p,request)
        self.write('import_text_tool',{'request':request,'preview_sha256':preview['preview_sha256']});clips=self.service.get_edit_workspace(self.p,objects['episode'])['current']['document']['clips']
        self.assertEqual([(r['in_frame'],r['out_frame']) for r in clips],[(12,36),(36,84)])
        retry=self.write('prepare_overseas_group',dict(prepare,version_id=chosen2['id'],base_classic_draft_id=second['classic_draft_id'],attempt_key=str(uuid.uuid4()),new_attempt=True));self.assertNotEqual(retry['id'],fixed['id'])
        self.assertEqual(self.service.get_text_tool(self.p,saved['unit_id'])['document']['groups'][1]['candidate_media_id'],source)

    def test_overseas_http_merge_readonly_history_and_unapproved_baseline_guard(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        objects,source,model,saved=self.overseas_fixture()
        app=create_app({'projects_root':str(self.root/'projects'),'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test','human_identity':'test-human','background_enabled':False},service=self.service)
        with TestClient(app) as client:
            base='/api/v1/projects/'+self.p+'/text-tools/overseas';request={'unit_id':saved['unit_id'],'version_id':saved['id'],'phase':'understanding'}
            self.assertEqual(client.post(base+'/baseline',json={'payload':request}).status_code,403)
            login=client.post('/api/v1/session',json={'token':'test'},headers={'Origin':'http://testserver'}).json();headers={'Origin':'http://testserver','X-CSRF-Token':login['csrf_token']}
            for path in ['/merge-preview','/run-preview']:self.assertEqual(client.post(base+path,json={'payload':None},headers=headers).status_code,422)
            body={'payload':request,'expected_revision':self.rev,'idempotency_key':uuid.uuid4().hex};response=client.post(base+'/baseline',json=body,headers=headers);self.assertEqual(response.status_code,200,response.text);self.rev=response.json()['revision']
            self.assertEqual(client.post(base+'/baseline',json=body,headers=headers).json(),response.json())
            read=client.get('/api/v1/projects/'+self.p+'/text-tools/units/'+saved['unit_id']).json();self.assertEqual(len(read['overseas']['baselines']),1);self.assertFalse(read['overseas']['baselines'][0]['approved'])
        invalid=dict(saved['document'],understanding_version_id=response.json()['id']);new=self.save('overseas',invalid,saved,episode=objects['episode'])
        with self.assertRaises(ResourceError) as error:self.write('run_text_tool',{'unit_id':saved['unit_id'],'input_version_id':new['id'],'action':'localize','new_attempt':True})
        self.assertEqual(error.exception.code,'overseas_baseline_unapproved');self.assertEqual(len(self.service.text_tool_host.calls),0)

    def test_manual_merge_exports_reparse_and_original_import(self):
        marker='人工修改标记 MANUAL-729\n第二行保留'
        first=self.save('novel',self.draft('novel',body=marker),title='第一集')
        second=self.save('novel',self.draft('novel',body='第二集正文'),title='第二集')
        merged=self.write('merge_text_tools',{'tool':'novel','version_ids':[second['id'],first['id']],'title':'人工合稿'})
        for format in ['txt','docx']:
            data,mime,name=self.service.text_tool_export(self.p,merged['id'],format)
            from vsc.assets.source_intake import extract_source
            extracted=extract_source(data,format)
            self.assertIn(marker,extracted['text']);self.assertLess(extracted['text'].index('第二集正文'),extracted['text'].index('MANUAL-729'))
        docx=self.service.text_tool_export(self.p,merged['id'],'docx')[0]
        if shutil.which('textutil'):
            path=self.root/'actual.docx';path.write_bytes(docx)
            rendered=subprocess.run(['textutil','-convert','txt','-stdout',str(path)],check=True,capture_output=True,text=True).stdout
            self.assertIn('MANUAL-729',rendered)
        request={'unit_id':first['unit_id'],'version_id':first['id']}
        preview=self.service.preview_text_tool_import(self.p,request)
        imported=self.write('import_text_tool',{'request':request,'preview_sha256':preview['preview_sha256']})
        source=self.service.get_source_version(self.p,imported['source_id'])
        self.assertIn('MANUAL-729',source['content'])
        next_=self.save('novel',self.draft('novel',body=marker+'\n更新'),first)
        changed=self.service.preview_text_tool_import(self.p,{'unit_id':first['unit_id'],'version_id':next_['id']})
        self.assertEqual(changed['plan']['change'],'update')
        self.assertEqual(self.service.get_text_tool(self.p,first['unit_id'])['document']['body'],marker+'\n更新')
        with self.assertRaises(ResourceError):self.service.text_tool_export(self.p,first['id'],'xlsx')

    def test_translation_fixed_reference_replay_failure_and_stale_result(self):
        terms=[{'source':'阿叶','target':'Aya','aliases':'叶子'}]
        first=self.save('translation',self.draft('translation',body='Aya fixed translation',target_language='English',terms=terms,proofread=True))
        second=self.save('translation',self.draft('translation',source_text='阿叶归来',target_language='English',episode_number=2,terms=terms,reference_version_ids=[first['id']]))
        request={'unit_id':second['unit_id'],'input_version_id':second['id'],'action':'translate','new_attempt':True}
        key=uuid.uuid4().hex;run=self.write('run_text_tool',request,idempotency_key=key)
        replay=self.service.run_text_tool(self.p,request,expected_revision=0,idempotency_key=key,actor='test-human')
        self.assertEqual(replay['id'],run['id']);self.assertEqual(len(self.service.text_tool_host.calls),1)
        reference=self.service.text_tool_host.calls[0][3][0];self.assertEqual(reference['id'],first['id']);self.assertTrue(reference['document']['proofread'])
        manual=self.save('translation',self.draft('translation',body='manual after run',target_language='English',terms=terms),second)
        with self.assertRaises(Conflict):self.accept(run,manual)
        self.assertEqual(self.service.get_text_tool(self.p,second['unit_id'])['document']['body'],'manual after run')
        self.service.text_tool_host.fail=True
        failed=self.write('run_text_tool',dict(request,input_version_id=manual['id']))
        self.assertEqual(failed['status'],'failed');self.assertEqual(self.service.get_text_tool(self.p,first['unit_id'])['document']['body'],'Aya fixed translation')
        self.assertTrue(next(r for r in self.service.list_text_tools(self.p,'translation')['items'] if r['id']==first['unit_id'])['proofread'])
        self.assertEqual(len(self.service.get_text_tool(self.p,second['unit_id'])['attempts']),2)
        self.write('set_text_tool_lock',{'unit_id':second['unit_id'],'locked':True})
        with self.assertRaises(Conflict):self.write('run_text_tool',dict(request,input_version_id=manual['id']))
        with self.assertRaises(Conflict):self.save('translation',manual['document'],manual)

    def test_scoring_explicit_criteria_compare_and_real_exports(self):
        saved=self.save('scoring',self.draft('scoring',source_text='第一场固定证据',channel='测试频道',card_start=2,card_end=3,
            criteria=[{'key':'cause','label':'因果','max_score':5,'weight':2}]))
        request={'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'score','new_attempt':True}
        runs=[self.write('run_text_tool',request) for _ in range(2)]
        self.assertNotEqual(runs[0]['id'],runs[1]['id'])
        adopted=self.accept(runs[0],saved)
        for format in ['json','csv','html']:
            data,mime,name=self.service.text_tool_export(self.p,adopted['id'],format);self.assertIn('第一场固定证据',data.decode())
        bad=self.draft('scoring',criteria=[{'key':'x','label':'x','max_score':5,'weight':1}],scores=[{'key':'x','score':99,'evidence':'x','reason':'x'}])
        with self.assertRaises(ResourceError):self.save('scoring',bad)

    def test_qc_ambiguity_actual_probe_decode_xlsx_and_zip(self):
        a,path=self.video();b,_=self.video('a.zh.mp4')
        subtitle={'filename':'a.zh.srt','text':'1\n00:00:00,100 --> 00:00:00,900\n合成字幕\n'}
        saved=self.save('qc',self.draft('qc',videos=[{'media_id':a,'name':'','sha256':''},{'media_id':b,'name':'','sha256':''}],subtitles=[subtitle],checks=['metadata','subtitles','decode']))
        read=self.service.get_text_tool(self.p,saved['unit_id']);self.assertEqual(read['matching'][0]['status'],'conflict')
        run=self.write('run_text_tool',{'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'check'})
        self.assertEqual(run['error_code'],'subtitle_match_conflict')
        fixed=self.save('qc',self.draft('qc',videos=[{'media_id':a,'name':'','sha256':''}],subtitles=[subtitle],checks=['metadata','subtitles','decode']),saved)
        run=self.write('run_text_tool',{'unit_id':fixed['unit_id'],'input_version_id':fixed['id'],'action':'check'})
        self.assertEqual(run['status'],'completed',run)
        accepted=self.accept(run,fixed)
        issues=accepted['document']['issues'];self.assertTrue(issues);self.assertFalse([r for r in issues if r['severity']=='error'],issues)
        xlsx=self.service.text_tool_export(self.p,accepted['id'],'xlsx')[0]
        from vsc.assets.source_intake import extract_source
        parsed=extract_source(xlsx,'xlsx',{'column_mapping':{'sheet':'Report','columns':{'text':'G','kind':'F'},'start_row':2}})
        self.assertIn('所选本地技术检查通过',parsed['text'])
        package=self.service.text_tool_export(self.p,accepted['id'],'zip')[0]
        with zipfile.ZipFile(io.BytesIO(package)) as z:
            video=next(n for n in z.namelist() if '/videos/' in n);self.assertEqual(z.read(video),path.read_bytes());self.assertTrue(any(n.endswith('.srt') for n in z.namelist()))
        self.assertEqual(len(self.service.text_tool_host.calls),0)

    def test_breakdown_and_nonzero_group_mapping_import_edit_workspace(self):
        media,path=self.video(duration=4)
        breakdown=self.save('breakdown',self.draft('breakdown',understanding_mode='manual',media_id=media,observations=[{'start_ms':1000,'end_ms':1500,'kind':'镜头','text':'合成测试图移动'}]))
        timed=self.service.text_tool_export(self.p,breakdown['id'],'timestamp-txt')[0].decode();plain=self.service.text_tool_export(self.p,breakdown['id'],'txt')[0].decode()
        self.assertIn('00:00:01.000',timed);self.assertNotIn('00:00:01.000',plain)
        objects=self.hierarchy()
        groups=[{'key':'g1','source_start_ms':500,'source_end_ms':1500,'candidate_media_id':media,'candidate_in_ms':0},{'key':'g2','source_start_ms':2000,'source_end_ms':3000,'candidate_media_id':media,'candidate_in_ms':1000}]
        segments=[{'key':'s2','group':'g2','source_start_ms':2200,'source_end_ms':2500,'localized_text':'第二组内200ms开始'}]
        overseas=self.save('overseas',self.draft('overseas',source_media_id=media,target_language='English',understanding='合成图案，无故事判断',groups=groups,segments=segments),episode=objects['episode'])
        read=self.service.get_text_tool(self.p,overseas['unit_id']);self.assertEqual(read['mapping'][0]['group_start_ms'],200)
        request={'unit_id':overseas['unit_id'],'version_id':overseas['id'],'episode_id':objects['episode']}
        preview=self.service.preview_text_tool_import(self.p,request)
        result=self.write('import_text_tool',{'request':request,'preview_sha256':preview['preview_sha256']})
        original=self.service.get_edit_workspace(self.p,objects['episode'])['current']['document']
        self.assertEqual([(r['in_frame'],r['out_frame']) for r in original['clips']],[(0,24),(24,48)])
        with self.assertRaises(Conflict):self.write('import_text_tool',{'request':request,'preview_sha256':preview['preview_sha256']})
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_unknown_attempt_recovery_preserves_fixed_input_and_blocks_unknown_retry(self):
        from sqlalchemy import insert
        from datetime import datetime,timedelta,timezone
        from vsc.adapters.persistence.postgres import schema as S
        saved=self.save('novel',self.draft('novel',body='fixed manual'))
        attempt=str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.text_tool_attempts).values(project_id=self.p,id=attempt,unit_id=saved['unit_id'],input_version_id=saved['id'],action='body',backend='synthetic',status='running',created_by='test-human',created_at=datetime.now(timezone.utc)-timedelta(minutes=11)))
        running=self.write('run_text_tool',{'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'body','new_attempt':True})
        self.assertEqual(running['id'],attempt);self.assertEqual(len(self.service.text_tool_host.calls),0)
        recovery=self.write('recover_text_tool_attempt',{'attempt_id':attempt})
        self.assertEqual(recovery['status'],'submission_unknown')
        run=self.write('run_text_tool',{'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'body','new_attempt':True})
        self.assertEqual(run['status'],'submission_unknown');self.assertEqual(run['id'],attempt)
        self.assertEqual(len(self.service.text_tool_host.calls),0)
        self.assertEqual(self.service.get_text_tool(self.p,saved['unit_id'])['document']['body'],'fixed manual')

    def test_host_result_survives_member_revocation_and_owner_recovers_without_new_call(self):
        import secrets
        from datetime import datetime,timedelta,timezone
        from sqlalchemy import select,update
        from sqlalchemy.exc import DBAPIError
        from vsc.assets.access_control import Principal,set_principal,reset_principal,current_principal
        from vsc.adapters.persistence.postgres import schema as S
        saved=self.save('novel',self.draft('novel',body='manual remains'))
        owner=self.service.ensure_local_access('test-human')
        token=set_principal(Principal(**owner))
        def command(action,payload):
            return self.service.access_command(action,payload,actor=current_principal().actor,
                expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex)
        try:
            preview=self.service.access_migration_preview(self.p,owner['workspace_id'])
            command('assign-project',dict(project_id=self.p,workspace_id=owner['workspace_id'],preview_sha256=preview['sha256']))
            secret=secrets.token_urlsafe(32)
            command('invitation',dict(scope='project',scope_id=self.p,role='editor',secret=secret,
                expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
            member=self.service.accept_access_invitation(dict(invitation_secret=secret,
                credential_secret=secrets.token_urlsafe(32),display_name='synthetic text member'))
            original=self.service.text_tool_host.generate
            def generate(*args,**kwargs):
                owner_token=set_principal(Principal(**owner))
                try:command('member',dict(scope='project',scope_id=self.p,identity_id=member['identity_id'],role='editor',active=False))
                finally:reset_principal(owner_token)
                return original(*args,**kwargs)
            self.service.text_tool_host.generate=generate
            member_token=set_principal(Principal(**member))
            try:
                with self.assertRaises(ResourceError) as caught:
                    self.service.run_text_tool(self.p,dict(unit_id=saved['unit_id'],input_version_id=saved['id'],action='body',new_attempt=True),
                        actor=member['actor'],expected_revision=self.store.get_project(self.p)['revision'],idempotency_key='revoked-during-host')
                self.assertEqual(caught.exception.status_code,403)
            finally:reset_principal(member_token)
            with self.engine.connect() as conn:
                receipt=conn.execute(select(S.text_tool_receipts).where(S.text_tool_receipts.c.project_id==self.p)).mappings().one()
            self.assertEqual(receipt['result']['body'],'建议结果，尚未接受')
            self.rev=self.store.get_project(self.p)['revision']
            recovered=self.write('recover_text_tool_attempt',dict(attempt_id=receipt['attempt_id']))
            self.assertEqual(recovered['status'],'completed')
            self.assertEqual(len(self.service.text_tool_host.calls),1)
            self.assertEqual(self.service.get_text_tool(self.p,saved['unit_id'])['document']['body'],'manual remains')
            with self.assertRaises(DBAPIError),self.engine.begin() as conn:
                conn.execute(update(S.text_tool_receipts).where(S.text_tool_receipts.c.project_id==self.p).values(result={'body':'replacement'}))
        finally:reset_principal(token)

    def test_standalone_workspace_and_fixed_cross_project_copy_keep_original_authority(self):
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        owner=self.service.ensure_local_access('test-human');token=set_principal(Principal(**owner))
        try:
            workspace=self.service.open_text_tool_workspace(actor='test-human')
            self.assertEqual(workspace['id'],self.service.open_text_tool_workspace(actor='test-human')['id'])
            self.assertEqual(workspace['profile'],'vsc.text-tools')
            self.assertEqual(self.service.get_project_tree(workspace['id'])['nodes'],[])
            target=self.p;self.p=workspace['id'];self.rev=workspace['revision']
            saved=self.save('translation',self.draft('translation',body='fixed translated words',target_language='English',proofread=True))
            source=self.service.get_text_tool(self.p,saved['unit_id'])
            request=dict(source_project_id=self.p,source_unit_id=saved['unit_id'],source_version_id=saved['id'],source_sha256=source['sha256'])
            before=self.service.get_project(self.p)['revision']
            # The owner explicitly binds the destination project before reuse.
            preview=self.service.access_migration_preview(target,owner['workspace_id'])
            self.service.access_command('assign-project',dict(project_id=target,workspace_id=owner['workspace_id'],preview_sha256=preview['sha256']),
                actor='test-human',expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex)
            plan=self.service.preview_text_tool_copy(target,request)
            payload={'request':request,'preview_sha256':plan['preview_sha256']}
            copied=self.service.copy_text_tool_to_project(target,payload,actor='test-human',expected_revision=plan['revision'],idempotency_key='one-fixed-copy')
            again=self.service.copy_text_tool_to_project(target,payload,actor='test-human',expected_revision=plan['revision'],idempotency_key='one-fixed-copy')
            self.assertEqual(copied,again)
            self.assertEqual(self.service.get_project(self.p)['revision'],before)
            document=self.service.get_text_tool(target,copied['unit_id'])['document']
            self.assertEqual(document['body'],'fixed translated words');self.assertFalse(document['proofread'])
            with self.engine.connect() as conn:
                self.assertEqual(conn.execute(select(func.count()).select_from(S.text_tool_copies).where(S.text_tool_copies.c.project_id==target)).scalar_one(),1)
            bad=dict(request,source_sha256='0'*64)
            with self.assertRaises(Conflict):self.service.preview_text_tool_copy(target,bad)
            other=self.service.ensure_local_access('other-tool-human');other_token=set_principal(Principal(**other))
            try:
                own=self.service.open_text_tool_workspace(actor='other-tool-human')
                self.assertNotEqual(own['id'],workspace['id'])
                with self.assertRaises(ResourceError):self.service.preview_text_tool_copy(own['id'],request)
            finally:reset_principal(other_token)
        finally:reset_principal(token)

    def test_http_session_save_extract_export_and_db_scope_constraints(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        app=create_app({'projects_root':str(self.root/'projects'),'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test','human_identity':'test-human','background_enabled':False},service=self.service)
        with TestClient(app) as client:
            base='/api/v1/projects/'+self.p+'/text-tools'
            payload={'tool':'novel','group_key':'http','unit_key':'1','title':'HTTP','ordinal':0,'episode_id':None,'document':self.draft('novel',body='实际HTTP标记'),'base_version_id':None}
            body={'payload':payload,'expected_revision':self.rev,'idempotency_key':uuid.uuid4().hex}
            self.assertEqual(client.post(base+'/units',json=body).status_code,403)
            login=client.post('/api/v1/session',json={'token':'test'},headers={'Origin':'http://testserver'}).json();headers={'Origin':'http://testserver','X-CSRF-Token':login['csrf_token']}
            saved=client.post(base+'/units',json=body,headers=headers);self.assertEqual(saved.status_code,200,saved.text);row=saved.json();self.rev=row['revision']
            self.assertEqual(client.post(base+'/units',json=body,headers=headers).json(),row)
            self.assertIn('实际HTTP标记',client.get(base+'/exports/'+row['id']+'?format=txt').text)
            raw='第1章 起点\n甲\n第2章 再会\n乙'
            response=client.post(base+'/extract',json={'payload':{'content_base64':base64.b64encode(raw.encode()).decode(),'format':'txt','split':'chapters'}},headers=headers)
            self.assertEqual(len(response.json()['units']),2,response.text)
            self.assertEqual(client.get(base+'/options').status_code,200)
            self.assertIn('text-tools.css',client.get('/').text)
        other=self.save('translation',self.draft('translation',body='another'))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:conn.execute(update(S.text_tool_units).where(S.text_tool_units.c.project_id==self.p,S.text_tool_units.c.id==row['unit_id']).values(current_version_id=other['id']))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:conn.execute(update(S.text_tool_units).where(S.text_tool_units.c.project_id==self.p,S.text_tool_units.c.id==row['unit_id']).values(tool='translation'))

    def test_translation_style_versions_fixed_selection_and_original_host_attempt(self):
        first=self.write('save_translation_style',{'style_id':None,'base_version_id':None,'title':'克制风格','language':'English','content':'Short sentences; preserve names.'})
        saved=self.save('translation',self.draft('translation',target_language='English',source_text='固定原文',style_version_id=first['id']))
        self.assertEqual(saved['document']['style'],'Short sentences; preserve names.')
        second=self.write('save_translation_style',{'style_id':first['style_id'],'base_version_id':first['id'],'title':'克制风格','language':'English','content':'Second version.'})
        self.assertNotEqual(second['id'],first['id'])
        self.assertEqual(self.service.get_text_tool(self.p,saved['unit_id'])['document']['style_version_id'],first['id'])
        with self.assertRaises(Conflict):self.write('save_translation_style',{'style_id':first['style_id'],'base_version_id':first['id'],'title':'stale','language':'English','content':'bad'})
        suggest=self.save('translation',self.draft('translation',source_text='参考段落',style_request=True,body='人工译文保持'))
        run=self.write('run_text_tool',{'unit_id':suggest['unit_id'],'input_version_id':suggest['id'],'action':'translate'})
        accepted=self.accept(run,suggest)
        self.assertEqual(accepted['document']['body'],'人工译文保持')
        self.assertIn('建议结果',accepted['document']['style'])
        self.assertEqual(self.service.text_tool_host.calls[-1][:2],('translation-style','body'))

    def test_novel_diff_original_episode_draft_requirements_replay_and_approval_preserved(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects=self.hierarchy()
        saved=self.save('novel',self.draft('novel',body='人工固定正文',characters=[{'name':'林','description':'固定人物需求'}]))
        request={'unit_id':saved['unit_id'],'version_id':saved['id'],'episode_id':None,'new_episode':{'work_id':objects['work'],'display_code':'EP-NEW','title':'新集','ordinal':1},'scene_id':None,'new_scene_title':'明确工作场','asset_mapping':{}}
        preview=self.service.preview_novel_tool_import(self.p,request)
        imported=self.write('import_text_tool_novel',{'request':request,'preview_sha256':preview['preview_sha256']})
        again=self.write('import_text_tool_novel',{'request':request,'preview_sha256':preview['preview_sha256']})
        self.assertEqual(again['episode_id'],imported['episode_id']);self.assertTrue(again['already_imported'])
        with self.engine.connect() as conn:
            draft=conn.execute(select(S.script_drafts).where(S.script_drafts.c.project_id==self.p,S.script_drafts.c.scope_key==imported['episode_id'])).mappings().one()
            self.assertEqual(draft['content']['body'],'人工固定正文')
            req=conn.execute(select(S.asset_requirements).where(S.asset_requirements.c.project_id==self.p,S.asset_requirements.c.artifact_id==imported['requirements_version_id'])).mappings().one()
            self.assertEqual(req['scene_id'],imported['scene_id']);self.assertIsNone(req['asset_id'])
        baseline=self.artifact('fixed-screenplay','screenplay',[objects['episode']],{'body':'批准原文'})
        second=self.save('novel',self.draft('novel',body='修改建议正文',characters=[]))
        target={'unit_id':second['unit_id'],'version_id':second['id'],'episode_id':objects['episode'],'scene_id':objects['scene'],'asset_mapping':{}}
        preview=self.service.preview_novel_tool_import(self.p,target)
        result=self.write('import_text_tool_novel',{'request':target,'preview_sha256':preview['preview_sha256']})
        self.assertEqual(json.loads(self.service.get_artifact_version(self.p,baseline)['document'])['body'],'批准原文')
        self.assertTrue(self.service.get_artifact_version(self.p,baseline)['approved'])
        third=self.save('novel',self.draft('novel',body='另一次正文'))
        target['unit_id'],target['version_id']=third['unit_id'],third['id']
        preview=self.service.preview_novel_tool_import(self.p,target)
        self.service.save_script_draft(self.p,{'scope_key':objects['episode'],'base_draft_revision':1,'content':{'body':'期间人工修改'}},actor='test-human')
        with self.assertRaises(Conflict):self.write('import_text_tool_novel',{'request':target,'preview_sha256':preview['preview_sha256']})

    def test_qc_partial_rules_evidence_and_subtitle_original_editor(self):
        from unittest.mock import patch
        objects=self.hierarchy();mid,path=self.video(duration=3)
        subtitle={'filename':'a.srt','text':'1\n00:00:00,500 --> 00:00:01,000\n前句\n\n2\n00:00:01,500 --> 00:00:02,000\n后句'}
        saved=self.save('qc',self.draft('qc',videos=[{'media_id':mid,'name':'','sha256':''}],subtitles=[subtitle],checks=['metadata','subtitles','decode']),episode=objects['episode'])
        run=self.write('run_text_tool',{'unit_id':saved['unit_id'],'input_version_id':saved['id'],'action':'check'})
        old=self.accept(run,saved)
        changed=deepcopy(old['document']);changed.update(base_report_version_id=old['id'],check_ranges=[{'media_id':mid,'start_ms':1000,'end_ms':2500}],checks=['decode'])
        local=self.save('qc',changed,old,episode=objects['episode'])
        from vsc.post.local_media_tools import command
        with patch('vsc.post.local_media_tools.command',wraps=command) as actual:
            rerun=self.write('run_text_tool',{'unit_id':local['unit_id'],'input_version_id':local['id'],'action':'check'})
        self.assertEqual(len(actual.call_args_list),1)
        args=actual.call_args_list[0].args[0];self.assertEqual(args[args.index('-ss')+1],'1.0');self.assertEqual(args[args.index('-t')+1],'1.5')
        updated=self.accept(rerun,local)
        self.assertEqual([(r['start_ms'],r['end_ms']) for r in updated['document']['issues'] if r['rule']=='metadata'],[(0,3000)])
        self.assertEqual(sorted((r['start_ms'],r['end_ms']) for r in updated['document']['issues'] if r['rule']=='decode'),[(0,1000),(1000,2500),(2500,3000)])
        evidence=self.write('capture_text_tool_evidence',{'version_id':updated['id'],'issue_index':0})
        with patch('vsc.post.local_media_tools.frame',side_effect=AssertionError('duplicate frame')):
            repeated=self.write('capture_text_tool_evidence',{'version_id':updated['id'],'issue_index':0})
        self.assertEqual(evidence['media_id'],repeated['media_id'])
        self.assertEqual(self.service.get_media(self.p,evidence['media_id'])['modality'],'image')
        self.write('save_edit_workspace',{'episode_id':objects['episode'],'edit_revision':0,'document':{'format':'vsc.edit-workspace/v1','width':128,'height':128,'fps':24,'clips':[{'id':'clip','media_id':mid,'in_frame':24,'out_frame':72,'volume':1,'muted':False}],'audio':[],'captions':[]}})
        request={'version_id':updated['id'],'episode_id':objects['episode'],'clip_id':'clip','subtitle_filename':'a.srt'}
        preview=self.service.preview_text_tool_subtitles(self.p,request)
        self.assertEqual(preview['plan']['document']['captions'][0]['start_frame'],12)
        result=self.write('apply_text_tool_subtitles',{'request':request,'preview_sha256':preview['preview_sha256']})
        data,_,temporary=self.service.export_edit_workspace(self.p,result['edit_version_id'],'srt')
        try:self.assertIn('后句',data.read_text());self.assertNotIn('前句',data.read_text())
        finally:temporary.cleanup()
        with self.assertRaises(Conflict):self.write('apply_text_tool_subtitles',{'request':request,'preview_sha256':preview['preview_sha256']})

class TextToolHostContractTests(unittest.TestCase):
    def test_single_turn_tool_free_host_parses_structured_output(self):
        from vsc.production.text_tool_host import GrokBuildTextTools
        calls=[]
        def runner(command,**kw):
            prompt=Path(command[command.index('--prompt-file')+1]).read_text()
            calls.append((command,prompt,kw))
            return subprocess.CompletedProcess(command,0,stdout=json.dumps({'structuredOutput':{'body':'translated'}}),stderr='')
        host=GrokBuildTextTools(runner=runner)
        result=host.generate('translation','translate',normalize_document('translation',dict(DEFAULTS['translation'],source_text='fixed source')),[])
        self.assertEqual(result,{'body':'translated'})
        command,prompt,kw=calls[0];self.assertIn('--no-subagents',command);self.assertIn('--disable-web-search',command)
        self.assertEqual(command[command.index('--tools')+1],'');self.assertEqual(command[command.index('--max-turns')+1],'1')
        self.assertEqual(kw['timeout'],120);self.assertIn('fixed source',prompt)

    def test_host_timeout_is_unknown_and_schema_violation_cannot_be_adopted(self):
        from vsc.production.text_tool_host import GrokBuildTextTools
        from vsc.assets.text_tools import validated_result
        def runner(command,**kw):raise subprocess.TimeoutExpired(command,kw['timeout'])
        with self.assertRaises(ResourceError) as raised:GrokBuildTextTools(runner=runner).generate('novel','body',{},[])
        self.assertEqual(raised.exception.code,'text_submission_unknown')
        with self.assertRaises(ResourceError):validated_result('novel','body',{'body':'x','approve':True},normalize_document('novel',DEFAULTS['novel']))
