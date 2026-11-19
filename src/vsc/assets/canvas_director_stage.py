"""In-canvas director stage and 3D preview documents.

The canvas node text owns the v1 document. Recognition, equirectangular
panoramas and reference videos stay on this machine: no paid provider call.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

from vsc.assets.resource_service import ResourceError

SCHEMA_VERSION = 1
TEXT_LIMIT = 50000
REFERENCE_VIDEO_MAX_BYTES = 8 * 1024 * 1024
REFERENCE_VIDEO_MAX_EDGE = 960
REFERENCE_VIDEO_FPS = 24
REFERENCE_VIDEO_MAX_FRAMES = 15 * REFERENCE_VIDEO_FPS

PALETTE = (
    "#829BB5", "#C49A7C", "#98AA87", "#AF91B2", "#BF8585", "#7FAAA5",
    "#C4B276", "#8D91B8", "#B18E9F", "#91AEBB", "#A5AA73", "#A18B79",
)
BODY_PRESETS = (
    {"id": "male_basic", "label": "男性素体", "color": "#7fb2ff"},
    {"id": "female_low_poly", "label": "女性素体", "color": "#ff8fb5"},
    {"id": "generous", "label": "宽厚素体", "color": "#f0a35c"},
    {"id": "robust", "label": "健壮素体", "color": "#f25f5c"},
    {"id": "slender", "label": "纤细素体", "color": "#72d6c9"},
    {"id": "young", "label": "少年素体", "color": "#8dd36f"},
    {"id": "children", "label": "儿童素体", "color": "#ffd166"},
    {"id": "two_heads_tall", "label": "二头身", "color": "#b28dff"},
)
POSE_PRESETS = (
    ("stand", "站立"), ("walk", "行走"), ("run", "奔跑"), ("sit", "坐姿"),
    ("crouch", "蹲姿"), ("kneel_single", "单膝跪"), ("kneel_double", "双膝跪"),
    ("combat", "格斗架势"), ("arms_crossed", "抱臂"), ("hands_on_hips", "叉腰"),
    ("wave", "招手"), ("reach", "伸手抓取"), ("lean", "倚靠"),
    ("look_phone", "低头看手机"), ("think", "托腮思考"), ("bow", "鞠躬"),
    ("push", "推搡"), ("kick", "踢腿"), ("throw", "投掷"),
    ("t_pose", "T-Pose 校准"), ("arms_up", "举手"),
)
PRIMITIVES = (
    ("cube", "立方体"), ("sphere", "球体"), ("cylinder", "圆柱体"),
    ("cone", "圆锥"), ("pyramid", "棱锥"), ("torus", "环状体"),
)
CAMERA_PRESETS = (
    {"id": "front_closeup", "label": "正面特写", "position": [0, 1.55, 1.8], "look": [0, 1.5, 0], "fov": 35},
    {"id": "front_medium", "label": "正面中景", "position": [0, 1.5, 4], "look": [0, 1.2, 0], "fov": 50},
    {"id": "front_wide", "label": "正面全景", "position": [0, 1.8, 7], "look": [0, 1.0, 0], "fov": 60},
    {"id": "back_medium", "label": "背面中景", "position": [0, 1.5, -4], "look": [0, 1.2, 0], "fov": 50},
    {"id": "over_shoulder_l", "label": "过肩镜头", "position": [-0.8, 1.55, -1.6], "look": [0.4, 1.3, 1.2], "fov": 50},
    {"id": "over_shoulder_r", "label": "过肩镜头（右）", "position": [0.8, 1.55, -1.6], "look": [-0.4, 1.3, 1.2], "fov": 50},
    {"id": "side_close", "label": "侧面近景", "position": [2.2, 1.45, 0.4], "look": [0, 1.4, 0], "fov": 50},
    {"id": "side_tracking", "label": "侧面跟拍", "position": [4.2, 1.3, 1.2], "look": [0, 1.1, 0], "fov": 50},
    {"id": "low_angle", "label": "低角度仰拍", "position": [0.4, 0.4, 3.2], "look": [0, 1.5, 0], "fov": 50},
    {"id": "low_wide", "label": "低角度广角", "position": [1.2, 0.35, 4.5], "look": [0, 1.2, 0], "fov": 50},
    {"id": "top_45", "label": "45° 俯拍", "position": [3.2, 4.4, 3.6], "look": [0, 0.8, 0], "fov": 50},
    {"id": "top_wide", "label": "俯拍全景", "position": [0.2, 7.2, 5.4], "look": [0, 0.4, 0], "fov": 50},
    {"id": "birdseye", "label": "鸟瞰", "position": [0, 9.5, 0.4], "look": [0, 0, 0], "fov": 50},
    {"id": "dutch", "label": "荷兰角", "position": [1.4, 1.4, 3.2], "look": [0, 1.2, 0], "fov": 50},
)
JOINT_AXES = (
    "body_bend", "body_tilt", "body_turn",
    "head_nod", "head_tilt", "head_turn",
    "torso_bend", "torso_tilt", "torso_turn",
    "left_shoulder_pitch", "left_shoulder_roll", "left_shoulder_yaw",
    "right_shoulder_pitch", "right_shoulder_roll", "right_shoulder_yaw",
    "left_elbow", "right_elbow",
    "left_hip_pitch", "left_hip_roll", "left_hip_yaw",
    "right_hip_pitch", "right_hip_roll", "right_hip_yaw",
    "left_knee", "right_knee",
)
LIGHT_TYPES = {"directional": "太阳光", "point": "点光源", "spot": "聚光灯"}
PANORAMA_SOURCES = {"none", "upload", "history", "generated", "linked", "image_to_panorama"}
OBJECT_KINDS = {"character", "prop", "primitive", "crowd", "uploaded_model", "light"}
ASPECTS = {"16:9", "9:16", "1:1", "4:3", "21:9", "2.35:1"}
SHOT_MODES = {"current": 1, "four": 4, "twelve": 12}
LINKED_REJECT = "已连接图片暂不支持直接识图，请重新上传本地图片"
IDENTITY_APPLIED = "身份配色已应用，请重新截图用于下游。"
IDENTITY_STALE = "场景已变化，请重新应用身份配色。"
FRAMING_OCCLUDED = "核心对象仍有遮挡，请检查场景或手动调整机位。"
MODEL_PLACEHOLDER = "模型上传中… 已本地导入占位模型"


def fail(message, code="invalid_director_stage"):
    raise ResourceError(message, code)


def dump_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _finite(value, low, high, message):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        fail(message)
    return float(value)


def _vec(value, low=-1000, high=1000):
    if not isinstance(value, list) or len(value) != 3:
        fail("位置、旋转或缩放需要三个数值")
    return [_finite(item, low, high, "场景数值超出范围") for item in value]


def _text(value, limit, message, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (not allow_empty and not value.strip()):
        fail(message)
    return value.strip() if not allow_empty else value


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        fail("对象标识须为 1–100 位字母、数字、下划线或短横线")
    return value


def default_stage():
    preset = CAMERA_PRESETS[1]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "scene": {
            "backgroundMode": "sky", "gridVisible": True, "groundVisible": True,
            "skyColor": "#87CEEB", "groundOpacity": 1, "groundHeight": 0, "unit": "m",
            "sceneScale": 1, "sceneTranslation": [0, 0, 0], "sceneRotation": [0, 0, 0],
        },
        "viewport": {"activeView": "director", "directorView": {"yaw": 0.6, "pitch": 0.35, "distance": 12, "target": [0, 1, 0]}},
        "objects": [],
        "groups": [],
        "cameras": [_camera_from_preset(preset, "cam-front-medium")],
        "selection": [],
        "panorama": {
            "sourceType": "none", "mediaId": None, "linkedNodeId": None, "url": "",
            "fileName": "", "rotationY": 0, "radius": 60, "status": "idle", "errorMessage": "", "origin": "none",
        },
        "capture": {"guides": {"thirds": False, "safe": False}},
        "ui": {"snapToGrid": True, "uniformScale": True},
        "identityStale": False,
        "identitySignature": "",
    }


def default_preview(document_id):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "documentRef": {"documentId": document_id, "revision": 1, "schemaVersion": SCHEMA_VERSION},
        "timelineSummary": {"durationSeconds": 15, "shotCount": 1},
        "mode": "preview",
        "playhead": 0,
        "stage": default_stage(),
    }


def _camera_from_preset(preset, identity):
    return {
        "id": identity, "name": preset["label"], "preset": preset["id"],
        "transform": {"position": list(preset["position"]), "rotation": [0, 0, 0], "scale": [1, 1, 1]},
        "fov": preset["fov"], "aspectRatio": "16:9", "lookAtTargetId": None,
        "lookAtPoint": list(preset["look"]), "screenshots": [], "framing": None, "roll": 0,
    }


def _blank_object(kind, identity, name):
    return {
        "id": identity, "kind": kind, "name": name, "variant": "", "pose": "stand", "joints": {},
        "color": "#829BB5", "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
        "visible": True, "locked": False, "groupId": None, "opacity": 1, "identity": None,
        "primitive": "", "crowd": None, "lightType": "", "semanticRole": kind, "refId": identity,
        "placeholder": "",
    }


def clamp_fov(value):
    return min(90.0, max(15.0, float(value)))


def clamp_crowd(rows, columns, spacing):
    if isinstance(rows, bool) or isinstance(columns, bool) or isinstance(spacing, bool):
        fail("群众阵列行数为 1–20，列数为 1–40，间距为 0.2–5")
    try:
        rows = int(rows)
        columns = int(columns)
        spacing = float(spacing)
    except (TypeError, ValueError):
        fail("群众阵列行数为 1–20，列数为 1–40，间距为 0.2–5")
    if not math.isfinite(spacing):
        fail("群众阵列行数为 1–20，列数为 1–40，间距为 0.2–5")
    return {"rows": min(20, max(1, rows)), "columns": min(40, max(1, columns)), "spacing": min(5.0, max(0.2, spacing))}


def load_stage(text):
    if text is None or text == "":
        return default_stage()
    if not isinstance(text, str):
        fail("导演台文档须为 JSON 文本")
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        fail("导演台文档 JSON 无效")
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_VERSION:
        fail("导演台文档须为 schemaVersion 1")
    base = default_stage()
    scene = raw.get("scene") if isinstance(raw.get("scene"), dict) else {}
    base["scene"].update({key: scene[key] for key in base["scene"] if key in scene})
    base["scene"]["skyColor"] = _color(base["scene"].get("skyColor") or "#87CEEB")
    base["scene"]["groundOpacity"] = _finite(base["scene"].get("groundOpacity", 1), 0, 1, "地面透明度须在 0–1")
    base["scene"]["groundHeight"] = _finite(base["scene"].get("groundHeight", 0), -100, 100, "地面高度超出范围")
    base["scene"]["sceneScale"] = _finite(base["scene"].get("sceneScale", 1), 0.01, 100, "整场缩放超出范围")
    base["scene"]["sceneTranslation"] = _vec(base["scene"].get("sceneTranslation") or [0, 0, 0])
    base["scene"]["sceneRotation"] = _vec(base["scene"].get("sceneRotation") or [0, 0, 0], -3600, 3600)
    for flag in ("gridVisible", "groundVisible"):
        if not isinstance(base["scene"][flag], bool):
            fail("地面和网格显隐须为布尔值")
    unit = base["scene"].get("unit") or "m"
    if unit not in {"m", "cm"}:
        fail("地面单位仅支持 m 或 cm")
    base["scene"]["unit"] = unit
    view = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {}
    if view.get("activeView"):
        base["viewport"]["activeView"] = _text(str(view["activeView"]), 100, "当前视角无效")
    if isinstance(view.get("directorView"), dict):
        director = view["directorView"]
        base["viewport"]["directorView"] = {
            "yaw": _finite(director.get("yaw", 0.6), -6.3, 6.3, "视角偏航超出范围"),
            "pitch": _finite(director.get("pitch", 0.35), -1.4, 1.4, "视角俯仰超出范围"),
            "distance": _finite(director.get("distance", 12), 0.2, 500, "视角距离超出范围"),
            "target": _vec(director.get("target") or [0, 1, 0]),
        }
    base["objects"] = [_object(item) for item in raw.get("objects") or []]
    if len(base["objects"]) > 80:
        fail("导演台最多 80 个对象")
    seen = set()
    for item in base["objects"]:
        if item["id"] in seen:
            fail("对象标识重复")
        seen.add(item["id"])
    base["groups"] = []
    for group in raw.get("groups") or []:
        if not isinstance(group, dict):
            fail("分组无效")
        base["groups"].append({"id": _key(group.get("id")), "name": _text(group.get("name", "分组"), 80, "分组名称无效")})
    if len(base["groups"]) > 40:
        fail("分组过多")
    cameras = raw.get("cameras") if isinstance(raw.get("cameras"), list) and raw.get("cameras") else base["cameras"]
    base["cameras"] = [_camera(item) for item in cameras]
    if not 1 <= len(base["cameras"]) <= 24:
        fail("机位数量须为 1–24")
    base["selection"] = [_key(item) for item in raw.get("selection") or [] if isinstance(item, str)][:80]
    pano = raw.get("panorama") if isinstance(raw.get("panorama"), dict) else {}
    source = pano.get("sourceType") or "none"
    if source not in PANORAMA_SOURCES:
        fail("全景来源类型无效")
    base["panorama"].update({
        "sourceType": source,
        "mediaId": pano.get("mediaId") or None,
        "linkedNodeId": pano.get("linkedNodeId") or None,
        "url": pano.get("url") if isinstance(pano.get("url"), str) else "",
        "fileName": pano.get("fileName") if isinstance(pano.get("fileName"), str) else "",
        "rotationY": _finite(pano.get("rotationY", 0), -360, 360, "全景旋转超出范围"),
        "radius": _finite(pano.get("radius", 60), 1, 500, "全景半径超出范围"),
        "status": pano.get("status") if pano.get("status") in {"idle", "loading", "ready", "error"} else "idle",
        "errorMessage": pano.get("errorMessage") if isinstance(pano.get("errorMessage"), str) else "",
        "origin": pano.get("origin") if pano.get("origin") in PANORAMA_SOURCES else source,
    })
    guides = ((raw.get("capture") or {}).get("guides") if isinstance(raw.get("capture"), dict) else {}) or {}
    base["capture"] = {"guides": {"thirds": bool(guides.get("thirds")), "safe": bool(guides.get("safe"))}}
    ui = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
    base["ui"] = {"snapToGrid": bool(ui.get("snapToGrid", True)), "uniformScale": bool(ui.get("uniformScale", True))}
    base["identityStale"] = bool(raw.get("identityStale"))
    signature = raw.get("identitySignature")
    base["identitySignature"] = signature if isinstance(signature, str) and len(signature) <= 4000 else ""
    return base


def _color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        fail("颜色需要六位十六进制值")
    return value.upper()


def _object(item):
    if not isinstance(item, dict):
        fail("场景对象无效")
    kind = item.get("kind")
    if kind not in OBJECT_KINDS:
        fail("场景对象类型无效")
    row = _blank_object(kind, _key(item.get("id")), _text(item.get("name") or kind, 80, "对象名称无效"))
    row["variant"] = item.get("variant") if isinstance(item.get("variant"), str) else ""
    if kind == "character":
        variant = row["variant"] or "male_basic"
        if variant not in {body["id"] for body in BODY_PRESETS}:
            fail("素体类型无效")
        row["variant"] = variant
        pose = item.get("pose") or "stand"
        if pose not in {pose_id for pose_id, _label in POSE_PRESETS}:
            fail("姿势预设无效")
        row["pose"] = pose
        row["color"] = _color(item.get("color") or next(body["color"] for body in BODY_PRESETS if body["id"] == variant))
    else:
        row["color"] = _color(item.get("color") or "#829BB5")
    joints = item.get("joints") or {}
    if not isinstance(joints, dict) or any(key not in JOINT_AXES for key in joints):
        fail("关节轴无效")
    row["joints"] = {key: _finite(value, -180, 180, "关节角度须在 -180–180") for key, value in joints.items()}
    transform = item.get("transform") if isinstance(item.get("transform"), dict) else {}
    row["transform"] = {
        "position": _vec(transform.get("position") or [0, 0, 0]),
        "rotation": _vec(transform.get("rotation") or [0, 0, 0], -3600, 3600),
        "scale": _vec(transform.get("scale") or [1, 1, 1], 0.01, 100),
    }
    for flag in ("visible", "locked"):
        if flag in item and not isinstance(item[flag], bool):
            fail("显隐和锁定须为布尔值")
        if flag in item:
            row[flag] = item[flag]
    if item.get("groupId"):
        row["groupId"] = _key(item["groupId"])
    row["opacity"] = _finite(item.get("opacity", 1), 0, 1, "透明度须在 0–1")
    if kind == "primitive":
        primitive = item.get("primitive") or "cube"
        if primitive not in {item_id for item_id, _label in PRIMITIVES}:
            fail("几何体预设无效")
        row["primitive"] = primitive
    if kind == "crowd":
        crowd = item.get("crowd") if isinstance(item.get("crowd"), dict) else {}
        row["crowd"] = clamp_crowd(crowd.get("rows", 3), crowd.get("columns", 3), crowd.get("spacing", 1))
    if kind == "light":
        light = item.get("lightType") or "directional"
        if light not in LIGHT_TYPES:
            fail("灯光类型无效")
        row["lightType"] = light
    if isinstance(item.get("semanticRole"), str):
        row["semanticRole"] = item["semanticRole"][:80]
    if isinstance(item.get("refId"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item["refId"]):
        row["refId"] = item["refId"]
    if isinstance(item.get("placeholder"), str):
        row["placeholder"] = item["placeholder"][:80]
    identity = item.get("identity")
    if identity is not None:
        row["identity"] = _identity(identity, row["id"])
    return row


def _identity(value, object_id):
    if not isinstance(value, dict):
        fail("身份配色无效")
    color = _color(value.get("markerColor") or "#829BB5")
    code = value.get("colorCode")
    if not isinstance(code, str) or not re.fullmatch(r"\d{2}", code):
        fail("身份色号无效")
    return {
        "objectKey": _key(value.get("objectKey") or object_id),
        "refId": _key(value.get("refId") or object_id),
        "semanticRole": _text(value.get("semanticRole") or "character", 80, "身份角色无效"),
        "colorCode": code,
        "markerColor": color,
    }


def _camera(item):
    if not isinstance(item, dict):
        fail("机位无效")
    preset = item.get("preset") or "front_medium"
    known = {row["id"]: row for row in CAMERA_PRESETS}
    if preset not in known:
        fail("机位预设无效")
    row = _camera_from_preset(known[preset], _key(item.get("id")))
    if isinstance(item.get("name"), str) and item["name"].strip():
        row["name"] = _text(item["name"], 80, "机位名称无效")
    transform = item.get("transform") if isinstance(item.get("transform"), dict) else {}
    if transform:
        row["transform"] = {
            "position": _vec(transform.get("position") or row["transform"]["position"]),
            "rotation": _vec(transform.get("rotation") or [0, 0, 0], -3600, 3600),
            "scale": [1, 1, 1],
        }
    row["fov"] = clamp_fov(_finite(item.get("fov", row["fov"]), 15, 90, "视野角度须在 15–90"))
    aspect = item.get("aspectRatio") or "16:9"
    if aspect not in ASPECTS:
        fail("画幅比例无效")
    row["aspectRatio"] = aspect
    if item.get("lookAtTargetId"):
        row["lookAtTargetId"] = _key(item["lookAtTargetId"])
        row["lookAtPoint"] = None
    elif item.get("lookAtPoint") is not None:
        row["lookAtPoint"] = _vec(item["lookAtPoint"])
        row["lookAtTargetId"] = None
    shots = []
    for shot in item.get("screenshots") or []:
        if not isinstance(shot, dict):
            fail("截图记录无效")
        shots.append({
            "id": _key(shot.get("id")),
            "mediaId": shot.get("mediaId") or None,
            "label": _text(shot.get("label") or "截图", 80, "截图名称无效"),
            "mode": shot.get("mode") if shot.get("mode") in SHOT_MODES else "current",
        })
    if len(shots) > 48:
        fail("单个机位截图过多")
    row["screenshots"] = shots
    framing = item.get("framing")
    row["framing"] = _framing(framing) if framing else None
    row["roll"] = _finite(item.get("roll", 12 if preset == "dutch" else 0), -180, 180, "机位滚转超出范围")
    return row


def _framing(value):
    if not isinstance(value, dict):
        fail("取景记录无效")
    scope = value.get("scope")
    if scope not in {"subject", "relationship", "environment"}:
        fail("取景范围无效")
    subjects = [_key(item) for item in value.get("subjectIds") or []]
    context = [_key(item) for item in value.get("contextIds") or []]
    if not subjects or len(subjects) > 40 or len(context) > 40:
        fail("取景对象数量无效")
    status = value.get("status")
    if status not in {"ok", "occluded", "unavailable"}:
        fail("取景状态无效")
    return {
        "scope": scope, "subjectIds": subjects, "contextIds": context, "status": status,
        "fingerprints": value.get("fingerprints") if isinstance(value.get("fingerprints"), str) and len(value["fingerprints"]) <= 2000 else "",
        "warning": FRAMING_OCCLUDED if status == "occluded" else "",
    }


def load_preview(text, document_id):
    if text is None or text == "":
        return default_preview(document_id)
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        fail("3D 预演文档 JSON 无效")
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_VERSION:
        fail("3D 预演文档须为 schemaVersion 1")
    ref = raw.get("documentRef") if isinstance(raw.get("documentRef"), dict) else {}
    summary = raw.get("timelineSummary") if isinstance(raw.get("timelineSummary"), dict) else {}
    stage_text = dump_json(raw["stage"]) if isinstance(raw.get("stage"), dict) else ""
    stage = load_stage(stage_text) if stage_text else default_stage()
    duration = _finite(summary.get("durationSeconds", 15), 0.1, 15, "预演时长须大于 0 且不超过 15 秒")
    shots = summary.get("shotCount", 1)
    if isinstance(shots, bool) or not isinstance(shots, int) or not 1 <= shots <= 64:
        fail("预演镜头数无效")
    mode = raw.get("mode") if raw.get("mode") in {"preview", "schedule"} else "preview"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "documentRef": {
            "documentId": _key(ref.get("documentId") or document_id),
            "revision": int(ref["revision"]) if isinstance(ref.get("revision"), int) and ref["revision"] >= 1 else 1,
            "schemaVersion": SCHEMA_VERSION,
        },
        "timelineSummary": {"durationSeconds": duration, "shotCount": shots},
        "mode": mode,
        "playhead": _finite(raw.get("playhead", 0), 0, duration, "播放头超出成片时长"),
        "stage": stage,
    }


def linked_panorama_blocked(document, stage_id, image_id, edges):
    linked = [edge.get("source") for edge in edges or [] if edge.get("target") == stage_id and edge.get("port") == "panorama_image"]
    panorama = (document or {}).get("panorama") or {}
    return image_id in linked or panorama.get("linkedNodeId") == image_id


def sync_linked_panorama(document, node_id, edges, nodes):
    links = [edge for edge in edges if edge.get("target") == node_id and edge.get("port") == "panorama_image"]
    if len(links) > 1:
        fail("全景图端口只能连接一张图片", "canvas_port_cardinality")
    pano = document["panorama"]
    if links:
        source = nodes[links[0]["source"]]
        pano["sourceType"] = "linked"
        pano["linkedNodeId"] = source["id"]
        pano["mediaId"] = source.get("media_id")
        pano["fileName"] = source.get("title") or pano.get("fileName") or ""
        pano["status"] = "ready" if source.get("media_id") else "idle"
        if pano.get("origin") in {None, "", "none", "linked"}:
            pano["origin"] = "linked"
    elif pano.get("sourceType") == "linked":
        radius, rotation = pano.get("radius", 60), pano.get("rotationY", 0)
        pano.update(sourceType="none", mediaId=None, linkedNodeId=None, url="", fileName="", status="idle", errorMessage="", origin="none", radius=radius, rotationY=rotation)
    return document


def identity_signature(document):
    rows = []
    for item in document.get("objects") or []:
        if item["kind"] in {"character", "prop", "primitive", "crowd", "uploaded_model"} and not str(item.get("semanticRole") or "").startswith("environment."):
            rows.append(item["id"] + ":" + item["kind"])
    return "|".join(rows)


def mark_identity_stale(document):
    signature = identity_signature(document)
    if document.get("identitySignature") and document["identitySignature"] != signature:
        document["identityStale"] = True
    return document


def finalize_canvas_director_nodes(nodes, edges):
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        if node["type"] == "director-stage":
            document = load_stage(node.get("text") or "")
            sync_linked_panorama(document, node["id"], edges, by_id)
            mark_identity_stale(document)
            node["text"] = dump_json(document)
        elif node["type"] == "3d-preview":
            document = load_preview(node.get("text") or "", node["id"])
            mark_identity_stale(document["stage"])
            node["text"] = dump_json(document)
        if node["type"] in {"director-stage", "3d-preview"} and len(node["text"]) > TEXT_LIMIT:
            fail("导演台文档超过长度上限")
    return nodes


def _eligible(item):
    return item["kind"] in {"character", "prop", "primitive", "crowd", "uploaded_model"} and not str(item.get("semanticRole") or "").startswith("environment.")


def apply_identity_colors(document):
    """Write stable identity colors. Existing camera screenshots stay byte-for-byte."""
    before = deepcopy([camera.get("screenshots") for camera in document["cameras"]])
    targets = [item for item in document["objects"] if _eligible(item)]
    for index, item in enumerate(targets):
        color = PALETTE[index % len(PALETTE)]
        item["identity"] = {
            "objectKey": item["id"], "refId": item.get("refId") or item["id"],
            "semanticRole": item.get("semanticRole") or item["kind"],
            "colorCode": f"{index + 1:02d}", "markerColor": color,
        }
        item["color"] = color
    if [camera.get("screenshots") for camera in document["cameras"]] != before:
        fail("身份配色不能改写已有截图")
    document["identitySignature"] = identity_signature(document)
    document["identityStale"] = False
    return document, IDENTITY_APPLIED


def _bounds(item):
    position = item["transform"]["position"]
    if item["kind"] == "crowd" and item.get("crowd"):
        crowd = item["crowd"]
        width = max(0, crowd["columns"] - 1) * crowd["spacing"]
        depth = max(0, crowd["rows"] - 1) * crowd["spacing"]
        return [position[0] - width / 2, position[1], position[2] - depth / 2, position[0] + width / 2, position[1] + 1.7, position[2] + depth / 2]
    return [position[0] - 0.4, position[1], position[2] - 0.4, position[0] + 0.4, position[1] + 1.7, position[2] + 0.4]


def auto_frame(document, camera_id, subject_ids, context_ids, scope):
    if scope not in {"subject", "relationship", "environment"}:
        fail("取景范围无效")
    by_id = {item["id"]: item for item in document["objects"]}
    subjects = [by_id[item] for item in subject_ids if item in by_id and by_id[item].get("visible", True)]
    if not subjects:
        fail("无法完成取景，请检查核心对象及模型加载状态。", "framing_unavailable")
    boxes = [_bounds(item) for item in subjects]
    if scope in {"relationship", "environment"}:
        boxes.extend(_bounds(by_id[item]) for item in context_ids if item in by_id and by_id[item].get("visible", True))
    low = [min(box[index] for box in boxes) for index in range(3)]
    high = [max(box[index + 3] for box in boxes) for index in range(3)]
    center = [(low[index] + high[index]) / 2 for index in range(3)]
    span = max(high[index] - low[index] for index in range(3)) or 1
    camera = next((item for item in document["cameras"] if item["id"] == camera_id), None)
    if camera is None:
        fail("机位不存在")
    camera["transform"]["position"] = [center[0], center[1] + span * 0.35, center[2] + max(2.5, span * 1.6)]
    camera["lookAtTargetId"] = subject_ids[0] if len(subject_ids) == 1 and scope == "subject" else None
    camera["lookAtPoint"] = None if camera["lookAtTargetId"] else center
    blocked = False
    for other in document["objects"]:
        if other["id"] in subject_ids or other.get("visible", True) is False:
            continue
        box = _bounds(other)
        if box[0] <= center[0] <= box[3] and box[2] <= (camera["transform"]["position"][2] + center[2]) / 2 <= box[5]:
            if box[1] < center[1] + 1.2:
                blocked = True
    fingerprints = ",".join(f"{item['id']}:{round(item['transform']['position'][0], 2)}" for item in subjects)
    camera["framing"] = {
        "scope": scope, "subjectIds": list(subject_ids), "contextIds": list(context_ids),
        "status": "occluded" if blocked else "ok", "fingerprints": fingerprints,
        "warning": FRAMING_OCCLUDED if blocked else "",
    }
    return camera


def apply_recognition(document, recognized, strategy):
    if strategy not in {"insert", "replace"}:
        fail("识图策略仅支持插入或覆盖")
    incoming_objects = [_object(item) for item in recognized.get("objects") or []]
    incoming_cameras = [_camera(item) for item in recognized.get("cameras") or []]
    if strategy == "replace":
        document["objects"] = [item for item in document["objects"] if item["kind"] == "light"]
        document["cameras"] = incoming_cameras or document["cameras"]
        document["panorama"] = default_stage()["panorama"]
        document["objects"].extend(incoming_objects)
    else:
        known = {item["id"] for item in document["objects"]}
        for item in incoming_objects:
            while item["id"] in known:
                item["id"] = (item["id"] + "-x")[:100]
            known.add(item["id"])
            document["objects"].append(item)
        known_cameras = {item["id"] for item in document["cameras"]}
        for camera in incoming_cameras:
            while camera["id"] in known_cameras:
                camera["id"] = (camera["id"] + "-x")[:100]
            known_cameras.add(camera["id"])
            document["cameras"].append(camera)
    mark_identity_stale(document)
    return document


def analyze_image_bytes(content):
    from PIL import Image
    image = Image.open(io.BytesIO(content)).convert("RGB")
    sample = image.resize((8, 8))
    pixels = list(sample.getdata())
    count = max(1, len(pixels))
    average = [sum(pixel[index] for pixel in pixels) / count for index in range(3)]
    objects = [_blank_object("character", "recog-a", "识图角色A")]
    objects[0]["variant"] = "male_basic"
    objects[0]["pose"] = "stand" if average[0] < 180 else "wave"
    objects[0]["color"] = "#7FB2FF"
    if average[1] > 90:
        second = _blank_object("character", "recog-b", "识图角色B")
        second["variant"] = "female_low_poly"
        second["transform"]["position"] = [1.6, 0, 0]
        second["color"] = "#FF8FB5"
        objects.append(second)
    if average[2] >= average[0]:
        cube = _blank_object("primitive", "recog-cube", "识图立方体")
        cube["primitive"] = "cube"
        cube["transform"]["position"] = [-1.4, 0, 0.6]
        objects.append(cube)
    if average[0] + average[1] > 220:
        crowd = _blank_object("crowd", "recog-crowd", "识图群众")
        crowd["crowd"] = {"rows": 2, "columns": 3, "spacing": 0.8}
        crowd["transform"]["position"] = [0, 0, -2]
        objects.append(crowd)
    camera = _camera_from_preset(CAMERA_PRESETS[1], "recog-cam")
    return {"schemaVersion": SCHEMA_VERSION, "objects": objects, "cameras": [camera], "average": [round(item, 2) for item in average]}


def compose_equirectangular(content=None):
    from PIL import Image, ImageEnhance
    width, height = 640, 320
    if content:
        source = Image.open(io.BytesIO(content)).convert("RGB")
        plate = source.resize((width, height))
        plate = ImageEnhance.Color(plate).enhance(0.85)
    else:
        plate = Image.new("RGB", (width, height))
        pixels = []
        for y in range(height):
            blend = y / max(1, height - 1)
            for _x in range(width):
                pixels.append((int(120 + 80 * (1 - blend)), int(170 + 40 * (1 - blend)), int(210 - 40 * blend)))
        plate.putdata(pixels)
    output = io.BytesIO()
    plate.save(output, format="PNG")
    return output.getvalue()


def decode_png(value, label):
    if not isinstance(value, str) or len(value) > 12_000_000:
        fail(label + "无效")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        fail(label + "不是有效的 Base64")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > 8 * 1024 * 1024:
        fail(label + "须为 8MiB 以内的 PNG")
    return raw


def expand_frames(images, frame_count):
    if not isinstance(images, list) or not images or len(images) > 48:
        fail("参考视频需要 1–48 张 PNG 帧", "invalid_reference_video")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or not 1 <= frame_count <= REFERENCE_VIDEO_MAX_FRAMES:
        fail("参考视频帧数须在 1–360", "invalid_reference_video")
    decoded = [decode_png(item, "参考帧") for item in images]
    return [decoded[index % len(decoded)] for index in range(frame_count)]


def encode_reference_video(frames, fps=REFERENCE_VIDEO_FPS):
    if fps != REFERENCE_VIDEO_FPS:
        fail("参考视频须为 24fps", "invalid_reference_video")
    if not frames or len(frames) > REFERENCE_VIDEO_MAX_FRAMES:
        fail("参考视频时长须大于 0 且不超过 15 秒", "invalid_reference_video")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        fail("本机缺少 ffmpeg，无法编码参考视频", "ffmpeg_missing")
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix="vsc-director-video-") as directory:
        folder = Path(directory)
        for index, blob in enumerate(frames):
            image = Image.open(io.BytesIO(blob)).convert("RGB")
            long_edge = max(image.size)
            if long_edge > REFERENCE_VIDEO_MAX_EDGE:
                scale = REFERENCE_VIDEO_MAX_EDGE / long_edge
                image = image.resize((max(2, int(image.width * scale)), max(2, int(image.height * scale))))
            width = image.width - image.width % 2
            height = image.height - image.height % 2
            image = image.resize((max(2, width), max(2, height)))
            image.save(folder / f"frame_{index:04d}.png")
        output = folder / "reference.mp4"
        encoded = None
        for crf in ("23", "32", "40"):
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", str(fps), "-i", str(folder / "frame_%04d.png"),
                "-frames:v", str(len(frames)), "-r", str(fps),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", crf,
                "-movflags", "+faststart", str(output),
            ], check=True, timeout=120)
            encoded = output.read_bytes()
            if len(encoded) <= REFERENCE_VIDEO_MAX_BYTES:
                break
        if encoded is None or len(encoded) > REFERENCE_VIDEO_MAX_BYTES:
            fail("参考视频体积超过 8MiB", "invalid_reference_video")
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate",
            "-show_entries", "format=duration", "-of", "json", str(output),
        ], timeout=30))
    stream = probe["streams"][0]
    duration = float(probe["format"]["duration"])
    width, height = int(stream["width"]), int(stream["height"])
    rate = stream.get("avg_frame_rate") or "0/1"
    num, den = rate.split("/")
    measured = float(num) / float(den) if float(den) else 0
    if not 0 < duration <= 15 or max(width, height) > REFERENCE_VIDEO_MAX_EDGE or abs(measured - 24) > 0.2:
        fail("参考视频未满足时长、画幅或帧率约束", "invalid_reference_video")
    return encoded, {"duration_seconds": duration, "width": width, "height": height, "fps": measured, "size_bytes": len(encoded)}


def plan_preview_edit(preview, text, has_image=False):
    stage = preview["stage"]
    message = text if isinstance(text, str) else ""
    if not message.strip():
        fail("请输入场景修改说明")
    if any(word in message for word in ("删除", "去掉", "移除")) and stage["objects"]:
        stage["objects"].pop()
    elif any(word in message for word in ("太阳", "日光", "方向光")):
        light = _blank_object("light", "light-" + str(len(stage["objects"]) + 1), "太阳光")
        light["lightType"] = "directional"
        light["transform"]["position"] = [4, 6, 2]
        stage["objects"].append(light)
    elif "聚光" in message:
        light = _blank_object("light", "light-" + str(len(stage["objects"]) + 1), "聚光灯")
        light["lightType"] = "spot"
        light["transform"]["position"] = [0, 3, 2]
        stage["objects"].append(light)
    elif any(word in message for word in ("点光", "灯泡", "灯光")):
        light = _blank_object("light", "light-" + str(len(stage["objects"]) + 1), "点光源")
        light["lightType"] = "point"
        light["transform"]["position"] = [1, 2.2, 1]
        stage["objects"].append(light)
    elif any(word in message for word in ("角色", "人物", "演员")):
        person = _blank_object("character", "actor-" + str(len(stage["objects"]) + 1), "对话角色")
        person["variant"] = "female_low_poly" if "女" in message else "male_basic"
        person["transform"]["position"] = [len(stage["objects"]) * 0.8, 0, 0]
        stage["objects"].append(person)
    else:
        prop = _blank_object("prop", "prop-" + str(len(stage["objects"]) + 1), "参考道具" if has_image else (message.strip()[:24] or "道具"))
        prop["transform"]["position"] = [0, 0, len(stage["objects"]) * 0.4]
        stage["objects"].append(prop)
    mark_identity_stale(stage)
    preview["stage"] = stage
    preview["documentRef"]["revision"] = int(preview["documentRef"].get("revision") or 1) + 1
    return preview


def hex_to_rgb(value):
    color = _color(value)
    number = int(color[1:], 16)
    return {"r": (number >> 16) & 255, "g": (number >> 8) & 255, "b": number & 255}


def rgb_to_hsl(red, green, blue):
    red, green, blue = [channel / 255 for channel in (red, green, blue)]
    high, low = max(red, green, blue), min(red, green, blue)
    lightness = (high + low) / 2
    if high == low:
        hue = saturation = 0
    else:
        delta = high - low
        saturation = delta / (2 - high - low) if lightness > 0.5 else delta / (high + low)
        if high == red:
            hue = ((green - blue) / delta) % 6
        elif high == green:
            hue = (blue - red) / delta + 2
        else:
            hue = (red - green) / delta + 4
        hue *= 60
    return {"h": round(hue, 2), "s": round(saturation * 100, 2), "l": round(lightness * 100, 2)}


def group_objects(document, object_ids, group_id):
    group_id = _key(group_id)
    picked = [item for item in document["objects"] if item["id"] in set(object_ids)]
    if len(picked) < 2:
        fail("打组至少需要两个对象")
    if not any(group["id"] == group_id for group in document["groups"]):
        document["groups"].append({"id": group_id, "name": "分组"})
    for item in picked:
        item["groupId"] = group_id
    return document


def ungroup_objects(document, group_id):
    for item in document["objects"]:
        if item.get("groupId") == group_id:
            item["groupId"] = None
    document["groups"] = [group for group in document["groups"] if group["id"] != group_id]
    return document


def _require_canvas_payload(payload, required, allowed, message, code):
    if not isinstance(payload, dict) or not required.issubset(payload) or set(payload) - allowed or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1:
        fail(message, code)
    _key(payload.get("node_id"))
    _key(payload.get("canvas_id")) if False else None
    from vsc.adapters.persistence.postgres.values import checked_id
    checked_id(payload.get("canvas_id"))


class CanvasDirectorStageService:
    def create_canvas_pic_recognize(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        _require_canvas_payload(payload, {"canvas_id", "canvas_revision", "node_id", "image_node_id", "strategy"},
                                 {"canvas_id", "canvas_revision", "node_id", "image_node_id", "strategy"},
                                 "识图导入需要导演台、图片和插入或覆盖策略", "invalid_director_stage")
        if payload.get("strategy") not in {"insert", "replace"}:
            fail("识图策略仅支持插入或覆盖")
        _key(payload.get("image_node_id"))

        def build(media):
            return analyze_image_bytes(self._read_verified_local_media_bytes(media))

        return self.store.create_canvas_pic_recognize(project_id, payload, build=build, **kw)

    def refresh_canvas_pic_recognize(self, project_id, canvas_id, task_id):
        return self.store.refresh_canvas_pic_recognize(project_id, canvas_id, task_id)

    def list_canvas_pic_recognize(self, project_id, canvas_id, payload):
        return self.store.list_canvas_pic_recognize(project_id, canvas_id, payload or {})

    def delete_canvas_pic_recognize(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or not {"canvas_id", "task_id"}.issubset(payload):
            fail("删除识图记录需要画布和记录标识")
        return self.store.delete_canvas_pic_recognize(project_id, payload, **kw)

    def capture_director_stage_screenshots(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        _require_canvas_payload(payload, {"canvas_id", "canvas_revision", "node_id", "mode", "images"},
                                 {"canvas_id", "canvas_revision", "node_id", "mode", "images"},
                                 "导演台截图需要方位和 PNG 画面", "invalid_director_stage")
        if payload.get("mode") not in SHOT_MODES:
            fail("截图方位须为当前、四方位或十二方位")
        images = payload.get("images")
        expected = SHOT_MODES[payload["mode"]]
        if not isinstance(images, list) or len(images) != expected:
            fail("截图数量与方位模式不符")
        decoded = [decode_png(item, "导演台截图") for item in images]

        def build():
            outputs = []
            for index, blob in enumerate(decoded):
                staged = self.storage.stage_upload(io.BytesIO(blob), f"director-shot-{index + 1}.png")
                outputs.append(self.storage.commit_upload(staged["staged_upload"]))
            return outputs

        return self.store.capture_director_stage_screenshots(project_id, payload, build=build, **kw)

    def generate_director_panorama(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        _require_canvas_payload(payload, {"canvas_id", "canvas_revision", "node_id"},
                                 {"canvas_id", "canvas_revision", "node_id", "source_node_id"},
                                 "全景生成需要导演台节点", "invalid_director_stage")
        if payload.get("source_node_id"):
            _key(payload["source_node_id"])

        def build(media):
            content = self._read_verified_local_media_bytes(media) if media else None
            staged = self.storage.stage_upload(io.BytesIO(compose_equirectangular(content)), "director-panorama.png")
            return self.storage.commit_upload(staged["staged_upload"])

        return self.store.generate_director_panorama(project_id, payload, build=build, **kw)

    def export_director_reference_video(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        _require_canvas_payload(payload, {"canvas_id", "canvas_revision", "node_id", "images", "frame_count"},
                                 {"canvas_id", "canvas_revision", "node_id", "images", "frame_count"},
                                 "参考视频需要帧画面和帧数", "invalid_reference_video")
        frames = expand_frames(payload.get("images"), payload.get("frame_count"))
        encoded, meta = encode_reference_video(frames)
        staged = self.storage.stage_upload(io.BytesIO(encoded), "director-reference.mp4")
        committed = self.storage.commit_upload(staged["staged_upload"])

        def build():
            return committed, meta

        return self.store.export_director_reference_video(project_id, payload, build=build, **kw)

    def edit_preview_scene(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        _require_canvas_payload(payload, {"canvas_id", "canvas_revision", "node_id", "text"},
                                 {"canvas_id", "canvas_revision", "node_id", "text", "reference_media_id"},
                                 "预演改场景需要说明文字", "invalid_director_stage")
        if not isinstance(payload.get("text"), str) or not payload["text"].strip() or len(payload["text"]) > 2000:
            fail("场景修改说明须为 1–2000 字")
        if payload.get("reference_media_id"):
            from vsc.adapters.persistence.postgres.values import checked_id
            checked_id(payload["reference_media_id"])
        return self.store.edit_preview_scene(project_id, payload, **kw)


def bind_canvas_director_stage_service(cls):
    for name in (
        "create_canvas_pic_recognize", "refresh_canvas_pic_recognize", "list_canvas_pic_recognize",
        "delete_canvas_pic_recognize", "capture_director_stage_screenshots", "generate_director_panorama",
        "export_director_reference_video", "edit_preview_scene",
    ):
        setattr(cls, name, getattr(CanvasDirectorStageService, name))
