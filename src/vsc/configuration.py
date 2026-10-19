"""One Dynaconf configuration entry for application initialization settings."""
import os
from pathlib import Path


class ConfigurationError(ValueError):
    pass


def workspace_env_path(environ=None):
    env = os.environ if environ is None else environ
    if "VSC_ENV_FILE" in env:
        return Path(env["VSC_ENV_FILE"]).expanduser() if env["VSC_ENV_FILE"] else None
    if env.get("VSC_WORKFLOW_ROOT"):
        return Path(env["VSC_WORKFLOW_ROOT"]).expanduser() / "config/.env"
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "workflow/kernel.json").is_file():
        return source_root / "config/.env"
    return Path.cwd() / "config/.env"


def _check_dotenv(path):
    """Reject invalid local files without putting credentials in diagnostics."""
    if path is None or not path.is_file():
        return
    from io import StringIO
    from dynaconf.vendor.dotenv.parser import parse_stream
    if path.stat().st_size > 1024 * 1024:
        raise ConfigurationError("项目 .env 超过 1 MiB 限制")
    try:
        content = path.read_text("utf-8")
        if "\x00" in content or any(binding.error for binding in parse_stream(StringIO(content))):
            raise ConfigurationError("项目 .env 格式无效，请检查 KEY=value 与引号")
    except UnicodeError:
        raise ConfigurationError("项目 .env 需要 UTF-8 编码") from None


def create_settings(root=None, *, env_file=None):
    """Defaults < process settings < config/.env < explicit CLI options.

    Like hcdataspider, use explicit settings paths, a project prefix, merging and
    dotenv_override. VSC_ENV_FILE='' isolates a process from the local file.
    No shell files or commands are executed. Restart after editing .env.
    """
    from dynaconf import Dynaconf
    from vsc.bootstrap import repository_root
    root = Path(root) if root is not None else repository_root()
    path = workspace_env_path() if env_file is None else Path(env_file)
    _check_dotenv(path)
    return Dynaconf(
        envvar_prefix="VSC",
        settings_files=[str(root / "config/default/settings.toml")],
        root_path=str(root),
        load_dotenv=path is not None,
        dotenv_path=str(path) if path is not None else None,
        dotenv_override=True,
        dotenv_verbose=False,
        merge_enabled=True,
        core_loaders=["TOML"],
        environments=False,
        encoding="utf-8",
    )


_settings = None


def get_settings():
    global _settings
    if _settings is None:
        _settings = create_settings()
    return _settings


def get_config(key, default=None):
    """Accept the existing CLI configuration keys, including custom env names."""
    settings = get_settings()
    if key.startswith("VSC_"):
        return settings.get(key[4:], default, fresh=True)
    settings.get("MEDIA_ROOT")
    return os.environ.get(key, default)


def __getattr__(name):
    if name == "settings":
        return get_settings()
    raise AttributeError(name)
