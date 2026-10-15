"""Explicit test URL, random schema, real migrations and reliable schema cleanup."""
from contextlib import contextmanager
import uuid

from support.paths import ROOT


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
            with admin.begin() as connection:
                connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        admin.dispose()
