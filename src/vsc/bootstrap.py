"""Locate workspace declarations and commands owned by a scripts subdirectory."""
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


def workspace_python(root=None):
    """Use the initialized workspace runtime for checks launched by any host."""
    root = Path(root) if root is not None else repository_root()
    candidate = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else sys.executable


def script_path(relative):
    entry = Path(relative)
    if (entry.is_absolute() or len(entry.parts) < 2 or ".." in entry.parts
            or entry.suffix != ".py" or "\\" in str(relative)):
        raise ValueError("CLI entry must be a grouped relative Python path")
    return repository_root() / "scripts" / entry


def service_from_environment(database_env="VSC_DATABASE_URL", media_root=None):
    from vsc.configuration import get_config
    from vsc.assets.resource_service import ResourceError, ResourceService
    url = get_config(database_env)
    if not url:
        raise ResourceError("未加载 " + database_env + "；请在工作区config/.env 中填写该项后重新启动工具", "database_not_configured")
    from vsc.adapters.persistence.postgres.store import PostgresResourceStore
    from vsc.adapters.storage.local.store import LocalStorage
    from sqlalchemy.exc import SQLAlchemyError
    try:
        store = PostgresResourceStore(url)
    except (SQLAlchemyError, ValueError):
        raise ResourceError("数据库连接配置不合法；请核对 " + database_env + " 的服务与连接格式", "invalid_database_config") from None
    try:
        storage = LocalStorage(media_root or get_config("VSC_MEDIA_ROOT"))
    except BaseException:
        store.close()
        raise
    return ResourceService(store, storage)

