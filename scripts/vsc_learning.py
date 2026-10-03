#!/usr/bin/env python3
"""Pure helpers for bounded retrieval and version-bound capability trials.

This module never calls a model, executes imported content, or updates project state.
"""
import hashlib
import json
import re
from pathlib import Path


METHOD_FORMAT = "vsc.capability-method/v1"
METHOD_FIELDS = {"format", "name", "kind", "method", "limits", "allowed_roles", "tags", "method_sha256"}
KINDS = {"action", "vfx", "layout", "emotion", "dialogue", "sound", "editing"}
CONCEPTS = {
    "action": ("action", "动作", "打斗", "武打", "追逐", "搏斗"),
    "vfx": ("vfx", "特效", "爆炸", "光效"),
    "layout": ("layout", "布局", "构图", "场景", "空间"),
    "emotion": ("emotion", "情绪", "感情", "张力"),
    "dialogue": ("dialogue", "对话", "对白", "台词"),
    "sound": ("sound", "声音", "音乐", "音效", "混音", "配乐"),
    "editing": ("editing", "剪辑", "转场", "衔接", "节奏"),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def method_digest(item):
    return digest({key: item.get(key, "") for key in ("name", "kind", "method", "limits", "allowed_roles", "tags")})


def features(text):
    text = text.lower()
    terms = set(re.findall(r"[a-z0-9_]{2,}", text))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.update(run[index:index + 2] for index in range(len(run) - 1))
    for concept, aliases in CONCEPTS.items():
        if any(alias in text for alias in aliases):
            terms.add("concept:" + concept)
    return terms


def retrieve(task, candidates, budget, forced_ids=()):
    """Return relevant knowledge within serialized character budget.

    Explicit selections must fit in full. Automatic candidates require lexical or
    domain overlap; high confidence alone does not make a memory relevant.
    """
    if not isinstance(budget, int) or budget < 1 or budget > 100000:
        raise ValueError("--budget-chars 必须在 1–100000 之间")
    forced = set(forced_ids)
    query = features(task)
    ranked = []
    found = set()
    for candidate in candidates:
        item = candidate["value"]
        item_id = item["id"]
        found.add(item_id)
        score = len(query & features(candidate["search"]))
        if item_id in forced or score:
            ranked.append((item_id not in forced, -score, item_id, candidate))
    if forced - found:
        raise ValueError("显式选择不可用：" + ",".join(sorted(forced - found)))
    ranked.sort(key=lambda row: row[:3])
    selected, used, omitted = [], 0, []
    for _optional, negative_score, item_id, candidate in ranked:
        size = len(json.dumps(candidate["value"], ensure_ascii=False, sort_keys=True))
        if used + size > budget:
            if item_id in forced:
                raise ValueError(f"显式选择 {item_id} 超出检索字符预算；提高 --budget-chars 或缩小选择")
            omitted.append(item_id)
            continue
        selected.append({**candidate, "score": -negative_score})
        used += size
    return selected, {"strategy": "lexical-and-domain-overlap/v1", "scope": "retrieved_knowledge",
                      "budget_chars": budget, "used_chars": used,
                      "selected_ids": [row["value"]["id"] for row in selected],
                      "omitted_for_budget": omitted, "candidate_count": len(candidates)}


def artifact_snapshot(item):
    return {key: item.get(key) for key in ("id", "type", "stage", "scope", "path", "sha256", "sha256_16")}


def source_problems(project, source, sha16):
    path = Path(source["path"])
    if not path.is_absolute():
        path = Path(project) / path
    if not path.is_file() or sha16(path) != source.get("sha256_16"):
        return [f"来源 {source['id']} 文件缺失或已改变；需要重新登记"]
    if source.get("sha256") and file_digest(path) != source["sha256"]:
        return [f"来源 {source['id']} 完整摘要不一致；需要重新登记"]
    return []


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def capability_source_problems(project, state, capability, sha16):
    if capability.get("origin") == "imported_method":
        return [] if capability.get("import_review") else ["导入方法尚未复核，先带 --note 决定 pilot"]
    observations = capability.get("observation_ids", [])
    if not observations:
        return ["能力缺少带证据的观察"]
    problems = []
    for observation_id in observations:
        observation = next((entry for entry in state["learning"]["observations"] if entry["id"] == observation_id), None)
        if not observation:
            problems.append(f"观察 {observation_id} 不存在")
            continue
        source = next((entry for entry in state["sources"] if entry["id"] == observation["source_id"]), None)
        if not source or source.get("rights") not in ("owned", "licensed"):
            problems.append(f"观察 {observation_id} 来源权属不能用于生产性学习")
        elif source:
            problems.extend(source_problems(project, source, sha16))
            if observation.get("source_sha256_16") and observation["source_sha256_16"] != source.get("sha256_16"):
                problems.append(f"观察 {observation_id} 来源版本绑定已改变")
            source_path = Path(source["path"])
            if not source_path.is_absolute():
                source_path = Path(project) / source_path
            if source_path.is_file() and observation.get("source_sha256") and file_digest(source_path) != observation["source_sha256"]:
                problems.append(f"观察 {observation_id} 绑定的来源完整摘要已改变")
        evidence = Path(observation["evidence_path"])
        if not evidence.is_absolute():
            evidence = Path(project) / evidence
        if not evidence.is_file() or sha16(evidence) != observation.get("evidence_sha256_16"):
            problems.append(f"观察 {observation_id} 证据缺失或已改变")
        elif observation.get("evidence_sha256") and file_digest(evidence) != observation["evidence_sha256"]:
            problems.append(f"观察 {observation_id} 证据完整摘要不一致")
    return problems


def context_problems(project, state, trial, capability, validate_artifact, sha16):
    problems = []
    context = next((entry for entry in state.get("contexts", []) if entry["id"] == trial.get("context_id")), None)
    if not context:
        return ["试用上下文不存在"]
    path = Path(context["path"])
    if not path.is_absolute():
        path = Path(project) / path
    if not path.is_file() or sha16(path) != context.get("sha256_16"):
        problems.append("试用上下文文件缺失或已改变")
    elif context.get("sha256") and file_digest(path) != context["sha256"]:
        problems.append("试用上下文文件完整摘要已改变")
    if trial.get("context_sha256_16") != context.get("sha256_16"):
        problems.append("试用绑定的上下文版本不一致")
    if context.get("sha256") and trial.get("context_sha256") != context["sha256"]:
        problems.append("试用绑定的上下文完整摘要不一致")
    if trial.get("method_sha256") != method_digest(capability):
        problems.append("试用方法版本已改变")
    if not trial.get("input_versions"):
        problems.append("试用没有已批准输入版本")
    for snapshot in trial.get("input_versions", []):
        artifact = next((entry for entry in state["artifacts"] if entry["id"] == snapshot.get("id")), None)
        if not artifact:
            problems.append(f"试用输入 {snapshot.get('id')} 不存在")
        elif artifact_snapshot(artifact) != snapshot:
            problems.append(f"试用输入 {artifact['id']} 版本已改变")
        else:
            problems.extend(validate_artifact(project, state, artifact, require_approved=True))
    return problems


def evaluation_problems(project, state, capability, evaluation, validate_artifact, sha16):
    if evaluation.get("format") != "vsc.capability-evaluation/v2":
        return ["旧评测缺少方法、上下文和输入/输出版本绑定，需重新评测"]
    trial = next((entry for entry in state["learning"].get("trials", []) if entry["id"] == evaluation.get("trial_id")), None)
    if not trial or trial.get("capability_id") != capability["id"]:
        return ["评测试用不存在或不属于该能力"]
    problems = context_problems(project, state, trial, capability, validate_artifact, sha16)
    if evaluation.get("method_sha256") != method_digest(capability):
        problems.append("评测方法版本已改变")
    if evaluation.get("context_id") != trial.get("context_id") or evaluation.get("input_versions") != trial.get("input_versions"):
        problems.append("评测与试用的上下文或输入版本不一致")
    if evaluation.get("context_sha256") != trial.get("context_sha256"):
        problems.append("评测与试用的上下文完整摘要不一致")
    if not isinstance(evaluation.get("criteria"), str) or not evaluation["criteria"].strip():
        problems.append("评测缺少通过标准")
    for label in ("output_version", "baseline_version", "evidence_version"):
        snapshot = evaluation.get(label)
        if not isinstance(snapshot, dict):
            problems.append(f"评测缺少 {label}")
            continue
        artifact = next((entry for entry in state["artifacts"] if entry["id"] == snapshot.get("id")), None)
        if not artifact:
            problems.append(f"{label} 产物不存在")
        elif artifact_snapshot(artifact) != snapshot:
            problems.append(f"{label} 版本已改变")
        else:
            problems.extend(validate_artifact(project, state, artifact, require_approved=True))
    return problems


def promotion_problems(project, state, capability, validate_artifact, sha16):
    evaluations = capability.get("evaluations", [])
    valid_passes = [entry for entry in evaluations if entry.get("result") == "pass"
                    and not evaluation_problems(project, state, capability, entry, validate_artifact, sha16)]
    problems = []
    if not valid_passes:
        problems.append("没有有效且绑定当前版本的通过评测；旧评测不可直接晋升")
    resolved = {entry_id for entry in valid_passes for entry_id in entry.get("resolves", [])}
    failures = [entry for entry in evaluations if entry.get("format") == "vsc.capability-evaluation/v2"
                and entry.get("result") == "fail" and entry.get("id") not in resolved]
    if failures:
        problems.append("存在未解决的失败评测：" + ",".join(entry.get("id", "legacy-failure") for entry in failures))
    return problems


def validate_method_package(data, roles):
    if not isinstance(data, dict) or data.get("format") != METHOD_FORMAT:
        raise ValueError(f"可复用方法格式必须为 {METHOD_FORMAT}")
    extra = set(data) - METHOD_FIELDS
    if extra:
        raise ValueError("方法包禁止携带项目/来源/记忆/评测字段：" + ",".join(sorted(extra)))
    for key in ("name", "method", "limits"):
        if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 6000:
            raise ValueError(f"方法包 {key} 必须是 1–6000 字符的文本")
    if data.get("kind") not in KINDS:
        raise ValueError("方法包 kind 不受支持")
    for key in ("allowed_roles", "tags"):
        values = data.get(key)
        if not isinstance(values, list) or len(values) > 20 or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in values):
            raise ValueError(f"方法包 {key} 必须是最多 20 个非空短文本的数组")
    if not data["allowed_roles"] or set(data["allowed_roles"]) - set(roles):
        raise ValueError("方法包 allowed_roles 缺失或含未知角色")
    if data.get("method_sha256") != method_digest(data):
        raise ValueError("方法包内容摘要不匹配")
    return {key: data[key] for key in ("name", "kind", "method", "limits", "allowed_roles", "tags")}


def main():
    import argparse
    import sys
    from vsc_kernel import role_cards
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    method = commands.add_parser("method").add_subparsers(dest="action", required=True)
    validate = method.add_parser("validate")
    validate.add_argument("file")
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        validate_method_package(data, role_cards())
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"METHOD: FAIL  {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"METHOD: PASS  {data['name']}")


if __name__ == "__main__":
    main()
