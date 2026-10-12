#!/usr/bin/env python3
"""Immutable source evidence and resolvable narrative provenance (no creative approval)."""
import json
from pathlib import Path

from vsc_artifacts import digest


def source_errors(project, source):
    path = Path(project) / source.get("path", "")
    if not source.get("snapshot"):
        return [f"来源 {source.get('id')} 尚无固定快照；重新 source add 后引用新版本"]
    if not path.is_file() or digest(path) != source.get("sha256"):
        return [f"来源 {source.get('id')} 快照缺失或 SHA 已变化"]
    return []


def locator_errors(path, locator):
    if not isinstance(locator, dict):
        return ["locator 必须是可解析的 lines / json_pointer / whole_file 定位对象"]
    kind = locator.get("kind")
    try:
        if kind == "lines":
            lines = Path(path).read_text("utf-8").splitlines()
            start, end = locator.get("start"), locator.get("end")
            if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)):
                return ["locator 行范围不存在"]
        elif kind == "json_pointer":
            value = json.loads(Path(path).read_text("utf-8"))
            pointer = locator.get("pointer")
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                return ["json_pointer 需要以 / 开头"]
            for part in pointer[1:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                value = value[int(part)] if isinstance(value, list) else value[part]
        elif kind == "whole_file":
            # Binary evidence can be identified precisely by its fixed bytes, without
            # pretending an unparsed page/time range has been inspected.
            if locator.get("sha256") != digest(path):
                return ["whole_file 必须绑定快照 SHA"]
        else:
            return ["不支持的 locator kind；不得以任意文字冒充可解析定位"]
    except (OSError, ValueError, KeyError, IndexError, TypeError, UnicodeError):
        return ["locator 无法在来源快照中解析"]
    return []


def provenance_errors(data, project, state, item):
    errors = []
    sources = {s['id']: s for s in state.get('sources', [])}
    decisions = {d['id']: d for d in state.get('decisions', [])}
    for unit in data.get('source_units', []):
        source = sources.get(unit.get('source_id'))
        if not source:
            errors.append(f"source_unit {unit.get('id')} 缺登记 source_id")
            continue
        errors.extend(source_errors(project, source))
        if unit.get('source_sha256') != source.get('sha256'):
            errors.append("source_unit 必须固定 source_sha256")
        if not source_errors(project, source):
            errors.extend(locator_errors(Path(project) / source['path'], unit.get('locator')))
        if unit.get('claim_kind') not in ('fact', 'character_claim', 'interpretation', 'adaptation'):
            errors.append("source_unit.claim_kind 必须区分事实、人物说法、解释和改编")
    for unit in data.get('screen_units', []):
        if unit.get('origin') == 'invention':
            decision = decisions.get(unit.get('decision_ref'), {})
            if unit.get('decision_ref') == 'self:invention':
                matches = [d for d in state.get('decisions', []) if d.get('target') == item.get('id') and d.get('kind') == 'invention']
                decision = matches[-1] if matches else {}
            if (decision.get('outcome') != 'accepted' or not decision.get('by') or not decision.get('reason')
                    or decision.get('target') != item.get('id') or decision.get('kind') != 'invention'):
                errors.append("新增 screen_unit 必须绑定针对该产物的真实 accepted invention 决策")
        elif unit.get('origin') not in ('source', 'adaptation') or not unit.get('source_refs'):
            errors.append("screen_unit 必须明确 origin 和来源；新增内容用 invention 决策")
    return errors
