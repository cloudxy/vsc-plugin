"""Versioned blocking units and independent previs share one bounded scene model."""
from copy import deepcopy
import math
import re

from vsc.assets.resource_service import ResourceError, required

KINDS = {"box", "sphere", "actor", "light", "mesh", "reference"}
POSES = {"stand", "sit", "crouch", "walk", "arms_up"}


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
    if not isinstance(value, dict) or set(value) - {"objects", "cameras", "duration", "width", "height", "background"}:
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
        if not isinstance(item, dict) or set(item) - {"id", "name", "kind", "position", "rotation", "scale", "color", "visible", "locked", "pose", "joints", "keyframes", "geometry", "media_id", "animation"}:
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
        if not isinstance(joints, dict) or set(joints) - {"left_arm", "right_arm", "head", "torso"}:
            invalid("人物关节只支持双臂、头部与躯干角度")
        row = {"id": identity, "name": label(item.get("name"), kind), "kind": kind,
            "position": vector(item.get("position"), [0, 0, 0]), "rotation": vector(item.get("rotation"), [0, 0, 0], -3600, 3600),
            "scale": vector(item.get("scale"), [1, 1, 1], .01, 100), "color": color(item.get("color", "#65a4c4")),
            "visible": item.get("visible", True), "locked": item.get("locked", False), "pose": pose,
            "joints": {name: number(angle, -180, 180) for name, angle in joints.items()},
            "keyframes": frames(item.get("keyframes", []), duration), "media_id": item.get("media_id") or None}
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
        if not isinstance(item, dict) or set(item) - {"id", "name", "position", "target", "fov", "keyframes"}:
            invalid("机位字段不正确")
        identity = key(item.get("id"))
        if identity in camera_keys:
            invalid("机位标识重复")
        camera_keys.add(identity)
        position, target = vector(item.get("position"), [6, 4, 8]), vector(item.get("target"), [0, 1, 0])
        if sum((a - b)**2 for a, b in zip(position, target)) < .0001:
            invalid("机位与注视目标不能重合")
        views.append({"id": identity, "name": label(item.get("name"), "机位"), "position": position, "target": target,
            "fov": number(item.get("fov", 45), 10, 120), "keyframes": frames(item.get("keyframes", []), duration, True)})
    return {"objects": output, "cameras": views, "duration": duration, "width": width, "height": height,
        "background": color(value.get("background", "#dce6ee"))}


def default_scene():
    return normalize_scene({"objects": [{"id": "floor", "name": "地面", "kind": "box", "position": [0, -.1, 0], "scale": [10, .2, 10], "color": "#b6c5b5"},
        {"id": "actor", "name": "人物", "kind": "actor", "position": [-1, 0, 0]},
        {"id": "bench", "name": "长椅", "kind": "box", "position": [1, .5, 0], "scale": [2, 1, .7], "color": "#ac815e"}],
        "cameras": [{"id": "camera-a", "name": "机位 A", "position": [6, 4, 8], "target": [0, 1, 0]},
            {"id": "camera-b", "name": "机位 B", "position": [-5, 2, 3], "target": [0, 1, 0]}]})


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
        from vsc.post.spatial_gltf import sample_model
        prepared = deepcopy(document);models = {};vertices=triangles=pixels=0
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
