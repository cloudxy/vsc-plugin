"""Project-media ACLs must correlate every grant to the returned project."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import unittest
import uuid

import support.paths  # Loads the existing isolated test database configuration.
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class ProjectMediaAuthorizationTests(ResourceStoreFixture, unittest.TestCase):
    def test_recycled_canvas_removes_active_source_link_but_keeps_media(self):
        media = self.media('retained canvas media')
        canvas = self.write('create_creative_canvas', {'title': 'source canvas',
            'document': {'nodes': [{'id': 'image', 'type': 'image', 'media_id': media}], 'edges': []}})

        def item():
            return next(row for row in self.service.list_project_media(project_id=self.p)['items']
                if row['id'] == media)

        original = item()
        self.assertIn(canvas['id'], original['source_href'])
        self.write('management_command', {'operation': 'trash', 'target_type': 'canvas',
            'target_id': canvas['id'], 'reason': 'test inactive source'})
        recycled = item()
        self.assertEqual(recycled['id'], media)
        self.assertEqual(recycled['content_url'], original['content_url'])
        self.assertIsNone(recycled['source_href'])
        self.assertIsNone(recycled['reuse_href'])
        self.write('management_command', {'operation': 'restore', 'target_type': 'canvas',
            'target_id': canvas['id'], 'reason': 'test original source recovery'})
        self.assertEqual(item()['source_href'], original['source_href'])

    def test_full_project_grants_and_paged_media_match_authoritative_access(self):
        from sqlalchemy import delete, insert, update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.media_catalog import ProjectMediaCatalog
        from vsc.assets.access_control import Principal, reset_principal, set_principal
        from vsc.assets.resource_service import ResourceError

        marker = 'acl-matrix-' + uuid.uuid4().hex
        self.media(marker + '-one')
        self.media(marker + '-two')
        secret = self.service.create_project({'name': 'private synthetic'}, actor='test-human')['id']
        child_project = self.service.create_project({'name': 'nested synthetic'}, actor='test-human')['id']
        unassigned = self.service.create_project({'name': 'unassigned synthetic'}, actor='test-human')['id']
        for p, suffix in ((secret, 'secret'), (child_project, 'nested'), (unassigned, 'unassigned')):
            name = marker + '-' + suffix
            digest = hashlib.sha256(name.encode()).hexdigest()
            self.service.register_media(p, {'name': name, 'modality': 'image', 'sha256': digest,
                'size_bytes': 1, 'mime_type': 'image/png', 'storage': 'local', 'object_key': digest + '.bin',
                'rights': 'owned', 'source': {'kind': 'test-owned', 'content': 'synthetic'}},
                actor='test-human', expected_revision=0, idempotency_key=uuid.uuid4().hex)

        member, local_member, owner, parent, child, other = [str(uuid.uuid4()) for _ in range(6)]
        with self.engine.begin() as conn:
            for identifier, prefix in ((member, 'remote:'), (local_member, 'local:'), (owner, 'remote:')):
                conn.execute(insert(S.access_identities).values(id=identifier, subject_key=prefix + identifier,
                    actor='actor:' + identifier, display_name='synthetic', preferences={}, active=True))
            conn.execute(insert(S.access_workspaces).values(id=parent, name='parent', kind='studio', created_by=owner))
            conn.execute(insert(S.access_workspaces).values(id=child, name='child', kind='substudio', parent_id=parent, created_by=owner))
            conn.execute(insert(S.access_workspaces).values(id=other, name='other', kind='studio', created_by=owner))
            for p, workspace in ((self.p, child), (secret, child), (child_project, other)):
                conn.execute(insert(S.access_projects).values(project_id=p, workspace_id=workspace, assigned_by=owner, review_lanes=[]))
            conn.execute(insert(S.access_project_members).values(project_id=self.p, identity_id=member, role='viewer', active=True))

        projects = {self.p, secret, child_project, unassigned}
        person = Principal(identity_id=member, actor='actor:' + member)

        def verify(principal, expected):
            token = set_principal(principal)
            try:
                with self.engine.connect() as conn:
                    projected = set(conn.execute(ProjectMediaCatalog(self.store, None)._readable_projects(conn)).scalars()) & projects
                    authoritative = set()
                    for p in projects:
                        try:
                            self.store._access_require(conn, p, 'read')
                            authoritative.add(p)
                        except ResourceError as exc:
                            self.assertEqual(exc.code, 'access_denied')
                self.assertEqual(projected, authoritative)
                self.assertEqual(projected, expected)
                seen, offset = [], 0
                while True:
                    page = self.service.list_project_media(query=marker, offset=offset, limit=1)
                    seen.extend(page['items'])
                    if page['next_offset'] is None:
                        break
                    offset = page['next_offset']
                self.assertEqual({row['project_id'] for row in seen}, expected)
                self.assertEqual(len({row['id'] for row in seen}), len(seen))
                self.assertEqual(len(seen), len(expected) + (1 if self.p in expected else 0))
            finally:
                reset_principal(token)

        # A direct grant to one project must not reveal a second project in
        # the same studio or any other studio, even in subsequent pages.
        verify(person, {self.p})
        for role, active, expected in [('editor', True, {self.p}), ('reviewer', True, {self.p}),
                                       ('viewer', False, set())]:
            with self.engine.begin() as conn:
                conn.execute(update(S.access_project_members).where(S.access_project_members.c.project_id == self.p,
                    S.access_project_members.c.identity_id == member).values(role=role, active=active))
            verify(person, expected)
        # A direct studio role applies to its own workspace; only ancestor
        # owners inherit into a child workspace.
        for workspace, role, expected in ((parent, 'viewer', set()), (parent, 'owner', {self.p, secret}),
                                           (child, 'viewer', {self.p, secret}), (other, 'editor', {child_project})):
            with self.engine.begin() as conn:
                conn.execute(delete(S.access_workspace_members).where(S.access_workspace_members.c.identity_id == member))
                conn.execute(insert(S.access_workspace_members).values(workspace_id=workspace, identity_id=member, role=role, active=True))
            verify(person, expected)
        with self.engine.begin() as conn:
            conn.execute(delete(S.access_workspace_members).where(S.access_workspace_members.c.identity_id == member))
        verify(Principal(local_read=True), {unassigned})
        verify(Principal(identity_id=local_member, actor='actor:' + local_member, local=True), {unassigned})

    def test_share_and_api_key_cannot_expand_complete_project_catalog(self):
        from vsc.assets.access_control import Principal, reset_principal, set_principal
        from vsc.assets.resource_service import ResourceError

        owner = self.service.ensure_local_access('test-human')
        token = set_principal(Principal(**owner))
        try:
            canvas = self.write('create_creative_canvas', {'title': 'synthetic canvas',
                'document': {'nodes': [{'id': 'text1', 'type': 'text', 'text': 'fixture', 'x': 0, 'y': 0}], 'edges': []}})
            # Assign the test project before creating a scoped share and key.
            preview = self.service.access_migration_preview(self.p, owner['workspace_id'])
            revision = self.service.access_snapshot()['access_revision']
            self.service.access_command('assign-project', {'project_id': self.p, 'workspace_id': owner['workspace_id'],
                'preview_sha256': preview['sha256']}, actor='test-human', expected_revision=revision, idempotency_key=uuid.uuid4().hex)
            share_secret = secrets.token_urlsafe(32)
            revision = self.service.access_snapshot()['access_revision']
            self.service.access_command('share', {'project_id': self.p, 'canvas_version_id': canvas['version_id'],
                'mode': 'view', 'secret': share_secret, 'expires_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
                actor='test-human', expected_revision=revision, idempotency_key=uuid.uuid4().hex)
            share = self.service.authenticate_access(share_secret)
            key_secret = secrets.token_urlsafe(32)
            self.write('issue_service_api_key', {'name': 'synthetic key', 'secret': key_secret, 'capabilities': ['read'],
                'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
            key = self.service.authenticate_service_api_key(key_secret)
        finally:
            reset_principal(token)

        token = set_principal(Principal(**share))
        try:
            self.assertEqual(self.service.list_project_media()['items'], [])
        finally:
            reset_principal(token)
        token = set_principal(key)
        try:
            with self.assertRaises(ResourceError) as denied:
                self.service.list_project_media()
            self.assertEqual(denied.exception.code, 'access_denied')
        finally:
            reset_principal(token)
