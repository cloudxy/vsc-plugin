#!/usr/bin/env python3
"""Compare an installed Vendor source with a downloaded candidate Skill snapshot.

This is deliberately an analysis module, not an updater. It never changes the active vendor source,
the tracked source lock, or VSC routing. Project-owned vendor_watch.py owns candidates and retention;
this script compares bounded resource bundles and classifies decisions required before adoption.
"""
import argparse
import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path

import vendor_skills
import vendor_bundle

FORMAT = "vsc.vendor-skill-analysis/v2"


def skill_files(root):
    """Compatibility name: values now hash resource bundles, not just SKILL.md."""
    bundles, _content = vendor_bundle.scan(root)
    return {path: value["sha256"] for path, value in bundles.items()}


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
    before_bundles, before_content = vendor_bundle.scan(current, allow_missing=True)
    after_bundles, after_content = vendor_bundle.scan(candidate, allow_missing=True)
    before = {path: value["sha256"] for path, value in before_bundles.items()}
    after = {path: value["sha256"] for path, value in after_bundles.items()}
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
    for change in changes:
        before_files = before_bundles.get(change["path"], {}).get("files", {})
        after_files = after_bundles.get(change["path"], {}).get("files", {})
        change["resources"] = [
            {"path": path, "kind": "added" if path not in before_files else "deleted" if path not in after_files else "changed",
             "before": before_files.get(path), "after": after_files.get(path)}
            for path in sorted(before_files.keys() | after_files.keys())
            if before_files.get(path) != after_files.get(path)
        ]
    counts = {}
    for change in changes:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
    blocking = [change for change in changes if change["kind"] in {
        "new_referenced_skill", "deleted_referenced_skill", "changed_referenced_skill",
    }]
    metadata_changes = [
        {"path": path, "kind": "added" if path not in before_content else "deleted" if path not in after_content else "changed",
         "before_sha256": hashlib.sha256(before_content[path]).hexdigest() if path in before_content else None,
         "after_sha256": hashlib.sha256(after_content[path]).hexdigest() if path in after_content else None}
        for path in sorted(before_content.keys() | after_content.keys())
        if vendor_bundle.metadata_path(path) and before_content.get(path) != after_content.get(path)
    ]
    unusable = {
        scope: [{"path": path, "route_stages": routes.get(path, []), "problems": bundle["problems"]}
                for path, bundle in bundles.items() if bundle.get("usable") is False]
        for scope, bundles in (("current", before_bundles), ("candidate", after_bundles))
    }
    external_runtime = [{"skill": path, **reference}
                        for path, bundle in after_bundles.items()
                        for reference in bundle.get("external_runtime_references", [])]
    return {
        "format": FORMAT,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"id": source_id, "current_revision": current_revision, "candidate_revision": candidate_revision},
        "current_path": str(Path(current).resolve()),
        "candidate_path": str(Path(candidate).resolve()),
        "summary": {
            "current_skill_count": len(before), "candidate_skill_count": len(after),
            "change_count": len(changes), "counts_by_kind": counts,
            "adoption": "blocked_pending_review" if blocking or metadata_changes or unusable["candidate"] else "no_routed_skill_change",
            "source_metadata_change_count": len(metadata_changes),
            "current_unusable_skill_count": len(unusable["current"]),
            "candidate_unusable_skill_count": len(unusable["candidate"]),
            "candidate_external_runtime_reference_count": len(external_runtime),
        },
        "policy": {
            "automatic_adoption": False,
            "new_skill": "unrouted_pending_review",
            "changed_referenced_skill": "semantic_and_compatibility_review_required",
            "deleted_referenced_skill": "retain_last_approved_snapshot_or_replace_route",
            "comparison_scope": "skill_directory_recursive_local_references_root_license_and_dependencies",
            "automatic_candidate_execution": False,
        },
        "bundles": {"current": before_bundles, "candidate": after_bundles},
        "source_metadata_changes": metadata_changes,
        "unusable_skills": unusable,
        "external_runtime_references": external_runtime,
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
    if report["source_metadata_changes"]:
        lines.extend(["## 根许可证／依赖声明变化", ""])
        lines.extend(f"- `{resource['kind']}` `{resource['path']}`" for resource in report["source_metadata_changes"])
        lines.append("")
    for scope, records in report["unusable_skills"].items():
        if not records:
            continue
        lines.extend([f"## {'当前' if scope == 'current' else '候选'}不可用 Skill（缺失或不安全本地引用）", ""])
        for record in records:
            lines.append(f"- `{record['path']}`：不可用，不能视为已就绪或采用；当前路由 {', '.join(record['route_stages']) or '无'}")
            lines.extend(f"  - `{problem['origin']}` `{problem['kind']}`：`{problem['reference']}`" for problem in record["problems"])
        lines.append("")
    if report["external_runtime_references"]:
        lines.extend(["## 外部运行时位置（未读取、未打包、未验证就绪）", ""])
        lines.extend(f"- `{reference['skill']}`：`{reference['reference']}`（`{reference['kind']}`）"
                     for reference in report["external_runtime_references"])
        lines.append("")
    if not report["changes"] and not report["source_metadata_changes"] and not any(report["unusable_skills"].values()):
        lines.append("没有发现 Skill 资源包变化（含规则、脚本、参考、资产、许可证与依赖声明）。\n")
        return "\n".join(lines)
    lines.extend(["| 类型 | 路径 | 当前路由 | 所需决定 |", "| --- | --- | --- | --- |"])
    for change in report["changes"]:
        routes = ", ".join(change["route_stages"]) or "未路由"
        lines.append(f"| `{change['kind']}` | `{change['path']}` | {routes} | `{change['required_action']}` |")
    for change in report["changes"]:
        lines.extend(["", f"### `{change['path']}` 的资源变化", ""])
        lines.extend(f"- `{resource['kind']}` `{resource['path']}`" for resource in change["resources"])
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
    source_id = report["source"]["id"]
    for value in (source_id, revision):
        if not value or not all(char.isalnum() or char in "_.-" for char in value) or value in {".", ".."}:
            raise vendor_bundle.BundleError("报告来源/版本标识不安全")
    base = f"{source_id}-{revision}"
    json_path = output / f"{base}.json"
    markdown_path = output / f"{base}.md"
    write_atomic(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_atomic(markdown_path, markdown(report))
    return json_path, markdown_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze_parser = commands.add_parser("analyze", help="对比完整 Skill 资源包；不执行候选内容")
    analyze_parser.add_argument("--source", required=True)
    analyze_parser.add_argument("--current", required=True)
    analyze_parser.add_argument("--candidate", required=True)
    analyze_parser.add_argument("--current-revision", default="")
    analyze_parser.add_argument("--candidate-revision", default="")
    analyze_parser.add_argument("--output-dir", help="同时写入 JSON 和 Markdown 报告")
    analyze_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = analyze(args.source, args.current, args.candidate, args.current_revision, args.candidate_revision)
    except (vendor_bundle.BundleError, OSError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    if args.output_dir:
        json_path, markdown_path = write_report(report, args.output_dir)
        print(f"REPORT: {json_path}")
        print(f"REPORT: {markdown_path}")
    if args.json or not args.output_dir:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
