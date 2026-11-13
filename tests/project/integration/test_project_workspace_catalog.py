"""Real project creator facts and authorized workspace directory boundaries."""
from contextlib import contextmanager
import hashlib
import tempfile
import unittest
import uuid

import support.paths
from support.paths import ROOT
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.access_control import Principal, reset_principal, set_principal
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class ProjectWorkspaceCatalogTests(ResourceStoreFixture, unittest.TestCase):
    @contextmanager
    def principal(self, **binding):
        token = set_principal(Principal(**binding))
        try:
            yield
        finally:
            reset_principal(token)

    def setup_catalog(self):
        from sqlalchemy import insert, update, delete
        from vsc.adapters.persistence.postgres import schema as S
        self.owner = self.service.ensure_local_access('test-human')
        self.marker = 'workspace-catalog-' + uuid.uuid4().hex
        self.a, self.b = str(uuid.uuid4()), str(uuid.uuid4())
        self.mine = self.service.create_project({'name': self.marker + '-mine'}, actor='test-human')['id']
        self.cross = self.service.create_project({'name': self.marker + '-cross'}, actor='other-creator')['id']
        self.secret = self.service.create_project({'name': self.marker + '-secret'}, actor='other-creator')['id']
        self.historic = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.projects).values(id=self.historic, name=self.marker + '-historical',
                profile='vsc.series-pg', profile_snapshot={}, storage_policy='postgres-series-v1'))
            for identifier, name in ((self.a, 'Team A'), (self.b, 'Team B')):
                conn.execute(insert(S.access_workspaces).values(id=identifier, name=name,
                    kind='studio', created_by=self.owner['identity_id']))
            conn.execute(insert(S.access_workspace_members).values(workspace_id=self.a,
                identity_id=self.owner['identity_id'], role='editor', active=True))
            for project, workspace in ((self.p, self.a), (self.mine, self.a),
                    (self.cross, self.b), (self.secret, self.b)):
                conn.execute(update(S.access_projects).where(S.access_projects.c.project_id == project)
                    .values(workspace_id=workspace, assigned_by=self.owner['identity_id'], review_lanes=[]))
                conn.execute(delete(S.access_project_members).where(S.access_project_members.c.project_id == project))
            conn.execute(insert(S.access_projects).values(project_id=self.historic,
                workspace_id=self.owner['workspace_id'], assigned_by=self.owner['identity_id'], review_lanes=[]))
            conn.execute(insert(S.access_project_members).values(project_id=self.cross,
                identity_id=self.owner['identity_id'], role='viewer', active=True))
        self.media_ids, self.canvas_ids = {}, {}
        for project in (self.p, self.mine, self.cross, self.secret, self.historic):
            name = self.marker + '-' + project
            digest = hashlib.sha256(name.encode()).hexdigest()
            media = self.service.register_media(project, dict(name=name, modality='image', sha256=digest,
                size_bytes=1, mime_type='image/png', storage='local', object_key=digest+'.bin', rights='owned',
                source=dict(kind='test-owned', content='synthetic')), actor='test-human',
                expected_revision=0, idempotency_key=uuid.uuid4().hex)
            canvas = self.service.create_creative_canvas(project, dict(title=name,
                document=dict(nodes=[dict(id='text1', type='text', text='synthetic')], edges=[])),
                actor='test-human', expected_revision=media['revision'], idempotency_key=uuid.uuid4().hex)
            self.media_ids[project], self.canvas_ids[project] = media['id'], canvas['id']
        return dict(self.owner, workspace_id=self.a)

    def test_creation_fact_is_immutable_and_cannot_be_supplied_by_payload(self):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        binding = self.service.ensure_local_access('test-human')
        with self.principal(**binding):
            created = self.service.create_project({'name': 'Creator audit', 'created_by': 'forged'},
                actor='test-human', idempotency_key='creator-audit')
            replay = self.service.create_project({'name': 'Creator audit', 'created_by': 'forged'},
                actor='test-human', idempotency_key='creator-audit')
            self.assertEqual(created, replay)
            self.assertEqual(created['created_by'], 'test-human')
            with self.assertRaises(ResourceError):
                self.service.create_project({'name': 'Spoof'}, actor='forged')
        for creator in ('someone-else', None):
            with self.subTest(creator=creator), self.assertRaises(IntegrityError), self.engine.begin() as conn:
                conn.execute(text('UPDATE projects SET created_by=:creator WHERE id=:id'),
                    dict(creator=creator, id=created['id']))
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE projects SET name=:name WHERE id=:id'), dict(name='Renamed', id=created['id']))
        self.assertEqual(self.service.get_project(created['id'])['created_by'], 'test-human')

    def test_workspace_and_relation_restrict_rows_counts_options_and_pages(self):
        from vsc.adapters.persistence.postgres.project_presentation import project_cards
        binding = self.setup_catalog()
        with self.principal(**binding):
            cards = {r['id']: r for r in project_cards(self.store,
                self.store.access_filter_projects(self.store.list_projects()))}
            self.assertNotIn(self.secret, cards)
            self.assertEqual((cards[self.mine]['workspace_id'], cards[self.mine]['workspace_name'],
                cards[self.mine]['workspace_kind'], cards[self.mine]['my_role'], cards[self.mine]['project_relation']),
                (self.a, 'Team A', 'studio', 'editor', 'created'))
            self.assertEqual((cards[self.cross]['my_role'], cards[self.cross]['project_relation']), ('viewer', 'participating'))
            self.assertEqual((cards[self.historic]['owner_kind'], cards[self.historic]['owner_actor'],
                cards[self.historic]['created_by'], cards[self.historic]['project_relation']),
                ('personal', 'test-human', None, 'unknown'))
            self.assertEqual((cards[self.mine]['owner_kind'], cards[self.mine]['owner_name'],
                cards[self.mine]['owner_actor']), ('team', 'Team A', None))
            for name, listing, identifiers in (
                    ('media', self.service.list_project_media, self.media_ids),
                    ('canvas', lambda **kw: self.service.list_canvas_library(creator_filter='all', **kw), self.canvas_ids)):
                with self.subTest(directory=name):
                    first = listing(workspace_id=self.a, query=self.marker, limit=1)
                    second = listing(workspace_id=self.a, query=self.marker, limit=1, offset=1)
                    self.assertEqual((first['total'], first['next_offset'], second['next_offset']), (2, 1, None))
                    self.assertEqual({r['id'] for page in (first, second) for r in page['items']},
                        {identifiers[self.p], identifiers[self.mine]})
                    page = listing(workspace_id=self.b, query=self.marker)
                    self.assertEqual((page['total'], [r['id'] for r in page['items']]), (1, [identifiers[self.cross]]))
                    self.assertEqual(page['items'][0]['workspace_name'], 'Team B')
                    created = listing(relation='created', query=self.marker)
                    self.assertEqual({r['project_id'] for r in created['items']}, {self.p, self.mine})
                    participating = listing(relation='participating', query=self.marker)
                    self.assertEqual({r['project_id'] for r in participating['items']}, {self.cross, self.historic})
                    self.assertEqual(listing(workspace_id=self.a, relation='participating', query=self.marker)['total'], 0)
                    historical = listing(owner_kind='personal', query=self.marker)
                    self.assertEqual([r['id'] for r in historical['items']], [identifiers[self.historic]])
                    self.assertEqual(historical['items'][0]['project_relation'], 'unknown')
                    team_first = listing(owner_kind='team', query=self.marker, limit=1)
                    team_second = listing(owner_kind='team', query=self.marker, limit=2, offset=1)
                    self.assertEqual((team_first['total'], team_first['next_offset'], team_second['next_offset']), (3, 1, None))
                    self.assertEqual({r['project_id'] for page in (team_first, team_second) for r in page['items']},
                        {self.p, self.mine, self.cross})
                    self.assertEqual(team_first['items'][0]['owner_kind'], 'team')
                    self.assertEqual(listing(query=self.marker)['total'], 4)
                    with self.assertRaises(ResourceError):
                        listing(project_id=self.secret, workspace_id=self.b)
            options = self.service.canvas_library_options(workspace_id=self.a)
            self.assertEqual({r['id'] for r in options['projects']}, {self.p, self.mine})
            self.assertEqual([r['id'] for r in self.service.canvas_library_options(
                owner_kind='personal')['projects'] if r['id'] in self.canvas_ids], [self.historic])
            self.assertEqual({r['id'] for r in self.service.canvas_library_options(
                relation='participating')['projects']} & set(self.canvas_ids), {self.cross, self.historic})

    def test_http_scope_and_invalid_filters(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        self.setup_catalog()
        with tempfile.TemporaryDirectory(prefix='vsc-project-catalog-') as directory:
            app = create_app(dict(projects_root=directory, allowed_hosts=['testserver'],
                allowed_origins=['http://testserver'], access_token='local-secret',
                human_identity='test-human', background_enabled=False), service=self.service)
            with TestClient(app) as client:
                self.assertEqual(client.post('/api/v1/session', json={'token': 'local-secret'},
                    headers={'Origin': 'http://testserver'}).status_code, 200)
                for path in ('/api/v1/project-media', '/api/v1/canvas-library'):
                    params = dict(workspace_id=self.b, query=self.marker, creator_filter='all')
                    response = client.get(path, params=params)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['total'], 1)
                    self.assertEqual(response.json()['items'][0]['project_id'], self.cross)
                    self.assertEqual(client.get(path, params={'relation': 'owner'}).status_code, 422)
                    self.assertEqual(client.get(path, params={'workspace_id': 'forged'}).status_code, 422)
                    self.assertEqual(client.get(path, params={'workspace_id': 'unassigned'}).status_code, 422)
                    self.assertEqual(client.get(path, params={'owner_kind': 'unassigned'}).status_code, 422)
                    self.assertEqual(client.get(path, params={'project_category': 'created'}).status_code, 422)
                    personal = client.get(path, params=dict(owner_kind='personal', query=self.marker, creator_filter='all'))
                    self.assertEqual(personal.status_code, 200, personal.text)
                    self.assertEqual([r['project_id'] for r in personal.json()['items']], [self.historic])
                    categorized = client.get(path, params=dict(project_category='personal', query=self.marker, creator_filter='all'))
                    self.assertEqual(categorized.status_code, 200, categorized.text)
                    self.assertEqual([r['project_id'] for r in categorized.json()['items']], [self.historic])
                options = client.get('/api/v1/canvas-library/options', params={'workspace_id': self.b})
                self.assertEqual(options.status_code, 200, options.text)
                self.assertEqual([r['id'] for r in options.json()['projects']], [self.cross])
                self.assertEqual(client.get('/api/v1/canvas-library/options',
                    params={'project_category': 'all'}).status_code, 422)
                categorized = client.get('/api/v1/canvas-library/options', params={'project_category': 'personal'})
                self.assertEqual(categorized.status_code, 200, categorized.text)
                self.assertEqual({r['id'] for r in categorized.json()['projects']} & set(self.canvas_ids), {self.historic})

    def test_project_categories_partition_authorized_rows_before_counts_pages_and_options(self):
        from sqlalchemy import insert, update
        from vsc.adapters.persistence.postgres import schema as S
        binding = self.setup_catalog()
        invited = self.service.create_project({'name': self.marker + '-invited-personal'}, actor='other-creator')['id']
        name = self.marker + '-invited-personal'
        digest = hashlib.sha256(name.encode()).hexdigest()
        media = self.service.register_media(invited, dict(name=name, modality='image', sha256=digest,
            size_bytes=1, mime_type='image/png', storage='local', object_key=digest+'.bin', rights='owned',
            source=dict(kind='test-owned', content='synthetic')), actor='other-creator',
            expected_revision=0, idempotency_key=uuid.uuid4().hex)
        self.service.create_creative_canvas(invited, dict(title=name,
            document=dict(nodes=[dict(id='text1', type='text', text='synthetic')], edges=[])),
            actor='other-creator', expected_revision=media['revision'], idempotency_key=uuid.uuid4().hex)
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_project_members).values(project_id=invited,
                identity_id=self.owner['identity_id'], role='viewer', active=True))
            subteam = str(uuid.uuid4())
            conn.execute(insert(S.access_workspaces).values(id=subteam, name='Subteam', kind='substudio',
                parent_id=self.a, created_by=self.owner['identity_id']))
            conn.execute(update(S.access_projects).where(S.access_projects.c.project_id == self.cross)
                .values(workspace_id=subteam))
        expected = dict(personal={self.historic}, participating={invited}, team={self.p, self.mine, self.cross})
        targets = set().union(*expected.values()) | {self.secret}
        with self.principal(**binding):
            with self.engine.connect() as conn:
                authorized = set(conn.execute(self.store._access_project_query(conn, 'read')).scalars()) & targets
            self.assertEqual(authorized, set().union(*expected.values()))
            for name, listing in (
                    ('media', self.service.list_project_media),
                    ('canvas', lambda **kw: self.service.list_canvas_library(creator_filter='all', **kw))):
                with self.subTest(directory=name):
                    categories = {}
                    for category, projects in expected.items():
                        seen, offset = [], 0
                        while True:
                            page = listing(project_category=category, query=self.marker, limit=1, offset=offset)
                            self.assertEqual(page['total'], len(projects))
                            seen.extend(row['project_id'] for row in page['items'])
                            if page['next_offset'] is None:
                                break
                            self.assertGreater(page['next_offset'], offset)
                            offset = page['next_offset']
                        self.assertEqual(set(seen), projects)
                        self.assertEqual(len(seen), len(projects))
                        categories[category] = set(seen)
                        beyond = listing(project_category=category, query=self.marker, offset=len(projects))
                        self.assertEqual((beyond['total'], beyond['items'], beyond['next_offset']), (len(projects), [], None))
                    self.assertTrue(categories['personal'].isdisjoint(categories['participating']))
                    self.assertTrue(categories['personal'].isdisjoint(categories['team']))
                    self.assertTrue(categories['participating'].isdisjoint(categories['team']))
                    self.assertEqual(set().union(*categories.values()), authorized)
                    aggregate = listing(query=self.marker)
                    self.assertEqual((aggregate['total'], {r['project_id'] for r in aggregate['items']}),
                        (len(authorized), authorized))
                    self.assertEqual(listing(project_category='participating', owner_kind='team', query=self.marker)['total'], 0)
            for category, projects in expected.items():
                options = self.service.canvas_library_options(project_category=category)
                self.assertEqual({row['id'] for row in options['projects']} & targets, projects)

    def test_previous_revision_keeps_historical_creator_unknown_and_upgrade_matches_model(self):
        from alembic import command
        from alembic.autogenerate import compare_metadata
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres import schema as S
        config = Config(str(ROOT / 'migrations/postgres/alembic.ini'))
        identifier, owner, workspace = [str(uuid.uuid4()) for _ in range(3)]
        with isolated_postgres(TEST_URL) as engine:
            with engine.begin() as conn:
                config.attributes['connection'] = conn
                command.downgrade(config, '0057_service_feedback')
                conn.execute(text("INSERT INTO access_identities (id,subject_key,actor,display_name,preferences,active) "
                    "VALUES (:id,'historical-owner','archived-owner','Archived Owner','{}',false)"), dict(id=owner))
                conn.execute(text("INSERT INTO access_workspaces (id,name,kind,created_by) "
                    "VALUES (:id,'Archived personal','personal',:owner)"), dict(id=workspace, owner=owner))
                conn.execute(text("INSERT INTO projects (id,name,profile,profile_snapshot,storage_policy) "
                    "VALUES (:id,'Historical','vsc.series-pg','{}','postgres-series-v1')"), dict(id=identifier))
                command.upgrade(config, 'head')
                self.assertIsNone(conn.scalar(text('SELECT created_by FROM projects WHERE id=:id'), dict(id=identifier)))
                self.assertEqual(str(conn.scalar(text('SELECT workspace_id FROM access_projects WHERE project_id=:id'),
                    dict(id=identifier))), workspace)
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])
            with self.assertRaises(IntegrityError), engine.begin() as conn:
                conn.execute(text("UPDATE projects SET created_by='guessed-from-editor' WHERE id=:id"), dict(id=identifier))
            with engine.connect() as conn:
                self.assertIsNone(conn.scalar(text('SELECT created_by FROM projects WHERE id=:id'), dict(id=identifier)))
            from vsc.adapters.persistence.postgres.project_presentation import project_cards
            from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
            store = PostgresResourceStore(engine=engine)
            card = project_cards(store, store.list_projects())[0]
            self.assertEqual((card['owner_kind'], card['owner_actor'], card['owner_name'], card['project_relation']),
                ('personal', 'archived-owner', 'Archived Owner', 'unknown'))

    def test_legacy_projects_without_an_account_cannot_remain_ownerless(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text
        from support.fixtures.postgres import isolated_postgres
        config = Config(str(ROOT / 'migrations/postgres/alembic.ini'))
        with isolated_postgres(TEST_URL) as engine:
            with engine.begin() as conn:
                config.attributes['connection'] = conn
                command.downgrade(config, '0057_service_feedback')
                conn.execute(text("INSERT INTO projects (id,name,profile,profile_snapshot,storage_policy) "
                    "VALUES (:id,'Historical','vsc.series-pg','{}','postgres-series-v1')"), dict(id=str(uuid.uuid4())))
            with self.assertRaisesRegex(RuntimeError, 'retained owner account'), engine.begin() as conn:
                config.attributes['connection'] = conn
                command.upgrade(config, 'head')
            with engine.connect() as conn:
                self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')), '0057_service_feedback')

    def test_ambiguous_legacy_ownership_requires_explicit_existing_actor(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text
        from support.fixtures.postgres import isolated_postgres
        config = Config(str(ROOT / 'migrations/postgres/alembic.ini'))
        project, owner_a, owner_b, workspace_a, workspace_b = [str(uuid.uuid4()) for _ in range(5)]
        with isolated_postgres(TEST_URL) as engine:
            with engine.begin() as conn:
                config.attributes['connection'] = conn
                command.downgrade(config, '0057_service_feedback')
                for owner, workspace, actor in ((owner_a, workspace_a, 'legacy-a'), (owner_b, workspace_b, 'legacy-b')):
                    conn.execute(text("INSERT INTO access_identities (id,subject_key,actor,display_name,preferences,active) "
                        "VALUES (:id,:actor,:actor,:actor,'{}',true)"), dict(id=owner, actor=actor))
                    conn.execute(text("INSERT INTO access_workspaces (id,name,kind,created_by) "
                        "VALUES (:id,:name,'personal',:owner)"), dict(id=workspace, name=actor, owner=owner))
                conn.execute(text("INSERT INTO projects (id,name,profile,profile_snapshot,storage_policy) "
                    "VALUES (:id,'Historical','vsc.series-pg','{}','postgres-series-v1')"), dict(id=project))
            with self.assertRaisesRegex(RuntimeError, 'legacy_project_owner_actor'), engine.begin() as conn:
                config.attributes['connection'] = conn
                command.upgrade(config, 'head')
            with engine.connect() as conn:
                self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')), '0057_service_feedback')
                self.assertEqual(conn.scalar(text('SELECT count(*) FROM access_projects')), 0)
            config.attributes['legacy_project_owner_actor'] = 'not-an-existing-owner'
            with self.assertRaisesRegex(RuntimeError, 'existing account'), engine.begin() as conn:
                config.attributes['connection'] = conn
                command.upgrade(config, 'head')
            config.attributes['legacy_project_owner_actor'] = 'legacy-a'
            with engine.begin() as conn:
                config.attributes['connection'] = conn
                command.upgrade(config, 'head')
                self.assertEqual(str(conn.scalar(text('SELECT workspace_id FROM access_projects WHERE project_id=:id'),
                    dict(id=project))), workspace_a)
                self.assertIsNone(conn.scalar(text('SELECT created_by FROM projects WHERE id=:id'), dict(id=project)))

    def test_direct_collaborator_sees_inactive_personal_owner_without_new_owner_claim(self):
        from sqlalchemy import insert, update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.project_presentation import project_cards
        self.setup_catalog()
        guest = self.service.ensure_local_access('catalog-guest-' + uuid.uuid4().hex)
        def restore_owner():
            with self.engine.begin() as conn:
                conn.execute(update(S.access_identities).where(S.access_identities.c.id == self.owner['identity_id'])
                    .values(active=True, display_name='test-human'))
        self.addCleanup(restore_owner)
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_project_members).values(project_id=self.historic,
                identity_id=guest['identity_id'], role='viewer', active=True))
            conn.execute(update(S.access_identities).where(S.access_identities.c.id == self.owner['identity_id'])
                .values(active=False, display_name='Archived Owner'))
        with self.principal(**guest):
            cards = project_cards(self.store, self.store.access_filter_projects(self.store.list_projects()))
            card = next(row for row in cards if row['id'] == self.historic)
            self.assertEqual((card['owner_actor'], card['owner_name'], card['created_by'], card['project_relation']),
                ('test-human', 'Archived Owner', None, 'unknown'))
            for listing in (self.service.list_project_media,
                    lambda **kw: self.service.list_canvas_library(creator_filter='all', **kw)):
                result = listing(owner_kind='personal', query=self.marker)
                self.assertEqual(result['total'], 1)
                self.assertEqual((result['items'][0]['owner_actor'], result['items'][0]['owner_name']),
                    ('test-human', 'Archived Owner'))
