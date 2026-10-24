"""The original CLI can import a fixed global version and use it in a real project."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture
from support.fixtures.resources import png_bytes


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and importlib.util.find_spec('psycopg'), 'requires configured isolated PostgreSQL')
class LibraryCliTest(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service.storage = LocalStorage(self.directory.name)
        self.library_key = 'cli-synthetic-' + uuid.uuid4().hex

    def description(self):
        return {'library_key': self.library_key, 'title': 'Synthetic CLI reference', 'category': 'image',
                'description': 'An owned integration fixture', 'allowed_purposes': ['first_frame'],
                'license': {'outcome': 'owned', 'allow_workspace_reuse': True, 'evidence': 'Synthetic fixture original'}}

    def actual_media(self):
        staged = self.service.storage.stage_upload(io.BytesIO(png_bytes()), 'fixture.png')
        media = self.write('register_media', {'name': 'CLI fixture', 'staged_upload': staged['staged_upload'],
            'rights': 'owned', 'rights_scope': {'purposes': ['*']}, 'source': {'kind': 'synthetic-owned', 'content': 'Owned fixture'}})
        self.write('record_media_check', {'media_id': media['id'], 'checker': 'fixture', 'criteria_version': '1', 'outcome': 'pass'})
        return media['id']

    def call_cli(self, arguments):
        from vsc.interfaces.cli.resources import main
        out = io.StringIO()
        with patch('vsc.interfaces.cli.resources.service_from_environment', return_value=self.service), contextlib.redirect_stdout(out):
            main(arguments)
        return json.loads(out.getvalue())

    def payload(self, name, value):
        path = Path(self.directory.name) / name
        path.write_text(json.dumps(value))
        return str(path)

    def test_import_without_project_and_original_apply_consumer(self):
        staged = self.service.storage.stage_upload(io.BytesIO(png_bytes()), 'synthetic.png')
        payload = dict(self.description(), import_key='cli-fixed-import', members=[{'member_key': 'reference', 'staged_upload': staged['staged_upload']}])
        path = self.payload('import.json', payload)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.call_cli(['library', 'import', '--payload', path, '--by', 'test-human'])
        self.assertEqual(error.exception.code, 2)
        published = self.call_cli(['library', 'import', '--payload', path, '--by', 'test-human', '--confirmed'])
        replay = self.call_cli(['library', 'import', '--payload', path, '--by', 'test-human', '--confirmed'])
        self.assertEqual(published, replay)
        found = self.call_cli(['library', 'search', 'Synthetic'])
        self.assertEqual(found['total'], 1)
        detail = self.call_cli(['library', 'show', published['library_version_id']])
        self.assertEqual(detail['version'], 1)
        objects = self.hierarchy()
        self.artifact(objects=[objects['shot']])
        self.artifact('state', 'scene-state', [objects['scene']], {'state_versions': [{'scene_id': objects['scene']}]})
        use_path = self.payload('use.json', {'library_version_id': published['library_version_id'], 'member_key': 'reference',
            'target_object_id': objects['shot'], 'role': 'first_frame', 'select': True})
        preview = self.call_cli(['library', 'preview-use', self.p, '--payload', use_path])
        self.assertTrue(preview['available'], preview['gaps'])
        used = self.call_cli(['apply', self.p, 'use_library', '--payload', use_path, '--expected-revision', str(self.rev), '--key', 'cli-use', '--by', 'test-human'])
        self.rev = used['revision']
        context = self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')
        self.assertTrue(context['ready'], context['gaps'])
        self.assertEqual(context['media'][0]['media_id'], used['media_id'])
        retire_path = self.payload('retire.json', {'reason': 'Synthetic CLI retirement', 'outcome': 'retire', 'idempotency_key': 'cli-retire'})
        self.call_cli(['library', 'retire', published['entry_id'], '--payload', retire_path, '--by', 'test-human', '--confirmed'])
        self.assertEqual(self.call_cli(['library', 'search'])['total'], 0)
        self.assertTrue(self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')['ready'])

    def test_original_apply_can_publish(self):
        media = self.actual_media()
        path = self.payload('publish.json', dict(self.description(), members=[{'media_id': media, 'member_key': 'reference'}]))
        result = self.call_cli(['apply', self.p, 'publish_library', '--payload', path, '--expected-revision', str(self.rev), '--key', 'cli-publish', '--by', 'test-human'])
        self.assertEqual(self.call_cli(['library', 'show', result['library_version_id']])['members'][0]['sha256'], self.service.get_media(self.p, media)['sha256'])
