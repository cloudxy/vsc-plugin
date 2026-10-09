#!/usr/bin/env python3
"""Explicit candidate maintenance: fetch, retain recoverable Skill bundles, analyze; never adopt.

Run once on demand; no scheduler or background service is installed. Download and analysis have separate durable
states: an already downloaded revision with failed/missing analysis is retried on the next invocation.
No checkout, install, hooks or candidate scripts are executed. Git can fetch only on explicit invocation.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import vendor_bundle
import vendor_review
import vendor_sync

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
CANDIDATE_FORMAT = "vsc.vendor-skill-candidate/v2"


class WatchError(RuntimeError):
    pass


def run(*args, binary=False):
    result = subprocess.run(args, capture_output=True, text=not binary, timeout=300)
    if result.returncode:
        detail = result.stderr.decode(errors="replace") if binary else result.stderr
        raise WatchError(f"命令失败：{' '.join(map(str, args))}\n{detail.strip()}")
    return result.stdout if binary else result.stdout.strip()


def load_json(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise WatchError(f"无法读取 JSON：{path}：{exc}") from exc


def write_json(path, data):
    vendor_review.write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def safe_child(root, *parts):
    root = Path(root).resolve()
    path = root.joinpath(*parts)
    # Reject symlink intermediates, even when their destinations happen to be inside root.
    cursor = root
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        if part in {"..", "."} or cursor.is_symlink():
            raise WatchError(f"不安全路径：{path}")
    resolved = path.resolve()
    if root not in resolved.parents:
        raise WatchError(f"不安全路径：{path}")
    return resolved


def read_source_lock(plugin):
    data = load_json(plugin / "vendor" / "sources.lock.json")
    if data.get("schema_version") != 4:
        raise WatchError("Vendor 锁定文件必须为 schema 4")
    issue = vendor_sync.validate_refresh_policy(data)
    if issue:
        raise WatchError(issue)
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise WatchError("缺 sources 数组")
    ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise WatchError("来源必须是对象")
        issue = vendor_sync.validate(source)
        if issue or source["id"] in ids:
            raise WatchError(f"非法来源：{issue or '重复 id'}")
        ids.add(source["id"])
    refresh = data["policy"]["upstream_refresh"]
    days = refresh["candidate_retention_days"]
    maximum = refresh["max_candidate_snapshots_per_source"]
    if days > 90 or maximum > 3:
        raise WatchError("候选保留策略不能超过 90 天或每来源 3 份（基线也计入）")
    return sources, days, maximum


def ensure_cache(cache, source):
    if cache.exists():
        if not (cache / ".git").is_dir() or cache.is_symlink():
            raise WatchError(f"拒绝覆盖非 Git 缓存：{cache}")
        if run("git", "-C", str(cache), "remote", "get-url", "origin") != source["url"]:
            raise WatchError("缓存 origin 与锁定 URL 不一致")
    else:
        cache.parent.mkdir(parents=True, exist_ok=True)
        run("git", "init", "-q", str(cache))
        run("git", "-C", str(cache), "remote", "add", "origin", source["url"])
    run("git", "-C", str(cache), "config", "remote.origin.promisor", "true")
    run("git", "-C", str(cache), "config", "remote.origin.partialclonefilter", "blob:none")


def fetch(cache, ref):
    run("git", "-c", "core.hooksPath=/dev/null", "-C", str(cache), "fetch", "--depth", "1", "--filter=blob:none", "origin", ref)
    revision = run("git", "-C", str(cache), "rev-parse", "FETCH_HEAD^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise WatchError("候选不是完整 commit")
    if re.fullmatch(r"[0-9a-f]{40}", ref) and revision != ref:
        raise WatchError("基线 commit 校验失败")
    return revision


def git_bundle(cache, revision):
    raw = run("git", "-C", str(cache), "ls-tree", "-rz", revision, binary=True)
    inventory = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, _object_id = header.split()
        path = vendor_bundle.safe_relative(name.decode("utf-8"))
        if any(part in vendor_bundle.EXCLUDED for part in Path(path).parts) or Path(path).name in vendor_bundle.INTERNAL_FILES:
            continue
        permission = int(mode, 8)
        file_mode = stat.S_IFREG | (permission & 0o777) if kind == b"blob" and mode != b"120000" else stat.S_IFLNK
        inventory[path] = {"mode": file_mode, "size": None}
        if len(inventory) > vendor_bundle.MAX_INVENTORY:
            raise WatchError("Git 清单超过安全上限")
    def read_blob(path):
        size = int(run("git", "-C", str(cache), "cat-file", "-s", f"{revision}:{path}"))
        inventory[path]["size"] = size
        if size > vendor_bundle.MAX_FILE_BYTES:
            raise vendor_bundle.ResourceError(f"资源文件超过 {vendor_bundle.MAX_FILE_BYTES} 字节：{path}")
        return run("git", "-C", str(cache), "show", f"{revision}:{path}", binary=True)
    return vendor_bundle.build_bundles(inventory, read_blob, allow_missing=True)


def materialize(cache, revision, source, target):
    bundles, content = git_bundle(cache, revision)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=target.parent, prefix=".pending-"))
    try:
        for relative, data in content.items():
            path = safe_child(temporary, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            executable = any(bundle["files"].get(relative, {}).get("executable") for bundle in bundles.values())
            path.chmod(0o755 if executable else 0o644)
        write_json(temporary / ".vsc-candidate.json", {
            "format": CANDIDATE_FORMAT, "source_id": source["id"], "url": source["url"],
            "bundle_algorithm": vendor_bundle.BUNDLE_ALGORITHM,
            "revision": revision, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scope": "recoverable_skill_resource_bundle_not_full_runtime_or_repository",
            "skills": bundles, "skill_count": len(bundles), "file_count": len(content),
            "resource_sha256": {path: hashlib.sha256(data).hexdigest() for path, data in content.items()},
        })
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary)
        raise
    return target


def verify_candidate(candidate, source_id, revision):
    metadata = load_json(candidate / ".vsc-candidate.json")
    if metadata.get("format") != CANDIDATE_FORMAT or metadata.get("bundle_algorithm") != vendor_bundle.BUNDLE_ALGORITHM or metadata.get("source_id") != source_id or metadata.get("revision") != revision:
        raise WatchError("候选格式或身份不匹配")
    bundles, content = vendor_bundle.scan(candidate, allow_missing=True)
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in content.items()}
    if bundles != metadata.get("skills") or hashes != metadata.get("resource_sha256"):
        raise WatchError(f"候选资源包完整性校验失败：{candidate}")


def existing_candidate(root, source_id, revision):
    for candidate in sorted(root.glob("*"), reverse=True):
        if candidate.is_symlink() or not candidate.is_dir() or not (candidate / ".vsc-candidate.json").is_file():
            continue
        meta = load_json(candidate / ".vsc-candidate.json")
        if meta.get("revision") == revision and meta.get("format") == CANDIDATE_FORMAT and meta.get("bundle_algorithm") == vendor_bundle.BUNDLE_ALGORITHM:
            verify_candidate(candidate, source_id, revision)
            return candidate
    return None


def prune_candidates(root, days, maximum):
    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - days * 86400
    retained = []
    for candidate in root.glob("*"):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        metadata = candidate / ".vsc-candidate.json"
        if not metadata.is_file():
            continue
        meta = load_json(metadata)
        if meta.get("format") not in {CANDIDATE_FORMAT, "vsc.vendor-skill-candidate/v1"}:
            continue
        created = datetime.datetime.fromisoformat(meta["created_at"]).timestamp()
        if created < cutoff:
            shutil.rmtree(candidate)
        else:
            retained.append((created, str(candidate), candidate))
    for _created, _name, candidate in sorted(retained, reverse=True)[maximum:]:
        shutil.rmtree(candidate)


def review_needed(plugin, candidate, current_revision):
    checkpoint = candidate / ".analysis.json"
    if not checkpoint.is_file():
        return True
    try:
        state = load_json(checkpoint)
    except WatchError:
        return True
    metadata = load_json(candidate / ".vsc-candidate.json")
    if not isinstance(state, dict) or state.get("status") != "completed" or state.get("analysis_format") != vendor_review.FORMAT or state.get("current_revision") != current_revision or state.get("candidate_revision") != metadata["revision"]:
        return True
    for key in ("json_report", "markdown_report"):
        path = Path(state.get(key, ""))
        if not path.is_file() or plugin / "vendor" / ".reviews" not in path.parents:
            return True
    try:
        report = load_json(Path(state["json_report"]))
    except WatchError:
        return True
    return not isinstance(report, dict) or report.get("format") != vendor_review.FORMAT or report.get("source") != {
        "id": metadata["source_id"], "current_revision": current_revision, "candidate_revision": metadata["revision"],
    }


def process(plugin, updater, source, days, maximum, review_fn=vendor_review.analyze):
    plugin, updater = Path(plugin).resolve(), Path(updater).resolve()
    cache = safe_child(updater / "repos" / "vsc-vendor-watch", source["id"])
    snapshots = safe_child(updater / "backups" / "vsc-vendor-candidates", source["id"])
    ensure_cache(cache, source)
    candidate_revision = fetch(cache, "HEAD")
    current_revision = source["revision"]
    snapshots.mkdir(parents=True, exist_ok=True)
    # Apply retention before locating snapshots; expired snapshots never silently remain active.
    prune_candidates(snapshots, days, maximum)

    def snapshot(revision):
        existing = existing_candidate(snapshots, source["id"], revision)
        if existing:
            return existing
        fetched = fetch(cache, revision)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        target = safe_child(snapshots, f"{stamp}-{fetched[:12]}")
        return materialize(cache, fetched, source, target)

    try:
        baseline = snapshot(current_revision)
        baseline_metadata = load_json(baseline / ".vsc-candidate.json")
        if candidate_revision == current_revision and not any(bundle.get("usable") is False for bundle in baseline_metadata["skills"].values()):
            print(f"UP-TO-DATE {source['id']} {candidate_revision[:12]} bundle=verified")
            return "up_to_date"
        candidate = snapshot(candidate_revision)
        if not review_needed(plugin, candidate, current_revision):
            print(f"UNCHANGED-CANDIDATE {source['id']} {candidate_revision[:12]} analysis=completed")
            return "unchanged"
        state = {"status": "pending", "current_revision": current_revision, "candidate_revision": candidate_revision,
                 "analysis_format": vendor_review.FORMAT}
        write_json(candidate / ".analysis.json", state)
        try:
            report = review_fn(source["id"], baseline, candidate, current_revision, candidate_revision)
            reports = safe_child(plugin / "vendor", ".reviews")
            json_path, markdown_path = vendor_review.write_report(report, reports)
            state.update(status="completed", json_report=str(json_path), markdown_report=str(markdown_path))
            write_json(candidate / ".analysis.json", state)
        except Exception as exc:
            state.update(status="failed", error=str(exc))
            write_json(candidate / ".analysis.json", state)
            raise
        print(f"CANDIDATE {source['id']} {current_revision[:12]} -> {candidate_revision[:12]} bundle=verified report=written")
        return "reviewed"
    finally:
        prune_candidates(snapshots, days, maximum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--maintenance-root", "--updater-root", dest="maintenance_root",
                        help="本机维护缓存根目录；默认 vendor/.maintenance；--updater-root 为兼容别名")
    parser.add_argument("--source", action="append", dest="source_ids")
    parser.add_argument("--plan", action="store_true", help="只验证并显示本次维护计划；不联网、不写入、不清理")
    args = parser.parse_args()
    plugin = Path(args.plugin).resolve()
    updater = Path(args.maintenance_root).resolve() if args.maintenance_root else plugin / "vendor" / ".maintenance"
    sources, days, maximum = read_source_lock(plugin)
    if args.source_ids:
        unknown = set(args.source_ids) - {source["id"] for source in sources}
        if unknown:
            raise WatchError("未声明来源：" + ", ".join(sorted(unknown)))
        sources = [source for source in sources if source["id"] in args.source_ids]
    if args.plan:
        print(json.dumps({"mode": "manual", "sources": [source["id"] for source in sources],
                          "maintenance_root": str(updater), "reports": str(plugin / "vendor" / ".reviews"),
                          "candidate_retention_days": days, "max_candidate_snapshots_per_source": maximum,
                          "automatic_adoption": False}, ensure_ascii=False, indent=2))
        return
    updater.mkdir(parents=True, exist_ok=True)
    lock_path = updater / ".vsc-vendor-watch.lock"
    if lock_path.is_symlink():
        raise WatchError("维护锁不能是符号链接")
    failures = []
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WatchError("已有候选维护运行中") from exc
        for source in sources:
            try:
                process(plugin, updater, source, days, maximum)
            except (WatchError, vendor_bundle.BundleError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
                failures.append(source["id"])
                print(f"FAILED {source['id']}: {exc}", file=sys.stderr)
    if failures:
        raise WatchError("候选维护失败：" + ", ".join(failures))


if __name__ == "__main__":
    try:
        main()
    except (WatchError, vendor_bundle.BundleError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
