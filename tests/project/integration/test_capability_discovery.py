"""Real HTTP/session boundary and isolated PostgreSQL discovery authority."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import secrets
import tempfile
import unittest
import uuid
from unittest.mock import patch

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.access_control import Principal, set_principal, reset_principal
from vsc.assets.capability_catalog import CapabilityCatalog, DOCUMENT_LIMIT, SOURCES, identity


class CapabilityHTTPTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-capability-http-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(dict(projects_root=self.temp.name, allowed_hosts=['testserver'],
            allowed_origins=['http://testserver'], human_identity='synthetic-human',
            access_token='synthetic-session-secret', background_enabled=False))
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        response = self.client.post('/api/v1/session', json={'token': 'synthetic-session-secret'},
                                    headers={'Origin': 'http://testserver'})
        self.assertEqual(response.status_code, 200)
        self.headers = {'Origin': 'http://testserver', 'X-CSRF-Token': response.json()['csrf_token']}

    def test_real_catalog_etag_three_tutorials_and_independence_from_legacy_service(self):
        for spa in ('/capability-center', '/capabilities'):
            html_res = self.client.get(spa)
            self.assertEqual(html_res.status_code, 200)
            self.assertIn('id="nav-capability-center"', html_res.text)
            self.assertIn('id="capability-center-view"', html_res.text)
        url = '/api/v1/discovery/capabilities'
        response = self.client.get(url, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(len(response.json()['items']), 55)
        self.assertIn('no-store', response.headers['cache-control'])
        unchanged = self.client.get(url, headers={**self.headers, 'If-None-Match': response.headers['etag']})
        self.assertEqual(unchanged.status_code, 304)
        self.assertEqual(unchanged.content, b'')
        # No PG service is needed for the independent directory or document read.
        self.assertEqual(self.client.get('/api/v1/discovery', headers=self.headers).status_code, 409)
        for item in [i for i in response.json()['items'] if i['source'] == 'tutorial']:
            doc_url = '/api/v1/discovery/documents/' + item['action']['document_id']
            doc = self.client.get(doc_url, headers=self.headers)
            self.assertEqual(doc.status_code, 200, doc.text)
            self.assertEqual(doc.json()['title'], item['name'])
            self.assertEqual(doc.json()['sha256'], item['sha256'])
            self.assertEqual(sha256(doc.json()['content'].encode('utf-8')).hexdigest(), item['sha256'])
            self.assertEqual(self.client.get(doc_url, headers={**self.headers, 'If-None-Match': doc.headers['etag']}).status_code, 304)
        external = next(i for i in response.json()['items'] if i['kind'] == 'external_method')
        doc = self.client.get('/api/v1/discovery/documents/' + external['action']['document_id'], headers=self.headers)
        if external['installation']['document'] == 'present':
            self.assertEqual(doc.status_code, 200)
            self.assertEqual(doc.json()['path'], external['path'])
        else:
            self.assertEqual(doc.status_code, 404)
            self.assertEqual(doc.json()['error'], 'document_not_found')
        for legacy in ('production', 'workspace', 'canvas'):
            old = self.client.get('/api/v1/discovery/tutorials/' + legacy, headers=self.headers)
            self.assertEqual(old.status_code, 200)
            self.assertEqual(set(old.json()), {'id', 'title', 'content', 'sha256'})
            self.assertEqual(old.json()['id'], legacy)

    def test_existing_actor_origin_csrf_guards_apply_before_catalog_read(self):
        doc = identity('doc_', 'tutorial', 'docs/guide/creative-workbench.md')
        for url in ('/api/v1/discovery/capabilities', '/api/v1/discovery/documents/' + doc):
            with self.subTest(url=url), patch.object(CapabilityCatalog, 'capabilities', side_effect=AssertionError('guard bypass')), patch.object(CapabilityCatalog, 'document', side_effect=AssertionError('guard bypass')):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.get(url, headers={**self.headers, 'X-CSRF-Token': 'wrong'}).status_code, 403)
                self.assertEqual(self.client.get(url, headers={**self.headers, 'Origin': 'https://evil.invalid'}).status_code, 403)
                cookie = self.client.cookies.get('vsc_session')
                self.client.cookies.clear()
                self.assertEqual(self.client.get(url, headers=self.headers).status_code, 403)
                self.client.cookies.set('vsc_session', cookie)
        # Origin is optional for same-origin GET, CSRF remains mandatory.
        self.assertEqual(self.client.get('/api/v1/discovery/capabilities',
            headers={'X-CSRF-Token': self.headers['X-CSRF-Token']}).status_code, 200)

    def test_source_filter_partial_unavailable_and_successful_empty_are_distinct(self):
        url = '/api/v1/discovery/capabilities'
        full = self.client.get(url, headers=self.headers).json()
        target = self.client.get(url, params={'source': 'vendor:inkos'}, headers=self.headers).json()
        self.assertEqual([s['id'] for s in target['sources']], ['vendor:inkos'])
        self.assertEqual({i['id'] for i in target['items']}, {i['id'] for i in full['items'] if i['source'] == 'vendor:inkos'})
        with patch.object(CapabilityCatalog, '_vendor', side_effect=OSError('not exposed')):
            partial = self.client.get(url, headers=self.headers)
            self.assertEqual(partial.status_code, 200)
            self.assertEqual(partial.json()['status'], 'partial')
            self.assertTrue(partial.json()['items'])
            unavailable = self.client.get(url, params={'source': 'vendor:inkos'}, headers=self.headers)
            self.assertEqual(unavailable.status_code, 503)
            self.assertEqual(unavailable.json()['status'], 'unavailable')
            self.assertEqual(unavailable.json()['items'], [])
            self.assertEqual(unavailable.json()['sources'][0]['error']['error'], 'capability_source_unavailable')
        with patch.object(CapabilityCatalog, '_vendor', return_value=[]):
            empty = self.client.get(url, params={'source': 'vendor:inkos'}, headers=self.headers)
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json()['status'], 'ok')
            self.assertEqual(empty.json()['items'], [])
        with patch.object(CapabilityCatalog, '_canvas', side_effect=OSError), patch.object(CapabilityCatalog, '_builtin', side_effect=OSError), patch.object(CapabilityCatalog, '_tutorial_items', side_effect=OSError), patch.object(CapabilityCatalog, '_vendor', side_effect=OSError):
            failed = self.client.get(url, headers=self.headers)
            self.assertEqual(failed.status_code, 503)
            self.assertEqual(failed.json()['status'], 'unavailable')
            self.assertEqual(failed.json()['items'], [])
            self.assertEqual([s['id'] for s in failed.json()['sources']], list(SOURCES))
            self.assertTrue(all(s['status'] == 'error' for s in failed.json()['sources']))
        for params in ({'source': 'https://evil.invalid'}, {'path': '/etc/passwd'}, [('source', 'canvas'), ('source', 'tutorial')]):
            invalid = self.client.get(url, params=params, headers=self.headers)
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()['error'], 'invalid_capability_source')
        body = self.client.request('GET', url, content=b'{}', headers=self.headers)
        self.assertEqual(body.status_code, 422)

    def test_document_http_statuses_and_no_path_or_html_execution(self):
        root = Path(self.temp.name)
        path = 'docs/guide/local.md'
        local = root / path
        local.parent.mkdir(parents=True)
        catalog = CapabilityCatalog(root, tutorials={'local': ('本地教程', path)}, skills={}, vendor_routes={})
        doc_id = identity('doc_', 'tutorial', path)
        url = '/api/v1/discovery/documents/' + doc_id
        with patch('vsc.assets.capability_catalog.CapabilityCatalog', return_value=catalog):
            for content, expected, code in [(None, 404, 'document_not_found'), (' ', 503, 'document_unavailable'),
                    (b'\xff', 503, 'document_unavailable'), (b'a' * (DOCUMENT_LIMIT + 1), 413, 'document_too_large')]:
                if content is not None:
                    local.write_bytes(content.encode() if isinstance(content, str) else content)
                response = self.client.get(url, headers=self.headers)
                self.assertEqual(response.status_code, expected, response.text)
                self.assertEqual(response.json()['error'], code)
                self.assertNotIn(self.temp.name, response.text)
            body = '<script>window.untrusted=true</script>\n# 原文'
            local.write_text(body, encoding='utf-8')
            response = self.client.get(url, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['content'], body)
            self.assertEqual(response.json()['format'], 'text/plain')
            self.assertEqual(self.client.get(url, params={'path': '/etc/passwd'}, headers=self.headers).status_code, 404)
            self.assertEqual(self.client.get(url, params={'source': 'tutorial'}, headers=self.headers).status_code, 404)
            local.unlink()
            local.symlink_to(Path('/etc/passwd'))
            forbidden = self.client.get(url, headers=self.headers)
            self.assertEqual(forbidden.status_code, 403)
            self.assertEqual(forbidden.json()['error'], 'document_forbidden')
            self.assertNotIn('passwd', forbidden.text)
            local.unlink()
            local.write_text('valid', encoding='utf-8')
            with patch.object(Path, 'open', side_effect=PermissionError('private')):
                # Permission errors after a valid containment check are 503.
                failed = self.client.get(url, headers=self.headers)
                self.assertEqual(failed.status_code, 503)
        for value in ('doc_' + '0' * 64, 'not-a-document', '%2Fetc%2Fpasswd', '..%2Fconfig%2F.env', ''):
            response = self.client.get('/api/v1/discovery/documents/' + value, headers=self.headers)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()['error'], 'document_not_found')

    def test_bad_utf8_source_file_does_not_poison_other_sources_in_same_stage(self):
        root = Path(self.temp.name)
        vendor = root / 'vendor'
        bad = vendor / 'inkos/method/SKILL.md'
        good = vendor / 'openwrite/method/SKILL.md'
        for file in (bad, good):
            file.parent.mkdir(parents=True)
        bad.write_bytes(b'\xff')
        good.write_text('---\nname: original-method\n---\n真实方法正文', encoding='utf-8')
        routes = {'script': [('inkos', 'method/SKILL.md', 'guide', '坏来源'),
                             ('openwrite', 'method/SKILL.md', 'runtime: bridge', '好来源')]}
        catalog = CapabilityCatalog(root, vendor, skills={}, tutorials={}, vendor_routes=routes)
        with patch('vsc.assets.capability_catalog.CapabilityCatalog', return_value=catalog):
            response = self.client.get('/api/v1/discovery/capabilities', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload['status'], 'partial')
            good_item = next(i for i in payload['items'] if i['source'] == 'vendor:openwrite')
            self.assertEqual(good_item['name'], 'original-method')
            self.assertEqual(good_item['action']['type'], 'read')
            doc = self.client.get('/api/v1/discovery/documents/' + good_item['action']['document_id'], headers=self.headers)
            self.assertEqual(doc.status_code, 200)
            self.assertIn('真实方法正文', doc.json()['content'])
            bad.write_text('---\nname: recovered-method\n---\n恢复原文', encoding='utf-8')
            retry = self.client.get('/api/v1/discovery/capabilities?source=vendor:inkos', headers=self.headers)
            self.assertEqual(retry.status_code, 200)
            self.assertEqual(retry.json()['status'], 'ok')
            self.assertEqual(len(retry.json()['items']), 1)
            self.assertEqual(retry.json()['items'][0]['source'], 'vendor:inkos')


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class CapabilityDiscoveryAuthorityTests(ResourceStoreFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.engine import make_url
        from vsc.configuration import get_config
        production = get_config('VSC_DATABASE_URL')
        target = make_url(TEST_URL)
        if production:
            original = make_url(production)
            if (target.host, target.port, target.database) == (original.host, original.port, original.database):
                raise AssertionError('isolated HTTP fixture must target the configured test database')
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-capability-pg-http-')
        self.addCleanup(self.temp.cleanup)
        self.owner = self.service.ensure_local_access('test-human')
        token = set_principal(Principal(**self.owner))
        self.addCleanup(reset_principal, token)
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app = create_app(dict(projects_root=self.temp.name, allowed_hosts=['testserver'],
            allowed_origins=['http://testserver'], human_identity='test-human',
            access_token='synthetic-only', background_enabled=False), service=self.service)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def command(self, action, payload):
        return self.service.access_command(action, payload,
            expected_revision=self.service.access_snapshot()['access_revision'],
            idempotency_key=uuid.uuid4().hex, actor='test-human')

    @contextmanager
    def as_identity(self, binding):
        token = set_principal(Principal(**binding))
        try:
            yield
        finally:
            reset_principal(token)

    def member(self, role):
        secret = secrets.token_urlsafe(32)
        credential = secrets.token_urlsafe(32)
        self.command('invitation', dict(scope='project', scope_id=self.p, role=role, secret=secret,
            expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
        binding = self.service.accept_access_invitation(dict(invitation_secret=secret,
            credential_secret=credential, display_name='合成成员'))
        return binding, credential

    def login(self, credential):
        response = self.client.post('/api/v1/access/login', json={'secret': credential},
                                    headers={'Origin': 'http://testserver'})
        self.assertEqual(response.status_code, 200, response.text)
        return {'Origin': 'http://testserver', 'X-CSRF-Token': response.json()['csrf_token']}

    def snapshot_counts(self):
        from sqlalchemy import text
        # All tables in the random fixture schema: read requests must add zero rows.
        with self.engine.connect() as connection:
            tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename")).scalars().all()
            return {name: connection.execute(text('SELECT count(*) FROM "' + name.replace('"', '""') + '"')).scalar_one() for name in tables}

    def test_original_edit_viewer_revoked_hidden_projects_and_legacy_shape_without_get_writes(self):
        editor, edit_secret = self.member('editor')
        viewer, view_secret = self.member('viewer')
        private = self.service.create_project({'name': '不可见合成项目'}, actor='test-human')['id']
        with self.as_identity(editor):
            hidden = self.service.create_project({'name': '已回收合成项目'}, actor=editor['actor'])
            self.service.management_command(hidden['id'], dict(operation='trash', target_type='project',
                target_id=hidden['id'], reason='合成隐藏fixture'), expected_revision=0,
                idempotency_key=uuid.uuid4().hex, actor=editor['actor'])
        headers = self.login(edit_secret)
        before = self.snapshot_counts()
        result = self.client.get('/api/v1/discovery', headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(set(result.json()), {'recent', 'templates', 'projects', 'skills', 'tutorials'})
        projects = {row['id']: row for row in result.json()['projects']}
        self.assertIn(self.p, projects)
        self.assertIn('edit', projects[self.p]['capabilities'])
        self.assertNotIn(private, projects)
        self.assertNotIn(hidden['id'], projects)
        # New read requests neither consult execution nor create/install anything.
        with patch.object(self.service.store, '_mutate', side_effect=AssertionError('GET attempted business write')):
            for _ in range(2):
                response = self.client.get('/api/v1/discovery/capabilities', headers=headers)
                self.assertEqual(response.status_code, 200)
                tutorial = next(i for i in response.json()['items'] if i['kind'] == 'tutorial')
                self.assertEqual(self.client.get('/api/v1/discovery/documents/' + tutorial['action']['document_id'], headers=headers).status_code, 200)
        self.assertEqual(self.snapshot_counts(), before)
        headers = self.login(view_secret)
        result = self.client.get('/api/v1/discovery', headers=headers)
        projects = {row['id']: row for row in result.json()['projects']}
        self.assertIn(self.p, projects)
        self.assertNotIn('edit', projects[self.p]['capabilities'])
        self.command('member', dict(scope='project', scope_id=self.p,
                                   identity_id=viewer['identity_id'], role='viewer', active=False))
        projects = self.client.get('/api/v1/discovery', headers=headers).json()['projects']
        self.assertNotIn(self.p, {row['id'] for row in projects})
        self.assertEqual(self.client.get('/api/v1/projects/' + self.p + '/tree', headers=headers).status_code, 403)
        # Revoking a project grant does not invent a new permission for global documents.
        self.assertEqual(self.client.get('/api/v1/discovery/capabilities', headers=headers).status_code, 200)


if __name__ == '__main__':
    unittest.main()
