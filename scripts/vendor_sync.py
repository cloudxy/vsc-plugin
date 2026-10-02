#!/usr/bin/env python3
"""审计式同步 VSC 本地 vendor 缓存。

默认只校验或列计划，绝不下载。--sync 只同步 sources.lock.json 中已获批准、固定到 40 位 Git
commit、带 SPDX 标识和许可证证据的 git 来源。每个来源都要声明是仅供参考、独立工具还是独立服务；
vendor 内容应被 .gitignore 排除，不能复制进 MIT 核心。此脚本不是法律意见。
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
COMMIT = re.compile(r"[0-9a-f]{40}\Z", re.I)
SAFE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z")
USAGE_MODES = ("reference_only", "external_tool", "external_service", "adapter_protocol")
INTERFACES = ("none", "file", "cli", "http")
AGPL_LICENSES = ("AGPL-3.0-only", "AGPL-3.0-or-later")


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
    if data.get("schema_version") != 2 or not isinstance(data.get("sources"), list):
        die("sources.lock.json 必须是 schema_version 2 且含 sources 数组")
    return data


def validate(source):
    required = ("id", "type", "url", "revision", "license_spdx", "license_evidence", "purpose", "owner", "usage", "review")
    missing = [key for key in required if not source.get(key)]
    if missing:
        return "缺字段：" + "、".join(missing)
    if source["type"] != "git":
        return "当前仅支持 type=git"
    if not SAFE_NAME.fullmatch(source["id"]):
        return "id 只能包含字母、数字、点、下划线和连字符，且不得以符号开头"
    if not COMMIT.fullmatch(source["revision"]):
        return "revision 必须是 40 位 Git commit，不接受 branch、tag 或浮动版本"
    if source["review"].get("status") != "approved":
        return "review.status 必须为 approved"
    if not source["review"].get("by") or not source["review"].get("at"):
        return "approved 来源必须记录 review.by 与 review.at"
    if source.get("redistribution") not in (None, "local_only"):
        return "redistribution 只能省略或为 local_only；vendor 不提供再分发通道"
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
    if usage["mode"] == "external_service" and source["license_spdx"] in AGPL_LICENSES and usage["modified"]:
        if not usage.get("network_source_offer"):
            return "修改后的 AGPL 外部服务必须记录 usage.network_source_offer；先完成网络源码义务评估"
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
    else:
        call("git", "clone", "--no-checkout", source["url"], str(destination))
    call("git", "-C", str(destination), "fetch", "--depth", "1", "origin", source["revision"])
    call("git", "-C", str(destination), "cat-file", "-e", source["revision"] + "^{commit}")
    call("git", "-C", str(destination), "checkout", "--detach", source["revision"])
    actual = call("git", "-C", str(destination), "rev-parse", "HEAD")
    if actual.lower() != source["revision"].lower():
        die(f"{source['id']} 校验失败：期望 {source['revision']}，实际 {actual}")
    print(f"SYNCED {source['id']} @ {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只校验锁定文件，不联网、不下载")
    mode.add_argument("--plan", action="store_true", help="显示会同步什么，不联网、不下载")
    mode.add_argument("--sync", action="store_true", help="同步已批准且固定版本的来源")
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
            print(f"PLAN {source['id']} @ {source['revision']}  {source['license_spdx']}  {usage['mode']}/{usage['interface']}  {source['purpose']}")
        print(f"PLAN: {len(sources)} 个来源；未联网、未下载")
        return
    for source in sources:
        sync(source)


if __name__ == "__main__":
    main()
