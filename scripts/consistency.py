#!/usr/bin/env python3
"""VSC 一致性：身份层（vsc.asset-bible/v1）、场景状态时间线（vsc.scene-state/v1）与生成记录（vsc.generation-record/v1）。

  bible validate FILE [--project DIR]          校验资产库；给出项目目录时核对参考素材与声音文件的 SHA-256
  state validate FILE [--bible FILE]           校验状态时间线；给出资产库时核对实体、变体与地点
  state at FILE SHOT [--bible FILE]            输出某镜头入点与出点的推导状态（JSON）
  anchors SHOT --bible FILE --state FILE [--text]
                                               输出该镜头的锚点包（JSON，含 sha256）；--text 输出可改写为提示词的文字
  record validate FILE                         校验一份生成记录的结构
  check --bible FILE --state FILE [--continuity PLAN] [--record FILE ...] [--project DIR]
                                               交叉检查；连续性计划须与时间线一致，生成记录须绑定当前锚点

资产库为人物、道具、物体、地点等实体登记不可变特征、命名变体、参考素材、生成锚点，以及人物音色与物体声音，
并给出全片统一的字幕样式。状态时间线为每场戏写基线状态，每个镜头只写该镜内发生的变化：任一镜头的入点状态
是基线加上之前各镜变化的累积，出点状态再加上本镜变化，因此同场不相邻的镜头天然一致。

锚点包是某个镜头生成时必须遵守的全部身份与状态：在场实体的不可变特征、变体、位置、手持物、参考素材与生成锚点，
地点与环境，以及本镜内的变化。生成记录用 anchors_sha256 绑定所用锚点包；资产库或时间线之后改动了该镜头的锚点，
交叉检查会指出该 take 已过期。
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
RECORD_FORMAT = "vsc.generation-record/v1"
RECORD_KINDS = ("video", "image", "audio")
PURPOSES = ("candidate", "animatic_temp")
STATUSES = ("succeeded", "partial", "failed")
FRAME_SOURCES = ("reference", "previous_exit", "generated")
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


# ---------- 锚点包 ----------

def anchor_pack(bible, state, shot_id):
    """推导某镜头生成时必须遵守的身份与状态；只含与该镜头相关的内容，其他实体的改动不影响它。"""
    derived = derive(state)
    if shot_id not in derived:
        raise ValueError(f"状态时间线中没有镜头 {shot_id}")
    item, index = derived[shot_id], entity_index(bible)
    scene = next(scene for scene in state["scenes"] if scene["id"] == item["scene"])
    order = [shot["id"] for shot in scene["shots"]]
    position = order.index(shot_id)
    changes = scene["shots"][position].get("changes", {})

    def entity(entity_id):
        source = index.get(entity_id, {})
        result = {key: source[key] for key in ("kind", "name", "identity", "generation") if key in source}
        result["references"] = source.get("references", [])
        return result

    present = sorted(set(item["entry"]["entities"]) | set(item["exit"]["entities"]))
    entities = {}
    for entity_id in present:
        info = entity(entity_id)
        for moment in ("entry", "exit"):
            value = item[moment]["entities"].get(entity_id)
            if value is not None:
                variant = value.get("variant", "default")
                info[moment] = {**value, "variant_description": index.get(entity_id, {}).get("variants", {}).get(variant)}
        entities[entity_id] = info
    location = entity(item["location_id"])
    return {
        "shot": shot_id, "scene": item["scene"],
        "previous_shot": order[position - 1] if position else None,
        "next_shot": order[position + 1] if position + 1 < len(order) else None,
        "location": {"id": item["location_id"], **location},
        "environment": {"entry": item["entry"]["environment"], "exit": item["exit"]["environment"]},
        "entities": entities,
        "changes": changes,
    }


def pack_sha256(pack):
    return hashlib.sha256(json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def anchor_text(pack):
    """把锚点包写成可改写为供应商提示词的中文段落：逐镜写出入点状态与本镜变化，而不是全片共用一段描述。"""
    location = pack["location"]
    lines = [f"镜头 {pack['shot']}（{pack['scene']}）。地点：{location.get('name', location['id'])}，"
             f"{'、'.join(location.get('identity', []))}；{'、'.join(str(v) for v in pack['environment']['entry'].values())}。"]
    order = {kind: rank for rank, kind in enumerate(("character", "creature", "vehicle", "prop", "object"))}
    for entity_id, info in sorted(pack["entities"].items(), key=lambda item: (order.get(item[1].get("kind"), 9), item[0])):
        if info.get("kind") == "location":
            continue
        entry = info.get("entry")
        if entry is None:
            continue
        parts = [f"{info.get('name', entity_id)}：{'、'.join(info.get('identity', []))}"]
        if entry.get("variant_description"):
            parts.append(entry["variant_description"])
        if entry.get("position"):
            parts.append(f"位于{entry['position']}")
        if entry.get("holding"):
            parts.append("手持" + "、".join(entry["holding"]))
        lines.append("；".join(parts) + "。")
    moves = []
    for entity_id, change in pack["changes"].get("entities", {}).items():
        if change.get("exit"):
            moves.append(f"{entity_id} 离开画面")
        else:
            moves.append(f"{entity_id} → " + "，".join(f"{key}={value if not isinstance(value, list) else '、'.join(value) or '空'}" for key, value in change.items()))
    lines.append("本镜变化：" + ("；".join(moves) if moves else "无") + "。")
    return "\n".join(lines)


# ---------- 生成记录 ----------

def record_errors(record):
    errors = []
    if not text(record.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    kind, purpose = record.get("kind"), record.get("purpose")
    if kind not in RECORD_KINDS:
        errors.append(f"kind 必须是 {'/'.join(RECORD_KINDS)}")
    if purpose not in PURPOSES:
        errors.append(f"purpose 必须是 {'/'.join(PURPOSES)}")
    if kind in ("video", "image") and not text(record.get("shot_id")):
        errors.append("画面生成必须写 shot_id")
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        errors.append("inputs 必须是对象")
        inputs = {}
    if inputs.get("anchors_sha256") is not None and not (isinstance(inputs["anchors_sha256"], str) and SHA256.fullmatch(inputs["anchors_sha256"])):
        errors.append("inputs.anchors_sha256 必须是 64 位小写十六进制或 null")
    if not (isinstance(inputs.get("references", []), list) and all(isinstance(x, str) and SHA256.fullmatch(x) for x in inputs.get("references", []))):
        errors.append("inputs.references 必须是参考素材 SHA-256 数组")
    for key in ("first_frame", "last_frame"):
        frame = inputs.get(key)
        if frame is not None:
            _media_errors(frame, f"inputs.{key}", errors)
            if isinstance(frame, dict) and frame.get("from") not in FRAME_SOURCES:
                errors.append(f"inputs.{key}.from 必须是 {'/'.join(FRAME_SOURCES)}")
    engine = record.get("engine")
    if not isinstance(engine, dict) or not text(engine.get("provider")) or not text(engine.get("model")):
        errors.append("engine 必须写 provider 与 model")
    budget = record.get("budget")
    if not isinstance(budget, dict) or not isinstance(budget.get("billable"), bool):
        errors.append("budget.billable 必须是布尔值")
    elif budget["billable"] and not (budget.get("usage") or (text(budget.get("currency")) and (number(budget.get("estimated", -1)) or number(budget.get("actual", -1))))):
        errors.append("计费任务必须记录预估或实际金额（含币种），或至少记录用量 usage")
    for key in ("submitted_at", "finished_at"):
        if not text(record.get(key)):
            errors.append(f"{key} 必须是时间字符串")
    status = record.get("status")
    if status not in STATUSES:
        errors.append(f"status 必须是 {'/'.join(STATUSES)}")
    outputs = record.get("outputs")
    if not isinstance(outputs, list):
        errors.append("outputs 必须是数组")
        outputs = []
    if status in ("succeeded", "partial") and not outputs:
        errors.append("成功的生成至少要有一个输出")
    ids = set()
    for index, output in enumerate(outputs):
        label = f"outputs[{index}]"
        _media_errors(output, label, errors)
        if not isinstance(output, dict):
            continue
        if not text(output.get("id")) or output["id"] in ids:
            errors.append(f"{label}.id 必须唯一")
        ids.add(output.get("id"))
    if not isinstance(record.get("errors", []), list):
        errors.append("errors 必须是数组")
    selection = record.get("selection")
    if selection is not None:
        if not isinstance(selection, dict) or selection.get("output_id") not in ids or not text(selection.get("by")):
            errors.append("selection 必须指向已有输出，并写选择人 by")
        elif purpose == "animatic_temp":
            errors.append("预演临时产物不能被选为交付候选")
    return errors


def record_problems(record, bible, state, project=None):
    """生成记录与当前资产库、时间线的交叉检查；返回 (问题, 提醒)。"""
    problems, warnings = [], []
    if record.get("project_id") != bible.get("project_id"):
        problems.append("生成记录与资产库的 project_id 不一致")
    index, inputs = entity_index(bible), record.get("inputs", {})
    label = record.get("shot_id") or record.get("kind")
    if record.get("kind") in ("video", "image"):
        try:
            pack = anchor_pack(bible, state, record["shot_id"])
        except ValueError as exc:
            return [str(exc)], warnings
        if inputs.get("anchors_sha256") is None:
            problems.append(f"{label}：生成时没有绑定锚点包，无法证明与资产库和时间线一致")
        elif inputs["anchors_sha256"] != pack_sha256(pack):
            problems.append(f"{label}：生成后资产库或时间线改动了本镜锚点，take 可能已过期，需复核或重生成")
        allowed = {ref["sha256"]: entity_id for entity_id, info in pack["entities"].items() for ref in info.get("references", [])}
        allowed.update({ref["sha256"]: pack["location"]["id"] for ref in pack["location"].get("references", [])})
        used = set(inputs.get("references", []))
        for sha in sorted(used - set(allowed)):
            problems.append(f"{label}：参考素材 {sha[:12]} 不属于本镜在场的实体或地点")
        for entity_id, info in pack["entities"].items():
            if info.get("kind") in ("character", "creature") and not used & {ref["sha256"] for ref in info.get("references", [])}:
                warnings.append(f"{label}：{entity_id} 没有使用任何参考素材，身份只靠文字锚定")
        frame = inputs.get("first_frame") or {}
        if frame.get("from") == "previous_exit" and frame.get("shot") != pack["previous_shot"]:
            problems.append(f"{label}：首帧取自 {frame.get('shot')} 的出点，但上一镜是 {pack['previous_shot']}")
    for output in record.get("outputs", []):
        speaker = output.get("entity")
        binding = index.get(speaker, {}).get("voice") if speaker else None
        if binding and output.get("voice") and output["voice"] != binding["voice"]:
            problems.append(f"{label}：{output['id']} 的音色 {output['voice']} 与资产库中 {speaker} 的绑定 {binding['voice']} 不一致")
    if project:
        items = [(f"{label} 输出 {output.get('id')}", output) for output in record.get("outputs", [])]
        items += [(f"{label} {key}", inputs[key]) for key in ("first_frame", "last_frame") if inputs.get(key)]
        for name, item in items:
            path = Path(project) / item["path"]
            if not path.is_file():
                problems.append(f"{name} 文件不存在：{item['path']}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                problems.append(f"{name} 文件内容与记录的 SHA-256 不一致：{item['path']}")
    return problems, warnings


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
    command = commands.add_parser("anchors")
    command.add_argument("shot")
    command.add_argument("--bible", required=True)
    command.add_argument("--state", required=True)
    command.add_argument("--text", action="store_true")
    record = commands.add_parser("record").add_subparsers(dest="action", required=True)
    command = record.add_parser("validate")
    command.add_argument("file")
    command = commands.add_parser("check")
    command.add_argument("--bible", required=True)
    command.add_argument("--state", required=True)
    command.add_argument("--continuity")
    command.add_argument("--record", action="append", default=[])
    command.add_argument("--project")
    args = parser.parse_args()
    try:
        if args.command == "anchors":
            bible_data, data = load(args.bible, BIBLE_FORMAT), load(args.state, STATE_FORMAT)
            problems = bible_errors(bible_data) or state_errors(data, bible_data)
            if not problems:
                pack = anchor_pack(bible_data, data, args.shot)
                print(anchor_text(pack) if args.text else json.dumps({"sha256": pack_sha256(pack), "pack": pack}, ensure_ascii=False, indent=2))
                return
            label = ""
        elif args.command == "record":
            data = load(args.file, RECORD_FORMAT)
            problems = record_errors(data)
            label = f"{data.get('kind')} 生成记录，{len(data.get('outputs', []))} 个输出"
        elif args.command == "bible":
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
            for path in args.record if not problems else []:
                record_data = load(path, RECORD_FORMAT)
                found, notes = (record_errors(record_data), []) if record_errors(record_data) else record_problems(record_data, bible_data, data, args.project)
                problems += [f"{Path(path).name}：{item}" for item in found]
                warnings += [f"{Path(path).name}：{item}" for item in notes]
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
