"""Local marketing display bytes: catalog coverage, HTTP seek and corruption."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import support.paths
from vsc.assets import marketing_media as M
from vsc.assets.marketing_cases import load_catalog
from vsc.assets.marketing_studio import marketing_methods
from vsc.assets.resource_service import ResourceError


class MarketingMediaTests(unittest.TestCase):
    def test_every_case_source_and_all_eight_methods_have_fixed_local_bytes(self):
        catalog, manifest = load_catalog(), M.load_manifest()
        self.assertEqual(manifest['catalog_sha256'], catalog['catalog_sha256'])
        expected = set()
        for group in catalog['metadata']['groups']:
            for case in group['examples']:
                for kind in ['cover', 'video']:
                    key = 'cases/' + case['template_key'] + '/' + kind
                    expected.add(key)
                    self.assertEqual(manifest['assets'][key]['source_url'], case[kind + '_url'])
        for method in marketing_methods():
            expected.add('methods/' + method['id'])
        self.assertEqual(set(manifest['assets']), expected)
        self.assertEqual(len(expected), 236)
        for key, item in manifest['assets'].items():
            with self.subTest(asset=key):
                self.assertEqual(item['id'], key)
                self.assertTrue(item['object_key'].startswith(item['sha256'] + '.'))
                self.assertGreater(item['size_bytes'], 0)

    def fixture(self, directory):
        content = b'fixed synthetic video response for byte range checks'
        item = dict(id='cases/example/video', sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content), mime_type='video/mp4', source_url='https://example.invalid/video.mp4')
        item['object_key'] = item['sha256'] + '.mp4'
        path = M.assets_root(directory) / item['object_key']
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
        return content, item, path

    def app(self, directory):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from vsc.interfaces.web.marketing_studio import install_marketing_case_routes
        app = FastAPI()
        @app.exception_handler(ResourceError)
        async def error(_request, error):
            return JSONResponse(dict(error=error.code), status_code=error.status_code)
        install_marketing_case_routes(app, lambda _request, value: value, media_root=directory)
        return app

    def test_local_http_full_head_seek_conditional_and_invalid_range(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory:
            content, item, _ = self.fixture(directory)
            with patch.object(M, 'load_manifest', return_value={'assets': {item['id']: item}}), \
                    TestClient(self.app(directory)) as client, patch('subprocess.run', side_effect=AssertionError('HTTP must stay offline')):
                url = '/api/v1/marketing-assets/' + item['id']
                full = client.get(url)
                self.assertEqual((full.status_code, full.content), (200, content))
                self.assertEqual(full.headers['content-type'], 'video/mp4')
                self.assertEqual(full.headers['accept-ranges'], 'bytes')
                head = client.head(url)
                self.assertEqual((head.status_code, head.content, int(head.headers['content-length'])), (200, b'', len(content)))
                part = client.get(url, headers={'Range': 'bytes=7-17'})
                self.assertEqual((part.status_code, part.content), (206, content[7:18]))
                self.assertEqual(part.headers['content-range'], f'bytes 7-17/{len(content)}')
                self.assertEqual(client.get(url, headers={'If-None-Match': full.headers['etag']}).status_code, 304)
                self.assertEqual(client.get(url, headers={'Range': 'bytes=10000-'}).status_code, 416)

    def test_missing_corrupt_symlink_and_unknown_never_serve_or_fetch_remote_content(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory:
            content, item, path = self.fixture(directory)
            with patch.object(M, 'load_manifest', return_value={'assets': {item['id']: item}}), TestClient(self.app(directory)) as client:
                url = '/api/v1/marketing-assets/' + item['id']
                self.assertEqual(client.get(url).status_code, 200)
                path.write_bytes(b'X' * len(content))
                self.assertEqual(client.get(url).status_code, 409)
                path.unlink()
                self.assertEqual(client.get(url).status_code, 404)
                elsewhere = Path(directory) / 'outside.mp4'
                elsewhere.write_bytes(content)
                path.symlink_to(elsewhere)
                self.assertEqual(client.get(url).status_code, 404)
                self.assertEqual(client.get('/api/v1/marketing-assets/methods/unknown').status_code, 404)
                self.assertEqual(client.get('/api/v1/marketing-assets/cases/example/%2e%2e/video').status_code, 404)

    def test_explicit_restore_checks_digest_before_replacing_existing_bytes(self):
        from tools.maintenance.marketing_media import restore
        with tempfile.TemporaryDirectory() as directory:
            content, item, path = self.fixture(directory)
            def response(command, **_kwargs):
                Path(command[command.index('--output') + 1]).write_bytes(b'incorrect remote content')
                return SimpleNamespace(returncode=0, stdout='200')
            with patch('tools.maintenance.marketing_media.subprocess.run', side_effect=response), \
                    patch('tools.maintenance.marketing_media.shutil.which', return_value='/usr/bin/curl'):
                with self.assertRaises(ValueError):
                    restore(directory, item)
                self.assertEqual(path.read_bytes(), content)
