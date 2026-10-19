"""User-invoked official tool checks and one-decision staged adoption.

No generated-media request, package script or candidate code is executed. Host
managed tools and unsupported distribution types explicitly remain unsupported.
Git Skills and the registered official npm package use separate fixed snapshots.
"""
import argparse
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from vsc.bootstrap import repository_root
from tools.maintenance import vendor_bundle, vendor_review, vendor_sync, vendor_watch, official_packages

OFFICIAL = {"volcengine-ark-cli": {"id": "volcengine-ark-cli", "type": "git",
    "url": "https://github.com/volcengine/ark-cli.git", "license_spdx": "Apache-2.0",
    "license_evidence": "https://github.com/volcengine/ark-cli/blob/main/LICENSE",
    "purpose": "官方 Ark CLI Skill 源码；不代表 npm CLI 已安装或已接入生产执行", "owner": "volcengine",
    "redistribution": "local_only", "usage": {"mode": "local_component", "interface": "file", "modified": False}}}
HOST = {"id": "openai-host-imagegen", "name": "OpenAI 宿主图像工具", "source_kind": "host_managed",
    "source_url": "https://platform.openai.com/docs/guides/image-generation", "status": "host_managed",
    "current_revision": None, "latest_revision": None, "can_update": False,
    "message": "版本由宿主管理；本工具不能安装、更新或回退宿主能力"}


class SyncError(RuntimeError):
    pass


def _git(*args):
    # Never echo command stderr; remote/tool errors may contain credential material.
    try:
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never", *args],
            capture_output=True, text=True, timeout=15 if args and args[0] == "ls-remote" else 90,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError("Git 检查失败或超时；当前版本保持不变") from exc
    if result.returncode:
        raise SyncError("Git 检查或下载失败；请核对网络、来源与本机 Git 权限")
    return result.stdout.strip()


