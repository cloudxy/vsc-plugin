"""Versioned blocking units and independent previs share one bounded scene model."""
from copy import deepcopy
import io
import math
import re

from vsc.assets.resource_service import ResourceError, required

KINDS = {"box", "sphere", "actor", "light", "mesh", "reference"}

POSE_CATALOG = [
    {"id": "stand", "label": "站立"},
    {"id": "walk", "label": "行走"},
    {"id": "run", "label": "奔跑"},
    {"id": "sit", "label": "坐姿"},
    {"id": "crouch", "label": "蹲姿"},
    {"id": "kneel_single", "label": "单膝跪"},
    {"id": "kneel_double", "label": "双膝跪"},
    {"id": "combat", "label": "格斗架势"},
    {"id": "arms_crossed", "label": "抱臂"},
    {"id": "hands_on_hips", "label": "叉腰"},
    {"id": "wave", "label": "挥手"},
    {"id": "reach", "label": "伸手抓取"},
    {"id": "lean", "label": "倚靠"},
    {"id": "look_phone", "label": "低头看手机"},
    {"id": "think", "label": "托腮思考"},
    {"id": "bow", "label": "鞠躬"},
    {"id": "push", "label": "推搡"},
    {"id": "kick", "label": "踢腿"},
    {"id": "throw", "label": "投掷"},
    {"id": "t_pose", "label": "T-Pose 校准"},
    {"id": "arms_up", "label": "举手"},
]
POSES = {item["id"] for item in POSE_CATALOG}

BODY_PRESETS = [
    {"id": "male_basic", "label": "标准男性", "color": "#7fb2ff", "scale": [1.0, 1.0, 1.0]},
    {"id": "female_low_poly", "label": "标准女性", "color": "#ff8fb5", "scale": [0.92, 0.95, 0.92]},
    {"id": "generous", "label": "魁梧丰满", "color": "#f0a35c", "scale": [1.22, 1.02, 1.18]},
    {"id": "robust", "label": "健壮肌肉", "color": "#f25f5c", "scale": [1.16, 1.06, 1.12]},
    {"id": "slender", "label": "修长纤细", "color": "#72d6c9", "scale": [0.86, 1.08, 0.86]},
    {"id": "young", "label": "少年体态", "color": "#8dd36f", "scale": [0.85, 0.88, 0.85]},
    {"id": "children", "label": "儿童体态", "color": "#ffd166", "scale": [0.72, 0.68, 0.72]},
    {"id": "two_heads_tall", "label": "二头身 Q 版", "color": "#b28dff", "scale": [0.78, 0.56, 0.78]},
]
BODY_PRESET_IDS = {item["id"] for item in BODY_PRESETS}

JOINT_GROUPS = [
    {"group": "head", "label": "头部", "axes": [("head_nod", "俯仰"), ("head_tilt", "侧倾"), ("head_turn", "转向")]},
    {"group": "torso", "label": "躯干", "axes": [("torso_pitch", "前倾"), ("torso_roll", "侧弯"), ("torso_yaw", "扭转")]},
    {"group": "left_shoulder", "label": "左肩", "axes": [("left_shoulder_pitch", "抬臂"), ("left_shoulder_roll", "外展"), ("left_shoulder_yaw", "旋臂")]},
    {"group": "right_shoulder", "label": "右肩", "axes": [("right_shoulder_pitch", "抬臂"), ("right_shoulder_roll", "外展"), ("right_shoulder_yaw", "旋臂")]},
    {"group": "elbows", "label": "双肘", "axes": [("left_elbow", "左肘弯曲"), ("right_elbow", "右肘弯曲")]},
    {"group": "hips", "label": "双胯", "axes": [("left_hip_pitch", "左腿抬起"), ("left_hip_roll", "左腿外展"), ("left_hip_yaw", "左腿旋转"), ("right_hip_pitch", "右腿抬起"), ("right_hip_roll", "右腿外展"), ("right_hip_yaw", "右腿旋转")]},
    {"group": "knees", "label": "双膝", "axes": [("left_knee", "左膝弯曲"), ("right_knee", "右膝弯曲")]},
]
ALLOWED_JOINTS = {"left_arm", "right_arm", "head", "torso"} | {axis[0] for g in JOINT_GROUPS for axis in g["axes"]}

