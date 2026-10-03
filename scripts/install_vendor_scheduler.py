#!/usr/bin/env python3
"""Explicitly deploy two thin VSC entrypoints into an existing plugin-updater.

Default/--check are read-only. --apply backs up the two exact old entrypoints, validates generated
syntax, then installs project delegators. Never edits cron, ZCode tasks, Vendor sources or route data.
"""
import argparse
import datetime
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

NAMES = ("vsc-vendor-watch.py", "vsc-vendor-maintenance.sh")


def validate_root(root, plugin):
    root, plugin = Path(root), Path(plugin)
    if root.is_symlink() or not root.is_absolute() or root.name != "plugin-updater" or not root.is_dir():
        raise ValueError("--updater-root 必须是现有、绝对路径、非符号链接的 plugin-updater 目录")
    if root.resolve() != root:
        raise ValueError("更新中心路径不能包含符号链接或 ..")
    if not plugin.is_absolute() or plugin.resolve() != plugin:
        raise ValueError("--plugin 必须是无符号链接的绝对路径")
    for filename in ("vendor_watch.py", "vsc-vendor-maintenance.sh"):
        if not (plugin / "scripts" / filename).is_file():
            raise ValueError(f"项目入口缺失：{filename}")
    for relative in ("scripts", "scripts/lib", "backups"):
        path = root / relative
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"部署目录不安全：{path}")
    for filename in NAMES:
        path = root / "scripts" / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"只允许替换现有普通入口：{path}")
    for filename in ("paths.sh", "log.sh", "lock.sh"):
        path = root / "scripts/lib" / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"中央日志/锁库缺失或不安全：{path}")
    return root, plugin


def entrypoints(root, plugin):
    worker = f'''#!/usr/bin/env python3
"""Thin compatibility entry; lifecycle implementation belongs to the VSC project."""
import subprocess
import sys

if __name__ == "__main__":
    raise SystemExit(subprocess.run([
        sys.executable, "-B", {str(plugin / "scripts/vendor_watch.py")!r},
        "--plugin", {str(plugin)!r}, "--updater-root", {str(root)!r}, *sys.argv[1:]
    ]).returncode)
'''
    shell = f'''#!/bin/bash
# Thin logged scheduler entry. Explicitly installed; no duplicated Vendor lifecycle logic.
set -u
export PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0
VSC_CENTRAL_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
source "$VSC_CENTRAL_SCRIPTS/lib/paths.sh"
source "$VSC_CENTRAL_SCRIPTS/lib/log.sh"
source "$VSC_CENTRAL_SCRIPTS/lib/lock.sh"
VSC_PLUGIN_ROOT={shlex.quote(str(plugin))}
init_log "$LOGS/vsc-vendor-maintenance-$(date +%Y%m%d).log"
ensure_lock "$BASE/state/vsc-vendor-maintenance.lock"
log "===== VSC Vendor 候选维护开始 ====="
log ">> 只下载资源包候选与分析；不执行或采用候选"
if /bin/bash "$VSC_PLUGIN_ROOT/scripts/vsc-vendor-maintenance.sh" --plugin "$VSC_PLUGIN_ROOT" --updater-root "$BASE" "$@" >> "$LOG" 2>&1; then
    log "===== VSC Vendor 候选维护结束：成功 ====="
    exit 0
else
    vsc_exit_status=$?
    log "===== VSC Vendor 候选维护结束：失败 exit=${{vsc_exit_status}}；当前 active Vendor 未变 ====="
    exit "$vsc_exit_status"
fi
'''
    return {NAMES[0]: worker.encode(), NAMES[1]: shell.encode()}


def atomic_bytes(path, content, mode):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".vsc-entrypoint-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def deploy(root, plugin, apply=False):
    root, plugin = validate_root(root, plugin)
    replacements = entrypoints(root, plugin)
    compile(replacements[NAMES[0]], NAMES[0], "exec")
    check = subprocess.run(["/bin/bash", "-n"], input=replacements[NAMES[1]], capture_output=True)
    if check.returncode:
        raise ValueError("生成的中央 shell 语法检查失败")
    originals = {name: ((root / "scripts" / name).read_bytes(), (root / "scripts" / name).stat().st_mode & 0o777)
                 for name in NAMES}
    changed = [name for name in NAMES if originals[name][0] != replacements[name]]
    if not changed or not apply:
        return {"status": "current" if not changed else "needs_deployment", "changed": changed,
                "targets": [str(root / "scripts" / name) for name in NAMES]}
    backup_root = root / "backups/vsc-vendor-entrypoints"
    if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
        raise ValueError("入口备份目录不安全")
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-")
    backup = Path(tempfile.mkdtemp(dir=backup_root, prefix=stamp))
    manifest = {"format": "vsc.vendor-entrypoint-backup/v1", "targets": {}}
    for name, (content, mode) in originals.items():
        atomic_bytes(backup / name, content, mode)
        manifest["targets"][name] = {"path": str(root / "scripts" / name), "sha256": hashlib.sha256(content).hexdigest(), "mode": mode}
    atomic_bytes(backup / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode(), 0o600)
    try:
        for name in NAMES:
            atomic_bytes(root / "scripts" / name, replacements[name], 0o755)
    except Exception:
        for name, (content, mode) in originals.items():
            atomic_bytes(root / "scripts" / name, content, mode)
        raise
    return {"status": "deployed", "changed": changed, "backup": str(backup), "targets": [str(root / "scripts" / name) for name in NAMES]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updater-root", required=True)
    parser.add_argument("--plugin", default=str(Path(__file__).resolve().parent.parent))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = deploy(Path(args.updater_root), Path(args.plugin), apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.check and result["status"] != "current":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
