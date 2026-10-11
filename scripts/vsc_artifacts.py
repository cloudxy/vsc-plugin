#!/usr/bin/env python3
"""产物版本模块：保存快照、检查契约/引用/依赖；不判断作品的审美质量。"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from vsc_kernel import ROOT, contract_catalog, relative_file


class ArtifactError(ValueError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def snapshot(project, source, artifact_id):
    source = Path(source)
    if not source.is_file() or source.stat().st_size == 0:
        raise ArtifactError("产物必须是非空文件")
    project = Path(project)
    target = project / "09-台账" / "产物" / (artifact_id + "-" + uuid.uuid4().hex[:12]) / ("content" + source.suffix)
    if target.exists():
        raise ArtifactError(f"版本快照已存在，拒绝覆盖：{target}")
    before = digest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    copied = digest(target)
    if before != copied or digest(source) != copied:
        target.unlink()
        raise ArtifactError("登记期间源文件发生变化，请重新登记")
    # 审片记录的同目录 QA 报告随版本保存；媒体/计划仍按报告内 hash 验证。
    if source.suffix.lower() == ".json" and source.stat().st_size <= 16 * 1024 * 1024:
        try:
            document = json.loads(source.read_text("utf-8"))
        except (ValueError, UnicodeError):
            document = {}
        if isinstance(document, dict) and document.get("format") == "vsc.sample-review/v1":
            reference = document.get("technical_report")
            if isinstance(reference, str) and reference and not Path(reference).is_absolute():
                origin = (source.parent / reference).resolve()
                resource = target.parent / reference
                if not origin.is_relative_to(source.parent.resolve()) or not resource.resolve().is_relative_to(target.parent.resolve()):
                    raise ArtifactError("相对 technical_report 必须在审片文件同目录内；不能包含越界路径")
                if resource.exists() or not origin.is_file() or origin.stat().st_size > 16 * 1024 * 1024:
                    raise ArtifactError("审片报告资源缺失、过大或与版本文件冲突")
                resource.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origin, resource)
                if digest(origin) != digest(resource):
                    raise ArtifactError("审片报告在版本登记期间发生变化")
    return str(target.relative_to(project)), copied


def brief_errors(data):
    errors = []
    for field in ("audience", "desired_experience", "decision_owner"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            errors.append(f"{field} 必须是非空文本")
        elif "请替换" in data[field] or "待填写" in data[field]:
            errors.append(f"{field} 仍是模板占位，请确认项目选择")
    goals = data.get("objectives")
    if not isinstance(goals, list) or not goals:
        errors.append("objectives 必须列出按优先级排序的创作目标")
    else:
        ids = set()
        for goal in goals:
            if not isinstance(goal, dict) or not all(isinstance(goal.get(k), str) and goal[k].strip()
                                                    for k in ("id", "goal", "success_evidence")):
                errors.append("每个目标必须有 id、goal 和 success_evidence")
            elif goal["id"] in ids:
                errors.append("目标 id 不能重复")
            else:
                ids.add(goal["id"])
    limits = data.get("nonnegotiables")
    if not isinstance(limits, list) or not all(isinstance(x, str) and x.strip() for x in limits):
        errors.append("nonnegotiables 必须是文本数组；没有硬约束时显式用 []")
    if not isinstance(data.get("conflict_policy"), str) or not data["conflict_policy"].strip():
        errors.append("conflict_policy 必须说明目标冲突如何裁决")
    return errors


def content_errors(path, artifact_type):
    path = Path(path)
    if not path.is_file():
        return ["版本文件不存在"]
    if path.stat().st_size == 0:
        return ["产物为空"]
    catalog = contract_catalog()
    expected = next((fmt for fmt, entry in catalog.items()
                     if artifact_type in entry.get("artifact_types", [])), None)
    # JSON 契约也可以保存在 Markdown 路径；格式由内容与类型决定，不由后缀猜测。
    if expected or path.suffix.lower() == ".json":
        if path.stat().st_size > 16 * 1024 * 1024:
            return ["契约 JSON 超过 16 MiB"]
        try:
            data = json.loads(path.read_text("utf-8"))
        except (ValueError, UnicodeError) as exc:
            return [f"产物需要有效 JSON 契约：{exc}"]
        if not isinstance(data, dict) or not data:
            return ["JSON 产物不能是空对象或非 object"]
        fmt = data.get("format")
        if expected and fmt != expected:
            return [f"{artifact_type} 必须采用 {expected}"]
        entry = catalog.get(fmt)
        if not entry or not entry.get("validator"):
            return [f"JSON 产物缺少可校验的已登记 format：{fmt}"]
        validator = entry["validator"]
        command = [sys.executable, "-B", str(relative_file(validator["script"], "validator")),
                   *validator["arguments"], str(path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [f"契约检查未完成：{exc}"]
        if result.returncode:
            return ["契约检查失败：" + (result.stdout + result.stderr).strip()[:3000]]
        return []
    if path.suffix.lower() in (".md", ".txt", ".csv"):
        if path.stat().st_size > 2 * 1024 * 1024:
            return ["文本产物超过 2 MiB，请拆分版本"]
        try:
            text = path.read_text("utf-8").strip()
        except UnicodeError:
            return ["文本产物不是 UTF-8"]
        if text in ("", "{}", "[]", "（待填写）", "TODO"):
            return ["产物仍为空壳或占位内容"]
    # 媒体这里只检查文件/版本；实际声画由 media QA 与人工审片验证。
    return []


def object_index(state):
    return {item["id"]: item for item in state.get("objects", [])}


def in_scope(objects, object_id, scope):
    seen = set()
    while object_id and object_id not in seen:
        if object_id == scope:
            return True
        seen.add(object_id)
        object_id = objects.get(object_id, {}).get("parent")
    return scope == "project"


def reference_errors(project, state, item, visited=None):
    objects = object_index(state)
    scope = item.get("scope", "project")
    errors = []
    if scope != "project" and scope not in objects:
        errors.append(f"范围对象不存在：{scope}")
    path = Path(project) / item["path"]
    if path.suffix.lower() != ".json" and not any(item["type"] in e.get("artifact_types", [])
                                                for e in contract_catalog().values()):
        return errors
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError, UnicodeError):
        return errors  # 内容检查负责解释格式错误。
    if not isinstance(data, dict):
        return errors
    if "project_id" in data and data["project_id"] != state["project_id"]:
        errors.append("project_id 不属于当前项目")

    def need(identifier, kind, label, check_scope=True):
        obj = objects.get(identifier) if isinstance(identifier, str) else None
        if not obj or obj["kind"] != kind:
            errors.append(f"{label} 引用了不存在的 {kind}：{identifier}")
        elif check_scope and not in_scope(objects, identifier, scope):
            errors.append(f"{label} 不在产物范围 {scope} 内：{identifier}")
        elif kind == "asset":
            bound = next((x for x in state["artifacts"] if x["id"] == obj.get("artifact")), None)
            if not bound or bound.get("status") != "approved" or bound.get("superseded_by"):
                errors.append(f"参考资产 {identifier} 没有有效已批准版本")
            elif not (Path(project) / bound["path"]).is_file() or digest(Path(project) / bound["path"]) != bound.get("sha256"):
                errors.append(f"参考资产 {identifier} 的版本文件失效")
            else:
                errors.extend(f"参考资产 {identifier}：{problem}" for problem in
                              validate_artifact(project, state, bound, visited=visited))

    fmt = data.get("format")
    if fmt == "vsc.adaptation-map/v1":
        for ep in data.get("episodes", []):
            need(ep.get("id"), "episode", "episodes")
        for unit in data.get("screen_units", []):
            need(unit.get("scene_id"), "scene", "screen_units.scene_id")
            scene = objects.get(unit.get("scene_id"), {})
            if scene and scene.get("parent") != unit.get("episode_id"):
                errors.append("场景所属集与改编 episode_id 不一致")
    elif fmt == "vsc.continuity-plan/v1":
        need(data.get("sequence_id"), "sequence", "sequence_id")
        for shot in data.get("shots", []):
            need(shot.get("id"), "shot", "shots.id")
            if objects.get(shot.get("id"), {}).get("parent") != data.get("sequence_id"):
                errors.append("镜头不属于当前 sequence")
            for ref in shot.get("reference_asset_ids", []):
                need(ref, "asset", "reference_asset_ids", False)
            for key in ("entry_state", "exit_state"):
                scene_id = shot.get(key, {}).get("scene_id")
                need(scene_id, "scene", key + ".scene_id")
                if objects.get(data.get("sequence_id"), {}).get("parent") != scene_id:
                    errors.append(f"{key}.scene_id 与 sequence 所属场景不一致；跨场应使用不同 sequence")
    elif fmt == "vsc.sound-cue-sheet/v1":
        need(data.get("sequence_id"), "sequence", "sequence_id")
        for boundary in data.get("boundaries", []):
            for key in ("from_shot", "to_shot"):
                need(boundary.get(key), "shot", key)
                if objects.get(boundary.get(key), {}).get("parent") != data.get("sequence_id"):
                    errors.append(f"{key} 不属于当前 sequence")
    elif fmt == "vsc.remotion-render-plan/v1":
        for segment in data.get("segments", []):
            if segment.get("source_shot_id"):
                need(segment["source_shot_id"], "shot", "source_shot_id")
    elif fmt == "vsc.sequence-links/v1":
        from vsc_sequence import sequence_problems
        errors.extend(sequence_problems(data, project))
        for unit in data.get("units", []):
            need(unit.get("id"), unit.get("kind"), "units.id")
            for key in ("entry_shot", "exit_shot"):
                need(unit.get(key), "shot", key)
                if not in_scope(objects, unit.get(key), unit.get("id")):
                    errors.append(f"{key} 不属于单元 {unit.get('id')}")
            baselines = [a for a in state.get("artifacts", []) if a["id"] in item.get("depends_on", [])
                         and a["type"] == "vsc.scene_state" and a.get("sha256") == unit.get("state_sha256")
                         and (Path(project) / a["path"]).resolve() == (Path(project) / unit.get("state_path", "")).resolve()]
            if not baselines:
                errors.append(f"单元 {unit.get('id')} 必须依赖匹配路径和 SHA 的 vsc.scene_state 版本")
    elif fmt in ("vsc.media-qa/v1", "vsc.sample-review/v1"):
        try:
            qa = data
            if fmt == "vsc.sample-review/v1":
                qa = json.loads((path.parent / data["technical_report"]).read_text("utf-8"))
                reports = [x for x in state["artifacts"] if x["id"] in item.get("depends_on", [])
                           and x["type"] == "vsc.media_qa" and x.get("sha256") == data.get("technical_report_sha256")]
                if not reports:
                    errors.append("审片必须依赖匹配报告 hash 的 vsc.media_qa 批准版本")
            elif not any(x["id"] in item.get("depends_on", []) and x["type"] in ("vsc.timeline", "vsc.remotion_render_plan")
                         and x.get("sha256") == qa.get("plan_sha256") for x in state["artifacts"]):
                errors.append("技术报告必须依赖匹配 plan_sha256 的已登记时间线版本")
            plan_path = Path(qa["plan_path"])
            errors.extend(reference_errors(project, state, {"type": "vsc.remotion_render_plan",
                                                            "path": str(plan_path), "scope": scope}, visited=visited))
        except (KeyError, OSError, ValueError, TypeError):
            errors.append("技术报告绑定的时间线计划不可读取")
    return errors


def validate_artifact(project, state, item, require_approved=True, visited=None):
    visited = set(visited or ())
    if item["id"] in visited:
        return ["产物依赖形成循环"]
    visited.add(item["id"])
    errors = []
    if item.get("legacy_unverified"):
        errors.append("迁移产物仍未经新规则验证，必须重新登记版本")
    if require_approved and item.get("status") != "approved":
        errors.append("产物尚未批准")
    if item.get("superseded_by"):
        errors.append(f"版本已被 {item['superseded_by']} 替代")
    path = Path(project) / item["path"]
    if not item.get("sha256"):
        errors.append("旧产物没有完整版本凭据，需要重新登记与批准")
    elif not path.is_file():
        errors.append("版本文件不存在")
    elif digest(path) != item["sha256"]:
        errors.append("版本内容已变化，必须登记新版本")
    if not errors or (path.is_file() and item.get("sha256") == digest(path)):
        errors.extend(content_errors(path, item["type"]))
        if not errors:
            errors.extend(reference_errors(project, state, item, visited=visited))
    artifacts = {x["id"]: x for x in state["artifacts"]}
    profile = state.get("profile_snapshot", {})
    stages = profile.get("stages", [])
    owner_index = next((i for i, stage in enumerate(stages) if stage["id"] == item["stage"]), None)
    if (profile.get("dependency_policy") == "previous_stage" and owner_index is not None and owner_index > 0
            and item["type"] in stages[owner_index].get("required", [])):
        previous_stage = stages[owner_index - 1]
        for kind in previous_stage.get("required", []):
            baselines = [artifacts[ref] for ref in item.get("depends_on", []) if ref in artifacts
                         and artifacts[ref]["type"] == kind and artifacts[ref]["stage"] == previous_stage["id"]
                         and artifacts[ref].get("scope", "project") in ("project", item.get("scope", "project"))]
            if not baselines:
                errors.append(f"缺少前置阶段 {previous_stage['id']} 的明确版本依赖：{kind}")
    versions = item.get("dependency_versions", {})
    for ref in item.get("depends_on", []):
        dependency = artifacts.get(ref)
        if not dependency:
            errors.append(f"依赖不存在：{ref}")
            continue
        if versions.get(ref) != dependency.get("sha256"):
            errors.append(f"依赖版本不匹配：{ref}")
        nested = validate_artifact(project, state, dependency, visited=visited)
        errors.extend(f"依赖 {ref}：{problem}" for problem in nested)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("brief",))
    parser.add_argument("file")
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.file).read_text("utf-8"))
        errors = brief_errors(data) if isinstance(data, dict) and data.get("format") == "vsc.creative-brief/v1" else ["format 必须是 vsc.creative-brief/v1"]
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        print("BRIEF: FAIL\n" + "\n".join(errors))
        return 1
    print("BRIEF: PASS（结构有效；目标与审美仍由责任人决定）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
