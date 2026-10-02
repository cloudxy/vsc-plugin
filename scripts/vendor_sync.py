#!/usr/bin/env python3
"""安装用户主动选择的 VSC 本地 Vendor 组件。

默认只校验或列计划，绝不下载。用户明确执行 --install/--sync 后，才从 sources.lock.json 中固定到
40 位 Git commit、带来源与许可证声明的记录下载完整上游项目。VSC 不以 MIT 作为来源准入条件：
本地 vendor 可使用 AGPL、Apache、MIT 等项目，且内容不提交到本仓库。此脚本不是法律意见。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "vendor" / "sources.lock.json"
VENDOR = ROOT / "vendor"
DECLARATION = VENDOR / "THIRD_PARTY.md"
COMMIT = re.compile(r"[0-9a-f]{40}\Z", re.I)
SAFE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z")
USAGE_MODES = ("reference_only", "external_tool", "local_component", "external_service", "adapter_protocol")
INTERFACES = ("none", "file", "cli", "http")
UPDATE_MODES = ("candidate_review",)


def validate_refresh_policy(data):
    """Check the repository-wide candidate policy before any source is trusted.

    Source records say how an individual upstream may be tracked.  The policy says
    whether the updater is allowed to make it active.  Keeping that distinction
    here prevents a malformed lock from quietly turning a review queue into an
    auto-updater.
    """
    policy = data.get("policy")
    refresh = policy.get("upstream_refresh") if isinstance(policy, dict) else None
    if not isinstance(refresh, dict):
        return "policy.upstream_refresh 必须是 object"
    if refresh.get("mode") != "candidate_review":
        return "policy.upstream_refresh.mode 必须为 candidate_review"
    if refresh.get("scheduler") != "zcode-plugin-updater":
        return "policy.upstream_refresh.scheduler 必须为 zcode-plugin-updater"
    if refresh.get("automatic_adoption") is not False:
        return "policy.upstream_refresh.automatic_adoption 必须为 false"
    required = {"changed_referenced_skill", "new_skill", "deleted_referenced_skill"}
    analyzed = refresh.get("analysis_required_for")
    if not isinstance(analyzed, list) or any(not isinstance(item, str) for item in analyzed) or not required.issubset(analyzed):
        return "policy.upstream_refresh.analysis_required_for 必须覆盖已引用变更、新增和已引用删除"
    for key in ("candidate_retention_days", "max_candidate_snapshots_per_source"):
        value = refresh.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return f"policy.upstream_refresh.{key} 必须是正整数"
    return ""


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_lock():
    try:
        data = json.loads(LOCK.read_text("utf-8"))
    except FileNotFoundError:
        die(f"缺锁定文件：{LOCK}")
    except json.JSONDecodeError as exc:
        die(f"锁定文件 JSON 损坏：{exc}")
    if data.get("schema_version") != 4 or not isinstance(data.get("sources"), list):
        die("sources.lock.json 必须是 schema_version 4 且含 sources 数组")
    policy_problem = validate_refresh_policy(data)
    if policy_problem:
        die(policy_problem)
    return data


def validate(source):
    required = ("id", "type", "url", "revision", "license_spdx", "license_evidence", "purpose", "owner", "usage")
    missing = [key for key in required if not source.get(key)]
    if missing:
        return "缺字段：" + "、".join(missing)
    if source["type"] != "git":
        return "当前仅支持 type=git"
    if not SAFE_NAME.fullmatch(source["id"]):
        return "id 只能包含字母、数字、点、下划线和连字符，且不得以符号开头"
    if not COMMIT.fullmatch(source["revision"]):
        return "revision 必须是 40 位 Git commit，不接受 branch、tag 或浮动版本"
    if source.get("redistribution") != "local_only":
        return "redistribution 必须为 local_only；vendor 不提供再分发通道"
    usage = source["usage"]
    if not isinstance(usage, dict):
        return "usage 必须是 object"
    if usage.get("mode") not in USAGE_MODES:
        return "usage.mode 必须是 " + "/".join(USAGE_MODES)
    if usage.get("interface") not in INTERFACES:
        return "usage.interface 必须是 " + "/".join(INTERFACES)
    if not isinstance(usage.get("modified"), bool):
        return "usage.modified 必须是布尔值"
    if usage["mode"] == "reference_only" and usage["interface"] != "none":
        return "reference_only 只能使用 interface=none"
    if usage["mode"] != "reference_only" and usage["interface"] == "none":
        return "可执行/交接来源必须声明 file、cli 或 http interface"
    sparse_paths = source.get("sparse_paths")
    if sparse_paths is not None:
        if not isinstance(sparse_paths, list) or not sparse_paths:
            return "sparse_paths 必须是非空数组"
        for path in sparse_paths:
            if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
                return "sparse_paths 只能包含相对、安全的仓库路径"
    update = source.get("update")
    if update is not None:
        if not isinstance(update, dict) or update.get("mode") not in UPDATE_MODES:
            return "update.mode 必须是 " + "/".join(UPDATE_MODES)
        if update.get("track_ref") != "HEAD":
            return "update.track_ref 当前必须为 HEAD"
        if not isinstance(update.get("analysis_required"), bool) or not isinstance(update.get("automatic_adoption"), bool):
            return "update.analysis_required 与 automatic_adoption 必须是布尔值"
        if update["automatic_adoption"]:
            return "当前 Vendor 策略不允许 automatic_adoption；必须先分析并显式采用候选版本"
        if update.get("deleted_referenced_skill") != "retain_last_approved_snapshot":
            return "update.deleted_referenced_skill 必须为 retain_last_approved_snapshot"
        if update.get("new_skill") != "unrouted_pending_review":
            return "update.new_skill 必须为 unrouted_pending_review"
    return ""


def target(source):
    path = (VENDOR / source["id"]).resolve()
    if path.parent != VENDOR.resolve():
        die(f"非法 vendor id：{source['id']}")
    return path


def call(*args):
    completed = subprocess.run(args, text=True, capture_output=True)
    if completed.returncode:
        die("命令失败：%s\n%s" % (" ".join(args), completed.stderr.strip()))
    return completed.stdout.strip()


def sync(source):
    destination = target(source)
    sparse_paths = source.get("sparse_paths")
    if destination.exists() and not (destination / ".git").is_dir():
        die(f"拒绝覆盖非 Git 目录：{destination}")
    if destination.exists():
        origin = call("git", "-C", str(destination), "remote", "get-url", "origin")
        if origin != source["url"]:
            die(f"拒绝同步 {source['id']}：现有 origin 与锁定 URL 不一致")
        if subprocess.run(["git", "-C", str(destination), "diff", "--quiet"]).returncode:
            die(f"拒绝覆盖 {source['id']} 的本地未提交修改")
        if subprocess.run(["git", "-C", str(destination), "diff", "--cached", "--quiet"]).returncode:
            die(f"拒绝覆盖 {source['id']} 的暂存修改")
        if sparse_paths:
            call("git", "-C", str(destination), "sparse-checkout", "set", "--no-cone", *sparse_paths)
    else:
        clone_args = ["git", "clone", "--no-checkout"]
        if sparse_paths:
            clone_args.append("--filter=blob:none")
        clone_args.extend([source["url"], str(destination)])
        call(*clone_args)
        if sparse_paths:
            call("git", "-C", str(destination), "sparse-checkout", "init", "--no-cone")
            call("git", "-C", str(destination), "sparse-checkout", "set", "--no-cone", *sparse_paths)
    call("git", "-C", str(destination), "fetch", "--depth", "1", "origin", source["revision"])
    call("git", "-C", str(destination), "cat-file", "-e", source["revision"] + "^{commit}")
    call("git", "-C", str(destination), "checkout", "--detach", source["revision"])
    actual = call("git", "-C", str(destination), "rev-parse", "HEAD")
    if actual.lower() != source["revision"].lower():
        die(f"{source['id']} 校验失败：期望 {source['revision']}，实际 {actual}")
    print(f"SYNCED {source['id']} @ {actual}")


def select_sources(sources, source_ids):
    if not source_ids:
        return sources
    by_id = {source["id"]: source for source in sources}
    missing = [source_id for source_id in source_ids if source_id not in by_id]
    if missing:
        die("未声明的来源：" + "、".join(missing))
    return [by_id[source_id] for source_id in source_ids]


def declaration_markdown(data):
    """Render the tracked human declaration from the authoritative source lock."""
    lines = [
        "# VSC 第三方开源项目声明",
        "",
        "此文件由 `vendor/sources.lock.json` 生成；不要手工维护项目列表。VSC 源码与文档采用 MIT。本项目也可在用户本机的 `vendor/` 目录直接使用下列开源项目；它们的源码、模型、依赖与资产**不随 VSC Git 仓库提交或再分发**，并继续受各自许可证约束。",
        "",
        "| 项目 | 用途 | 上游许可证 | 安装 id |",
        "| --- | --- | --- | --- |",
    ]
    for source in data["sources"]:
        project = source["id"]
        url = source["url"].removesuffix(".git")
        purpose = source["purpose"].replace("|", "\\|")
        lines.append(f"| [{project}]({url}) | {purpose} | {source['license_spdx']} | `{project}` |")
    lines.extend([
        "",
        "来源 URL、固定 commit、许可证证据与本地调用模式见 [sources.lock.json](sources.lock.json)。用户可自行执行：",
        "",
        "```bash",
        "python3 scripts/vendor_sync.py --install inkos openwrite",
        "```",
        "",
        "这份清单是 VSC 对“借用了哪些开源项目”的公开声明，不改变上游许可证，也不构成对商业使用、再分发、模型权重、声音、图像或数据权利的额外授权。",
        "",
    ])
    return "\n".join(lines)


def write_declaration(data, path=None):
    path = path or DECLARATION
    path.write_text(declaration_markdown(data), "utf-8")
    try:
        label = path.relative_to(ROOT)
    except ValueError:
        label = path
    print(f"DECLARATION: {label} 已从 sources.lock.json 生成")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只校验锁定文件，不联网、不下载")
    mode.add_argument("--plan", action="store_true", help="显示会同步什么，不联网、不下载")
    mode.add_argument("--install", action="store_true", help="安装指定来源；没有名称时安装全部已声明来源")
    mode.add_argument("--sync", action="store_true", help="--install 的兼容别名")
    mode.add_argument("--write-declaration", action="store_true", help="从锁定文件更新已跟踪的 vendor/THIRD_PARTY.md，不联网、不下载")
    parser.add_argument("source_ids", nargs="*", metavar="SOURCE", help="要安装的来源 id，仅与 --install/--sync 一起使用")
    args = parser.parse_args()
    sources = load_lock()["sources"]
    bad = [(source.get("id", "<未命名>"), validate(source)) for source in sources if validate(source)]
    if bad:
        for source_id, reason in bad:
            print(f"INVALID {source_id}: {reason}", file=sys.stderr)
        raise SystemExit(1)
    if args.check:
        print(f"CHECK: PASS  {len(sources)} 个来源；未联网、未下载")
        return
    if args.plan:
        for source in sources:
            usage = source["usage"]
            sparse = f"  sparse={','.join(source['sparse_paths'])}" if source.get("sparse_paths") else ""
            print(f"PLAN {source['id']} @ {source['revision']}  {source['license_spdx']}  {usage['mode']}/{usage['interface']}{sparse}  {source['purpose']}")
        print(f"PLAN: {len(sources)} 个来源；未联网、未下载")
        return
    if args.write_declaration:
        write_declaration(load_lock())
        return
    if args.source_ids and not (args.install or args.sync):
        die("SOURCE 只能与 --install 或 --sync 一起使用")
    selected = select_sources(sources, args.source_ids)
    for source in selected:
        sync(source)


if __name__ == "__main__":
    main()
