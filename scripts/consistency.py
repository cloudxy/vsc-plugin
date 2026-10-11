#!/usr/bin/env python3
"""VSC 一致性：身份层（vsc.asset-bible/v1）与场景状态时间线（vsc.scene-state/v1）。

  bible validate FILE [--project DIR]          校验资产库；给出项目目录时核对参考素材与声音文件的 SHA-256
  state validate FILE [--bible FILE]           校验状态时间线；给出资产库时核对实体、变体与地点
  state at FILE SHOT [--bible FILE]            输出某镜头入点与出点的推导状态（JSON）
  check --bible FILE --state FILE [--continuity PLAN] [--project DIR]
                                               交叉检查；给出连续性计划时核对其出入点状态与时间线一致

资产库为人物、道具、物体、地点等实体登记不可变特征、命名变体、参考素材、生成锚点，以及人物音色与物体声音，
并给出全片统一的字幕样式。状态时间线为每场戏写基线状态，每个镜头只写该镜内发生的变化：任一镜头的入点状态
是基线加上之前各镜变化的累积，出点状态再加上本镜变化，因此同场不相邻的镜头天然一致。
"""
import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

BIBLE_FORMAT = "vsc.asset-bible/v1"
STATE_FORMAT = "vsc.scene-state/v1"
KINDS = ("character", "prop", "object", "location", "creature", "vehicle")
HOLDABLE = ("prop", "object")
RIGHTS = ("owned", "licensed", "temp_only", "unknown")
POSITIONS = ("bottom", "top", "center", "custom")
ENVIRONMENT_KEYS = ("time", "weather", "lighting")
# 实体、变体、场景与镜头 ID：Unicode 字母数字开头，可含点、下划线、连字符，便于与中文连续性计划对齐。
SAFE_ID = re.compile(r"[^\W_][\w.-]*\Z")
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value, minimum=0.0, inclusive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value >= minimum if inclusive else value > minimum


def load(path, expected):
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取 {path}：{exc}") from exc
    if not isinstance(data, dict) or data.get("format") != expected:
        raise ValueError(f"{path} 的 format 必须是 {expected}")
    return data


# ---------- 身份层 ----------

def _media_errors(item, label, errors):
    if not isinstance(item, dict):
        errors.append(f"{label} 必须是对象")
        return
    path = item.get("path")
    if not text(path) or Path(path).is_absolute() or ".." in Path(path).parts:
        errors.append(f"{label}.path 必须是项目内的相对路径")
    if not isinstance(item.get("sha256"), str) or not SHA256.fullmatch(item["sha256"]):
        errors.append(f"{label}.sha256 必须是 64 位小写十六进制，绑定具体文件版本")


