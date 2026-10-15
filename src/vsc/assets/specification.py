"""Stable asset identity, variants, reference media and shared style contracts."""
import copy
import hashlib
import re
from pathlib import Path

BIBLE_FORMAT = "vsc.asset-bible/v1"


KINDS = ("character", "prop", "object", "location", "creature", "vehicle")


RIGHTS = ("owned", "licensed", "temp_only", "unknown")


POSITIONS = ("bottom", "top", "center", "custom")


REFERENCE_PURPOSES = ("identity", "appearance", "composition", "action", "voice", "sound")


REFERENCE_MEDIA = ("image", "video", "audio")


SAFE_ID = re.compile(r"[^\W_][\w.-]*\Z")


HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")


SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value, minimum=0.0, inclusive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value >= minimum if inclusive else value > minimum


def _media_errors(item, label, errors):
    if not isinstance(item, dict):
        errors.append(f"{label} 必须是对象")
        return
    path = item.get("path")
    if not text(path) or Path(path).is_absolute() or ".." in Path(path).parts:
        errors.append(f"{label}.path 必须是项目内的相对路径")
    if not isinstance(item.get("sha256"), str) or not SHA256.fullmatch(item["sha256"]):
        errors.append(f"{label}.sha256 必须是 64 位小写十六进制，绑定具体文件版本")


def reference_info(ref):
    """旧 SHA 引用默认是身份图片；新引用保留媒体、用途、实体和版本元数据。"""
    if isinstance(ref, str):
        return {"sha256": ref, "media_type": "image", "purpose": "identity"}
    return {"media_type": "image", "purpose": "identity", **ref}


def _reference_errors(ref, label, errors, asset=False):
    if isinstance(ref, str) and not asset:
        if not SHA256.fullmatch(ref):
            errors.append(f"{label} 必须是 SHA-256 或带用途的引用对象")
        return
    if not isinstance(ref, dict):
        errors.append(f"{label} 必须是引用对象")
        return
    if asset or "path" in ref:
        _media_errors(ref, label, errors)
    elif ref.get("sha256") is None and isinstance(ref.get("source_uri"), str) and ref["source_uri"].startswith(("https://", "http://", "asset://")):
        pass  # 透明保留未提供内容摘要的远程输入，交叉检查仍不能把它当作已核实身份。
    elif not isinstance(ref.get("sha256"), str) or not SHA256.fullmatch(ref["sha256"]):
        errors.append(f"{label}.sha256 必须是 64 位小写十六进制")
    info = reference_info(ref)
    if info["media_type"] not in REFERENCE_MEDIA or info["purpose"] not in REFERENCE_PURPOSES:
        errors.append(f"{label} 必须声明有效 media_type 与 purpose")
    elif ((info["purpose"] in ("identity", "appearance", "composition") and info["media_type"] != "image")
          or (info["purpose"] == "action" and info["media_type"] != "video")
          or (info["purpose"] in ("voice", "sound") and info["media_type"] != "audio")):
        errors.append(f"{label} 的媒体类别与用途不相容")
    for key in ("entity_id", "role"):
        if key in ref and ref[key] is not None and not text(ref[key]):
            errors.append(f"{label}.{key} 必须是非空字符串或 null")
    if ref.get("role") and info["media_type"] in REFERENCE_MEDIA and ref["role"] != "reference_" + info["media_type"]:
        errors.append(f"{label}.role 与 media_type 不一致")
    variants = ref.get("variants")
    if variants is not None and not (isinstance(variants, list) and variants and all(text(v) for v in variants)):
        errors.append(f"{label}.variants 必须是非空变体 ID 数组")
    if asset and info["purpose"] == "appearance" and not variants:
        errors.append(f"{label} 的外观参考必须声明适用 variants")


def applicable_references(entity, variants):
    """通用身份可跨变体；专用参考只进入实际使用该变体的镜头。"""
    return [copy.deepcopy(ref) for ref in entity.get("references", [])
            if not ref.get("variants") or set(ref["variants"]) & set(variants)]


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
            _reference_errors(ref, f"{label}.references[{ref_index}]", errors, asset=True)
            if isinstance(ref, dict) and isinstance(ref.get("variants"), list) and all(text(v) for v in ref["variants"]) and isinstance(variants, dict):
                if set(ref["variants"]) - set(variants):
                    errors.append(f"{label}.references[{ref_index}] 含未登记的变体")
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
                if "pronunciations" in voice:
                    guide = voice["pronunciations"]
                    if (not isinstance(guide, list) or any(not isinstance(row, dict)
                            or not text(row.get("term")) or not text(row.get("spoken")) for row in guide)):
                        errors.append(f"{label}.voice.pronunciations 须为 term/spoken 非空文本数组")
                    elif len({row["term"] for row in guide}) != len(guide):
                        errors.append(f"{label}.voice.pronunciations 词条不得重复")
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


