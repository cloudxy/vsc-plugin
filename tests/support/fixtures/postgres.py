"""Explicit test URL, random schema, real migrations and reliable schema cleanup."""
from contextlib import contextmanager
import uuid

from support.paths import ROOT


def snapshot_project_ownership(connection):
    """Retain actual synthetic ownership before a pre-access-schema downgrade."""
    from sqlalchemy import select
    from vsc.adapters.persistence.postgres import schema as S
    return {name: [dict(row) for row in connection.execute(select(getattr(S, name))).mappings()]
        for name in ('access_identities', 'access_workspaces', 'access_workspace_members',
            'access_projects', 'access_project_members')}


def upgrade_with_project_ownership(config, connection, snapshot):
    """Restore fixed fixture owners before the strict 0058 ownership preflight.

    No actor is inferred from revision/editor history. Each binding and owner
    comes from the same test database's captured pre-downgrade facts.
    """
    from alembic import command
    from sqlalchemy import insert
    from vsc.adapters.persistence.postgres import schema as S
    config.attributes['connection'] = connection
    command.upgrade(config, '0057_service_feedback')
    for name, rows in snapshot.items():
        table = getattr(S, name)
        if name == 'access_workspaces':
            pending, restored = list(rows), set()
            while pending:
                ready = [row for row in pending if row['parent_id'] is None or row['parent_id'] in restored]
                if not ready:
                    raise AssertionError('captured fixture ownership contains a missing or cyclic workspace parent')
                connection.execute(insert(table), ready)
                restored.update(row['id'] for row in ready)
                pending = [row for row in pending if row['id'] not in restored]
        elif rows:
            connection.execute(insert(table), rows)
    command.upgrade(config, 'head')


def drop_schema(engine, schema):
    """Drop one test schema. A full migrated schema can exceed the shared lock table, so fall back to one object per transaction."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    quoted = '"' + schema.replace('"', '""') + '"'
    try:
        with engine.begin() as connection:
            connection.execute(text('DROP SCHEMA IF EXISTS ' + quoted + ' CASCADE'))
        return
    except OperationalError as error:
        if 'shared memory' not in str(error).lower():
            raise
    with engine.connect() as connection:
        relations = connection.execute(text(
            "SELECT c.relkind, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=:schema AND c.relkind IN ('v','m','f','r','p','S') "
            "ORDER BY CASE c.relkind WHEN 'v' THEN 0 WHEN 'm' THEN 1 WHEN 'f' THEN 2 ELSE 3 END, c.relname"
        ), {"schema": schema}).all()
        functions = connection.execute(text(
            "SELECT p.proname, pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema"
        ), {"schema": schema}).all()
    kinds = {'v': 'VIEW', 'm': 'MATERIALIZED VIEW', 'f': 'FOREIGN TABLE', 'r': 'TABLE', 'p': 'TABLE', 'S': 'SEQUENCE'}
    for kind, name in relations:
        with engine.begin() as connection:
            connection.execute(text('DROP ' + kinds[kind] + ' IF EXISTS ' + quoted + '."' + name.replace('"', '""') + '" CASCADE'))
    for name, arguments in functions:
        with engine.begin() as connection:
            connection.execute(text('DROP FUNCTION IF EXISTS ' + quoted + '."' + name.replace('"', '""') + '"(' + arguments + ') CASCADE'))
    with engine.begin() as connection:
        connection.execute(text('DROP SCHEMA IF EXISTS ' + quoted + ' CASCADE'))


@contextmanager
def isolated_postgres(url):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    schema = "vsc_test_" + uuid.uuid4().hex
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_engine(url)
    engine = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text('CREATE SCHEMA "' + schema + '"'))
        created = True
        engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
        config = Config(str(ROOT / "migrations/postgres/alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            drop_schema(admin, schema)
        admin.dispose()
