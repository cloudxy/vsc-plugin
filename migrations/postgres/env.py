"""Explicit migrations; never read legacy projects or create schemas on app boot."""
import os
from alembic import context
from sqlalchemy import create_engine, pool
from vsc.adapters.persistence.postgres.schema import metadata

config = context.config
target_metadata = metadata


def database_url():
    url = config.attributes.get("database_url") or os.environ.get("VSC_DATABASE_URL")
    if not url:
        raise RuntimeError("Set VSC_DATABASE_URL for an explicit PostgreSQL migration")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+"):
        raise RuntimeError("PostgreSQL migration requires a PostgreSQL URL")
    return url


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(database_url(), poolclass=pool.NullPool)
        with engine.connect() as conn:
            context.configure(connection=conn, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
