"""Locate workspace-owned workflow declarations and compatible CLI entries."""
import os
from pathlib import Path
import sys


def repository_root():
    explicit = os.environ.get("VSC_WORKFLOW_ROOT")
    candidates = [Path(explicit).expanduser()] if explicit else [Path(__file__).resolve().parents[2], Path(sys.prefix) / "share/vsc-workflow"]
    for candidate in candidates:
        if (candidate / "workflow/kernel.json").is_file():
            return candidate.resolve()
    raise RuntimeError("找不到 VSC workflow/kernel.json；请设置 VSC_WORKFLOW_ROOT 指向工作流根目录")


def script_path(name):
    if Path(name).name != name or not name.endswith(".py"):
        raise ValueError("CLI entry must be a Python basename")
    return repository_root() / "scripts" / name


def service_from_environment(database_env="VSC_DATABASE_URL", media_root=None):
    from vsc.assets.resource_service import ResourceError, ResourceService
    url = os.environ.get(database_env)
    if not url:
        raise ResourceError("未加载 " + database_env + "；请在启动 shell 加载 ~/.zshenv 并显式传入进程", "database_not_configured")
    from vsc.adapters.persistence.postgres.store import PostgresResourceStore
    from vsc.adapters.storage.local.store import LocalStorage
    from sqlalchemy.exc import SQLAlchemyError
    try:
        store = PostgresResourceStore(url)
    except (SQLAlchemyError, ValueError):
        raise ResourceError("数据库连接配置不合法；请核对 " + database_env + " 的服务与连接格式", "invalid_database_config") from None
    try:
        storage = LocalStorage(media_root or os.environ.get("VSC_MEDIA_ROOT", ".vsc-resource-media"))
    except BaseException:
        store.close()
        raise
    return ResourceService(store, storage)

