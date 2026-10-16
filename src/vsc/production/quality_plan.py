"""Read-only evidence coverage and rework audit; never grants production approval.

The small check interface consumes a local evidence manifest. It does not load or
mutate project authority, call providers, or interpret aesthetic quality.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _pointer(value, pointer):
    if pointer == "":
        return value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("JSON pointer 必须为空或以 / 开头")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                raise ValueError("非法数组位置")
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise ValueError("字段位置不是容器")
    return value


class _Evidence:
    def __init__(self, root, problems, read_ref=None):
        self.root = Path(root).resolve()
        self.problems = problems
        self.read_ref = read_ref

    def read(self, ref, label, *, structured=False):
        try:
            if not isinstance(ref, dict) or not (_text(ref.get("path")) or (self.read_ref and _text(ref.get("artifact_id")))):
                raise ValueError("缺少 path / sha256 引用")
            digest = ref.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("需要完整 sha256")
            if self.read_ref is not None:
                content = self.read_ref(ref)
                if not isinstance(content, bytes):
                    raise ValueError("证据读取器必须返回固定原始字节")
            else:
                path = (self.root / ref["path"]).resolve()
                path.relative_to(self.root)
                content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("文件摘要已改变")
            if structured or "pointer" in ref:
                value = _pointer(json.loads(content), ref.get("pointer", ""))
                if value is None or value == "" or value == [] or value == {}:
                    raise ValueError("引用字段为空")
                return value
            if not content:
                raise ValueError("证据文件为空")
            return digest
        except (ValueError, OSError, KeyError, IndexError, TypeError) as exc:
            self.problems.append(f"{label}: {exc}")
            return None


def _rows(data, key, problems):
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        problems.append(f"{key} 必须是对象数组")
        return []
    return value


def _union(intervals, duration):
    if not isinstance(intervals, list):
        raise ValueError("usable_intervals 必须是数组；未知用 null")
    pairs = []
    for pair in intervals:
        if not isinstance(pair, list) or len(pair) != 2 or not all(_number(x) for x in pair):
            raise ValueError("采用区间必须为非负有限秒数对")
        start, end = pair
        if not start < end <= duration:
            raise ValueError("采用区间越界或为空")
        pairs.append((start, end))
    merged = []
    for start, end in sorted(pairs):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def check(plan, root, *, read_ref=None):
    """Return auditable facts and unknowns. No report field is a quality pass."""
    problems, unknowns, warnings = [], [], []
    report = {"format": "vsc.quality-report/v1", "quality_result": "unknown",
              "execution_authorized": False, "problems": problems, "unknowns": unknowns,
              "warnings": warnings, "coverage": [], "rework": [], "review_reuse": []}
    if not isinstance(plan, dict):
        report.update(status="blocked")
        problems.append("检查包必须是 JSON 对象")
        return report
    evidence = _Evidence(root, problems, read_ref)
    if plan.get("format") != "vsc.quality-plan/v1":
        problems.append("format 必须为 vsc.quality-plan/v1")
    if not _text(plan.get("project_id")):
        problems.append("需要 project_id；不得混合项目统计")
    requirements = _rows(plan, "requirements", problems)
    if not requirements:
        problems.append("缺少必要要求，不能确认输入覆盖")
    inputs = {}
    for row in _rows(plan, "inputs", problems):
        key = row.get("id")
        if not _text(key) or key in inputs:
            problems.append("input id 缺失或重复")
            continue
        inputs[key] = evidence.read(row.get("ref"), f"input {key}", structured=True)
        if row.get("channel") not in ("request", "reference", "audio", "post_task"):
            problems.append(f"input {key}: 未知 channel")
    seen = set()
    for req in requirements:
        key = req.get("id")
        if not _text(key) or key in seen:
            problems.append("requirement id 缺失或重复")
            continue
        seen.add(key)
        before = len(problems)
        if req.get("priority") not in ("must", "preference"):
            problems.append(f"{key}: priority 必须为 must 或 preference")
        for field in ("criterion", "tolerance"):
            if not _text(req.get(field)):
                problems.append(f"{key}: 缺少 {field}")
        source_value = evidence.read(req.get("source"), f"{key} 规格来源")
        bindings = _rows(req, "bindings", problems)
        if not bindings:
            if req.get("priority") == "preference":
                warnings.append(f"{key}: 偏好项未覆盖")
            else:
                problems.append(f"{key}: 必要要求未进入输入")
        linked = 0
        for binding in bindings:
            try:
                if not _text(binding.get("input_id")):
                    raise ValueError("input_id 必须为字符串")
                value = inputs.get(binding.get("input_id"))
                if value is None:
                    raise ValueError("输入缺失或摘要无效")
                if "pointer" not in binding:
                    raise ValueError("缺少实际输入字段 pointer")
                value = _pointer(value, binding["pointer"])
                if value is None or value == "" or value == [] or value == {}:
                    raise ValueError("实际输入字段为空")
                if "expected" in binding and value != binding["expected"]:
                    raise ValueError("实际输入与固定期望不符（检查变体／参数）")
                if binding.get("equals_source") is True and value != source_value:
                    raise ValueError("实际输入与固定规格字段不一致")
                linked += 1
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                problems.append(f"{key} coverage: {exc}")
        report["coverage"].append({"requirement_id": key, "linked_inputs": linked,
            "status": "linked" if linked and before == len(problems) else "unresolved",
            "semantic_result": "requires_review"})

    # A quoted evaluation is a traceable reference, never a new trial authority.
    for risk in _rows(plan, "risks", problems):
        label = risk.get("id", "risk")
        if not all(_text(risk.get(field)) for field in ("id", "hypothesis", "stop_condition")):
            problems.append(f"{label}: 需要假设与停止条件")
        if not risk.get("evaluation_ref"):
            unknowns.append(f"{label}: 缺少代表性实片评测，不能据此扩大生产")
            continue
        evaluation = evidence.read(risk["evaluation_ref"], f"{label} evaluation", structured=True)
        if not isinstance(evaluation, dict) or evaluation.get("format") != "vsc.capability-evaluation/v2":
            problems.append(f"{label}: 需引用既有 capability-evaluation/v2")
        elif evaluation.get("result") != "pass":
            unknowns.append(f"{label}: 评测尚未通过")
        else:
            unknowns.append(f"{label}: 已引用 pass；须由既有 trial 校验器核对输入、方法、批准与适用性")

    limit = plan.get("repeated_failure_limit", 2)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        problems.append("repeated_failure_limit 必须为正整数")
        limit = 2
    groups, measures, media = {}, defaultdict(lambda: defaultdict(list)), {}
    attempt_ids = set()
    for attempt in _rows(plan, "attempts", problems):
        aid = attempt.get("id")
        if not _text(aid) or aid in attempt_ids:
            problems.append("attempt id 缺失或重复（不得重复记账）")
            continue
        attempt_ids.add(aid)
        if attempt.get("project_id", plan.get("project_id")) != plan.get("project_id"):
            problems.append(f"{aid}: 跨项目记录")
            continue
        for field in ("logical_shot_id", "purpose", "task_id", "version", "method"):
            if not _text(attempt.get(field)):
                problems.append(f"{aid}: 缺少 {field}")
        category = attempt.get("category")
        if category not in ("production", "planned_experiment", "requirement_change", "recovery"):
            problems.append(f"{aid}: category 不明，不能归因返工")
            category = "unknown"
        result = attempt.get("result")
        if result not in ("usable", "failed", "unknown"):
            problems.append(f"{aid}: result 必须为 usable / failed / unknown")
        if result == "unknown":
            unknowns.append(f"{aid}: 可用性未知")
        if result in ("usable", "failed"):
            evidence.read(attempt.get("assessment_ref"), f"{aid} assessment")
        key = tuple(str(attempt.get(f, "")) for f in ("logical_shot_id", "purpose", "method"))
        group = groups.setdefault(key, {"logical_shot_id": key[0], "purpose": key[1], "method": key[2],
            "attempt_ids": [], "failure_counts": defaultdict(int), "unknown_count": 0})
        group["attempt_ids"].append(aid)
        group["unknown_count"] += int(result == "unknown")
        defects = _rows(attempt, "defects", problems)
        codes = set()
        for defect in defects:
            if not _text(defect.get("code")) or not _text(defect.get("observation")):
                problems.append(f"{aid}: 缺陷需 code 和可观察描述")
                continue
            codes.add(defect["code"])
            cause = defect.get("cause")
            if cause:
                if not isinstance(cause, dict) or cause.get("status") not in ("hypothesis", "confirmed", "ruled_out"):
                    problems.append(f"{aid}: 原因必须区分假设／证实／排除")
                elif cause["status"] in ("confirmed", "ruled_out"):
                    evidence.read(cause.get("evidence_ref"), f"{aid} 原因证据")
                    warnings.append(f"{aid}: 原因标记是记录者主张；本工具不验证因果")
        if result == "failed" and category != "recovery":
            if not codes:
                unknowns.append(f"{aid}: 失败未分类，不能统计同类缺陷")
            for code in codes:
                group["failure_counts"][code] += 1
        for field in ("active_seconds", "wait_seconds"):
            value = attempt.get(field)
            if value is not None and not _number(value):
                problems.append(f"{aid}: {field} 无效")
                value = None
            if value is None:
                unknowns.append(f"{aid}: {field} 未知")
            measures[category][field].append(value)
        costs = _rows(attempt, "costs", problems)
        if not costs:
            unknowns.append(f"{aid}: 实际用量／费用未知")
        elif not any(cost.get("basis") == "actual" for cost in costs):
            unknowns.append(f"{aid}: 只有估算，实际用量／费用未知")
        cost_units = set()
        for cost in costs:
            unit, value = cost.get("unit"), cost.get("amount")
            basis = cost.get("basis")
            if basis not in ("actual", "estimate"):
                problems.append(f"{aid}: cost basis 需 actual / estimate")
                continue
            if not _text(unit) or (basis, unit) in cost_units or (value is not None and not _number(value)):
                problems.append(f"{aid}: cost 单位缺失／重复或数值无效")
                continue
            cost_units.add((basis, unit))
            if value is None:
                unknowns.append(f"{aid}: {basis} {unit} 未知")
            measures[category][f"{cost['basis']}:{unit}"].append(value)
        if attempt.get("media_ref"):
            media_value = evidence.read(attempt["media_ref"], f"{aid} media")
            digest = attempt["media_ref"]["sha256"] if media_value is not None else None
            duration, intervals = attempt.get("generated_seconds"), attempt.get("usable_intervals")
            if not _number(duration) or duration == 0:
                problems.append(f"{aid}: 需正数 generated_seconds")
            elif digest is not None:
                prior = media.setdefault(digest, {"duration": duration, "intervals": [], "unknown": False})
                if prior["duration"] != duration:
                    problems.append(f"{aid}: 同一媒体时长冲突")
                if intervals is None:
                    prior["unknown"] = True
                    unknowns.append(f"{aid}: 可用区间未知")
                else:
                    try:
                        _union(intervals, duration)
                        evidence.read(attempt.get("assessment_ref"), f"{aid} 区间审查")
                        prior["intervals"].extend(intervals)
                    except ValueError as exc:
                        problems.append(f"{aid}: {exc}")

    for group in groups.values():
        group["failure_counts"] = dict(group["failure_counts"])
        group["recommendation"] = "stop_and_compare_routes" if any(
            value >= limit for value in group["failure_counts"].values()) else "review_evidence"
        report["rework"].append(group)
    report["metrics"] = {category: {unit: {"known_total": sum(v for v in values if v is not None),
        "unknown_count": sum(v is None for v in values)} for unit, values in units.items()}
        for category, units in measures.items()}
    report["media_usage"] = {"unique_generated_seconds": sum(row["duration"] for row in media.values()),
        "known_usable_seconds": sum(_union(row["intervals"], row["duration"]) for row in media.values()),
        "unknown_media_count": sum(row["unknown"] for row in media.values()), "basis": "declared_intervals_union"}
    for reuse in _rows(plan, "review_reuse", problems):
        before = len(problems)
        fingerprints = []
        for side in ("prior", "current"):
            snapshot = reuse.get(side)
            if not isinstance(snapshot, dict):
                problems.append(f"review_reuse {side}: 缺少完整复用条件")
                fingerprints.append(None)
                continue
            parts = []
            for field in ("media", "criteria", "authorization"):
                ref = snapshot.get(field)
                value = evidence.read(ref, f"review_reuse {side}.{field}")
                parts.append((ref.get("sha256"), ref.get("pointer", ""), value) if isinstance(ref, dict) else None)
            if not _text(snapshot.get("purpose")):
                problems.append(f"review_reuse {side}: 缺少 purpose")
            deps = _rows(snapshot, "dependencies", problems)
            if not deps:
                problems.append(f"review_reuse {side}: 依赖不能省略")
            dependency_ids = set()
            dependencies = []
            for ref in deps:
                dependency_id = ref.get("id")
                if not _text(dependency_id) or dependency_id in dependency_ids:
                    problems.append(f"review_reuse {side}: 依赖 id 缺失或重复")
                    continue
                dependency_ids.add(dependency_id)
                value = evidence.read(ref, f"review_reuse {side}.dependency")
                dependencies.append((dependency_id, ref.get("sha256"), ref.get("pointer", ""), value))
            parts.extend(sorted(dependencies, key=lambda row: row[0]))
            parts.append(snapshot.get("purpose"))
            fingerprints.append(parts)
        reusable = before == len(problems) and fingerprints[0] == fingerprints[1]
        report["review_reuse"].append({"id": reuse.get("id"), "eligible_for_reuse": reusable,
            "requires_authority_check": True})
        if not reusable:
            warnings.append(f"{reuse.get('id', 'review')}: 复用条件不匹配，重新审查变化与影响项")
    stopped = any(row["recommendation"] == "stop_and_compare_routes" for row in report["rework"])
    report["status"] = "blocked" if problems or stopped else "review_required" if unknowns else "ready_for_review"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查规格输入覆盖、同类返工及审查复用；不授权生成")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("plan", type=Path)
    parser.add_argument("--root", type=Path, help="证据根目录，默认检查包所在目录")
    args = parser.parse_args(argv)
    try:
        report = check(json.loads(args.plan.read_text(encoding="utf-8")), args.root or args.plan.parent)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "problems": [str(exc)]}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 2 if report["status"] == "blocked" else 1 if report["status"] == "review_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
