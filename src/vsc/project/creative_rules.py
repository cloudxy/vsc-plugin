"""Opt-in creative constraints, shared by original contract and post consumers.

Profile defaults are overridden by a fixed approved brief for the same scope.
No declaration means no new duration, line-length or reading-speed gate.
"""
import copy
import math
import unicodedata

SAFE_AREA = {"top": .05, "bottom": .05, "left": .09, "right": .09}


def number(value, minimum=0, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > minimum if positive else value >= minimum)


def merge_rules(defaults=None, override=None):
    if (defaults is not None and not isinstance(defaults, dict)) or (override is not None and not isinstance(override, dict)):
        raise ValueError("creative_rules规则层必须为object")
    value = copy.deepcopy(defaults or {})
    for key, item in (override or {}).items():
        if isinstance(item, dict) and isinstance(value.get(key), dict):
            value[key] = merge_rules(value[key], item)
        else:
            value[key] = copy.deepcopy(item)
    return value


def rule_errors(value):
    if not isinstance(value, dict):
        return ["creative_rules 必须为object"]
    errors = []
    extra = set(value) - {"subtitle", "duration", "line_length", "require_risk_refs"}
    if extra:
        errors.append("未知creative_rules字段: " + ", ".join(sorted(extra)))
    subtitle = value.get("subtitle", {})
    if not isinstance(subtitle, dict):
        errors.append("creative_rules.subtitle 必须为object")
    else:
        if set(subtitle) - {"safe_area", "mixed_spacing", "max_cps", "min_cue_ms", "max_cue_ms"}:
            errors.append("creative_rules.subtitle 含未知规则")
        if "mixed_spacing" in subtitle and type(subtitle["mixed_spacing"]) is not bool:
            errors.append("subtitle.mixed_spacing 必须为boolean")
        area = subtitle.get("safe_area", {})
        if (not isinstance(area, dict) or set(area) - set(SAFE_AREA)
                or any(not number(v) or v >= 1 for v in area.values())):
            errors.append("subtitle.safe_area 必须为top/bottom/left/right的0..1有限遮挡比例")
        else:
            area = {**SAFE_AREA, **area}
            if area["top"] + area["bottom"] >= 1 or area["left"] + area["right"] >= 1:
                errors.append("subtitle.safe_area 不得遮满画幅")
        for key in ("max_cps", "min_cue_ms", "max_cue_ms"):
            if key in subtitle:
                item = subtitle[key]
                if (not isinstance(item, dict) or set(item) != {"value", "level"}
                        or not number(item.get("value"), positive=True) or item.get("level") not in {"warning", "error"}):
                    errors.append("subtitle." + key + " 需要正数value与明确warning/error级别")
        if all(isinstance(subtitle.get(key), dict) and number(subtitle[key].get("value")) for key in ("min_cue_ms", "max_cue_ms")):
            if subtitle["min_cue_ms"]["value"] > subtitle["max_cue_ms"]["value"]:
                errors.append("subtitle最短Cue不得大于最长Cue")
    duration = value.get("duration", {})
    if not isinstance(duration, dict):
        errors.append("creative_rules.duration 必须为object")
    else:
        if set(duration) - {"target_ms", "tolerance_ms", "level", "scope_targets"}:
            errors.append("creative_rules.duration 含未知规则")
        targets = duration.get("scope_targets", {})
        if not isinstance(targets, dict) or any(not isinstance(k, str) or not k or not isinstance(v, dict) for k, v in targets.items()):
            errors.append("duration.scope_targets 必须为按真实范围标识声明的object")
            targets = {}
        for label, item in [("duration", duration)] + [("duration.scope_targets." + k, v) for k, v in targets.items()]:
            if label != "duration" and set(item) - {"target_ms", "tolerance_ms", "level"}:
                errors.append(label + " 含未知规则")
            if "target_ms" in item and not number(item["target_ms"], positive=True):
                errors.append(label + ".target_ms 必须为有限正毫秒")
            if "tolerance_ms" in item and not number(item["tolerance_ms"]):
                errors.append(label + ".tolerance_ms 必须为有限非负毫秒")
            if "level" in item and item["level"] not in {"error", "warning"}:
                errors.append(label + ".level 必须为error/warning")
    line = value.get("line_length")
    if line is not None and (not isinstance(line, dict) or set(line) != {"max_characters", "level"}
            or type(line.get("max_characters")) is not int or line["max_characters"] < 1
            or line.get("level") not in {"warning", "error"}):
        errors.append("line_length 需要正整数max_characters与warning/error")
    if "require_risk_refs" in value and type(value["require_risk_refs"]) is not bool:
        errors.append("require_risk_refs 必须为boolean")
    return errors


