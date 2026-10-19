"""Load the workspace's local initialization file without executing shell code."""
import os
from pathlib import Path
import re
import shlex


class ConfigurationError(ValueError):
    pass


def workspace_env_path(environ=None):
    env = os.environ if environ is None else environ
    if "VSC_ENV_FILE" in env:
        return Path(env["VSC_ENV_FILE"]).expanduser() if env["VSC_ENV_FILE"] else None
    if env.get("VSC_WORKFLOW_ROOT"):
        return Path(env["VSC_WORKFLOW_ROOT"]).expanduser() / ".env"
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "workflow/kernel.json").is_file():
        return source_root / ".env"
    return Path.cwd() / ".env"


def read_env_file(path):
    path = Path(path)
    if not path.is_file():
        return {}
    if path.stat().st_size > 1024 * 1024:
        raise ConfigurationError("项目 .env 超过 1 MiB 限制")
    try:
        lines = path.read_text("utf-8-sig").splitlines()
    except UnicodeError:
        raise ConfigurationError("项目 .env 需要 UTF-8 编码") from None
    values = {}
    for number, original in enumerate(lines, 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigurationError("项目 .env 第 %d 行不是有效的 KEY=value" % number)
        if value.startswith(("'", '"')):
            try:
                parts = shlex.split(value, comments=True, posix=True)
                if len(parts) != 1:
                    raise ValueError()
                value = parts[0]
            except ValueError:
                raise ConfigurationError("项目 .env 第 %d 行的引号或行尾格式无效" % number) from None
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        if "\x00" in value:
            raise ConfigurationError("项目 .env 第 %d 行含空字符" % number)
        values[key] = value
    return values


def load_workspace_env(path=None, *, environ=None):
    """The local file is authoritative; explicit CLI options still take priority.

    No variable expansion or command substitution is performed. VSC_ENV_FILE=''
    disables automatic loading for an isolated deployment/test process.
    """
    env = os.environ if environ is None else environ
    path = workspace_env_path(env) if path is None else Path(path)
    if path is None:
        return ()
    values = read_env_file(path)
    env.update(values)
    return tuple(values)