CAMERA_PRESETS = [
    {"id": "front_closeup", "label": "正面特写", "offset": [0, 1.55, 1.6], "target_offset": [0, 1.5, 0], "fov": 32, "roll": 0},
    {"id": "front_medium", "label": "正面中景", "offset": [0, 1.35, 3.2], "target_offset": [0, 1.2, 0], "fov": 42, "roll": 0},
    {"id": "front_wide", "label": "正面全景", "offset": [0, 1.8, 6.5], "target_offset": [0, 1.0, 0], "fov": 50, "roll": 0},
    {"id": "back_medium", "label": "背面中景", "offset": [0, 1.45, -3.4], "target_offset": [0, 1.2, 0], "fov": 42, "roll": 0},
    {"id": "ots_left", "label": "过肩镜头", "offset": [-0.85, 1.55, -2.2], "target_offset": [0.25, 1.35, 1.5], "fov": 38, "roll": 0},
    {"id": "ots_right", "label": "过肩镜头（右）", "offset": [0.85, 1.55, -2.2], "target_offset": [-0.25, 1.35, 1.5], "fov": 38, "roll": 0},
    {"id": "side_close", "label": "侧面近景", "offset": [2.2, 1.45, 0.2], "target_offset": [0, 1.4, 0], "fov": 36, "roll": 0},
    {"id": "side_tracking", "label": "侧面跟拍", "offset": [4.2, 1.3, 0.6], "target_offset": [0, 1.1, 0], "fov": 45, "roll": 0},
    {"id": "low_angle", "label": "低角度仰拍", "offset": [0.6, 0.35, 2.8], "target_offset": [0, 1.45, 0], "fov": 48, "roll": 0},
    {"id": "low_wide", "label": "低角度广角", "offset": [1.2, 0.3, 3.8], "target_offset": [0, 1.2, 0], "fov": 68, "roll": 0},
    {"id": "high_45", "label": "45° 俯拍", "offset": [3.5, 4.6, 3.8], "target_offset": [0, 0.9, 0], "fov": 45, "roll": 0},
    {"id": "high_wide", "label": "俯拍全景", "offset": [0, 6.8, 5.6], "target_offset": [0, 0.6, 0], "fov": 54, "roll": 0},
    {"id": "birds_eye", "label": "鸟瞰", "offset": [0, 9.5, 0.2], "target_offset": [0, 0, 0], "fov": 56, "roll": 0},
    {"id": "dutch_angle", "label": "荷兰角", "offset": [1.4, 1.2, 3.0], "target_offset": [0, 1.3, 0], "fov": 44, "roll": 18},
]


def invalid(message):
    raise ResourceError(message, "invalid_spatial_scene")