def resolve_rules(profile=None, brief=None):
    value = merge_rules((profile or {}).get("creative_rules"), (brief or {}).get("creative_rules"))
    errors = rule_errors(value)
    if errors:
        raise ValueError("；".join(errors))
    return value


def subtitle_policy(rules=None):
    rules = rules or {}
    errors = rule_errors(rules)
    if errors:
        raise ValueError("；".join(errors))
    subtitle = rules.get("subtitle", {})
    return {**subtitle, "safe_area": {**SAFE_AREA, **subtitle.get("safe_area", {})},
            "safe_area_declared": "safe_area" in subtitle, "mixed_spacing": subtitle.get("mixed_spacing", False)}


def visible_characters(text, *, punctuation=True):
    """Visible units: NFC, no whitespace/control/combining extenders.

    Combining accents, variation selectors, emoji modifiers and a ZWJ sequence
    stay with their preceding visible unit. Latin letters/digits each count one;
    this is a declared engineering count, never estimated speaking duration.
    """
    count, joined, regional = 0, False, False
    for char in unicodedata.normalize("NFC", text):
        category = unicodedata.category(char)
        if char == "\u200d":
            joined = True
            continue
        if char.isspace() or category[0] in {"M", "C"} or 0xFE00 <= ord(char) <= 0xFE0F or 0x1F3FB <= ord(char) <= 0x1F3FF:
            continue
        if not punctuation and category[0] == "P":
            continue
        indicator = 0x1F1E6 <= ord(char) <= 0x1F1FF
        if not joined and not (indicator and regional):
            count += 1
        joined = False
        regional = indicator and not regional
    return count


def interval_union(intervals):
    total, cursor = 0, None
    for start, end in sorted(intervals):
        if cursor is None or start > cursor:
            total += end - start
        elif end > cursor:
            total += end - cursor
        cursor = max(cursor or end, end)
    return total


def document_diagnostics(data, rules, scope=None):
    """Each stage checks only its own facts; warnings stay distinguishable."""
    errors, warnings, metrics = [], [], {}
    errors.extend(rule_errors(rules))
    if errors:
        return {"errors": errors, "warnings": warnings, "metrics": metrics}
    fmt = data.get("format")
    measured = None
    if fmt == "vsc.screenplay/v1":
        values = [scene.get("estimated_duration_ms") for scene in data.get("scenes", []) if isinstance(scene, dict)]
        if values and all(number(v, positive=True) for v in values):
            measured = sum(values)
            metrics["duration_basis"] = "scene_budgets_parallel_dialogue_not_added"
        line_rule = rules.get("line_length")
        if line_rule:
            for scene in data.get("scenes", []):
                for line in scene.get("dialogue", []):
                    count = visible_characters(line.get("text", ""), punctuation=False)
                    if count > line_rule["max_characters"]:
                        (errors if line_rule["level"] == "error" else warnings).append(
                            "对白 " + str(line.get("id")) + " 字数%d超过%d（中文/英文/数字逐可见单位，空白标点不计）" % (count, line_rule["max_characters"]))
    elif fmt == "vsc.continuity-plan/v1":
        values = [shot.get("duration_ms") for shot in data.get("shots", []) if isinstance(shot, dict)]
        if values and all(number(v, positive=True) for v in values):
            measured = sum(values)
            metrics["duration_basis"] = "planned_shots_sum_not_final_edit_duration"
    elif fmt in {"vsc.timeline/v1", "vsc.remotion-render-plan/v1"}:
        plan = data.get("render_plan", data)
        from vsc.post.remotion_plan import frame_rate
        try:
            fps = frame_rate(plan["composition"]["fps"])
            intervals = [(s["from_frame"], s["from_frame"] + s["duration_in_frames"])
                for s in plan["segments"] if s.get("kind") in {"video", "image"} and not s.get("overlay")]
            coverage = interval_union(intervals) * 1000 / fps
            measured = plan["composition"]["duration_in_frames"] * 1000 / fps
            metrics.update(duration_basis="composition_range_with_visual_union", rendered_duration_ms=measured,
                visual_coverage_ms=coverage, uncovered_visual_ms=max(0, measured - coverage),
                overlapping_visual_ms=(sum(end - start for start, end in intervals) * 1000 / fps - coverage))
        except (KeyError, TypeError, ValueError):
            errors.append("时长门缺少有效timeline帧规格")
    duration = merge_rules(rules.get("duration"), rules.get("duration", {}).get("scope_targets", {}).get(scope or data.get("scope", data.get("sequence_id"))))
    if measured is not None:
        metrics["duration_ms"] = measured
        if "target_ms" in duration and abs(measured - duration["target_ms"]) > duration.get("tolerance_ms", 0) + 1e-6:
            # A shot budget is advisory: overlaps/handles/edit choices are not
            # yet a final timeline fact.
            target = warnings if fmt == "vsc.continuity-plan/v1" or duration.get("level", "error") == "warning" else errors
            target.append("当前范围时长%.3fms与目标%.3fms超出容差%.3fms" % (measured, duration["target_ms"], duration.get("tolerance_ms", 0)))
    return {"errors": errors, "warnings": warnings, "metrics": metrics}