def bible_errors(data):
    errors = []
    if not text(data.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    entities = data.get("entities")
    if not isinstance(entities, list) or not entities:
        return errors + ["entities 必须是非空数组"]
    seen = set()
    for index, entity in enumerate(entities):
        label = f"entities[{index}]"
        if not isinstance(entity, dict):
            errors.append(f"{label} 必须是对象")
            continue
        entity_id, kind = entity.get("id"), entity.get("kind")
        if not isinstance(entity_id, str) or not SAFE_ID.fullmatch(entity_id) or entity_id in seen:
            errors.append(f"{label}.id 必须唯一，且以字母或数字开头，只含字母、数字、点、下划线和连字符")
        seen.add(entity_id)
        label = f"{entity_id or label}"
        if kind not in KINDS:
            errors.append(f"{label}.kind 必须是 {'/'.join(KINDS)}")
        if not text(entity.get("name")):
            errors.append(f"{label}.name 必须是非空字符串")
        identity = entity.get("identity", [])
        if not isinstance(identity, list) or not all(text(item) for item in identity):
            errors.append(f"{label}.identity 必须是非空字符串数组")
        elif kind in ("character", "location") and not identity:
            errors.append(f"{label}.identity 不能为空：人物和地点必须写不可变特征")
        variants = entity.get("variants")
        if not isinstance(variants, dict) or "default" not in variants:
            errors.append(f"{label}.variants 必须是对象并包含 default")
        elif not all(SAFE_ID.fullmatch(name) and text(value) for name, value in variants.items()):
            errors.append(f"{label}.variants 的名称须为安全 ID，说明须为非空字符串")
        for ref_index, ref in enumerate(entity.get("references", [])):
            _media_errors(ref, f"{label}.references[{ref_index}]", errors)
        if "generation" in entity and not isinstance(entity["generation"], dict):
            errors.append(f"{label}.generation 必须是对象")
        voice = entity.get("voice")
        if voice is not None:
            if kind not in ("character", "creature"):
                errors.append(f"{label}.voice 只用于人物或生物")
            elif not isinstance(voice, dict) or not text(voice.get("engine")) or not text(voice.get("voice")):
                errors.append(f"{label}.voice 必须写 engine 与 voice")
            else:
                if "rate" in voice and not number(voice["rate"], 0, inclusive=False):
                    errors.append(f"{label}.voice.rate 必须是正数")
                if voice.get("rights") not in RIGHTS:
                    errors.append(f"{label}.voice.rights 必须是 {'/'.join(RIGHTS)}")
        sound = entity.get("sound")
        if sound is not None:
            _media_errors(sound, f"{label}.sound", errors)
            if isinstance(sound, dict) and sound.get("rights") not in RIGHTS:
                errors.append(f"{label}.sound.rights 必须是 {'/'.join(RIGHTS)}")
    style = data.get("subtitle_style")
    if style is not None:
        errors.extend(style_errors(style))
    return errors


def style_errors(style):
    if not isinstance(style, dict):
        return ["subtitle_style 必须是对象"]
    errors = []
    if "font" in style and not text(style["font"]):
        errors.append("subtitle_style.font 必须是字体文件路径")
    if "font_size" in style and not (isinstance(style["font_size"], int) and number(style["font_size"], 1)):
        errors.append("subtitle_style.font_size 必须是正整数")
    for key in ("color", "stroke_color"):
        if key in style and not (isinstance(style[key], str) and HEX_COLOR.fullmatch(style[key])):
            errors.append(f"subtitle_style.{key} 必须是 #RRGGBB")
    if style.get("background") is not None and not (isinstance(style["background"], str) and HEX_COLOR.fullmatch(style["background"])):
        errors.append("subtitle_style.background 必须是 #RRGGBB 或 null")
    if "stroke_width" in style and not number(style["stroke_width"]):
        errors.append("subtitle_style.stroke_width 必须是非负数")
    if "position" in style and style["position"] not in POSITIONS:
        errors.append(f"subtitle_style.position 必须是 {'/'.join(POSITIONS)}")
    if "custom_position" in style and not (number(style["custom_position"]) and style["custom_position"] <= 100):
        errors.append("subtitle_style.custom_position 必须在 0–100")
    if "rounded" in style and not isinstance(style["rounded"], bool):
        errors.append("subtitle_style.rounded 必须是布尔值")
    return errors


def entity_index(bible):
    return {entity["id"]: entity for entity in bible.get("entities", []) if isinstance(entity, dict) and "id" in entity}


def media_problems(bible, project):
    """核对资产库引用的文件存在且 SHA-256 一致。"""
    problems = []
    for entity in bible.get("entities", []):
        items = [(f"{entity['id']}.references[{i}]", ref) for i, ref in enumerate(entity.get("references", []))]
        if entity.get("sound"):
            items.append((f"{entity['id']}.sound", entity["sound"]))
        for label, item in items:
            path = Path(project) / item["path"]
            if not path.is_file():
                problems.append(f"{label} 文件不存在：{item['path']}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                problems.append(f"{label} 文件内容与登记的 SHA-256 不一致：{item['path']}")
    return problems


# ---------- 状态时间线 ----------

def _entity_state_errors(entity_id, value, label, errors, partial):
    if not isinstance(entity_id, str) or not SAFE_ID.fullmatch(entity_id):
        errors.append(f"{label} 的实体 ID 无效：{entity_id}")
    if not isinstance(value, dict):
        errors.append(f"{label}.{entity_id} 必须是对象")
        return
    if partial and value.get("exit") is True:
        if set(value) != {"exit"}:
            errors.append(f"{label}.{entity_id} 离场时只能写 exit")
        return
    for key in ("variant", "position"):
        if key in value and not text(value[key]):
            errors.append(f"{label}.{entity_id}.{key} 必须是非空字符串")
    if "holding" in value and not (isinstance(value["holding"], list) and all(isinstance(x, str) for x in value["holding"])):
        errors.append(f"{label}.{entity_id}.holding 必须是实体 ID 数组")
    unknown = set(value) - {"variant", "position", "holding", "note", "exit"}
    if unknown:
        errors.append(f"{label}.{entity_id} 含未知字段：{'/'.join(sorted(unknown))}")


def _apply(state, changes):
    for key in ENVIRONMENT_KEYS:
        if key in changes.get("environment", {}):
            state["environment"][key] = changes["environment"][key]
    for entity_id, change in changes.get("entities", {}).items():
        if change.get("exit") is True:
            state["entities"].pop(entity_id, None)
            continue
        current = state["entities"].setdefault(entity_id, {"variant": "default"})
        current.update({key: value for key, value in change.items() if key != "exit"})


def _consistency_errors(snapshot, where, bible, errors):
    """同一时刻：手持物必须在场、不能被两人同时拿着；资产库给出时核对实体与变体。"""
    entities = snapshot["entities"]
    holders = {}
    for entity_id, value in entities.items():
        for held in value.get("holding", []):
            if held not in entities:
                errors.append(f"{where}：{entity_id} 手持的 {held} 不在场")
            if held in holders:
                errors.append(f"{where}：{held} 同时被 {holders[held]} 与 {entity_id} 拿着")
            holders[held] = entity_id
    if bible is None:
        return
    index = entity_index(bible)
    for entity_id, value in entities.items():
        entity = index.get(entity_id)
        if entity is None:
            errors.append(f"{where}：{entity_id} 不在资产库中")
            continue
        if value.get("variant", "default") not in entity.get("variants", {}):
            errors.append(f"{where}：{entity_id} 没有变体 {value.get('variant')}")
        for held in value.get("holding", []):
            if held in index and index[held]["kind"] not in HOLDABLE:
                errors.append(f"{where}：{entity_id} 手持的 {held} 不是道具或物体")


def state_errors(data, bible=None):
    errors = []
    if not text(data.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    if bible is not None and data.get("project_id") != bible.get("project_id"):
        errors.append("状态时间线与资产库的 project_id 不一致")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return errors + ["scenes 必须是非空数组"]
    index = entity_index(bible) if bible is not None else {}
    scene_ids, shot_ids, reference = set(), set(), []
    for scene_index, scene in enumerate(scenes):
        label = f"scenes[{scene_index}]"
        if not isinstance(scene, dict):
            errors.append(f"{label} 必须是对象")
            continue
        scene_id = scene.get("id")
        if not isinstance(scene_id, str) or not SAFE_ID.fullmatch(scene_id) or scene_id in scene_ids:
            errors.append(f"{label}.id 必须唯一，且为安全 ID")
        scene_ids.add(scene_id)
        label = scene_id or label
        location = scene.get("location_id")
        if not text(location):
            errors.append(f"{label}.location_id 必须是非空字符串")
        elif bible is not None and index.get(location, {}).get("kind") != "location":
            reference.append(f"{label}.location_id {location} 不是资产库中的地点")
        baseline = scene.get("baseline")
        if not isinstance(baseline, dict) or not isinstance(baseline.get("entities"), dict):
            errors.append(f"{label}.baseline 必须含 entities 对象")
            continue
        for entity_id, value in baseline["entities"].items():
            _entity_state_errors(entity_id, value, f"{label}.baseline.entities", errors, partial=False)
        shots = scene.get("shots")
        if not isinstance(shots, list) or not shots:
            errors.append(f"{label}.shots 必须是非空数组")
            continue
        for shot_index, shot in enumerate(shots):
            shot_label = f"{label}.shots[{shot_index}]"
            if not isinstance(shot, dict):
                errors.append(f"{shot_label} 必须是对象")
                continue
            shot_id = shot.get("id")
            if not isinstance(shot_id, str) or not SAFE_ID.fullmatch(shot_id) or shot_id in shot_ids:
                errors.append(f"{shot_label}.id 必须在全片唯一，且为安全 ID")
            shot_ids.add(shot_id)
            changes = shot.get("changes", {})
            if not isinstance(changes, dict) or set(changes) - {"environment", "entities"}:
                errors.append(f"{shot_id or shot_label}.changes 只能含 environment 与 entities")
                continue
            for entity_id, value in changes.get("entities", {}).items():
                _entity_state_errors(entity_id, value, f"{shot_id}.changes.entities", errors, partial=True)
    if errors:
        return errors  # 结构不完整时无法推导状态
    for shot_id, item in derive(data).items():
        for moment in ("entry", "exit"):
            _consistency_errors(item[moment], f"{shot_id} {'入点' if moment == 'entry' else '出点'}", bible, reference)
    return reference


def derive(data):
    """返回 {镜头 ID: {scene, location_id, entry, exit}}；entry/exit 含 environment 与 entities。"""
    result = {}
    for scene in data["scenes"]:
        state = {"environment": {key: scene["baseline"].get(key) for key in ENVIRONMENT_KEYS if key in scene["baseline"]},
                 "entities": copy.deepcopy(scene["baseline"]["entities"])}
        for value in state["entities"].values():
            value.setdefault("variant", "default")
        for shot in scene["shots"]:
            entry = copy.deepcopy(state)
            _apply(state, shot.get("changes", {}))
            result[shot["id"]] = {"scene": scene["id"], "location_id": scene["location_id"], "entry": entry, "exit": copy.deepcopy(state)}
    return result


# ---------- 交叉检查：连续性计划 ----------

def continuity_problems(plan, derived, bible):
    """连续性计划的出入点必须与状态时间线推导的状态一致；人物键应使用资产库 ID。"""
    problems, warnings = [], []
    index = entity_index(bible)
    for shot in plan.get("shots", []):
        shot_id = shot.get("id")
        if shot_id not in derived:
            warnings.append(f"{shot_id}：状态时间线中没有该镜头")
            continue
        for moment, key in (("entry", "entry_state"), ("exit", "exit_state")):
            expected, actual = derived[shot_id][moment], shot.get(key, {})
            where = f"{shot_id} {key}"
            if actual.get("location_id") != derived[shot_id]["location_id"]:
                problems.append(f"{where}.location_id={actual.get('location_id')}，时间线为 {derived[shot_id]['location_id']}")
            for name, character in actual.get("characters", {}).items():
                if name not in index:
                    warnings.append(f"{where}.characters 的键「{name}」不是资产库 ID，无法核对")
                    continue
                state = expected["entities"].get(name)
                if state is None:
                    problems.append(f"{where}：{name} 在时间线中此刻不在场")
                    continue
                costume = character.get("costume_id")
                if costume and costume != state.get("variant", "default"):
                    problems.append(f"{where}：{name} 的 costume_id={costume}，时间线变体为 {state.get('variant')}")
                prop = character.get("prop")
                if prop in index and prop not in state.get("holding", []):
                    problems.append(f"{where}：{name} 拿着 {prop}，时间线此刻没有")
    return problems, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    bible = commands.add_parser("bible").add_subparsers(dest="action", required=True)
    command = bible.add_parser("validate")
    command.add_argument("file")
    command.add_argument("--project")
    state = commands.add_parser("state").add_subparsers(dest="action", required=True)
    command = state.add_parser("validate")
    command.add_argument("file")
    command.add_argument("--bible")
    command = state.add_parser("at")
    command.add_argument("file")
    command.add_argument("shot")
    command.add_argument("--bible")
    command = commands.add_parser("check")
    command.add_argument("--bible", required=True)
    command.add_argument("--state", required=True)
    command.add_argument("--continuity")
    command.add_argument("--project")
    args = parser.parse_args()
    try:
        if args.command == "bible":
            data = load(args.file, BIBLE_FORMAT)
            problems = bible_errors(data)
            if not problems and args.project:
                problems = media_problems(data, args.project)
            label = f"{len(data.get('entities', []))} 个实体"
        elif args.command == "state":
            data = load(args.file, STATE_FORMAT)
            bible_data = load(args.bible, BIBLE_FORMAT) if args.bible else None
            problems = state_errors(data, bible_data)
            if args.action == "at" and not problems:
                derived = derive(data)
                if args.shot not in derived:
                    raise ValueError(f"没有镜头 {args.shot}")
                print(json.dumps(derived[args.shot], ensure_ascii=False, indent=2))
                return
            label = f"{len(data.get('scenes', []))} 场"
        else:
            bible_data = load(args.bible, BIBLE_FORMAT)
            data = load(args.state, STATE_FORMAT)
            problems = bible_errors(bible_data) or state_errors(data, bible_data)
            if not problems and args.project:
                problems = media_problems(bible_data, args.project)
            warnings = []
            if not problems and args.continuity:
                plan = json.loads(Path(args.continuity).read_text("utf-8"))
                problems, warnings = continuity_problems(plan, derive(data), bible_data)
            for warning in warnings:
                print(f"WARN {warning}")
            label = "资产库与状态时间线"
    except ValueError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print(f"VALID: {label}")


if __name__ == "__main__":
    main()
