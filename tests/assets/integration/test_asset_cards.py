"""Project cards preserve original specs and media through copies and episode aliases."""
import unittest
import uuid
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.resource_service import ResourceError,Conflict

@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class AssetCardTests(ResourceStoreFixture,unittest.TestCase):
    def card(self,name='人物',kind='character',media=None,voice=None):
        return self.write('save_asset_card',dict(name=name,asset_kind=kind,base_revision=0,forms=[dict(form_key='master',name='默认形态',base_version_id=None,description='明确的形态描述',media_id=media,voice_spec_id=voice)]))

    def test_fixed_blocking_projection_is_opt_in_paged_and_respects_recycle(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        import tempfile
        objects=self.hierarchy();image=self.media('站位参考')
        candidate=self.write('propose_binding',dict(target_object_id=objects['shot'],media_id=image,role='first_frame',slot_key='station'))
        selection=self.write('save_working_selection',dict(shot_id=objects['shot'],output_kind='image',candidate_id=candidate['candidate_id'],base_version_id=None))
        flow=self.write('create_intelligent_workflow',dict(episode_id=objects['episode'],title='流程',route='storyboard',script_text='合成剧本'))['id']
        state=self.service.get_intelligent_workflow(self.p,flow)
        body=state['state'];body['units']=[dict(unit_key='station',kind='blocking',title='B 站位',description='',duration_ms=5000,
            segments=[dict(start_ms=0,end_ms=5000,text='等待')],skip_reason='',lineart_purpose='none',shot_id=objects['shot'],spatial_version_id=None)]
        body['media']=[dict(unit_key='station',purpose='blocking',media_id=image,decision_id=None,
            working_selection_version_id=selection['selection_version_id'],spatial_export_id=None)]
        payload=dict(workflow_id=flow,base_version_id=state['version']['id'],state=body)
        impact=self.service.preview_intelligent_change(self.p,payload)
        saved=self.write('save_intelligent_workflow',dict(payload,impact_sha256=impact['sha256']))
        self.write('save_working_selection',dict(shot_id=objects['shot'],output_kind='image',candidate_id=None,base_version_id=selection['selection_version_id']))
        self.card('A 人物');self.card('C 人物')
        self.assertEqual(self.service.list_asset_cards(self.p)['total'],2)
        pages=[self.service.list_asset_cards(self.p,include_blocking=True,offset=i,limit=1) for i in range(3)]
        self.assertEqual([p['total'] for p in pages],[3,3,3])
        rows=[p['items'][0] for p in pages];self.assertEqual([r['name'] for r in rows],['A 人物','B 站位','C 人物'])
        station=rows[1];self.assertEqual(station['record_kind'],'blocking');self.assertEqual(station['source']['version_id'],saved['version_id'])
        self.assertEqual(station['source']['media_id'],image);self.assertEqual(station['forms'],[]);self.assertEqual(station['preview']['media_id'],image)
        self.assertEqual(self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['total'],1)
        self.assertEqual(self.service.list_asset_cards(self.p,query='站位',include_blocking=True)['total'],1)
        self.assertEqual(self.service.list_asset_cards(self.p,include_blocking=True,favorites=True,actor='test-human')['total'],0)
        with self.assertRaises(ResourceError):self.service.list_asset_cards(self.p,asset_kind='blocking')
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test',
                'human_identity':'test-human','background_enabled':False},catalog=ResourceCatalog(root,service=self.service))
            with TestClient(app) as client:
                client.post('/api/v1/session',json={'token':'test'},headers={'origin':'http://testserver'})
                path='/api/v1/projects/'+self.p+'/asset-cards'
                response=client.get(path,params={'asset_kind':'blocking','include_blocking':'true'})
                self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['total'],1)
                self.assertEqual(client.get(path,params={'asset_kind':'blocking'}).status_code,422)
        parent=objects['work'];second={}
        for kind in ('episode','scene','sequence','shot'):
            row=self.write('create_object',dict(kind=kind,display_code=kind+'2',parent_id=parent,ordinal=1))
            second[kind]=row['id'];parent=row['id']
        candidate2=self.write('propose_binding',dict(target_object_id=second['shot'],media_id=image,role='first_frame',slot_key='station'))
        selection2=self.write('save_working_selection',dict(shot_id=second['shot'],output_kind='image',candidate_id=candidate2['candidate_id'],base_version_id=None))
        flow2=self.write('create_intelligent_workflow',dict(episode_id=second['episode'],route='storyboard',script_text='第二集'))['id']
        current2=self.service.get_intelligent_workflow(self.p,flow2);state2=current2['state']
        state2['units']=[dict(body['units'][0],unit_key='second',title='D 站位',shot_id=second['shot'])]
        state2['media']=[dict(unit_key='second',purpose='blocking',media_id=image,decision_id=None,
            working_selection_version_id=selection2['selection_version_id'],spatial_export_id=None)]
        payload2=dict(workflow_id=flow2,base_version_id=current2['version']['id'],state=state2)
        self.write('save_intelligent_workflow',dict(payload2,impact_sha256=self.service.preview_intelligent_change(self.p,payload2)['sha256']))
        self.assertEqual({r['source']['episode_id'] for r in self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['items']},
            {objects['episode'],second['episode']})
        other=self.service.create_project({'name':'隔离项目'},actor='test-human')['id']
        self.assertEqual(self.service.list_asset_cards(other,asset_kind='blocking',include_blocking=True)['total'],0)
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        owner=self.service.ensure_local_access('test-human');owner_token=set_principal(Principal(**owner))
        try:
            migration=self.service.access_migration_preview(self.p,owner['workspace_id'])
            self.service.access_command('assign-project',dict(project_id=self.p,workspace_id=owner['workspace_id'],preview_sha256=migration['sha256']),
                expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
            unauthorized=set_principal(Principal(local_read=True))
            try:
                with self.assertRaises(ResourceError):self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)
            finally:reset_principal(unauthorized)
            self.write('management_command',dict(operation='trash',target_type='object',target_id=objects['episode'],reason='测试回收'))
            self.assertEqual(self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['total'],1)
            self.write('management_command',dict(operation='restore',target_type='object',target_id=objects['episode'],reason='测试恢复'))
            self.assertEqual(self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['total'],2)
        finally:reset_principal(owner_token)
        self.write('decide_rights',dict(media_id=image,outcome='revoked',reason='测试撤权'))
        revoked=self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['items'][0]
        self.assertIsNone(revoked['preview']);self.assertIn('rights_unknown_or_restricted',revoked['availability_gaps'])
        self.write('decide_media_lifecycle',dict(media_id=image,outcome='deprecate',reason='测试回收'))
        self.assertEqual(self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['total'],0)

    def test_blocking_projection_rejects_inconsistent_fixed_source_and_deduplicates_export(self):
        import tempfile
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.spatial_scene import default_scene
        objects=self.hierarchy();other=self.media('错误的图')
        previous_storage=self.service.storage
        self.addCleanup(setattr,self.service,'storage',previous_storage)
        with tempfile.TemporaryDirectory() as directory:
            self.service.storage=LocalStorage(directory)
            doc=default_scene();doc.update(width=320,height=180)
            scene=self.write('create_spatial_scene',dict(mode='blocking',scene_id=objects['scene'],document=doc,title='站位'))
            exported=self.write('create_spatial_export',dict(spatial_scene_id=scene['id'],scene_revision=1,camera_id='camera-b',format='png',time=.25))
            complete=self.service.execute_spatial_export(self.p,exported['id']);self.rev=self.service.get_project(self.p)['revision']
            self.assertEqual(complete['status'],'succeeded');image=complete['media_id']
            fixed=self.service.get_spatial_scene(self.p,scene['id'])['version_id']
            flow=self.write('create_intelligent_workflow',dict(episode_id=objects['episode'],route='storyboard',script_text='合成剧本'))['id']
            current=self.service.get_intelligent_workflow(self.p,flow);state=current['state'];state['blocking_mode']='3d'
            def unit(key):return dict(unit_key=key,kind='blocking',title='站位'+key,description='',duration_ms=5000,
                segments=[dict(start_ms=0,end_ms=5000,text='等')],skip_reason='',lineart_purpose='none',shot_id=objects['shot'],spatial_version_id=fixed)
            state['units']=[unit('one'),unit('two'),unit('mismatch')]
            state['media']=[dict(unit_key=key,purpose='blocking',media_id=mid,decision_id=None,spatial_export_id=exported['id'])
                for key,mid in [('one',image),('two',image),('mismatch',other)]]
            payload=dict(workflow_id=flow,base_version_id=current['version']['id'],state=state)
            impact=self.service.preview_intelligent_change(self.p,payload)
            with self.assertRaises(ResourceError):self.write('save_intelligent_workflow',dict(payload,impact_sha256=impact['sha256']))
            state['units']=state['units'][:2];state['media']=state['media'][:2]
            impact=self.service.preview_intelligent_change(self.p,payload);self.write('save_intelligent_workflow',dict(payload,impact_sha256=impact['sha256']))
            found=self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)
            self.assertEqual(found['total'],1);self.assertEqual(found['items'][0]['source']['media_id'],image)
            self.assertEqual(found['items'][0]['source']['spatial_export_id'],exported['id'])
            self.assertEqual(found['items'][0]['preview']['media_id'],image)
            self.assertIn('technical_check_missing',found['items'][0]['availability_gaps'])
            # A browseable screenshot is not a production approval. The real
            # selection consumer still requires its technical check.
            candidate=self.candidate(objects['shot'],image)
            with self.assertRaises(ResourceError) as failure:self.select(candidate)
            self.assertIn('technical_check_missing',str(failure.exception))
            self.write('decide_rights',dict(media_id=image,outcome='revoked',reason='测试撤销来源'))
            blocked=self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['items'][0]
            self.assertIsNone(blocked['preview']);self.assertIn('rights_unknown_or_restricted',blocked['availability_gaps'])

    def test_prop_filter_opt_in_groups_legacy_objects_before_pagination(self):
        import tempfile
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        assets={}
        for name,kind in [('A prop','prop'),('B object','object'),('C prop','prop'),('D person','character')]:
            assets[name]=self.write('create_object',dict(kind='asset',asset_kind=kind,display_code=uuid.uuid4().hex,title=name))['id']
        other=self.service.create_project({'name':'其他项目'},actor='test-human')['id']
        self.service.create_object(other,dict(kind='asset',asset_kind='object',display_code='OTHER',title='AA other project'),
            actor='test-human',expected_revision=0,idempotency_key='other-object')
        legacy=self.service.list_asset_cards(self.p,asset_kind='prop')
        self.assertEqual([row['id'] for row in legacy['items']],[assets['A prop'],assets['C prop']])
        self.assertEqual([row['id'] for row in self.service.list_asset_cards(self.p,asset_kind='object')['items']],[assets['B object']])
        first=self.service.list_asset_cards(self.p,asset_kind='prop',include_object=True,limit=2)
        second=self.service.list_asset_cards(self.p,asset_kind='prop',include_object=True,limit=2,offset=first['next_offset'])
        self.assertEqual(first['total'],3);self.assertEqual(second['total'],3);self.assertIsNone(second['next_offset'])
        self.assertEqual([row['id'] for row in first['items']+second['items']],
            [assets['A prop'],assets['B object'],assets['C prop']])
        self.assertEqual([row['asset_kind'] for row in first['items']+second['items']],['prop','object','prop'])
        self.write('favorite_asset_card',dict(asset_id=assets['B object'],active=True))
        favorites=self.service.list_asset_cards(self.p,asset_kind='prop',include_object=True,actor='test-human',favorites=True)
        self.assertEqual([row['id'] for row in favorites['items']],[assets['B object']])
        self.assertEqual(self.service.list_asset_cards(self.p,asset_kind='prop',include_object=True,query='object')['total'],1)
        for kind in ('','object','character'):
            with self.subTest(kind=kind),self.assertRaises(ResourceError):
                self.service.list_asset_cards(self.p,asset_kind=kind,include_object=True)
        with self.assertRaises(ResourceError):self.service.list_asset_cards(self.p,asset_kind='prop',include_object='true')
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test',
                'human_identity':'test-human','background_enabled':False},catalog=ResourceCatalog(root,service=self.service))
            with TestClient(app) as client:
                client.post('/api/v1/session',json={'token':'test'},headers={'origin':'http://testserver'})
                path='/api/v1/projects/'+self.p+'/asset-cards'
                combined=client.get(path,params={'asset_kind':'prop','include_object':'true','limit':2})
                self.assertEqual(combined.status_code,200,combined.text);self.assertEqual(combined.json()['total'],3)
                self.assertEqual([row['id'] for row in combined.json()['items']],[assets['A prop'],assets['B object']])
                self.assertEqual(client.get(path,params={'asset_kind':'prop'}).json()['total'],2)
                self.assertEqual(client.get(path,params={'asset_kind':'character','include_object':'true'}).status_code,422)
                self.assertEqual(client.get(path,params={'asset_kind':'prop','include_object':'invalid'}).status_code,422)

    def legacy_asset(self,name='旧人物'):
        asset=self.write('create_object',dict(kind='asset',asset_kind='character',display_code=uuid.uuid4().hex,title=name))['id']
        spec=dict(id=str(uuid.uuid4()),asset_id=asset,variant_key='master',description='旧版固定形态')
        self.write('create_artifact',dict(artifact_key='legacy-'+uuid.uuid4().hex,artifact_type='asset-bible',
            document={'asset_specs':[spec]},object_ids=[asset],asset_specs=[spec]))
        return asset,spec['id']

    def test_legacy_preview_is_current_usable_selection_and_does_not_change_forms(self):
        from sqlalchemy import insert,select,update
        from vsc.adapters.persistence.postgres import schema as S
        previous_storage=self.service.storage;self.service.storage=None
        self.addCleanup(setattr,self.service,'storage',previous_storage)
        asset,spec=self.legacy_asset();empty=self.service.get_asset_card(self.p,asset)
        self.assertIsNone(empty['preview']);self.assertEqual(empty['forms'][0]['spec_id'],spec)
        self.assertIsNone(empty['forms'][0]['media_id'])
        face1=self.media('人像一');face2=self.media('人像二');costume=self.media('服装')
        first=self.candidate(asset,face1,role='identity_face',slot_key='front',variant_spec_id=spec);self.select(first)
        second=self.candidate(asset,face2,role='identity_face',slot_key='side')
        selection=self.select(second)
        costume_candidate=self.candidate(asset,costume,role='costume',slot_key='outfit');self.select(costume_candidate)
        card=self.service.get_asset_card(self.p,asset);preview=card['preview']
        self.assertEqual(preview,dict(media_id=face2,source='current_binding',slot_id=second['slot_id'],slot_key='side',role='identity_face',variant_spec_id=None,candidate_id=second['candidate_id'],decision_id=selection['decision_id']))
        self.assertIsNone(card['forms'][0]['media_id'])
        self.assertEqual(self.service.list_asset_cards(self.p)['items'][0]['preview'],preview)
        # A selected historical registration may become invalid later. A
        # recycle action linked to its lifecycle decision represents that case.
        deprecated=self.write('decide_media_lifecycle',dict(media_id=face2,outcome='deprecate',reason='历史用料失效'))
        with self.engine.begin() as conn:
            conn.execute(insert(S.media_recycle_actions).values(project_id=self.p,id=str(uuid.uuid4()),media_id=face2,decision_id=deprecated['id']))
        preview=self.service.get_asset_card(self.p,asset)['preview']
        self.assertEqual(preview['media_id'],face1);self.assertEqual(preview['variant_spec_id'],spec)
        with self.engine.begin() as conn:
            blob=conn.execute(select(S.media_items.c.blob_id).where(S.media_items.c.project_id==self.p,S.media_items.c.id==face1)).scalar_one()
            conn.execute(update(S.blob_locations).where(S.blob_locations.c.blob_id==blob).values(available=False))
        self.assertEqual(self.service.get_asset_card(self.p,asset)['preview']['media_id'],costume)
        self.write('decide_media_lifecycle',dict(media_id=face1,outcome='deprecate',reason='不再有效'))
        self.assertEqual(self.service.get_asset_card(self.p,asset)['preview']['media_id'],costume)
        self.write('retire_binding',dict(slot_id=costume_candidate['slot_id'],reason='结束选择'))
        self.assertIsNone(self.service.get_asset_card(self.p,asset)['preview'])
        self.assertIsNone(self.service.get_asset_card(self.p,asset)['forms'][0]['media_id'])

    def test_preview_does_not_cross_project_or_override_working_card(self):
        previous_storage=self.service.storage;self.service.storage=None
        self.addCleanup(setattr,self.service,'storage',previous_storage)
        asset,_=self.legacy_asset();image=self.media('旧选图')
        chosen=self.candidate(asset,image,role='identity_face');self.select(chosen)
        target=self.service.create_project({'name':'另一项目'},actor='test-human')['id']
        with self.assertRaises(ResourceError):self.service.get_asset_card(target,asset)
        self.assertEqual(self.service.list_asset_cards(target)['items'],[])
        result=self.write('save_asset_card',dict(asset_id=asset,name='已有工作卡',asset_kind='character',base_revision=0,
            forms=[dict(form_key='master',name='默认',base_version_id=None,description='工作卡优先',media_id=None)]))
        card=self.service.get_asset_card(self.p,asset)
        self.assertEqual(card['revision'],1);self.assertIsNone(card['preview']);self.assertIsNone(card['forms'][0]['media_id'])
        self.assertEqual(result['forms'][0]['media_id'],None)

    def test_original_specs_history_voice_and_episode_alias_refresh(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        nodes=self.hierarchy();media=self.media();audio=self.media('音色',modality='audio')
        voice=self.card('人物声线','voice',audio);voice_id=self.service.get_asset_card(self.p,voice['id'])['forms'][0]['voice_spec_id']
        created=self.card(media=media,voice=voice_id);card=self.service.get_asset_card(self.p,created['id']);first=card['forms'][0]
        self.assertEqual(card['revision'],1);self.assertEqual(first['voice_spec_id'],voice_id)
        self.write('reference_asset_card',dict(asset_id=card['id'],asset_revision=1,episode_ids=[nodes['episode']]))
        original=self.service.list_episode_assets(self.p,nodes['episode'])['items'][0];form=original['forms'][0];old=form['current_version_id']
        self.write('save_episode_asset',dict(id=original['id'],episode_id=nodes['episode'],asset_key=original['asset_key'],asset_kind='character',name='本集别名',base_revision=original['revision'],forms=[dict(form_key='master',name='本集夜装',base_version_id=old,source_asset_id=card['id'],spec_id=first['spec_id'],media_id=media)]))
        self.write('save_asset_card',dict(asset_id=card['id'],name='新的项目名',asset_kind='character',base_revision=1,forms=[dict(form_key='master',name='新的项目形态',base_version_id=first['version_id'],description='新描述',media_id=media,voice_spec_id=voice_id)]))
        updated=self.service.get_asset_card(self.p,card['id']);self.assertEqual(len(updated['forms'][0]['history']),2)
        self.write('reference_asset_card',dict(asset_id=card['id'],asset_revision=2,episode_ids=[nodes['episode']]))
        refreshed=self.service.list_episode_assets(self.p,nodes['episode'])['items'][0]
        self.assertEqual(refreshed['id'],original['id']);self.assertEqual(refreshed['name'],'本集别名');self.assertEqual(refreshed['forms'][0]['name'],'本集夜装');self.assertEqual(refreshed['forms'][0]['spec_id'],updated['forms'][0]['spec_id'])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(S.episode_asset_form_versions.c.spec_id).where(S.episode_asset_form_versions.c.id==old)).scalar_one(),first['spec_id'])
            self.assertEqual(conn.execute(select(func.count()).select_from(S.artifact_decisions).where(S.artifact_decisions.c.project_id==self.p)).scalar_one(),0)
        self.write('favorite_asset_card',dict(asset_id=card['id'],active=True))
        self.assertEqual(self.service.list_asset_cards(self.p,actor='test-human',favorites=True)['total'],1)
        self.assertEqual(self.service.list_asset_cards(self.p,actor='another',favorites=True)['total'],0)
        self.assertTrue(self.service.asset_card_options(self.p)['voices'])

    def test_copy_fixed_forms_to_two_projects_and_retry_preserves_source(self):
        media=self.media();audio=self.media('音色',modality='audio');voice=self.card('声线','voice',audio);vid=self.service.get_asset_card(self.p,voice['id'])['forms'][0]['voice_spec_id'];created=self.card(media=media,voice=vid);card=self.service.get_asset_card(self.p,created['id']);fixed=card['forms'][0]
        payload=dict(source_project_id=self.p,source_asset_id=card['id'],form_version_ids=[fixed['version_id']]);source_revision=self.rev
        for n in range(2):
            target=self.service.create_project({'name':'复制目标'+str(n)},actor='test-human')['id'];key=uuid.uuid4().hex
            result=self.service.copy_asset_card(target,payload,expected_revision=0,idempotency_key=key,actor='test-human')
            self.assertEqual(self.service.copy_asset_card(target,payload,expected_revision=0,idempotency_key=key,actor='test-human'),result)
            copied=self.service.get_asset_card(target,result['id']);self.assertNotEqual(copied['id'],card['id']);self.assertNotEqual(copied['forms'][0]['spec_id'],fixed['spec_id']);self.assertNotEqual(copied['forms'][0]['voice_spec_id'],vid);self.assertEqual(result['copied_voice_count'],1)
            self.assertEqual(self.service.get_media(target,copied['forms'][0]['media_id'])['blob_id'],self.service.get_media(self.p,media)['blob_id'])
        self.assertEqual(self.service.get_project(self.p)['revision'],source_revision)
        self.assertEqual(self.service.get_asset_card(self.p,card['id'])['forms'][0]['version_id'],fixed['version_id'])

    def test_conflicts_wrong_media_and_cross_identity_rollback(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        media=self.media();card=self.card(media=media);other=self.card(name='另一人物',media=media);form=self.service.get_asset_card(self.p,card['id'])['forms'][0]
        before=self.rev
        with self.assertRaises(Conflict):self.write('save_asset_card',dict(asset_id=card['id'],name='旧输入',asset_kind='character',base_revision=0,forms=[dict(form_key='master',name='默认',base_version_id=form['version_id'])]))
        audio=self.media('audio',modality='audio');before=self.rev
        with self.assertRaises(ResourceError):self.card(name='无效人物',media=audio)
        self.assertEqual(self.service.get_project(self.p)['revision'],before)
        target=self.service.create_project({'name':'目标'},actor='test-human')['id'];otherfixed=self.service.get_asset_card(self.p,other['id'])['forms'][0]['version_id']
        with self.assertRaises(ResourceError):self.service.copy_asset_card(target,dict(source_project_id=self.p,source_asset_id=card['id'],form_version_ids=[otherfixed]),expected_revision=0,idempotency_key='wrong-form',actor='test-human')
        self.assertEqual(self.service.list_asset_cards(target)['total'],0)
        with self.engine.connect() as conn:self.assertEqual(conn.execute(select(func.count()).select_from(S.creative_objects).where(S.creative_objects.c.project_id==self.p,S.creative_objects.c.title=='无效人物')).scalar_one(),0)

    def test_import_manifest_completes_original_asset_card_once(self):
        import tempfile,hashlib
        from support.fixtures.resources import png_bytes
        from vsc.adapters.storage.local.store import LocalStorage
        with tempfile.TemporaryDirectory() as directory:
            self.service.storage=LocalStorage(directory);data=png_bytes();episode=self.hierarchy()['episode']
            batch=self.write('create_media_import',dict(title='本地资产导入',asset_kind='character',episode_id=episode,files=[dict(filename='人物.png',size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest())]))
            item=self.service.get_media_import(self.p,batch['id'])['items'][0]
            self.service.upload_import_chunk(self.p,batch['id'],item['id'],0,data,actor='test-human');self.rev=self.service.get_project(self.p)['revision']
            result=self.write('process_media_import_item',dict(batch_id=batch['id'],item_id=item['id']),idempotency_key='process-card')
            card=self.service.get_asset_card(self.p,result['asset_id']);self.assertEqual(card['forms'][0]['media_id'],result['media_id']);self.assertEqual(card['revision'],1)
            self.assertEqual(self.service.list_episode_assets(self.p,episode)['items'][0]['forms'][0]['media_id'],result['media_id'])
            replay=self.service.process_media_import_item(self.p,dict(batch_id=batch['id'],item_id=item['id']),expected_revision=0,idempotency_key='process-card',actor='test-human')
            self.assertEqual(replay,result);self.assertEqual(self.service.get_asset_card(self.p,result['asset_id'])['revision'],1)

    def test_http_cards_and_original_canvas_consumer(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        import tempfile
        media=self.media();payload=dict(name='API 人物',asset_kind='character',base_revision=0,forms=[dict(form_key='master',name='默认形态',base_version_id=None,media_id=media)])
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test','human_identity':'test-human','background_enabled':False},catalog=ResourceCatalog(root,service=self.service))
            with TestClient(app) as client:
                path='/api/v1/projects/'+self.p;body=dict(payload=payload,expected_revision=self.rev,idempotency_key='card-http')
                self.assertEqual(client.post(path+'/asset-cards',json=body).status_code,403)
                login=client.post('/api/v1/session',json={'token':'test'},headers={'origin':'http://testserver'}).json();headers={'origin':'http://testserver','x-csrf-token':login['csrf_token']}
                result=client.post(path+'/asset-cards',json=body,headers=headers);self.assertEqual(result.status_code,200,result.text);self.rev=result.json()['revision']
                rows=client.get(path+'/asset-cards').json();self.assertEqual(rows['total'],1)
                canvas=dict(title='人物画布',episode_id=None,document=dict(nodes=[dict(id='asset',type='image',title='人物',x=120,y=120,media_id=media)],edges=[]))
                result=client.post(path+'/creative-canvases',json=dict(payload=canvas,expected_revision=self.rev,idempotency_key='card-canvas'),headers=headers);self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(client.get(path+'/asset-card-options').status_code,200)