def number(value, minimum=-10000, maximum=10000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum or not math.isfinite(value):
        invalid("场景数值不是范围内的有限数字")
    return float(value)


def vector(value, default, minimum=-10000, maximum=10000):
    value = default if value is None else value
    if not isinstance(value, list) or len(value) != 3:
        invalid("位置、旋转、缩放必须各有三个数值")
    return [number(x, minimum, maximum) for x in value]


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        invalid("对象和机位需要稳定标识")
    return value


def label(value, default):
    value = default if value is None else value
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        invalid("名称须为 1–200 字")
    return value.strip()


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        invalid("颜色需要六位十六进制值")
    return value.lower()


def frames(value, duration, camera=False):
    if not isinstance(value, list) or len(value) > 50:
        invalid("每个对象最多 50 个关键帧")
    result, times = [], set()
    allowed = {"time", "position", "rotation", "target"} if camera else {"time", "position", "rotation"}
    for frame in value:
        if not isinstance(frame, dict) or set(frame) - allowed or "position" not in frame:
            invalid("关键帧需要时刻与位置")
        instant = number(frame.get("time"), 0, duration)
        if instant in times:
            invalid("关键帧时刻不能重复")
        times.add(instant)
        row = {"time": instant, "position": vector(frame["position"], [0, 0, 0])}
        if "rotation" in frame:
            row["rotation"] = vector(frame["rotation"], [0, 0, 0], -3600, 3600)
        if camera and "target" in frame:
            row["target"] = vector(frame["target"], [0, 1, 0])
        result.append(row)
    return sorted(result, key=lambda row: row["time"])


def normalize_scene(value):
    scene_fields = {"objects", "cameras", "duration", "width", "height", "background", "panorama_media_id", "sphere_radius"}
    if not isinstance(value, dict) or set(value) - scene_fields:
        invalid("场景需要对象、机位与画幅设置")
    duration = number(value.get("duration", 5), .1, 30)
    width, height = value.get("width", 960), value.get("height", 540)
    if type(width) is not int or type(height) is not int or min(width, height) < 128 or max(width, height) > 1920 or width * height > 2073600 or width % 2 or height % 2:
        invalid("画幅为 128–1920 的偶数尺寸，最多 2073600 像素")
    objects, cameras = value.get("objects", []), value.get("cameras", [])
    if not isinstance(objects, list) or len(objects) > 64 or not isinstance(cameras, list) or not 1 <= len(cameras) <= 8:
        invalid("场景最多 64 个对象，需要 1–8 个机位")
    output, keys, vertices, faces_count = [], set(), 0, 0
    for item in objects:
        if not isinstance(item, dict) or set(item) - {"id", "name", "kind", "position", "rotation", "scale", "color", "visible", "locked", "pose", "joints", "keyframes", "geometry", "media_id", "animation", "body_preset"}:
            invalid("对象包含未支持字段")
        identity, kind = key(item.get("id")), item.get("kind")
        if identity in keys or not isinstance(kind, str) or kind not in KINDS:
            invalid("对象标识重复或类型未支持")
        keys.add(identity)
        for flag in ("visible", "locked"):
            if flag in item and not isinstance(item[flag], bool):
                invalid("隐藏和锁定必须为布尔值")
        pose = item.get("pose", "stand")
        if not isinstance(pose, str) or pose not in POSES:
            invalid("姿态未支持")
        joints = item.get("joints", {})
        if not isinstance(joints, dict) or set(joints) - ALLOWED_JOINTS:
            invalid("人物关节包含未支持的轴向字段")
        row = {"id": identity, "name": label(item.get("name"), kind), "kind": kind,
            "position": vector(item.get("position"), [0, 0, 0]), "rotation": vector(item.get("rotation"), [0, 0, 0], -3600, 3600),
            "scale": vector(item.get("scale"), [1, 1, 1], .01, 100), "color": color(item.get("color", "#65a4c4")),
            "visible": item.get("visible", True), "locked": item.get("locked", False), "pose": pose,
            "joints": {name: number(angle, -180, 180) for name, angle in joints.items()},
            "keyframes": frames(item.get("keyframes", []), duration), "media_id": item.get("media_id") or None}
        if "body_preset" in item and item["body_preset"] is not None:
            if kind != "actor" or item["body_preset"] not in BODY_PRESET_IDS:
                invalid("角色体态预设仅支持人物对象且须在预设列表中")
            row["body_preset"] = item["body_preset"]
        geometry = item.get("geometry")
        if kind == "mesh" and isinstance(geometry, dict) and "source_sha256" in geometry:
            if set(geometry) != {"source_sha256", "scene"} or not isinstance(geometry["source_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", geometry["source_sha256"]):
                invalid("GLB 引用需要固定媒体摘要与场景索引")
            if not row["media_id"] or type(geometry["scene"]) is not int or not 0 <= geometry["scene"] < 16:
                invalid("GLB 引用需要原项目媒体及有效场景索引")
            animation = item.get("animation", {})
            if not isinstance(animation, dict) or set(animation) - {"clip", "speed", "offset", "loop"}:
                invalid("GLB 动画设置无效")
            clip = animation.get("clip")
            if clip is not None and (type(clip) is not int or not 0 <= clip < 16):
                invalid("GLB 动画索引无效")
            if type(animation.get("loop", False)) is not bool:
                invalid("循环动画需要布尔值")
            row["geometry"] = dict(geometry)
            row["animation"] = {"clip": clip, "speed": number(animation.get("speed", 1), 0, 4),
                "offset": number(animation.get("offset", 0), -3600, 3600), "loop": animation.get("loop", False)}
        elif kind == "mesh":
            if not isinstance(geometry, dict) or set(geometry) != {"vertices", "triangles"}:
                invalid("网格需要顶点与三角面")
            points, triangles = geometry["vertices"], geometry["triangles"]
            if not isinstance(points, list) or not 3 <= len(points) <= 6000 or not isinstance(triangles, list) or not 1 <= len(triangles) <= 12000:
                invalid("导入单网格最多 6000 顶点和 12000 三角面")
            points = [vector(point, [0, 0, 0]) for point in points]
            if any(not isinstance(t, list) or len(t) != 3 or any(type(i) is not int or not 0 <= i < len(points) for i in t) for t in triangles):
                invalid("三角面索引越界")
            vertices += len(points)
            faces_count += len(triangles)
            if vertices > 12000 or faces_count > 24000:
                invalid("当前场景导入网格累计最多 12000 顶点、24000 三角面")
            row["geometry"] = {"vertices": points, "triangles": deepcopy(triangles)}
        elif geometry is not None:
            invalid("只有网格对象可以携带几何数据")
        if "animation" in item and not (kind == "mesh" and "source_sha256" in row.get("geometry", {})):
            invalid("动画片段只用于 GLB 媒体引用")
        output.append(row)
    views = []
    camera_keys = set()
    for item in cameras:
        if not isinstance(item, dict) or set(item) - {"id", "name", "position", "target", "fov", "roll", "keyframes"}:
            invalid("机位字段不正确")
        identity = key(item.get("id"))
        if identity in camera_keys:
            invalid("机位标识重复")
        camera_keys.add(identity)
        position, target = vector(item.get("position"), [6, 4, 8]), vector(item.get("target"), [0, 1, 0])
        if sum((a - b)**2 for a, b in zip(position, target)) < .0001:
            invalid("机位与注视目标不能重合")
        cam_row = {"id": identity, "name": label(item.get("name"), "机位"), "position": position, "target": target,
            "fov": number(item.get("fov", 45), 10, 120), "keyframes": frames(item.get("keyframes", []), duration, True)}
        if "roll" in item and item["roll"] is not None:
            cam_row["roll"] = number(item["roll"], -90, 90)
        views.append(cam_row)
    result = {"objects": output, "cameras": views, "duration": duration, "width": width, "height": height,
        "background": color(value.get("background", "#dce6ee"))}
    if value.get("panorama_media_id"):
        result["panorama_media_id"] = key(value["panorama_media_id"])
    if "sphere_radius" in value and value["sphere_radius"] is not None:
        result["sphere_radius"] = number(value["sphere_radius"], 10, 200)
    return result


def default_scene():
    return normalize_scene({"objects": [{"id": "floor", "name": "地面", "kind": "box", "position": [0, -.1, 0], "scale": [10, .2, 10], "color": "#b6c5b5"},
        {"id": "actor", "name": "人物", "kind": "actor", "position": [-1, 0, 0]},
        {"id": "bench", "name": "长椅", "kind": "box", "position": [1, .5, 0], "scale": [2, 1, .7], "color": "#ac815e"}],
        "cameras": [{"id": "camera-a", "name": "机位 A", "position": [6, 4, 8], "target": [0, 1, 0]},
            {"id": "camera-b", "name": "机位 B", "position": [-5, 2, 3], "target": [0, 1, 0]}]})


def _segment_intersects_aabb(start, end, box_min, box_max):
    tmin, tmax = 0.04, 0.96
    for axis in range(3):
        delta = end[axis] - start[axis]
        if abs(delta) < 1e-8:
            if start[axis] < box_min[axis] or start[axis] > box_max[axis]:
                return False
        else:
            inv = 1.0 / delta
            t1 = (box_min[axis] - start[axis]) * inv
            t2 = (box_max[axis] - start[axis]) * inv
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return False
    return True


def check_camera_occlusion(document, camera_id, target_object_id=None):
    cam = next((c for c in document["cameras"] if c["id"] == camera_id), document["cameras"][0])
    actors = [o for o in document["objects"] if o.get("visible", True) and o["kind"] == "actor"]
    if target_object_id:
        actors = [o for o in document["objects"] if o["id"] == target_object_id and o.get("visible", True)] or actors
    if not actors:
        actors = [o for o in document["objects"] if o.get("visible", True) and o["kind"] not in {"light", "reference"} and o["id"] != "floor"][:1]
    blockers = [
        o for o in document["objects"]
        if o.get("visible", True)
        and o["kind"] in {"box", "sphere", "mesh"}
        and o["id"] != "floor"
        and o["scale"][1] > 0.35
        and o["id"] not in {a["id"] for a in actors}
    ]
    occluded_ids = []
    for actor in actors:
        chest = [actor["position"][0], actor["position"][1] + 1.2 * actor["scale"][1], actor["position"][2]]
        for obs in blockers:
            half = [0.5 * abs(s) for s in obs["scale"]]
            bmin = [obs["position"][i] - half[i] for i in range(3)]
            bmax = [obs["position"][i] + half[i] for i in range(3)]
            if _segment_intersects_aabb(cam["position"], chest, bmin, bmax):
                occluded_ids.append(actor["id"])
                break
    return {
        "occluded": bool(occluded_ids),
        "occluded_object_ids": occluded_ids,
        "warning": "核心对象仍有遮挡，请检查场景或手动调整机位" if occluded_ids else None,
    }


def auto_frame_camera(document, camera_id, target_object_id=None):
    doc = normalize_scene(document)
    cam = next((c for c in doc["cameras"] if c["id"] == camera_id), None)
    if cam is None:
        invalid("所选机位不属于当前场景")
    subjects = [o for o in doc["objects"] if o.get("visible", True) and o["kind"] == "actor"]
    if target_object_id:
        picked = [o for o in doc["objects"] if o["id"] == target_object_id and o.get("visible", True)]
        if picked:
            subjects = picked
    if not subjects:
        subjects = [o for o in doc["objects"] if o.get("visible", True) and o["kind"] not in {"light", "reference"} and o["id"] != "floor"] or doc["objects"][:1]
    cx = sum(o["position"][0] for o in subjects) / len(subjects)
    cy = sum(o["position"][1] + (1.15 * o["scale"][1] if o["kind"] == "actor" else 0.5 * o["scale"][1]) for o in subjects) / len(subjects)
    cz = sum(o["position"][2] for o in subjects) / len(subjects)
    span = max(
        1.4,
        max(
            math.hypot(o["position"][0] - cx, o["position"][2] - cz) + max(o["scale"][0], o["scale"][1])
            for o in subjects
        ) * 1.65,
    )
    candidates = [
        [cx + span * 0.35, cy + 0.35, cz + span * 1.45],
        [cx - span * 0.45, cy + 0.4, cz + span * 1.45],
        [cx + span * 0.9, cy + 0.55, cz + span * 1.15],
        [cx - span * 0.9, cy + 0.55, cz + span * 1.15],
        [cx, cy + 1.25, cz + span * 1.6],
    ]
    chosen_pos = candidates[0]
    chosen_check = None
    for pos in candidates:
        cam["position"] = [round(v, 3) for v in pos]
        cam["target"] = [round(cx, 3), round(cy, 3), round(cz, 3)]
        check = check_camera_occlusion(doc, camera_id, target_object_id)
        chosen_pos = cam["position"]
        chosen_check = check
        if not check["occluded"]:
            break
    cam["position"] = chosen_pos
    cam["target"] = [round(cx, 3), round(cy, 3), round(cz, 3)]
    return {"document": doc, "camera": cam, **chosen_check}


class SpatialSceneService:
    def create_spatial_plan_task(self,p,payload,**kw):return self._write('create_spatial_plan_task',p,payload,**kw)
    def get_spatial_plan_task(self,p,identifier):return self.store.get_spatial_plan_task(p,identifier)
    def execute_spatial_plan_task(self,p,identifier):
        from vsc.production.spatial_planner import execute
        return execute(self,p,identifier)
    def decide_spatial_plan_task(self,p,payload,**kw):return self._write('decide_spatial_plan_task',p,payload,**kw)

    def list_spatial_scenes(self, project_id, mode=None):
        return self.store.list_spatial_scenes(project_id, mode)

    def get_spatial_scene(self, project_id, scene_id, version=None):
        result = self.store.get_spatial_scene(project_id, scene_id, version)
        # Keep the saved document readable even if a source location was lost.
        result["model_catalog"] = self.spatial_model_catalog(project_id, result["document"])
        return result

    def spatial_model_catalog(self, project_id, document):
        result = {}
        for item in document["objects"]:
            geometry = item.get("geometry", {})
            if "source_sha256" not in geometry or geometry["source_sha256"] in result:
                continue
            try:
                model = self._spatial_model(project_id, item)
                result[geometry["source_sha256"]] = {"clips": [{"id": i, "name": a["name"], "duration": a["duration"]} for i,a in enumerate(model["animations"])],
                    "scenes": [{"id": i, "name": str(s.get("name", "场景 %d" % (i+1)))[:200]} for i,s in enumerate(model["scenes"])]}
            except ResourceError as error:
                result[geometry["source_sha256"]] = {"error": str(error)}
        return result

    def _spatial_model(self, project_id, item):
        from vsc.post.spatial_gltf import decode_glb, MAX_BYTES
        media = self.store.get_media(project_id, item["media_id"])
        if media["sha256"] != item["geometry"]["source_sha256"]:
            raise ResourceError("GLB 来源摘要与固定场景不符", "spatial_model_sha_mismatch")
        if self.storage is None:
            raise ResourceError("未配置受控媒体存储", "storage_unavailable")
        self._verify_media(project_id, item["media_id"])
        location = next((l for l in media["locations"] if l["storage"] == "local" and l.get("available")), None)
        if not location:
            raise ResourceError("GLB 来源字节不可读取；原场景保留", "media_unavailable")
        if media.get("size_bytes", 0) and media["size_bytes"] > MAX_BYTES:
            raise ResourceError("GLB 文件超过 20 MiB", "invalid_spatial_glb")
        return decode_glb(self.storage.read(location["object_key"], media["sha256"]))

    def prepare_spatial_scene(self, project_id, document):
        """Resolve authorized original media once; decoded data never enters SQL."""
        from PIL import Image
        from vsc.post.spatial_gltf import sample_model
        prepared = deepcopy(document);models = {};vertices=triangles=pixels=0
        if prepared.get("panorama_media_id"):
            pano_media = self.store.get_media(project_id, prepared["panorama_media_id"])
            if pano_media["modality"] != "image":
                raise ResourceError("全景环境背景仅支持图片素材", "spatial_media_type")
            if self.storage is not None:
                location = next((l for l in pano_media["locations"] if l["storage"] == "local" and l.get("available")), None)
                if location:
                    raw_pano = self.storage.read(location["object_key"], pano_media["sha256"])
                    with Image.open(io.BytesIO(raw_pano)) as opened:
                        sky = opened.convert("RGB")
                        if max(sky.size) > 1024:
                            scale = 1024 / max(sky.size)
                            sky = sky.resize((max(1, round(sky.width * scale)), max(1, round(sky.height * scale))))
                        prepared["_panorama"] = (sky.width, sky.height, sky.tobytes())
        for item in prepared["objects"]:
            geometry = item.get("geometry", {})
            if "source_sha256" in geometry:
                cache_key = (item["media_id"], geometry["source_sha256"])
                if cache_key not in models:
                    models[cache_key] = self._spatial_model(project_id, item)
                    pixels += models[cache_key]["pixel_count"]
                model = models[cache_key];item["_gltf"] = model
                meshes = sample_model(model, geometry["scene"], item["animation"]["clip"], 0)
                vertices += sum(len(m["vertices"]) for m in meshes)
                triangles += sum(len(m["triangles"]) for m in meshes)
            elif item["kind"] == "mesh":
                vertices += len(geometry["vertices"]);triangles += len(geometry["triangles"])
            if vertices > 12000 or triangles > 24000 or pixels > 4*1024*1024:
                raise ResourceError("场景 GLB 累计最多 12000 顶点、24000 面、4 Mi 纹理像素", "spatial_render_limit")
        return prepared

    def auto_frame_spatial_scene(self, project_id, payload):
        self.store.get_project(project_id)
        if not isinstance(payload, dict):
            invalid("需要场景与目标机位")
        return auto_frame_camera(required(payload, "document"), required(payload, "camera_id"), payload.get("target_object_id"))

    def capture_spatial_batch_views(self, project_id, payload, **kw):
        from vsc.post.spatial_export import render_still_png
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) - {"spatial_scene_id", "count", "camera_id", "time", "radius", "elevation"}:
            invalid("多方位批量截图参数无效")
        count = payload.get("count", 4)
        if count not in {4, 12}:
            invalid("多方位截图仅支持四方位 (4) 或十二方位 (12)")
        if self.storage is None:
            raise ResourceError("批量截图需要受控本地媒体存储", "storage_unavailable")
        checked_payload = dict(payload, count=count)
        def render_fn(scene, row, raw_doc):
            base_doc = normalize_scene(raw_doc)
            if not base_doc["objects"]:
                raise ResourceError("空场景不能生成多方位截图", "spatial_viewport_empty")
            cam_id = payload.get("camera_id") or base_doc["cameras"][0]["id"]
            cam = next((c for c in base_doc["cameras"] if c["id"] == cam_id), base_doc["cameras"][0])
            instant = number(payload.get("time", 0), 0, base_doc["duration"])
            target = list(cam["target"])
            dx, dy, dz = cam["position"][0] - target[0], cam["position"][1] - target[1], cam["position"][2] - target[2]
            radius = number(payload.get("radius", max(1.8, math.hypot(dx, dz))), 0.5, 200)
            elevation = number(payload.get("elevation", dy), -50, 100)
            base_angle = math.atan2(dx, dz)
            prepared = self.prepare_spatial_scene(project_id, base_doc)
            labels_4 = ["正面", "右侧", "背面", "左侧"]
            rendered = []
            for idx in range(count):
                deg = round(idx * 360 / count)
                rad = base_angle + math.radians(deg)
                working = deepcopy(prepared)
                wcam = next(c for c in working["cameras"] if c["id"] == cam["id"])
                wcam["position"] = [target[0] + radius * math.sin(rad), target[1] + elevation, target[2] + radius * math.cos(rad)]
                wcam["target"] = target
                png_bytes = render_still_png(working, wcam["id"], instant)
                angle_label = labels_4[idx] if count == 4 else f"{deg}度"
                fname = f"{row['title']}-{count}方位-{idx + 1:02d}-{angle_label}.png"[:200]
                staged = self.storage.stage_upload(io.BytesIO(png_bytes), fname)
                committed = self.storage.commit_upload(staged["staged_upload"])
                rendered.append({
                    "index": idx + 1,
                    "angle_deg": deg,
                    "label": angle_label,
                    "name": fname,
                    "count": count,
                    "committed": committed,
                })
            return rendered
        return self.store.capture_spatial_batch_views(project_id, checked_payload, render_fn=render_fn, **kw)

    def create_spatial_scene(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        document = normalize_scene(payload.get("document", default_scene()))
        self.prepare_spatial_scene(project_id, document)
        return self.store.create_spatial_scene(project_id, dict(payload, document=document), **kw)

    def save_spatial_scene(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        document = normalize_scene(required(payload, "document"))
        self.prepare_spatial_scene(project_id, document)
        return self.store.save_spatial_scene(project_id, dict(payload, document=document), **kw)

    def preview_spatial_scene(self, project_id, payload):
        from vsc.post.spatial_export import render_png
        document = normalize_scene(required(payload, "document"))
        return render_png(self.prepare_spatial_scene(project_id, document), required(payload, "camera_id"), number(payload.get("time", 0), 0, document["duration"]), maximum=640)

    def capture_spatial_viewport(self, project_id, payload):
        """Download the current view. This writes no media, canvas node, or workflow reference."""
        from vsc.post.spatial_export import render_still_png
        self.store.get_project(project_id)
        document = normalize_scene(required(payload, "document"))
        if not document["objects"]:
            raise ResourceError("空场景不能截取当前视窗", "spatial_viewport_empty")
        prepared = self.prepare_spatial_scene(project_id, document)
        return render_still_png(prepared, required(payload, "camera_id"), number(payload.get("time", 0), 0, document["duration"]))

    def import_spatial_glb(self, project_id, media_id):
        media = self.store.get_media(project_id, media_id)
        item = {"id": "import-1", "name": str(media.get("name") or "GLB 模型")[:200], "kind": "mesh", "media_id": media_id,
            "color": "#ffffff", "geometry": {"source_sha256": media["sha256"], "scene": 0}}
        model = self._spatial_model(project_id, item)
        item["geometry"]["scene"] = model["scene"]
        item["animation"] = {"clip": 0 if model["animations"] else None}
        objects = normalize_scene({"objects": [item], "cameras": [{"id":"validate"}]})["objects"]
        return {"objects": objects, "source_media_id": media_id,
            "model_catalog": {media["sha256"]: {"clips": [{"id": i, "name": a["name"], "duration": a["duration"]} for i,a in enumerate(model["animations"])],
                "scenes": [{"id": i, "name": str(s.get("name", "场景 %d" % (i+1)))[:200]} for i,s in enumerate(model["scenes"])]}}}

    def create_spatial_export(self, project_id, payload, **kw):
        return self._write("create_spatial_export", project_id, payload, **kw)

    def get_spatial_export(self, project_id, export_id):
        return self.store.get_spatial_export(project_id, export_id)

    def cancel_spatial_export(self, project_id, payload, **kw):
        return self._write("cancel_spatial_export", project_id, payload, **kw)

    def execute_spatial_export(self, project_id, export_id):
        from vsc.post.spatial_export import SpatialExporter
        return SpatialExporter(self).run(project_id, export_id)

    def spatial_export_to_canvas(self, project_id, payload, **kw):
        return self._write("spatial_export_to_canvas", project_id, payload, **kw)
