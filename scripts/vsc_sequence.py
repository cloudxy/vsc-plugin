#!/usr/bin/env python3
"""只读校验集／场衔接；不生成叙事决定、不批准创作内容。

  validate FILE             只校验 vsc.sequence-links/v1 结构，不读取引用文件
  check FILE --project DIR  核对项目、状态文件 SHA、首尾镜头与跨单元状态变化

units 数组给出顺序。scene 单元覆盖状态文件中的完整一场；episode 单元覆盖
所绑定状态文件的全部镜头（该文件须由作者划定为一集）。边界状态只从
consistency.derive 推导，不另存副本。字段用点路径；数组按一个叶字段比较。
叙事承接、音频桥与变化理由须由创作者填写；通过检查不等于人工批准。
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import consistency as C


FORMAT = "vsc.sequence-links/v1"
KINDS = ("episode", "scene")
MODES = ("continuous", "ellipsis", "location_change")
_MISSING = object()
_AMBIGUOUS = object()


def _safe_id(value):
    return isinstance(value, str) and C.SAFE_ID.fullmatch(value) is not None


def _relative_path(value):
    return (C.text(value) and "\\" not in value and "\0" not in value
            and not Path(value).is_absolute() and ".." not in Path(value).parts
            and Path(value) != Path("."))


def _field(value):
    return (C.text(value) and value == value.strip() and "\0" not in value
            and all(value.split(".")) and value.split(".")[0] in ("location_id", "environment", "entities"))


def _object(value, label, allowed, errors):
    if not isinstance(value, dict):
        errors.append(f"{label} 必须是对象")
        return False
    unknown = set(value) - allowed
    if unknown:
        errors.append(f"{label} 含未知字段：{'/'.join(sorted(unknown))}")
    return True


def sequence_errors(data):
    """仅结构与显式顺序，不访问项目文件，也不判断创意质量。"""
    errors = []
    if not _object(data, "root", {"format", "project_id", "units", "links"}, errors):
        return errors
    if data.get("format") != FORMAT:
        errors.append(f"format 必须是 {FORMAT}")
    if not C.text(data.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    units = data.get("units")
    if not isinstance(units, list) or not units:
        return errors + ["units 必须是非空有序数组"]
    ids, seen = [], set()
    for index, unit in enumerate(units):
        label = f"units[{index}]"
        if not _object(unit, label, {"id", "kind", "state_path", "state_sha256", "entry_shot", "exit_shot"}, errors):
            continue
        unit_id = unit.get("id")
        if not _safe_id(unit_id) or unit_id in seen:
            errors.append(f"{label}.id 必须唯一，且为安全 ID")
        else:
            seen.add(unit_id)
            ids.append(unit_id)
        if unit.get("kind") not in KINDS:
            errors.append(f"{label}.kind 必须是 {'/'.join(KINDS)}")
        if not _relative_path(unit.get("state_path")):
            errors.append(f"{label}.state_path 必须是项目内相对文件路径")
        sha = unit.get("state_sha256")
        if not isinstance(sha, str) or not C.SHA256.fullmatch(sha):
            errors.append(f"{label}.state_sha256 必须是 64 位小写十六进制")
        for key in ("entry_shot", "exit_shot"):
            if not _safe_id(unit.get(key)):
                errors.append(f"{label}.{key} 必须是安全镜头 ID")
    links = data.get("links")
    if not isinstance(links, list):
        return errors + ["links 必须是数组"]
    actual = []
    for index, link in enumerate(links):
        label = f"links[{index}]"
        if not _object(link, label, {"from", "to", "mode", "purpose", "narrative", "audio", "match_fields", "changes"}, errors):
            continue
        source, target = link.get("from"), link.get("to")
        if not _safe_id(source) or not _safe_id(target):
            errors.append(f"{label}.from/to 必须是单元 ID")
        else:
            actual.append((source, target))
        if link.get("mode") not in MODES:
            errors.append(f"{label}.mode 必须是 {'/'.join(MODES)}")
        if not C.text(link.get("purpose")):
            errors.append(f"{label}.purpose 必须由创作者填写衔接目的")
        for key, fields in (("narrative", ("carry", "receive")), ("audio", ("strategy", "description"))):
            value = link.get(key)
            if _object(value, f"{label}.{key}", set(fields), errors):
                for field in fields:
                    if not C.text(value.get(field)):
                        errors.append(f"{label}.{key}.{field} 必须由创作者填写非空文字")
        fields = link.get("match_fields")
        if not isinstance(fields, list) or not all(_field(field) for field in fields):
            errors.append(f"{label}.match_fields 必须是 location_id/environment/entities 下的点路径数组")
        elif len(set(fields)) != len(fields):
            errors.append(f"{label}.match_fields 不能重复")
        changes = link.get("changes")
        if not isinstance(changes, list):
            errors.append(f"{label}.changes 必须是数组")
            continue
        changed = set()
        for change_index, change in enumerate(changes):
            change_label = f"{label}.changes[{change_index}]"
            if not _object(change, change_label, {"field", "reason"}, errors):
                continue
            field = change.get("field")
            if not _field(field):
                errors.append(f"{change_label}.field 必须是边界状态点路径")
            elif field in changed:
                errors.append(f"{change_label}.field 不能重复")
            else:
                changed.add(field)
            if not C.text(change.get("reason")):
                errors.append(f"{change_label}.reason 必须由创作者填写变化理由")
    if len(ids) == len(units):
        expected = list(zip(ids, ids[1:]))
        if len(actual) != len(expected) or set(actual) != set(expected):
            errors.append("links 必须为 units 中每对相邻单元恰好登记一次，不得跳接、反接或重复")
    return errors


def _at(snapshot, field):
    """点路径也容纳包含点的实体 ID；无法唯一解析时拒绝猜测。"""
    def find(value, remaining):
        if not remaining:
            return [value]
        if not isinstance(value, dict):
            return []
        results = []
        for key, child in value.items():
            if remaining == key:
                results.append(child)
            elif remaining.startswith(key + "."):
                results.extend(find(child, remaining[len(key) + 1:]))
        return results

    values = find(snapshot, field)
    return values[0] if len(values) == 1 else (_AMBIGUOUS if values else _MISSING)


def _same(left, right):
    if left is _MISSING or right is _MISSING:
        return left is right
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _differences(left, right, prefix=()):
    """递归比较叶字段；空对象中新添一项不产生虚假的父字段变化。"""
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            result.extend(_differences(left.get(key, _MISSING), right.get(key, _MISSING), prefix + (key,)))
        return result
    if isinstance(left, dict) and left and right is _MISSING:
        return [path for key, value in left.items() for path in _differences(value, _MISSING, prefix + (key,))]
    if isinstance(right, dict) and right and left is _MISSING:
        return [path for key, value in right.items() for path in _differences(_MISSING, value, prefix + (key,))]
    return [] if _same(left, right) else [prefix]


def _link_problems(link, left, right):
    label = f"{link['from']} → {link['to']}"
    problems = []
    for field in link["match_fields"]:
        before, after = _at(left, field), _at(right, field)
        if before is _MISSING or after is _MISSING:
            problems.append(f"{label}：match_fields {field} 在至少一个端点不存在（两端缺失也不能视为相等）")
        elif before is _AMBIGUOUS or after is _AMBIGUOUS:
            problems.append(f"{label}：match_fields {field} 点路径有歧义")
        elif not _same(before, after):
            problems.append(f"{label}：要求连续的 {field} 不一致")
    explained = []
    for change in link["changes"]:
        field = change["field"]
        before, after = _at(left, field), _at(right, field)
        if before is _AMBIGUOUS or after is _AMBIGUOUS:
            problems.append(f"{label}：changes {field} 点路径有歧义")
        elif before is _MISSING and after is _MISSING:
            problems.append(f"{label}：changes {field} 在两个端点都不存在")
        elif _same(before, after):
            problems.append(f"{label}：changes {field} 没有实际变化")
        elif isinstance(before, dict) and isinstance(after, dict):
            problems.append(f"{label}：changes {field} 须逐叶字段说明；新增／移除对象才可整体说明")
        else:
            explained.append(field)
    for path in sorted(_differences(left, right)):
        field = ".".join(path)
        if not any(field == reason or field.startswith(reason + ".") for reason in explained):
            problems.append(f"{label}：{field} 的变化未在 changes 中说明理由")
    moved = left["location_id"] != right["location_id"]
    if moved and link["mode"] == "continuous":
        problems.append(f"{label}：地点改变须使用 location_change 或 ellipsis")
    if not moved and link["mode"] == "location_change":
        problems.append(f"{label}：location_change 的两端地点相同")
    return problems


def sequence_problems(data, project):
    """核对真实项目与状态版本。所有文件只读，不写状态／台账／批准。"""
    problems = sequence_errors(data)
    if problems:
        return problems
    try:
        root = Path(project).resolve()
        project_path = (root / "vsc.json").resolve()
        project_path.relative_to(root)
        project_state = json.loads(project_path.read_text("utf-8"))
        if not isinstance(project_state, dict) or not C.text(project_state.get("project_id")):
            raise ValueError("vsc.json 缺少 project_id")
    except (OSError, RuntimeError, ValueError) as exc:
        return [f"无法读取项目 vsc.json：{exc}"]
    project_id = project_state["project_id"]
    if data["project_id"] != project_id:
        return ["衔接计划与项目 vsc.json 的 project_id 不一致"]
    states, endpoints, last_end = {}, {}, {}
    for unit in data["units"]:
        label = unit["id"]
        try:
            path = (root / unit["state_path"]).resolve()
            path.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            problems.append(f"{label}：state_path 解析后超出项目目录或路径无效")
            continue
        if path not in states:
            try:
                raw = path.read_bytes()
                state = json.loads(raw)
                if not isinstance(state, dict) or state.get("format") != C.STATE_FORMAT:
                    raise ValueError(f"format 必须是 {C.STATE_FORMAT}")
                if state.get("project_id") != project_id:
                    raise ValueError("状态文件与项目的 project_id 不一致")
                errors = C.state_errors(state)
                if errors:
                    raise ValueError("；".join(errors))
                states[path] = (hashlib.sha256(raw).hexdigest(), C.derive(state))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                states[path] = str(exc)
        bound = states[path]
        if isinstance(bound, str):
            problems.append(f"{label}：无法绑定状态文件 {unit['state_path']}：{bound}")
            continue
        sha, derived = bound
        if sha != unit["state_sha256"]:
            problems.append(f"{label}：状态文件 SHA-256 不一致，绑定版本已漂移")
            continue
        order = list(derived)
        entry, exit_ = unit["entry_shot"], unit["exit_shot"]
        if entry not in derived or exit_ not in derived:
            problems.append(f"{label}：entry_shot/exit_shot 不在所绑定状态文件中")
            continue
        first, last = order.index(entry), order.index(exit_)
        if first > last:
            problems.append(f"{label}：entry_shot 排在 exit_shot 之后")
            continue
        scope = order if unit["kind"] == "episode" else [shot for shot in order if derived[shot]["scene"] == derived[entry]["scene"]]
        if entry != scope[0] or exit_ != scope[-1]:
            problems.append(f"{label}：首尾镜头须覆盖完整{('集状态文件' if unit['kind'] == 'episode' else '同一场')}，不能截取中间镜头")
            continue
        if path in last_end and first <= last_end[path]:
            problems.append(f"{label}：同一状态文件的单元顺序重叠或倒置")
            continue
        last_end[path] = last
        endpoints[label] = {
            moment: {"location_id": derived[shot]["location_id"], **derived[shot][moment]}
            for moment, shot in (("entry", entry), ("exit", exit_))
        }
    for link in data["links"]:
        if link["from"] in endpoints and link["to"] in endpoints:
            problems.extend(_link_problems(link, endpoints[link["from"]]["exit"], endpoints[link["to"]]["entry"]))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="仅校验结构").add_argument("file")
    check = commands.add_parser("check", help="只读核对真实项目与状态版本")
    check.add_argument("file")
    check.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        data = C.load(args.file, FORMAT)
        errors = sequence_errors(data) if args.command == "validate" else sequence_problems(data, args.project)
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("通过集／场衔接结构校验" if args.command == "validate" else "通过集／场衔接只读核对（状态版本、边界与显式变化）")
    print("叙事承接、音频桥和变化理由仍须人工审阅；本检查不构成批准。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
