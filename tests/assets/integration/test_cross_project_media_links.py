"""A canvas media link pins its typed source and preserves live copy lineage."""
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class CrossProjectMediaLinkTests(ResourceStoreFixture, unittest.TestCase):
    def prepare_link(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S

        source_media = self.media('跨项目固定源')
        card = self.write('save_asset_card', dict(name='固定来源', asset_kind='character', base_revision=0,
            forms=[dict(form_key='master', name='默认', base_version_id=None, description='', media_id=source_media)]))
        with self.engine.connect() as conn:
            blob = conn.execute(select(S.media_blobs).join(S.media_items, S.media_items.c.blob_id == S.media_blobs.c.id)
                .where(S.media_items.c.project_id == self.p, S.media_items.c.id == source_media)).mappings().one()
        target = self.service.create_project({'name': '目标项目'}, actor='test-human')['id']
        target_media = self.service.register_media(target, dict(name='复制图片', modality='image',
            sha256=blob['sha256'], size_bytes=blob['size_bytes'], mime_type=blob['mime_type'],
            storage='local', object_key=blob['sha256']+'.bin', rights='owned',
            source={'kind': 'test-source', 'content': 'synthetic source'}), expected_revision=0,
            idempotency_key=uuid.uuid4().hex, actor='test-human')
        canvas = self.service.create_creative_canvas(target, {'document': {'nodes': [
            {'id': 'copied', 'type': 'image', 'media_id': target_media['id']}], 'edges': []}},
            expected_revision=target_media['revision'], idempotency_key=uuid.uuid4().hex, actor='test-human')
        command_key = uuid.uuid4().hex
        row = dict(project_id=target, id=str(uuid.uuid4()), source_project_id=self.p,
            source_media_id=source_media, target_media_id=target_media['id'], blob_id=blob['id'],
            sha256=blob['sha256'], source_form_version_id=card['forms'][0]['version_id'],
            source_workflow_version_id=None, source_unit_key=None, source_purpose=None,
            canvas_version_id=canvas['version_id'], node_key='copied', command_key=command_key,
            created_by='test-human')
        return row, canvas, canvas['revision']

    def write_link(self, row, canvas, revision):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S

        def callback(conn, project):
            conn.execute(insert(S.canvas_project_media_links).values(**row))
            return dict(id=canvas['id'], version_id=canvas['version_id'], node_id=row['node_key'],
                        media_id=row['target_media_id'])
        return self.store._mutate(row['project_id'], 'add_canvas_project_media_node', {},
            expected_revision=revision, idempotency_key=row['command_key'], actor='test-human',
            callback=callback, _related_projects=(row['project_id'], row['source_project_id']))

    def test_fixed_relation_receipt_immutability_and_live_source_rights(self):
        from sqlalchemy import delete, select, update
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.copy_lineage import copy_media_gaps, source_projects_for_copy

        row, canvas, revision = self.prepare_link()
        first = self.write_link(row, canvas, revision)
        self.assertEqual(self.write_link(row, canvas, revision), first)
        with self.engine.connect() as conn:
            self.assertIn(self.p, source_projects_for_copy(conn, row['project_id']))
            self.assertEqual(copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'reference_image'), [])
            self.assertEqual(conn.scalar(select(S.canvas_project_media_links.c.id).where(
                S.canvas_project_media_links.c.project_id == row['project_id'])), row['id'])
        for action in ('update', 'delete'):
            with self.subTest(action=action), self.assertRaises(DBAPIError), self.engine.begin() as conn:
                query = update(S.canvas_project_media_links).values(created_by='replacement') if action == 'update' else delete(S.canvas_project_media_links)
                conn.execute(query.where(S.canvas_project_media_links.c.project_id == row['project_id'], S.canvas_project_media_links.c.id == row['id']))
        self.write('decide_rights', {'media_id': row['source_media_id'], 'outcome': 'revoked', 'reason': '隔离测试撤权'})
        with self.engine.connect() as conn:
            self.assertIn('copy_source_rights_restricted', copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'reference_image'))

    def test_original_lifecycle_checks_and_purpose_are_rechecked_on_identical_bytes(self):
        import hashlib
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.copy_lineage import copy_media_gaps

        row, canvas, revision = self.prepare_link(); self.write_link(row, canvas, revision)
        source_id = self.service.get_media(self.p, row['source_media_id'])['sources'][0]['source_id']
        self.write('decide_rights', dict(media_id=row['source_media_id'], outcome='licensed', source_id=source_id,
            scope={'purposes': ['first_frame']}, reason='限定用途'))
        with self.engine.connect() as conn:
            allowed=copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'first_frame')
            denied=copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'reference_image')
        self.assertNotIn('copy_source_rights_scope_mismatch', allowed)
        self.assertIn('copy_source_rights_scope_mismatch', denied)
        # A historical asset-copy edge may refer to a different blob. The
        # new canvas rule must not treat that other file's failed decode as
        # evidence about these bytes.
        other=self.service.create_project({'name':'不同字节来源'},actor='test-human')['id']
        raw=b'different';other_media=self.service.register_media(other,dict(name='其他图',modality='image',
            sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),mime_type='image/png',storage='local',
            object_key='test/different.png',rights='owned',source={'kind':'test','content':'different'}),
            expected_revision=0,idempotency_key=uuid.uuid4().hex,actor='test-human')
        failed=self.service.record_media_check(other,dict(media_id=other_media['id'],checker='test-probe',
            criteria_version='1',outcome='fail'),expected_revision=other_media['revision'],
            idempotency_key=uuid.uuid4().hex,actor='test-human')
        other_card=self.service.save_asset_card(other,dict(name='其他素材',asset_kind='character',base_revision=0,
            forms=[dict(form_key='master',name='默认',base_version_id=None,description='',media_id=other_media['id'])]),
            expected_revision=failed['revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
        with self.engine.begin() as conn:
            conn.execute(insert(S.asset_card_copy_sources).values(id=str(uuid.uuid4()),project_id=self.p,
                target_form_version_id=row['source_form_version_id'],source_project_id=other,
                source_form_version_id=other_card['forms'][0]['version_id'],created_by='test-human'))
        with self.engine.connect() as conn:
            self.assertNotIn('copy_source_technical_check_failed',copy_media_gaps(self.store,conn,row['project_id'],row['target_media_id'],'first_frame'))
        self.write('record_media_check', dict(media_id=row['source_media_id'], checker='test-probe',
            criteria_version='1', outcome='fail', report={'reason': '隔离测试'}))
        with self.engine.connect() as conn:
            self.assertIn('copy_source_technical_check_failed', copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'first_frame'))
        self.write('record_media_check', dict(media_id=row['source_media_id'], checker='test-probe',
            criteria_version='1', outcome='pass', report={'reason': '隔离测试恢复'}))
        with self.engine.connect() as conn:
            self.assertNotIn('copy_source_technical_check_failed', copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'first_frame'))
        self.write('decide_media_lifecycle', dict(media_id=row['source_media_id'], outcome='deprecate', reason='停用来源'))
        with self.engine.connect() as conn:
            self.assertIn('copy_source_media_deprecated', copy_media_gaps(self.store, conn, row['project_id'], row['target_media_id'], 'first_frame'))

    def test_only_actual_controlled_decodable_image_receives_machine_check(self):
        import hashlib
        import struct
        import tempfile
        import zlib
        from unittest.mock import patch
        from sqlalchemy import func, insert, select, update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure
        from vsc.adapters.storage.local.store import LocalStorage

        def chunk(kind, data):
            return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data)&0xffffffff)
        good = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x30\x60\x90'))+chunk(b'IEND',b'')
        bad = b'\x89PNG\r\n\x1a\ncorrupt'
        with tempfile.TemporaryDirectory() as directory:
            storage=LocalStorage(directory)
            def register(raw, name):
                sha=hashlib.sha256(raw).hexdigest(); key='synthetic/'+name+'.png'
                path=storage.resolve(key);path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
                result=self.write('register_media', dict(name=name, modality='image', sha256=sha,
                    size_bytes=len(raw), mime_type='image/png', storage='local', object_key=key,
                    rights='owned', source={'kind':'test-owned','content':'synthetic'}))
                return result['id'],path
            valid,path=register(good,'valid');broken,_=register(bad,'broken')
            def check(media_id, actual_storage):
                result=self.store._mutate(self.p,'test_canvas_byte_probe',{'media_id':media_id},
                    expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor='test-human',
                    callback=lambda conn,project:self.store._record_canvas_copy_byte_check(conn,project,media_id,actual_storage))
                self.rev=result['revision'];return result
            unavailable=check(valid,None);self.assertEqual((unavailable['status'],unavailable['reason']),('unavailable','local_storage_unavailable'))
            path.write_bytes(good+b'changed')
            blob=self.service.get_media(self.p,valid)['blob_id']
            with self.engine.begin() as conn:
                conn.execute(insert(S.blob_locations).values(id=str(uuid.uuid4()),blob_id=blob,storage='s3',object_key='synthetic/remote.png'))
            changed=check(valid,storage);self.assertEqual((changed['status'],changed['reason']),('invalid','local_bytes_missing_or_changed'))
            with self.engine.begin() as conn:
                conn.execute(update(S.blob_locations).where(S.blob_locations.c.blob_id==blob,
                    S.blob_locations.c.storage=='local').values(available=False))
            remote_only=check(valid,storage);self.assertEqual((remote_only['status'],remote_only['reason']),('invalid','local_bytes_missing_or_changed'))
            with self.engine.begin() as conn:
                conn.execute(update(S.blob_locations).where(S.blob_locations.c.blob_id==blob,
                    S.blob_locations.c.storage=='local').values(available=True))
            failed=check(broken,storage);self.assertEqual((failed['status'],failed['reason']),('invalid','image_decode_failed'))
            with self.engine.connect() as conn:
                self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_checks).where(S.media_checks.c.project_id==self.p)),0)
            second=storage.resolve('synthetic/alternate.png');second.write_bytes(good)
            with self.engine.begin() as conn:
                conn.execute(insert(S.blob_locations).values(id=str(uuid.uuid4()),blob_id=blob,storage='local',object_key='synthetic/alternate.png'))
            for code,reason in [('missing_tool','probe_missing_tool'),('decode_timeout','probe_timeout')]:
                with self.subTest(code=code),patch.object(LocalProbeAdapter,'probe',side_effect=ProbeFailure(code,'synthetic')):
                    result=check(valid,storage);self.assertEqual((result['status'],result['reason']),('unavailable',reason))
            original=LocalProbeAdapter.probe
            with patch.object(LocalProbeAdapter,'probe',autospec=True,side_effect=original) as probe:
                result=check(valid,storage);self.assertTrue(result['checked'],result);self.assertEqual(probe.call_count,1)
            with self.engine.connect() as conn:
                rows=conn.execute(select(S.media_checks).where(S.media_checks.c.project_id==self.p)).mappings().all()
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['outcome'],'pass')
                self.assertEqual(rows[0]['blob_sha256'],hashlib.sha256(good).hexdigest())
                self.assertEqual(rows[0]['report']['probe']['decode']['mode'],'complete')
                self.assertNotIn('path',rows[0]['report']['probe'])

    def test_inconsistent_source_node_and_missing_receipt_are_rejected(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S

        row, _, _ = self.prepare_link()
        cases = [dict(sha256='0'*64), dict(source_form_version_id=str(uuid.uuid4())),
                 dict(node_key='missing'), dict(source_project_id=row['project_id']),
                 dict(source_workflow_version_id=str(uuid.uuid4()), source_form_version_id=None,
                      source_unit_key='unit', source_purpose=None), {}]
        # The last candidate has a valid source and node but no command receipt;
        # its deferred foreign key/receipt check must reject transaction commit.
        for changes in cases:
            candidate = dict(row, id=str(uuid.uuid4()), command_key=uuid.uuid4().hex, **changes)
            with self.subTest(changes=changes), self.assertRaises(DBAPIError), self.engine.begin() as conn:
                conn.execute(insert(S.canvas_project_media_links).values(**candidate))

    def test_canvas_copy_rechecks_racing_bytes_and_falls_back_to_another_copy(self):
        import io
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from sqlalchemy import func, insert, select
        from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceError

        previous=self.service.storage;self.addCleanup(setattr,self.service,'storage',previous)
        scenarios=[('delete',False,'missing_media'),('replace',False,'media_unreadable'),
                   ('delete',False,'missing_tool'),('delete',True,'missing_media'),('replace',True,'media_changed_during_probe')]
        for index,(change,backup,error_code) in enumerate(scenarios):
            with self.subTest(change=change,backup=backup,error_code=error_code),tempfile.TemporaryDirectory() as directory:
                storage=LocalStorage(directory);self.service.storage=storage
                data=io.BytesIO();Image.new('RGB',(8,8),(10+index,60,90)).save(data,format='PNG');raw=data.getvalue()
                staged=storage.stage_upload(io.BytesIO(raw),'original.png')
                source=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned',
                    'source':{'kind':'test','content':'synthetic'}})['id']
                card=self.write('save_asset_card',dict(name='原图',asset_kind='character',base_revision=0,
                    forms=[dict(form_key='master',name='默认',base_version_id=None,media_id=source)]))
                source_media=self.service.get_media(self.p,source)
                if backup:
                    key='copies/'+uuid.uuid4().hex+'.png'
                    alternate=storage.resolve(key);alternate.parent.mkdir(parents=True,exist_ok=True);alternate.write_bytes(raw)
                    with self.engine.begin() as conn:
                        conn.execute(insert(S.blob_locations).values(id=str(uuid.uuid4()),blob_id=source_media['blob_id'],
                            storage='local',object_key=key))
                target=self.service.create_project({'name':'隔离目标'},actor='test-human')['id']
                canvas=self.service.create_creative_canvas(target,{'document':{'nodes':[],'edges':[]}},
                    expected_revision=0,idempotency_key='canvas',actor='test-human')
                payload=dict(canvas_id=canvas['id'],canvas_revision=1,source_project_id=self.p,
                    source=dict(kind='asset_form',asset_id=card['id'],form_version_id=card['forms'][0]['version_id'],media_id=source))
                calls=[];original=LocalProbeAdapter.probe
                def race(adapter,path):
                    calls.append(str(path))
                    if len(calls)==1:
                        if change=='delete':Path(path).unlink()
                        else:Path(path).write_bytes(b'changed during probe')
                        raise ProbeFailure(error_code,'synthetic race')
                    return original(adapter,path)
                with patch.object(LocalProbeAdapter,'probe',autospec=True,side_effect=race):
                    if backup:
                        result=self.service.add_canvas_project_media_node(target,payload,expected_revision=canvas['revision'],
                            idempotency_key='transfer',actor='test-human')
                        self.assertEqual(result['byte_check']['status'],'verified');self.assertEqual(len(calls),2)
                        from vsc.project.resource_catalog import ResourceCatalog
                        self.assertEqual(ResourceCatalog(directory,service=self.service,media_root=directory).content_path(target,result['media_id']).read_bytes(),raw)
                    else:
                        with self.assertRaises(ResourceError) as failure:
                            self.service.add_canvas_project_media_node(target,payload,expected_revision=canvas['revision'],
                                idempotency_key='transfer',actor='test-human')
                        self.assertEqual(failure.exception.code,'canvas_project_source_bytes_invalid')
                        with self.engine.connect() as conn:
                            self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id==target)),0)
                            self.assertEqual(conn.scalar(select(func.count()).select_from(S.canvas_project_media_links).where(S.canvas_project_media_links.c.project_id==target)),0)
                        self.assertEqual(self.service.get_creative_canvas(target,canvas['id'])['canvas_revision'],1)

    def test_reverse_project_mutations_share_the_same_lock_order(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from sqlalchemy import text

        first = self.p
        second = self.service.create_project({'name': '并发目标'}, actor='test-human')['id']
        start = Barrier(2)
        def mutate(target, source):
            start.wait(timeout=5)
            def callback(conn, project):
                conn.execute(text("SET LOCAL lock_timeout = '3s'"))
                conn.execute(text('SELECT pg_sleep(0.1)'))
                return {'target': project['id']}
            return self.store._mutate(target, 'cross_project_lock_probe', {}, expected_revision=0,
                idempotency_key=uuid.uuid4().hex, actor='test-human', callback=callback,
                _related_projects=(target, source))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(mutate, first, second), pool.submit(mutate, second, first)]
            self.assertEqual({result.result(timeout=10)['target'] for result in results}, {first, second})

    def test_canvas_copy_of_nested_grid_inherits_only_original_live_authority(self):
        import io
        import tempfile
        from PIL import Image
        from vsc.adapters.storage.local.store import LocalStorage

        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.addCleanup(setattr,self.service,'storage',previous)
            self.service.storage=LocalStorage(directory)
            encoded=io.BytesIO();Image.new('RGB',(8,8),'green').save(encoded,format='PNG')
            staged=self.service.storage.stage_upload(io.BytesIO(encoded.getvalue()),'original.png')
            original=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned',
                'source':{'kind':'test','content':'synthetic original'}})['id']
            canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'source','type':'image','media_id':original}],'edges':[]}})
            split=self.write('split_canvas_image',dict(canvas_id=canvas['id'],canvas_revision=1,node_id='source',
                rows=2,columns=2,cells=[{'row':1,'column':1}]))
            nested=self.write('split_canvas_image',dict(canvas_id=canvas['id'],canvas_revision=2,node_id=split['node_ids'][0],
                rows=2,columns=2,cells=[{'row':1,'column':1}]))['media_ids'][0]
            card=self.write('save_asset_card',dict(name='嵌套切片',asset_kind='character',base_revision=0,
                forms=[dict(form_key='master',name='默认',base_version_id=None,media_id=nested)]))
            legacy_target=self.service.create_project({'name':'普通资产复制'},actor='test-human')['id']
            legacy=self.service.copy_asset_card(legacy_target,dict(source_project_id=self.p,source_asset_id=card['id'],
                form_version_ids=[card['forms'][0]['version_id']]),expected_revision=0,
                idempotency_key='legacy-copy',actor='test-human')
            with self.engine.connect() as conn:
                old_gaps=self.store._usable(conn,legacy_target,legacy['forms'][0]['media_id'],'first_frame')[1]
            self.assertTrue(any('rights_unknown' in gap for gap in old_gaps),old_gaps)
            target=self.service.create_project({'name':'目标项目'},actor='test-human')['id']
            target_canvas=self.service.create_creative_canvas(target,{'document':{'nodes':[],'edges':[]}},
                expected_revision=0,idempotency_key='canvas',actor='test-human')
            transferred=self.service.add_canvas_project_media_node(target,dict(canvas_id=target_canvas['id'],canvas_revision=1,
                source_project_id=self.p,source=dict(kind='asset_form',asset_id=card['id'],
                form_version_id=card['forms'][0]['version_id'],media_id=nested)),expected_revision=target_canvas['revision'],
                idempotency_key='nested-transfer',actor='test-human')
            copied=transferred['media_id']
            self.assertEqual(self.service.get_media(self.p,nested)['rights']['outcome'],'unknown')
            self.assertEqual(self.service.get_media(target,copied)['rights']['outcome'],'unknown')
            def gaps(role):
                with self.engine.connect() as conn:return self.store._usable(conn,target,copied,role)[1]
            self.assertEqual(gaps('first_frame'),[])
            source_id=self.service.get_media(self.p,original)['sources'][0]['source_id']
            self.write('decide_rights',dict(media_id=original,outcome='licensed',source_id=source_id,
                scope={'purposes':['first_frame','image_edit']},reason='限定用途'))
            self.assertEqual(gaps('first_frame'),[])
            self.assertTrue(any('scope_mismatch' in gap for gap in gaps('identity_face')))
            self.write('decide_rights',dict(media_id=original,outcome='licensed',source_id=source_id,
                scope={'purposes':['first_frame']},reason='未授权编辑'))
            self.assertTrue(any('scope_mismatch' in gap for gap in gaps('first_frame')))
            self.write('decide_rights',dict(media_id=original,outcome='licensed',source_id=source_id,
                scope={'purposes':['first_frame','image_edit']},reason='恢复编辑用途'))
            self.assertEqual(gaps('first_frame'),[])
            self.write('decide_rights',dict(media_id=nested,outcome='unknown',reason='显式重置切片权利'))
            self.assertTrue(any('rights_unknown' in gap for gap in gaps('first_frame')))
            self.write('decide_rights',dict(media_id=original,outcome='revoked',reason='撤销原图'))
            self.assertTrue(any('rights_' in gap for gap in gaps('first_frame')))

    def test_unreceipted_grid_operation_cannot_grant_canvas_copy_rights(self):
        import io
        import tempfile
        from PIL import Image
        from vsc.adapters.storage.local.store import LocalStorage

        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.addCleanup(setattr,self.service,'storage',previous)
            self.service.storage=LocalStorage(directory)
            encoded=io.BytesIO();Image.new('RGB',(8,8),'purple').save(encoded,format='PNG')
            staged=self.service.storage.stage_upload(io.BytesIO(encoded.getvalue()),'parent.png')
            parent=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned',
                'source':{'kind':'test','content':'synthetic'}})['id']
            staged=self.service.storage.stage_upload(io.BytesIO(encoded.getvalue()),'fake.png')
            fake=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'unknown'})['id']
            self.write('create_media_operation',dict(operation_type='image-grid-split',recipe_version='canvas-grid/v1',
                tool='vsc-local-image-grid',tool_version='1',parameters={'source_sha256':self.service.get_media(self.p,parent)['sha256'],
                'cells':[{'row':1,'column':1}]},inputs=[{'media_id':parent,'role':'source'}],outputs=[{'media_id':fake,'role':'tile'}]))
            card=self.write('save_asset_card',dict(name='伪造切片',asset_kind='character',base_revision=0,
                forms=[dict(form_key='master',name='默认',base_version_id=None,media_id=fake)]))
            target=self.service.create_project({'name':'目标'},actor='test-human')['id']
            canvas=self.service.create_creative_canvas(target,{'document':{'nodes':[],'edges':[]}},
                expected_revision=0,idempotency_key='canvas',actor='test-human')
            result=self.service.add_canvas_project_media_node(target,dict(canvas_id=canvas['id'],canvas_revision=1,
                source_project_id=self.p,source=dict(kind='asset_form',asset_id=card['id'],
                form_version_id=card['forms'][0]['version_id'],media_id=fake)),expected_revision=canvas['revision'],
                idempotency_key='fake-transfer',actor='test-human')
            with self.engine.connect() as conn:
                gaps=self.store._usable(conn,target,result['media_id'],'first_frame')[1]
            self.assertTrue(any('rights_unknown' in gap for gap in gaps),gaps)
            evidence=self.service.get_media(self.p,parent)['sources'][0]['source_id']
            self.write('decide_rights',dict(media_id=fake,outcome='owned',source_id=evidence,
                scope={'purposes':['*']},reason='单独确认原素材'))
            with self.engine.connect() as conn:
                gaps=self.store._usable(conn,target,result['media_id'],'first_frame')[1]
            self.assertTrue(any('rights_unknown' in gap for gap in gaps),gaps)


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class CrossProjectMediaMigrationTests(ResourceStoreFixture, unittest.TestCase):
    prepare_link = CrossProjectMediaLinkTests.prepare_link
    write_link = CrossProjectMediaLinkTests.write_link

    def test_upgrade_keeps_old_facts_and_rejects_lossy_downgrade(self):
        from alembic import command
        from alembic.autogenerate import compare_metadata
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from sqlalchemy import select, text
        from sqlalchemy.exc import DBAPIError
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres import schema as S

        row, canvas, revision = self.prepare_link()
        config = Config(str(ROOT / 'migrations/postgres/alembic.ini'))
        with self.engine.begin() as conn:
            config.attributes['connection'] = conn
            command.downgrade(config, '0048_official_asset_catalog')
            self.assertIsNone(conn.scalar(text("SELECT to_regclass('canvas_project_media_links')")))
            self.assertEqual(conn.scalar(select(S.media_items.c.id).where(
                S.media_items.c.project_id == self.p, S.media_items.c.id == row['source_media_id'])), row['source_media_id'])
        with self.engine.begin() as conn:
            config.attributes['connection'] = conn
            command.upgrade(config, 'head')
            self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])
            self.assertEqual(conn.scalar(select(S.creative_canvas_nodes.c.media_id).where(
                S.creative_canvas_nodes.c.project_id == row['project_id'],
                S.creative_canvas_nodes.c.version_id == canvas['version_id'],
                S.creative_canvas_nodes.c.node_key == 'copied')), row['target_media_id'])
        self.write_link(row, canvas, revision)
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                config.attributes['connection'] = conn
                command.downgrade(config, '0048_official_asset_catalog')
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(S.canvas_project_media_links.c.id).where(
                S.canvas_project_media_links.c.project_id == row['project_id'])), row['id'])
            self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')), '0049_canvas_project_media')
