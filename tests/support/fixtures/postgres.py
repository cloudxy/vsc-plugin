"""Explicit test URL, random schema, real migrations and reliable schema cleanup."""
from contextlib import contextmanager
import uuid

from support.paths import ROOT


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
