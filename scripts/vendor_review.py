#!/usr/bin/env python3
"""Compare an installed Vendor source with a downloaded candidate Skill snapshot.

This is deliberately an analysis module, not an updater. It never changes the active vendor source,
the tracked source lock, or VSC routing. The ZCode updater owns downloading candidates and retention;
this script classifies what needs a human decision before a candidate can be adopted.
"""
import argparse
import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path

import vendor_skills

FORMAT = "vsc.vendor-skill-analysis/v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def skill_files(root):
    root = Path(root)
    if not root.is_dir():
        return {}
    result = {}
    for path in sorted(root.rglob("SKILL.md")):
        if ".git" in path.parts or not path.is_file():
            continue
        result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def routed_paths(source_id):
    routes = {}
    for stage, records in vendor_skills.ROUTES.items():
        for route_source, relative_path, _readiness, _purpose in records:
            if route_source == source_id:
                routes.setdefault(relative_path, []).append(stage)
    return {path: sorted(stages) for path, stages in routes.items()}


def item(path, before, after, route_stages, kind, action):
    result = {"path": path, "kind": kind, "route_stages": route_stages, "required_action": action}
    if before:
        result["before_sha256"] = before
    if after:
        result["after_sha256"] = after
    return result


def analyze(source_id, current, candidate, current_revision="", candidate_revision=""):
    before = skill_files(current)
    after = skill_files(candidate)
    routes = routed_paths(source_id)
    changes = []
    for path in sorted(after.keys() - before.keys()):
        stages = routes.get(path, [])
        changes.append(item(
            path, "", after[path], stages,
            "new_referenced_skill" if stages else "new_skill",
            "review_existing_route_before_use" if stages else "unrouted_pending_review",
        ))
    for path in sorted(before.keys() - after.keys()):
        stages = routes.get(path, [])
        changes.append(item(
            path, before[path], "", stages,
            "deleted_referenced_skill" if stages else "deleted_skill",
            "retain_last_approved_snapshot_or_replace_route" if stages else "record_and_do_not_route",
        ))
    for path in sorted(before.keys() & after.keys()):
        if before[path] == after[path]:
            continue
        stages = routes.get(path, [])
        changes.append(item(
            path, before[path], after[path], stages,
            "changed_referenced_skill" if stages else "changed_skill",
            "semantic_and_compatibility_review_required" if stages else "observe_only_until_routed",
        ))
    counts = {}
    for change in changes:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
    blocking = [change for change in changes if change["kind"] in {
        "new_referenced_skill", "deleted_referenced_skill", "changed_referenced_skill",
    }]
    return {
        "format": FORMAT,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"id": source_id, "current_revision": current_revision, "candidate_revision": candidate_revision},
        "current_path": str(Path(current).resolve()),
        "candidate_path": str(Path(candidate).resolve()),
        "summary": {
            "current_skill_count": len(before), "candidate_skill_count": len(after),
            "change_count": len(changes), "counts_by_kind": counts,
            "adoption": "blocked_pending_review" if blocking else "no_routed_skill_change",
        },
        "policy": {
            "automatic_adoption": False,
            "new_skill": "unrouted_pending_review",
            "changed_referenced_skill": "semantic_and_compatibility_review_required",
            "deleted_referenced_skill": "retain_last_approved_snapshot_or_replace_route",
        },
        "changes": changes,
    }


def markdown(report):
    source = report["source"]
    summary = report["summary"]
    lines = [
        f"# Vendor Skill 更新分析：{source['id']}",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 当前 revision：`{source['current_revision'] or '未识别'}`",
        f"- 候选 revision：`{source['candidate_revision'] or '未识别'}`",
        f"- Skill：{summary['current_skill_count']} → {summary['candidate_skill_count']}；变化 {summary['change_count']} 项",
        f"- 采用状态：**{summary['adoption']}**",
        "",
        "此报告不自动更新 active vendor、路由或 `sources.lock.json`。新增 Skill 默认不路由；已路由 Skill 发生变化或删除时，必须先完成语义/兼容性审查并记录决定。",
        "",
    ]
    if not report["changes"]:
        lines.append("没有发现 `SKILL.md` 内容或路径变化。\n")
        return "\n".join(lines)
    lines.extend(["| 类型 | 路径 | 当前路由 | 所需决定 |", "| --- | --- | --- | --- |"])
    for change in report["changes"]:
        routes = ", ".join(change["route_stages"]) or "未路由"
        lines.append(f"| `{change['kind']}` | `{change['path']}` | {routes} | `{change['required_action']}` |")
    lines.extend([
        "",
        "## 审查结论（待填写）",
        "",
        "- 变化后的已路由 Skill 是否仍符合 VSC 的角色、产物、权属与安全边界：",
        "- 新增 Skill 是否应新增显式 VSC 路由；若是，目标阶段、运行环境和测试是什么：",
        "- 已删除 Skill 是保留最后批准快照、替换路由，还是退役：",
        "- 是否显式更新 `vendor/sources.lock.json` 的 revision 并重新安装：",
        "",
    ])
    return "\n".join(lines)


def write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(content)
    os.replace(temporary, path)


def write_report(report, output_dir):
    output = Path(output_dir)
    revision = (report["source"]["candidate_revision"] or "unknown")[:12]
    base = f"{report['source']['id']}-{revision}"
    json_path = output / f"{base}.json"
    markdown_path = output / f"{base}.md"
    write_atomic(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_atomic(markdown_path, markdown(report))
    return json_path, markdown_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze_parser = commands.add_parser("analyze", help="对比当前 Vendor 与候选快照中的 SKILL.md")
    analyze_parser.add_argument("--source", required=True)
    analyze_parser.add_argument("--current", required=True)
    analyze_parser.add_argument("--candidate", required=True)
    analyze_parser.add_argument("--current-revision", default="")
    analyze_parser.add_argument("--candidate-revision", default="")
    analyze_parser.add_argument("--output-dir", help="同时写入 JSON 和 Markdown 报告")
    analyze_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = analyze(args.source, args.current, args.candidate, args.current_revision, args.candidate_revision)
    if args.output_dir:
        json_path, markdown_path = write_report(report, args.output_dir)
        print(f"REPORT: {json_path}")
        print(f"REPORT: {markdown_path}")
    if args.json or not args.output_dir:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
