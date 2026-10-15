"""Synthetic legacy state and isolated PostgreSQL migration fixtures."""
import copy
import hashlib
import json
import uuid

from vsc.project import migration as M


def legacy(root, sqlite=False, *, profile=None, revision=4, state_overrides=None, legacy_profile_digest=False):
    root.mkdir(parents=True, exist_ok=True)
    profile = copy.deepcopy(profile or {"profile_id": "vsc.synthetic", "version": "1", "stages": []})
    if sqlite:
        profile["storage_policy"] = "sqlite-series-v1"
    digest = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if legacy_profile_digest else M._digest(profile)
    state = {"schema_version": 3, "project_id": "legacy-project", "revision": revision,
        "title": "迁移测试", "owner": "source-owner", "profile_id": profile["profile_id"],
        "profile_version": profile["version"], "profile_snapshot": profile, "profile_sha256": digest,
        "objects": [], "artifacts": [], "sources": [], "decisions": [], "events": []}
    state.update(state_overrides or {})
    M._write(root / "vsc.json", state)
    if sqlite:
        from vsc.adapters.persistence.sqlite import series
        series.commit_state(root, state, revision - 1)
    return state


def setup_postgres(case, root, test_url):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from vsc.adapters.persistence.postgres.store import PostgresResourceStore
    case.schema = "vsc_migration_test_" + uuid.uuid4().hex
    url = test_url.replace("postgresql://", "postgresql+psycopg://", 1)
    case.admin = create_engine(url)
    with case.admin.begin() as conn:
        conn.execute(text('CREATE SCHEMA "' + case.schema + '"'))
    case.engine = create_engine(url, connect_args={"options": "-csearch_path=" + case.schema})
    config = Config(str(root / "migrations/postgres/alembic.ini"))
    with case.engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    case.store = PostgresResourceStore(engine=case.engine)


def teardown_postgres(case):
    from sqlalchemy import text
    case.engine.dispose()
    with case.admin.begin() as conn:
        conn.execute(text('DROP SCHEMA "' + case.schema + '" CASCADE'))
    case.admin.dispose()