class ProviderSync:
    def __init__(self, root=None, active_jobs=None, task_guard=None):
        self.root = Path(root or repository_root()).resolve()
        self.vendor = self.root / "vendor"
        self.lock_path = self.vendor / "sources.lock.json"
        self.work = self.vendor / ".provider-sync"
        self.active_jobs = active_jobs
        self.task_guard = task_guard

    def _lock_data(self):
        try:
            data = json.loads(self.lock_path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise SyncError("Vendor 来源登记不可读") from exc
        if not isinstance(data.get("sources"), list):
            raise SyncError("Vendor 来源登记无效")
        return data

    def _sources(self):
        data = self._lock_data()
        sources = {source["id"]: source for source in data["sources"]}
        for key, source in OFFICIAL.items():
            sources.setdefault(key, source)
        return sources

    def _tool(self, source):
        key = source.get("id", "")
        if not vendor_watch.SAFE_ID.fullmatch(key):
            raise SyncError("工具 ID 无效")
        url = source.get("url", "")
        official = key in OFFICIAL and url == OFFICIAL[key]["url"]
        installed = (self.vendor / key / ".git").is_dir()
        supported = (source.get("type") == "git" and url.startswith("https://") and "@" not in url
                     and "?" not in url and "#" not in url and (official or installed))
        return {"id": key, "name": "Ark CLI 官方 Skills 源码" if official else key,
            "source_url": url if supported else None, "source_kind": "official_git" if official else "registered_vendor_git",
            "official": official, "status": "unchecked" if supported else "unsupported_source",
            "current_revision": source.get("revision") if installed else None, "latest_revision": None,
            "can_update": False, "message": "仅更新 Skill 源码；CLI 执行器需另行接入" if official else
                "已登记 Git 来源，未声明为模型供应商官方工具" if supported else "此来源尚未安装或分发格式尚不支持"}

    def list(self):
        return {"tools": [self._tool(source) for source in self._sources().values()] + [self._package_tool(), dict(HOST)]}

    def _package_tool(self, check=False):
        try:
            return official_packages.check(self.work) if check else official_packages.tool(self.work)
        except Exception:
            return {"id": official_packages.TOOL_ID, "name": "Ark CLI 官方分发包（交互参考）",
                "source_kind": "official_npm", "status": "check_failed", "can_update": False,
                "current_revision": None, "latest_revision": None,
                "message": "官方包来源检查失败或固定环境改变；未切换版本"}

    def check(self, tool_id=None):
        sources = self._sources()
        if tool_id and tool_id not in (HOST["id"], official_packages.TOOL_ID) and tool_id not in sources:
            raise SyncError("工具不存在")
        def check_one(source):
            key = source["id"]
            item = self._tool(source)
            if item["status"] != "unsupported_source":
                try:
                    head = _git("ls-remote", source["url"], "HEAD").split()
                    if len(head) < 2 or not re.fullmatch(r"[0-9a-f]{40}", head[0]):
                        raise SyncError("官方来源没有返回有效固定版本")
                    active = self.vendor / key
                    if active.exists():
                        if active.is_symlink() or _git("-C", str(active), "remote", "get-url", "origin") != source["url"]:
                            raise SyncError("已安装来源身份与登记不一致")
                        if _git("-C", str(active), "rev-parse", "HEAD") != source.get("revision"):
                            raise SyncError("已安装版本与锁定版本不一致")
                    item.update(latest_revision=head[0], status="up_to_date" if item["current_revision"] == head[0] else "update_available",
                                can_update=item["current_revision"] != head[0])
                except SyncError as exc:
                    item.update(status="check_failed", message=str(exc), can_update=False)
            return item
        selected = [source for key, source in sources.items() if not tool_id or key == tool_id]
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(check_one, selected))
        if tool_id in (None, official_packages.TOOL_ID):
            result.append(self._package_tool(check=True))
        if tool_id in (None, HOST["id"]):
            result.append(dict(HOST))
        return {"tools": result}

    @contextmanager
    def _locked(self):
        self.work.mkdir(parents=True, exist_ok=True)
        if self.work.is_symlink():
            raise SyncError("更新工作目录不可为符号链接")
        path = self.work / "sync.lock"
        if path.is_symlink():
            raise SyncError("更新锁不可为符号链接")
        with path.open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SyncError("另一个更新正在执行，请稍后重试") from exc
            try:
                self._recover()
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _recover(self):
        journal = self.work / "transaction.json"
        if not journal.exists():
            return
        state = json.loads(journal.read_text("utf-8"))
        key = state["source_id"]
        if not vendor_watch.SAFE_ID.fullmatch(key):
            raise SyncError("更新恢复记录无效")
        active, backup = self.vendor / key, self.work / (key + ".previous")
        if backup.exists():
            if active.exists():
                shutil.rmtree(active)
            os.replace(backup, active)
        elif not state["had_active"] and active.exists():
            shutil.rmtree(active)
        vendor_review.write_atomic(self.lock_path, state["lock_before"])
        journal.unlink()

    def update(self, tool_id, expected_revision, actor):
        if tool_id == HOST["id"]:
            raise SyncError(HOST["message"])
        if tool_id == official_packages.TOOL_ID:
            with (self.task_guard() if self.task_guard else nullcontext()), self._locked():
                if self.active_jobs is None or self.active_jobs(tool_id):
                    raise SyncError("未连接任务权威或存在在途任务；未切换工具版本")
                try:
                    return official_packages.adopt(self.work, expected_revision, actor, self.active_jobs)
                except official_packages.PackageError as exc:
                    raise SyncError(str(exc)) from None
        if not actor or not re.fullmatch(r"[0-9a-f]{40}", str(expected_revision)):
            raise SyncError("更新需要人工操作身份和检查所得固定版本")
        with (self.task_guard() if self.task_guard else nullcontext()), self._locked():
            sources = self._sources()
            if tool_id not in sources:
                raise SyncError("工具不存在")
            source = dict(sources[tool_id])
            if self._tool(source)["status"] == "unsupported_source":
                raise SyncError("此来源暂不支持更新")
            if self.active_jobs is None:
                raise SyncError("未连接任务权威，无法确认在途任务，未切换工具版本")
            if self.active_jobs(tool_id):
                raise SyncError("存在在途或提交结果未知的任务；等待完成后再更新")
            before = self.lock_path.read_text("utf-8")
            active = self.vendor / tool_id
            if active.exists():
                if active.is_symlink() or _git("-C", str(active), "remote", "get-url", "origin") != source["url"]:
                    raise SyncError("已安装来源身份不匹配")
                if _git("-C", str(active), "rev-parse", "HEAD") != source.get("revision") or _git("-C", str(active), "status", "--porcelain"):
                    raise SyncError("活跃目录版本已改变或有本地修改，未覆盖")
            if source.get("revision") == expected_revision and active.exists():
                return dict(self._tool(source), status="up_to_date", latest_revision=expected_revision)
            stage = Path(tempfile.mkdtemp(prefix=tool_id + "-", dir=self.work))
            try:
                # Reuse the vendor fetch and recoverable bundle checks before checkout.
                cache = self.work / (tool_id + ".cache")
                vendor_watch.ensure_cache(cache, source)
                revision = vendor_watch.fetch(cache, expected_revision)
                candidate = stage / "candidate"
                vendor_watch.materialize(cache, revision, source, candidate)
                vendor_watch.verify_candidate(candidate, tool_id, revision)
                report = vendor_review.analyze(tool_id, active, candidate, source.get("revision", ""), revision)
                if report["summary"]["candidate_unusable_skill_count"] or any(
                        change["kind"] == "deleted_referenced_skill" for change in report["changes"]):
                    raise SyncError("新版缺少已引用 Skill 或资源不完整；保留旧版")
                checkout = stage / "checkout"
                sparse = source.get("sparse_paths", [])
                _git("clone", "--depth", "1", "--no-checkout", *(["--filter=blob:none"] if sparse else []), "--", source["url"], str(checkout))
                if sparse:
                    _git("-C", str(checkout), "sparse-checkout", "init", "--no-cone")
                    _git("-C", str(checkout), "sparse-checkout", "set", "--no-cone", *sparse)
                _git("-C", str(checkout), "fetch", "--depth", "1", "origin", revision)
                _git("-C", str(checkout), "checkout", "--detach", revision)
                if _git("-C", str(checkout), "rev-parse", "HEAD") != revision:
                    raise SyncError("下载版本不匹配")
                # Scan the actual activated tree, not just a separately validated candidate.
                bundles, _ = vendor_bundle.scan(checkout, allow_missing=True, entry_paths=vendor_review.routed_paths(tool_id))
                if bundles != report["bundles"]["candidate"]:
                    raise SyncError("安装内容与已校验候选不一致")
                if self.lock_path.read_text("utf-8") != before or self.active_jobs(tool_id):
                    raise SyncError("更新基线或在途任务发生变化，请重新检查")
                if active.exists() and (_git("-C", str(active), "rev-parse", "HEAD") != source.get("revision") or _git("-C", str(active), "status", "--porcelain")):
                    raise SyncError("活跃目录在下载期间发生变化，未覆盖")
                source["revision"] = revision
                if vendor_sync.validate(source):
                    raise SyncError("新版本来源登记不满足 Vendor 约束")
                data = json.loads(before)
                data["sources"] = [row for row in data["sources"] if row["id"] != tool_id] + [source]
                report["adoption"] = {"actor": actor, "decision": "update", "scope": "source_snapshot_only_no_runtime_execution"}
                report["summary"]["adoption"] = "adopted_by_update_action"
                vendor_review.write_report(report, self.vendor / ".reviews")
                backup = self.work / (tool_id + ".previous")
                journal = self.work / "transaction.json"
                vendor_review.write_atomic(journal, json.dumps({"source_id": tool_id, "had_active": active.exists(), "lock_before": before}))
                if active.exists():
                    os.replace(active, backup)
                os.replace(checkout, active)
                vendor_review.write_atomic(self.lock_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                # Removing the journal commits the pair; exceptions before this restore both.
                journal.unlink()
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                return dict(self._tool(source), status="updated", current_revision=revision, latest_revision=revision,
                    message="已下载并验证固定 Git Skill 源码；没有安装运行依赖、执行候选代码或调用模型")
            except Exception as exc:
                self._recover()
                if isinstance(exc, SyncError):
                    raise
                raise SyncError("下载、兼容检查或切换失败；旧版保持可用（" + type(exc).__name__ + "）") from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="官方工具：检查 → 更新／不更新（不更新无需执行命令）")
    parser.add_argument("action", choices=["check", "update"])
    parser.add_argument("--tool")
    parser.add_argument("--revision", help="检查返回的固定 commit 或包版本摘要")
    parser.add_argument("--actor", help="执行更新的真实操作人")
    parser.add_argument("--database-env", default="VSC_DATABASE_URL")
    args = parser.parse_args(argv)
    engine = None
    try:
        updater = ProviderSync()
        if args.action == "check":
            result = updater.check(args.tool)
        else:
            if not args.tool or not args.revision or not args.actor:
                parser.error("update 需要 --tool、--revision、--actor；该命令即采用授权")
            from sqlalchemy import create_engine
            from vsc.adapters.persistence.postgres.resource_settings_store import ResourceSettingsRepository
            url = os.environ.get(args.database_env)
            if not url:
                raise SyncError("当前进程未加载 " + args.database_env + "；请从 ~/.zshenv 显式传入")
            engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
            updater.active_jobs = ResourceSettingsRepository(engine).active_jobs
            updater.task_guard = ResourceSettingsRepository(engine).execution_guard
            result = updater.update(args.tool, args.revision, args.actor)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"error": "provider_sync_failed", "message": str(exc) if isinstance(exc, SyncError) else "工具更新失败，请检查本机配置"}, ensure_ascii=False))
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