def context_diagnostics(data, profile, records, dependency_ids, scope, objects):
    """Evaluate a fixed artifact using real same-project objects and approvals.

    records use id/type/sha256/status/scope/document. Callers own retrieval and
    verify the stored bytes; no caller-provided approved booleans are accepted.
    """
    errors, warnings, metrics = [], [], {}
    rows = list(objects.values()) if isinstance(objects, dict) else list(objects)
    by_id = {row["id"]: row for row in rows}
    aliases = {str(row.get("display_code", row["id"])): row["id"] for row in rows}
    aliases.update({identifier: identifier for identifier in by_id})
    def canonical(identifier):
        return aliases.get(identifier, identifier)
    def ancestry(identifier):
        result, cursor = ["project"], canonical(identifier)
        seen = set()
        while cursor != "project" and cursor in by_id and cursor not in seen:
            seen.add(cursor)
            result.append(cursor)
            cursor = by_id[cursor].get("parent", by_id[cursor].get("parent_id"))
        return result
    def under(identifier, parent):
        return parent == "project" or canonical(parent) in ancestry(identifier)
    def episode(identifier):
        return next((key for key in ancestry(identifier) if key in by_id and by_id[key]["kind"] == "episode"), None)
    scope = canonical(scope or data.get("scope", data.get("sequence_id", "project")))
    fmt = data.get("format")
    relevant = {"vsc.screenplay/v1", "vsc.continuity-plan/v1", "vsc.timeline/v1", "vsc.remotion-render-plan/v1"}
    if fmt == "vsc.quality-plan/v1":
        from vsc.production.quality_plan import validation_errors
        errors.extend(validation_errors(data))
        if errors:
            return {"errors": errors, "warnings": warnings, "metrics": metrics, "rules": {}}
        for risk in data.get("risks", []) if isinstance(data.get("risks", []), list) else []:
            if not isinstance(risk, dict):
                continue
            risk_scope = risk.get("scope", scope)
            if risk_scope != "project" and canonical(risk_scope) not in by_id or not under(risk_scope, scope):
                errors.append("quality-plan风险范围不存在或超出登记范围: " + str(risk.get("id")))
            for identifier in risk.get("shot_ids", []) if isinstance(risk.get("shot_ids", []), list) else []:
                target = by_id.get(canonical(identifier), {})
                if target.get("kind") != "shot" or not under(identifier, risk_scope):
                    errors.append("quality-plan风险镜头不存在或超出风险范围: " + str(identifier))
        return {"errors": errors, "warnings": warnings, "metrics": metrics, "rules": {}}
    if fmt == "vsc.creative-brief/v1":
        declared = data.get("creative_rules", {})
        errors.extend(rule_errors(declared))
        if errors:
            return {"errors": errors, "warnings": warnings, "metrics": metrics, "rules": {}}
        for identifier in declared.get("duration", {}).get("scope_targets", {}) if isinstance(declared, dict) else ():
            if canonical(identifier) not in by_id or not under(identifier, scope):
                errors.append("创作目标时长引用的范围不存在或超出当前范围: " + str(identifier))
        return {"errors": errors, "warnings": warnings, "metrics": metrics, "rules": {}}
    if fmt not in relevant:
        return {"errors": [], "warnings": [], "metrics": {}, "rules": {}}
    sources = [row for row in records if row.get("type") == "vsc.creative_brief" and row.get("status") == "approved"
        and not row.get("superseded_by") and row.get("document", {}).get("creative_rules")
        and under(scope, row.get("scope", "project"))]
    pinned = [row for row in sources if row["id"] in dependency_ids]
    if sources and not pinned:
        errors.append("已声明创作规则，当前产物必须明确依赖同范围的已批准creative_brief固定版本")
    chosen = None
    if pinned:
        depths = {row["id"]: len(ancestry(row.get("scope", "project"))) for row in pinned}
        deepest = max(depths.values())
        options = [row for row in pinned if depths[row["id"]] == deepest]
        if len(options) != 1:
            errors.append("当前范围存在多个创作规则来源，须固定一个明确版本")
        else:
            chosen = options[0]
    try:
        rules = resolve_rules(profile, chosen["document"] if chosen else None)
    except ValueError as exc:
        return {"errors": errors + [str(exc)], "warnings": [], "metrics": {}, "rules": {}}
    for identifier in rules.get("duration", {}).get("scope_targets", {}):
        if canonical(identifier) not in by_id:
            errors.append("时长目标引用了当前项目不存在的范围: " + str(identifier))
    plan = data.get("render_plan", data)
    declared = plan.get("creative_rules", data.get("creative_rules"))
    if declared is not None and declared != rules:
        errors.append("产物creative_rules与固定Profile/已批准委托不一致，不能自行改写或弱化")
    if fmt in {"vsc.timeline/v1", "vsc.remotion-render-plan/v1"} and rules.get("subtitle") and declared != rules:
        errors.append("时间线必须保存由固定Profile/已批准委托解析的creative_rules供实际字幕消费者读取")
    units = [(scope, data)]
    if fmt == "vsc.screenplay/v1" and scope == "project":
        groups = {}
        for scene in data.get("scenes", []):
            ep = episode(scene.get("id"))
            if ep:
                groups.setdefault(ep, []).append(scene)
        if groups:
            units = [(ep, dict(data, scenes=scenes)) for ep, scenes in groups.items()]
    for unit_scope, document in units:
        scoped_rules = copy.deepcopy(rules)
        targets = scoped_rules.get("duration", {}).get("scope_targets", {})
        if targets:
            scoped_rules["duration"]["scope_targets"] = {canonical(key): value for key, value in targets.items()}
        result = document_diagnostics(document, scoped_rules, unit_scope)
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])
        metrics[unit_scope] = result["metrics"]
    shots = data.get("shots", []) if fmt == "vsc.continuity-plan/v1" else []
    references = [(row, row.get("id")) for row in shots if isinstance(row, dict)]
    active_risks = rules.get("require_risk_refs") or any("risk_ids" in row or "risks" in row for row, _ in references)
    if active_risks:
        ref = data.get("quality_plan")
        quality = next((row for row in records if isinstance(ref, dict) and row["id"] == ref.get("id")
            and row.get("sha256") == ref.get("sha256") and row["id"] in dependency_ids
            and row.get("status") == "approved" and row.get("type") in {"vsc.quality_plan", "quality-plan"}), None)
        if quality is None:
            errors.append("镜头风险必须引用明确依赖的已批准quality-plan固定ID/SHA")
        else:
            quality_data = quality["document"]
            if quality_data.get("project_id") != data.get("project_id"):
                errors.append("quality-plan风险来源不属于当前项目")
            from vsc.production.quality_plan import validation_errors
            errors.extend(validation_errors(quality_data))
            risks = {row["id"]: row for row in quality_data.get("risks", []) if isinstance(row, dict) and isinstance(row.get("id"), str)}
            for row, identifier in references:
                if "risks" in row:
                    errors.append("风险正文只能保存在quality-plan，镜头仅使用risk_ids: " + str(identifier))
                ids = row.get("risk_ids", [])
                if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids) or rules.get("require_risk_refs") and not ids:
                    errors.append("镜头risk_ids缺失或格式无效: " + str(identifier))
                    continue
                for risk_id in ids:
                    risk = risks.get(risk_id)
                    if not risk:
                        errors.append("镜头引用不存在风险: " + risk_id)
                    elif not under(identifier, risk.get("scope", quality.get("scope", "project"))) or risk.get("shot_ids") and canonical(identifier) not in {canonical(x) for x in risk["shot_ids"]}:
                        errors.append("镜头引用了其他范围的风险: " + risk_id)
    return {"errors": errors, "warnings": warnings, "metrics": metrics, "rules": rules,
            "brief_source": {"id": chosen["id"], "sha256": chosen["sha256"]} if chosen else None}


def file_context_diagnostics(data, project, state, item):
    import hashlib
    import json
    from pathlib import Path
    from vsc.production.handoffs import local_file
    artifacts = {row["id"]: row for row in state.get("artifacts", [])}
    dependencies, visiting = set(), set()
    def visit(owner):
        if owner.get("id") in visiting:
            return
        visiting.add(owner.get("id"))
        for identifier in owner.get("depends_on", []):
            parent = artifacts.get(identifier, {})
            if parent and owner.get("dependency_versions", {}).get(identifier) == parent.get("sha256"):
                dependencies.add(identifier)
                visit(parent)
    visit(item)
    records = []
    for row in artifacts.values():
        if row.get("type") not in {"vsc.creative_brief", "vsc.quality_plan", "quality-plan"}:
            continue
        try:
            raw = local_file(Path(project), row["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
                continue
            document = json.loads(raw)
            if isinstance(document, dict):
                records.append(dict(row, document=document))
        except (OSError, ValueError, KeyError):
            continue
    return context_diagnostics(data, state.get("profile_snapshot", {}), records, dependencies,
        item.get("scope", "project"), state.get("objects", []))
