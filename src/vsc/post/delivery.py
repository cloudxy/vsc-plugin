#!/usr/bin/env python3
"""Build and verify a local delivery bundle without publishing or copying sources implicitly.

Only registered artifact snapshots and explicitly authorized manifest media are
copied. Original snapshots remain byte-identical. The relative index is the
migration map; stored QA is historical evidence, fresh QA uses packaged paths.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from vsc.production.handoffs import digest, local_file, project_errors, safe_relative, sha, validation_errors

FORMAT = "vsc.delivery-bundle/v1"


def _load(path):
    data = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON必须为object：" + str(path))
    return data


def _write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _closure(state, identifier):
    artifacts = {row["id"]: row for row in state.get("artifacts", [])}
    result, visiting = {}, set()
    def visit(current):
        if current in visiting:
            raise ValueError("依赖形成循环：" + current)
        if current in result:
            return
        row = artifacts.get(current)
        if not row:
            raise ValueError("依赖未登记：" + current)
        visiting.add(current)
        for ref in row.get("depends_on", []):
            visit(ref)
            if row.get("dependency_versions", {}).get(ref) != artifacts[ref].get("sha256"):
                raise ValueError("依赖版本漂移：" + current + " -> " + ref)
        visiting.remove(current)
        result[current] = row
    visit(identifier)
    return list(result.values())


def build_bundle(project, state, manifest_id, destination, validate_callback=None):
    """Build a fresh directory. Never changes a project, approved snapshot or approval."""
    project, destination = Path(project).resolve(), Path(destination)
    if destination.exists():
        raise ValueError("打包目标必须是新目录，拒绝覆盖：" + str(destination))
    if destination.resolve().is_relative_to(project):
        raise ValueError("交付包必须在作品目录之外，避免递归打包")
    artifacts = _closure(state, manifest_id)
    item = next(row for row in artifacts if row["id"] == manifest_id)
    if item.get("type") != "vsc.delivery_manifest" or item.get("status") != "approved":
        raise ValueError("只能打包真实已批准的vsc.delivery_manifest版本")
    manifest = _load(local_file(project, item["path"]))
    errors = project_errors(manifest, project, state, item, validate_callback)
    if errors:
        raise ValueError("交付检查失败：" + "; ".join(errors))
    # Plan first: every copy is explicit, project-contained and hash-bound.
    planned = {}
    def stage(relative, expected, role):
        source = local_file(project, relative)
        if not sha(expected) or digest(source) != expected:
            raise ValueError("打包输入SHA不匹配：" + relative)
        target = "project/" + relative
        if target in planned and planned[target]["sha256"] != expected:
            raise ValueError("打包路径冲突：" + relative)
        planned[target] = {"source": source, "sha256": expected, "role": role}
    for artifact in artifacts:
        # Successful draft candidates are evidence, selection is the approval.
        if artifact.get("superseded_by") or artifact.get("legacy_unverified"):
            raise ValueError("交付依赖版本失效：" + artifact["id"])
        if artifact.get("status") != "approved" and artifact.get("type") != "vsc.generation_record":
            raise ValueError("交付依赖尚未批准：" + artifact["id"])
        stage(artifact["path"], artifact.get("sha256"), "artifact")
    for media in manifest["package_media"]:
        stage(media["path"], media["sha256"], "media")
    for engineering in manifest["engineering_files"]:
        stage(engineering["path"], engineering["sha256"], "engineering")
    source_ids = set()
    for artifact in artifacts:
        if artifact.get("type") == "vsc.adaptation_plan":
            document = _load(local_file(project, artifact["path"]))
            source_ids.update(row.get("source_id") for row in document.get("source_units", []) if row.get("source_id"))
    source_references = []
    for source in state.get("sources", []):
        if source["id"] not in source_ids:
            continue
        reference = {key: source[key] for key in ("id", "kind", "sha256", "rights") if key in source}
        reference["snapshot_included"] = "project/" + source.get("path", "") in planned
        if reference["snapshot_included"]:
            reference["path"] = source["path"]
        else:
            reference["availability"] = "not_packaged_requires_separate_authorization"
        source_references.append(reference)
    if source_ids - {row["id"] for row in source_references}:
        raise ValueError("交付依赖来源没有登记版本")
    # A review may have a relative QA attachment copied with its immutable snapshot.
    for artifact in artifacts:
        if artifact.get("type") != "vsc.sample_review":
            continue
        review = _load(local_file(project, artifact["path"]))
        attachment = review.get("technical_report")
        if isinstance(attachment, str) and safe_relative(attachment):
            relative = (Path(artifact["path"]).parent / attachment).as_posix()
            stage(relative, review.get("technical_report_sha256"), "review_attachment")
    file_rows = [{"path": path, "sha256": row["sha256"], "role": row["role"]}
                 for path, row in sorted(planned.items())]
    bundle = {
        "format": FORMAT, "project_id": state["project_id"], "delivery_id": manifest["delivery_id"],
        "manifest": {"id": item["id"], "sha256": item["sha256"], "path": "project/" + item["path"]},
        "artifacts": [{k: row[k] for k in ("id", "type", "path", "sha256", "status", "scope", "depends_on", "dependency_versions") if k in row} for row in artifacts],
        "objects": state.get("objects", []), "decisions": state.get("decisions", []),
        "source_references": source_references,
        "files": file_rows, "tool_versions": manifest["tool_versions"],
        "render_parameters": manifest["render_parameters"],
        "evidence_limits": ["原始QA路径只作历史证据；迁移复检使用包内文件。", "打包不构成新的创作批准或对外发布。"],
    }
    destination.mkdir(parents=True)
    for relative, row in planned.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(row["source"], target)
        if digest(target) != row["sha256"] or digest(row["source"]) != row["sha256"]:
            raise ValueError("输入在复制期间变化，交付包未完成：" + relative)
    _write(destination / "bundle.json", bundle)
    result = verify_bundle(destination, rerun_qa=False)
    if result["errors"]:
        raise ValueError("包内复检失败：" + "; ".join(result["errors"]))
    return bundle


def verify_bundle(directory, rerun_qa=True, adapter=None):
    """Verify all bytes after migration and optionally rerun actual local media QA.

    Returns explicit passed/failed/not_checked evidence. A missing FFmpeg tool or
    incomplete media never turns into a successful QA result.
    """
    root = Path(directory).resolve()
    errors, qa_results = [], []
    result = {"format": "vsc.delivery-verification/v1", "status": "failed", "errors": errors,
              "integrity": "failed", "qa": qa_results, "human_review": "original_versions_only",
              "source_revalidation": "not_checked"}
    try:
        bundle = _load(local_file(root, "bundle.json"))
        if bundle.get("format") != FORMAT or not isinstance(bundle.get("files"), list):
            raise ValueError("无效delivery-bundle格式")
        index = {}
        for row in bundle["files"]:
            if not isinstance(row, dict) or not sha(row.get("sha256")):
                raise ValueError("包文件清单必须有完整SHA")
            path = row.get("path")
            if path in index:
                errors.append("包文件路径重复：" + str(path))
            index[path] = row
            try:
                file = local_file(root, path)
                if digest(file) != row["sha256"]:
                    errors.append("包文件SHA不匹配：" + path)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        # Reject unlisted payloads; verification reports are outside immutable payload.
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                errors.append("交付包中不允许符号链接：" + relative)
            elif path.is_file() and relative != "bundle.json" and not relative.startswith("verification/") and relative not in index:
                errors.append("发现未声明包文件：" + relative)
        manifest_ref = bundle.get("manifest", {})
        row = index.get(manifest_ref.get("path"), {})
        if row.get("sha256") != manifest_ref.get("sha256"):
            errors.append("manifest未绑定包内SHA清单")
        manifest = _load(local_file(root, manifest_ref.get("path")))
        errors.extend(validation_errors(manifest))
        artifacts = bundle.get("artifacts", [])
        state = {"project_id": bundle.get("project_id"), "objects": bundle.get("objects", []),
                 "decisions": bundle.get("decisions", []), "artifacts": artifacts}
        item = next((a for a in artifacts if a["id"] == manifest_ref.get("id")), None)
        if not item or item.get("sha256") != manifest_ref.get("sha256"):
            errors.append("manifest没有对应登记版本")
        else:
            closure = _closure(state, item["id"])
            for artifact in closure:
                stored = index.get("project/" + artifact.get("path", ""), {})
                if stored.get("sha256") != artifact.get("sha256"):
                    errors.append("依赖文件未完整归档：" + artifact["id"])
                if artifact.get("status") != "approved" and artifact.get("type") != "vsc.generation_record":
                    errors.append("包依赖尚未批准：" + artifact["id"])
            if not errors:
                # Hash/object/choice checks use relocated paths, never the old project.
                def validate_packaged(project, current, artifact, require_approved=True):
                    path = local_file(project, artifact["path"])
                    try:
                        document = _load(path)
                    except (ValueError, UnicodeError):
                        return []
                    if document.get("format") in {"vsc.screenplay/v1", "vsc.coverage-plan/v1", "vsc.selected-takes/v1", "vsc.animatic/v1", "vsc.timeline/v1", "vsc.mix/v1"}:
                        return project_errors(document, project, current, artifact, validate_packaged)
                    return []
                errors.extend(project_errors(manifest, root / "project", state, item, validate_packaged))
        if errors:
            return result
        result["integrity"] = "passed"
        sources = bundle.get("source_references", [])
        if sources and all(row.get("snapshot_included") for row in sources):
            from vsc.assets.sources import locator_errors
            source_index = {row["id"]: row for row in sources}
            for artifact in artifacts:
                if artifact.get("type") != "vsc.adaptation_plan":
                    continue
                document = _load(local_file(root / "project", artifact["path"]))
                for unit in document.get("source_units", []):
                    source = source_index.get(unit.get("source_id"), {})
                    path = local_file(root / "project", source.get("path"))
                    if digest(path) != unit.get("source_sha256") or digest(path) != source.get("sha256"):
                        errors.append("迁移来源SHA不匹配：" + str(unit.get("source_id")))
                    errors.extend(locator_errors(path, unit.get("locator")))
            result["source_revalidation"] = "failed" if errors else "passed"
        elif not sources:
            result["source_revalidation"] = "not_applicable"
        if rerun_qa:
            from vsc.adapters.media.qa import LocalProbeAdapter, check_plan
            tool = adapter or LocalProbeAdapter()
            verification = root / "verification"
            verification.mkdir(exist_ok=True)
            by_id = {a["id"]: a for a in artifacts}
            for i, variant in enumerate(manifest["release_variants"]):
                timeline = _load(local_file(root / "project", by_id[variant["timeline"]["id"]]["path"]))
                qa = _load(local_file(root / "project", by_id[variant["qa"]["id"]]["path"]))
                plan_path = local_file(root / "project", by_id[variant["timeline"]["id"]]["path"])
                report = check_plan(plan_path, root / "project", tool,
                                    local_file(root / "project", variant["render"]["path"]),
                                    qa.get("loudness_target"))
                report["delivery_id"] = manifest["delivery_id"]
                report["release_variant_id"] = variant["id"]
                report["original_timeline_sha256"] = variant["timeline"]["sha256"]
                _write(verification / f"variant-{i + 1}-qa.json", report)
                qa_results.append({"variant_id": variant["id"], "status": report["status"],
                                   "simulated": report.get("simulated", False),
                                   "report": f"verification/variant-{i + 1}-qa.json"})
                if report["status"] != "passed" or report.get("simulated"):
                    errors.append("迁移QA未实际通过：" + variant["id"])
        else:
            qa_results.append({"status": "not_checked", "reason": "未请求迁移QA；仅检查包内版本和SHA"})
        result["status"] = "failed" if errors else "passed"
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("project")
    build.add_argument("manifest_id")
    build.add_argument("output")
    verify = sub.add_parser("verify")
    verify.add_argument("directory")
    verify.add_argument("--no-qa", action="store_true", help="仅版本/SHA核验；明确保留QA未复检状态")
    args = parser.parse_args()
    try:
        if args.command == "build":
            from vsc.project.artifacts import validate_artifact
            state = _load(Path(args.project) / "vsc.json")
            bundle = build_bundle(args.project, state, args.manifest_id, args.output, validate_artifact)
            print("DELIVERY BUNDLE: PASS " + bundle["delivery_id"])
            return 0
        report = verify_bundle(args.directory, rerun_qa=not args.no_qa)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError) as exc:
        print("DELIVERY BUNDLE: FAIL " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
