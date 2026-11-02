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
