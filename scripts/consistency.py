#!/usr/bin/env python3
"""VSC 一致性：身份层（vsc.asset-bible/v1）、场景状态时间线（vsc.scene-state/v1）与生成记录（vsc.generation-record/v1）。

  bible validate FILE [--project DIR]          校验资产库；给出项目目录时核对参考素材与声音文件的 SHA-256
  state validate FILE [--bible FILE]           校验状态时间线；给出资产库时核对实体、变体与地点
  state at FILE SHOT [--bible FILE]            输出某镜头入点与出点的推导状态（JSON）
  anchors SHOT --bible FILE --state FILE [--text] [--moment entry|exit]
                                               输出该镜头的锚点包（JSON，含 sha256）；--text 输出可改写为提示词的文字，
                                               加 --moment 时只写入点或出点的完整状态，用于生成首帧、尾帧
  record validate FILE                         校验一份生成记录的结构
  visual validate FILE                         校验一份 AI 视觉检查报告（vsc.visual-check/v1）的结构
  check --bible FILE --state FILE [--continuity PLAN] [--record FILE ...] [--project DIR]
                                               交叉检查；连续性计划须与时间线一致，生成记录须绑定当前锚点。
                                               同时给出资产图、关键帧与视频的记录时，沿“资产图 → 关键帧 → 视频”追溯
                                               身份锚定，并核对相邻镜头视频的交界帧是同一张图

资产库为人物、道具、物体、地点等实体登记不可变特征、命名变体、参考素材、生成锚点，以及人物音色与物体声音，
并给出全片统一的字幕样式。状态时间线为每场戏写基线状态，每个镜头只写该镜内发生的变化：任一镜头的入点状态
是基线加上之前各镜变化的累积，出点状态再加上本镜变化，因此同场不相邻的镜头天然一致。

锚点包是某个镜头生成时必须遵守的全部身份与状态：在场实体的不可变特征、变体、位置、手持物、参考素材与生成锚点，
地点与环境，以及本镜内的变化。生成记录用 anchors_sha256 绑定所用锚点包；资产库或时间线之后改动了该镜头的锚点，
交叉检查会指出该 take 已过期。

画面按“资产图 → 关键帧 → 视频”三段生成，生成记录相应写明：
- 资产图：purpose=asset，不写 shot_id；生成后应登记为资产库中对应实体的参考素材。
- 关键帧：图像记录写 shot_id 和 inputs.moment（entry/exit）。以上一张关键帧为底图编辑或参考时，写 inputs.base_frame（use=edit/reference），身份沿它逐级上溯到资产图。
- 视频：inputs.first_frame 和 inputs.last_frame 写两帧的 SHA；同场相邻两镜，前一镜的尾帧与后一镜的首帧必须是同一张图。
  供应商返回的视频尾帧作为输出登记（role=last_frame），它就是该镜出点，可直接作为下一镜首帧。

视觉检查报告逐条记录 AI 对画面的判断（pass/fail/unsure）与依据，advisory 必须为 true：它只作提醒，不能代替人工批准。
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
PURPOSES = ("candidate", "animatic_temp", "asset")
MOMENTS = ("entry", "exit")
BASE_USES = ("reference", "edit")
OUTPUT_ROLES = ("last_frame",)
VISUAL_FORMAT = "vsc.visual-check/v1"
VERDICTS = ("pass", "fail", "unsure")
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


def anchor_text(pack, moment=None):
    """把锚点包写成可改写为供应商提示词的中文段落：逐镜写出入点状态与本镜变化，而不是全片共用一段描述。

    moment 为 entry 或 exit 时只写该时刻的完整状态（用于生成首帧、尾帧），不写本镜变化。
    """
    state_moment = moment or "entry"
    names = {entity_id: info.get("name", entity_id) for entity_id, info in pack["entities"].items()}

    def named(items):
        return "、".join(names.get(item, item) for item in items)

    def describe(info):
        # 外观描述可写得更生动，但不可变特征每一镜都必须出现，不能被外观描述替换掉。
        appearance = info.get("generation", {}).get("prompt")
        identity = "、".join(info.get("identity", []))
        return "；".join(part for part in (appearance, f"不可改变：{identity}" if identity else "") if part)

    location = pack["location"]
    label = {"entry": "入点", "exit": "出点"}.get(moment, "")
    lines = [f"镜头 {pack['shot']}{label}（{pack['scene']}）。地点：{location.get('name', location['id'])}，"
             f"{describe(location)}；{'、'.join(str(v) for v in pack['environment'][state_moment].values())}。"]
    order = {kind: rank for rank, kind in enumerate(("character", "creature", "vehicle", "prop", "object"))}
    for entity_id, info in sorted(pack["entities"].items(), key=lambda item: (order.get(item[1].get("kind"), 9), item[0])):
        if info.get("kind") == "location":
            continue
        entry = info.get(state_moment)
        if entry is None:
            continue
        parts = [f"{names[entity_id]}：{describe(info)}"]
        if entry.get("variant_description"):
            parts.append(entry["variant_description"])
        if entry.get("position"):
            parts.append(f"位于{entry['position']}")
        if entry.get("holding"):
            parts.append("手持" + named(entry["holding"]))
        lines.append("；".join(parts) + "。")
    if moment:
        return "\n".join(lines)
    moves = []
    for entity_id, change in pack["changes"].get("entities", {}).items():
        name = names.get(entity_id, entity_id)
        if change.get("exit"):
            moves.append(f"{name}离开画面")
            continue
        entered = pack["entities"].get(entity_id, {}).get("entry") is None
        steps = []
        if "position" in change:
            steps.append(f"{'出现在' if entered else '移到'}{change['position']}")
        if "holding" in change:
            steps.append(f"改为手持{named(change['holding'])}" if change["holding"] else "放下手中之物")
        if "variant" in change:
            exit_state = pack["entities"].get(entity_id, {}).get("exit", {})
            steps.append(f"变为{exit_state.get('variant_description') or change['variant']}")
        moves.append(name + "，".join(steps))
    lines.append("本镜变化：" + ("；".join(moves) if moves else "无") + "。")
    return "\n".join(lines)


# ---------- 生成记录 ----------

def record_errors(record):
    if not isinstance(record, dict):
        return ["生成记录必须是对象"]
    errors = []
    if record.get("format") != RECORD_FORMAT:
        errors.append(f"format 必须为 {RECORD_FORMAT}")
    if not text(record.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    kind, purpose = record.get("kind"), record.get("purpose")
    if kind not in RECORD_KINDS:
        errors.append(f"kind 必须是 {'/'.join(RECORD_KINDS)}")
    if purpose not in PURPOSES:
        errors.append(f"purpose 必须是 {'/'.join(PURPOSES)}")
    if purpose == "asset" and kind != "image":
        errors.append("资产生成（purpose=asset）只能是图像")
    elif kind in ("video", "image") and purpose != "asset" and not text(record.get("shot_id")):
        errors.append("镜头画面生成必须写 shot_id")
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        errors.append("inputs 必须是对象")
        inputs = {}
    if kind == "image" and inputs.get("moment") is not None and inputs["moment"] not in MOMENTS:
        errors.append(f"inputs.moment 必须是 {'/'.join(MOMENTS)}")
    if inputs.get("base_frame") is not None:
        if kind != "image":
            errors.append("只有图像记录可以写 inputs.base_frame")
        _media_errors(inputs["base_frame"], "inputs.base_frame", errors)
        if isinstance(inputs["base_frame"], dict) and inputs["base_frame"].get("use") not in BASE_USES:
            errors.append(f"inputs.base_frame.use 必须是 {'/'.join(BASE_USES)}")
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
        output_id = output.get("id")
        if not text(output_id) or output_id in ids:
            errors.append(f"{label}.id 必须唯一")
        if output.get("role") is not None and (kind != "video" or output["role"] not in OUTPUT_ROLES):
            errors.append(f"{label}.role 只用于视频输出，取值 {'/'.join(OUTPUT_ROLES)}")
        if text(output_id):
            ids.add(output_id)
    if not isinstance(record.get("errors", []), list):
        errors.append("errors 必须是数组")
    selection = record.get("selection")
    if selection is not None:
        if not isinstance(selection, dict) or not text(selection.get("output_id")) or selection["output_id"] not in ids or not text(selection.get("by")):
            errors.append("selection 必须指向已有输出，并写选择人 by")
        elif purpose == "animatic_temp":
            errors.append("预演临时产物不能被选为交付候选")
    return errors


def _anchor_record(record, project_id=None):
    """只有同作品、结构完整且有成功输出的记录可承载身份来源。"""
    return (not record_errors(record) and record.get("status") in ("succeeded", "partial")
            and (project_id is None or record.get("project_id") == project_id))


def keyframe_sources(keyframes, digest, project_id=None):
    """读取同一文件的全部合法来源；兼容旧调用方传入的单记录索引。"""
    sources = keyframes.get(digest, [])
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, (list, tuple)):
        return []
    return [record for record in sources if _anchor_record(record, project_id)
            and ((record.get("kind") == "image" and record.get("purpose") == "candidate"
                  and any(output["sha256"] == digest for output in record["outputs"]))
                 or (record.get("kind") == "video" and any(output.get("role") == "last_frame" and output["sha256"] == digest
                                                           for output in record["outputs"])))]


def identity_references(record, keyframes, seen=(), project_id=None):
    """沿基础帧或视频首帧追溯身份；同一 SHA 可有多个来源，循环按记录截断。"""
    project_id = project_id or (record.get("project_id") if isinstance(record, dict) else None)
    if not _anchor_record(record, project_id) or id(record) in seen:
        return set()
    inputs = record.get("inputs", {})
    used = set(inputs.get("references", []))
    base = (inputs.get("first_frame" if record.get("kind") == "video" else "base_frame") or {}).get("sha256")
    for source in keyframe_sources(keyframes, base, project_id):
        used |= identity_references(source, keyframes, (*seen, id(record)), project_id)
    return used


def record_problems(record, bible, state, project=None, keyframes=None):
    """生成记录与当前资产库、时间线的交叉检查；返回 (问题, 提醒)。

    keyframes 是 {输出 SHA-256: 来源记录数组}，也兼容旧的单记录索引。关键帧的身份来自它用到的资产图以及它所基于的上一张关键帧；
    视频首尾帧能追溯到这样的关键帧时，身份算作由图像锚定。
    """
    problems, warnings = [], []
    structural = record_errors(record)
    if structural:
        return structural, warnings
    keyframes = keyframes or {}
    if record.get("project_id") != bible.get("project_id"):
        problems.append("生成记录与资产库的 project_id 不一致")
    index, inputs = entity_index(bible), record.get("inputs", {})
    label = record.get("shot_id") or record.get("kind")
    if record.get("purpose") == "asset":
        registered = {ref["sha256"] for entity in bible.get("entities", []) for ref in entity.get("references", [])}
        for output in record.get("outputs", []):
            if output.get("sha256") not in registered:
                warnings.append(f"资产图 {output.get('id')} 尚未登记为资产库中任何实体的参考素材")
    elif record.get("kind") in ("video", "image"):
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
        for sha in sorted(set(inputs.get("references", [])) - set(allowed)):
            problems.append(f"{label}：参考素材 {sha[:12]} 不属于本镜在场的实体或地点")
        used = (set(inputs.get("references", [])) if record.get("kind") == "video"
                else identity_references(record, keyframes, project_id=bible.get("project_id")))
        base = inputs.get("base_frame")
        if base and keyframes and not keyframe_sources(keyframes, base["sha256"], bible.get("project_id")):
            warnings.append(f"{label}：基础帧 {base['path']} 追溯不到关键帧记录")
        boundaries = {"first_frame": ((record["shot_id"], "entry"), (pack["previous_shot"], "exit")),
                      "last_frame": ((record["shot_id"], "exit"),)}
        frame_sources = {}
        if record.get("kind") == "video":
            for key in ("first_frame", "last_frame"):
                sources = keyframe_sources(keyframes, (inputs.get(key) or {}).get("sha256"), bible.get("project_id"))
                frame_sources[key] = sources
                if inputs.get(key) and not sources and keyframes:
                    warnings.append(f"{label}：{key} {inputs[key]['path']} 追溯不到关键帧记录，无法确认它用资产图锚定")
                for source in sources:
                    if moment_of(source) in boundaries[key]:
                        used |= identity_references(source, keyframes, project_id=bible.get("project_id"))
        for entity_id, info in pack["entities"].items():
            if info.get("kind") in ("character", "creature") and not used & {ref["sha256"] for ref in info.get("references", [])}:
                warnings.append(f"{label}：{entity_id} 没有使用任何参考素材或由资产图生成的关键帧，身份只靠文字锚定")
        frame = inputs.get("first_frame") or {}
        if frame.get("from") == "previous_exit" and frame.get("shot") != pack["previous_shot"]:
            problems.append(f"{label}：首帧取自 {frame.get('shot')} 的出点，但上一镜是 {pack['previous_shot']}")
        first, last = frame_sources.get("first_frame", []), frame_sources.get("last_frame", [])
        if first and not any(moment_of(source) in boundaries["first_frame"] for source in first):
            problems.append(f"{label}：首帧对应的关键帧既不是本镜入点也不是上一镜出点")
        if last and not any(moment_of(source) in boundaries["last_frame"] for source in last):
            problems.append(f"{label}：尾帧对应的关键帧不是本镜出点")
    for output in record.get("outputs", []):
        speaker = output.get("entity")
        binding = index.get(speaker, {}).get("voice") if speaker else None
        if binding and output.get("voice") and output["voice"] != binding["voice"]:
            problems.append(f"{label}：{output['id']} 的音色 {output['voice']} 与资产库中 {speaker} 的绑定 {binding['voice']} 不一致")
    if project:
        items = [(f"{label} 输出 {output.get('id')}", output) for output in record.get("outputs", [])]
        items += [(f"{label} {key}", inputs[key]) for key in ("first_frame", "last_frame", "base_frame") if inputs.get(key)]
        for name, item in items:
            path = Path(project) / item["path"]
            if not path.is_file():
                problems.append(f"{name} 文件不存在：{item['path']}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                problems.append(f"{name} 文件内容与记录的 SHA-256 不一致：{item['path']}")
    return problems, warnings


def visual_errors(report):
    if not isinstance(report, dict):
        return ["视觉检查报告必须是对象"]
    errors = []
    if report.get("format") != VISUAL_FORMAT:
        errors.append(f"format 必须为 {VISUAL_FORMAT}")
    if not text(report.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    shot, entities = report.get("shot_id"), report.get("entities")
    if not (text(shot) or (isinstance(entities, list) and entities and all(text(item) for item in entities))):
        errors.append("必须写 shot_id（核对镜头），或写 entities（核对资产图中的实体）")
    if report.get("moment") is not None and report["moment"] not in MOMENTS:
        errors.append(f"moment 必须是 {'/'.join(MOMENTS)} 或 null")
    _media_errors(report.get("subject"), "subject", errors)
    if text(shot) and not (isinstance(report.get("anchors_sha256"), str) and SHA256.fullmatch(report["anchors_sha256"])):
        errors.append("核对镜头时 anchors_sha256 必须是 64 位小写十六进制")
    engine = report.get("engine")
    if not isinstance(engine, dict) or not text(engine.get("provider")) or not text(engine.get("model")):
        errors.append("engine 必须写 provider 与 model")
    if report.get("advisory") is not True:
        errors.append("advisory 必须为 true：AI 视觉检查只作提醒")
    results = report.get("results")
    if not isinstance(results, list) or not results:
        errors.append("results 必须是非空数组")
        results = []
    for index, item in enumerate(results):
        if not isinstance(item, dict) or not text(item.get("item")) or item.get("verdict") not in VERDICTS:
            errors.append(f"results[{index}] 必须写 item 与 verdict（{'/'.join(VERDICTS)}）")
        if not isinstance(item, dict) or not text(item.get("evidence")):
            errors.append(f"results[{index}].evidence 必须是非空字符串")
    if "checklist" in report:
        checklist = report["checklist"]
        if not isinstance(checklist, list) or not checklist or not all(text(item) for item in checklist):
            errors.append("checklist 必须是非空字符串数组")
        else:
            if len(set(checklist)) != len(checklist):
                errors.append("checklist 不能包含重复条目")
            returned = [item["item"] for item in results if isinstance(item, dict) and text(item.get("item"))]
            if len(set(returned)) != len(returned):
                errors.append("results 不能重复核对同一条目")
            if set(checklist) - set(returned):
                errors.append("results 遗漏 checklist 中的条目")
            if set(returned) - set(checklist):
                errors.append("results 含 checklist 之外的条目")
    if not isinstance(report.get("issues", []), list):
        errors.append("issues 必须是数组")
    return errors


def keyframe_index(records, project_id=None):
    """{SHA-256: 来源记录数组}：图像记录的输出，加上视频返回的实际尾帧。

    视频尾帧是该镜的出点；它的身份来自该视频的参考素材，以及视频首帧所在的关键帧链。
    """
    index = {}
    for record in records:
        if not _anchor_record(record, project_id):
            continue
        for output in record["outputs"]:
            if ((record["kind"] == "image" and record["purpose"] == "candidate")
                    or (record["kind"] == "video" and output.get("role") == "last_frame")):
                sources = index.setdefault(output["sha256"], [])
                if not any(source is record for source in sources):
                    sources.append(record)
    return index


def moment_of(record):
    return record.get("shot_id"), "exit" if record.get("kind") == "video" else record.get("inputs", {}).get("moment")


def chain_problems(records, state):
    """同场相邻视频以实际尾帧核对交界；未返回实际尾帧时才退回请求尾帧。"""
    videos = {record["shot_id"]: record for record in records
              if _anchor_record(record, state.get("project_id")) and record.get("kind") == "video"}
    problems = []
    for scene in state["scenes"]:
        order = [shot["id"] for shot in scene["shots"]]
        for previous, current in zip(order, order[1:]):
            if previous in videos and current in videos:
                tails = {output["sha256"] for output in videos[previous]["outputs"] if output.get("role") == "last_frame"}
                if not tails:
                    tails = {(videos[previous].get("inputs", {}).get("last_frame") or {}).get("sha256")}
                tails.discard(None)
                head = (videos[current].get("inputs", {}).get("first_frame") or {}).get("sha256")
                if not tails or not head:
                    problems.append(f"{previous}→{current}：缺首帧或尾帧，交界无法核对")
                elif head not in tails:
                    problems.append(f"{previous}→{current}：后一镜首帧与前一镜尾帧不是同一张图")
    return problems


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
    command.add_argument("--moment", choices=("entry", "exit"), help="只写入点或出点时刻的状态（用于首帧、尾帧）")
    record = commands.add_parser("record").add_subparsers(dest="action", required=True)
    command = record.add_parser("validate")
    command.add_argument("file")
    visual = commands.add_parser("visual").add_subparsers(dest="action", required=True)
    command = visual.add_parser("validate")
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
                print(anchor_text(pack, args.moment) if args.text else json.dumps({"sha256": pack_sha256(pack), "pack": pack}, ensure_ascii=False, indent=2))
                return
            label = ""
        elif args.command == "record":
            data = load(args.file, RECORD_FORMAT)
            problems = record_errors(data)
            outputs = data.get("outputs")
            label = f"{data.get('kind')} 生成记录，{len(outputs) if isinstance(outputs, list) else 0} 个输出"
        elif args.command == "visual":
            data = load(args.file, VISUAL_FORMAT)
            problems = visual_errors(data)
            results = data.get("results") if isinstance(data.get("results"), list) else []
            failed = sum(1 for item in results if isinstance(item, dict) and item.get("verdict") == "fail")
            label = f"视觉检查 {len(results)} 条，未通过 {failed} 条（仅供参考）"
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
            records = [(path, load(path, RECORD_FORMAT)) for path in (args.record if not problems else [])]
            valid_records = []
            for path, record_data in records:
                structural = record_errors(record_data)
                problems += [f"{Path(path).name}：{item}" for item in structural]
                if not structural:
                    valid_records.append((path, record_data))
            keyframes = keyframe_index([record for _, record in valid_records], bible_data.get("project_id"))
            for path, record_data in valid_records:
                found, notes = record_problems(record_data, bible_data, data, args.project, keyframes)
                problems += [f"{Path(path).name}：{item}" for item in found]
                warnings += [f"{Path(path).name}：{item}" for item in notes]
            if records and not problems:
                problems += chain_problems([record for _, record in records], data)
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
