"""Canvas core local image operations, agent session state/queue, and camera motion templates."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, ResourceError
from . import schema as S
from .values import checked_id, clean, new_id


BUILTIN_CAMERA_MOTIONS = (
    {"id": "builtin-push-in", "name": "推进镜头 Push In", "prompt_fragment": "摄影机平稳缓慢向前推进，聚焦主体细节", "horizontal_pan": 0, "vertical_tilt": 0, "zoom_delta": 50, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-pull-out", "name": "拉远镜头 Pull Out", "prompt_fragment": "摄影机平稳向后拉远，逐渐展现完整环境空间", "horizontal_pan": 0, "vertical_tilt": 0, "zoom_delta": -50, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-truck-left", "name": "左移镜头 Truck Left", "prompt_fragment": "摄影机沿水平轨道向左平移跟拍", "horizontal_pan": -55, "vertical_tilt": 0, "zoom_delta": 0, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-truck-right", "name": "右移镜头 Truck Right", "prompt_fragment": "摄影机沿水平轨道向右平移跟拍", "horizontal_pan": 55, "vertical_tilt": 0, "zoom_delta": 0, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-tilt-up", "name": "上摇镜头 Tilt Up", "prompt_fragment": "摄影机由低向高缓慢仰摇，凸显空间纵深与气势", "horizontal_pan": 0, "vertical_tilt": 45, "zoom_delta": 10, "roll_deg": 0, "speed_preset": "slow", "builtin": True},
    {"id": "builtin-tilt-down", "name": "下摇镜头 Tilt Down", "prompt_fragment": "摄影机由高处俯摇下降，自然落幅至人物主体", "horizontal_pan": 0, "vertical_tilt": -45, "zoom_delta": 10, "roll_deg": 0, "speed_preset": "slow", "builtin": True},
    {"id": "builtin-orbit", "name": "环绕运镜 Orbit", "prompt_fragment": "摄影机围绕主体呈圆弧轨迹平滑环绕拍摄", "horizontal_pan": 65, "vertical_tilt": 10, "zoom_delta": 15, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-handheld", "name": "手持呼吸跟拍 Handheld", "prompt_fragment": "电影感手持摄影机轻微呼吸晃动，贴近角色跟拍", "horizontal_pan": 12, "vertical_tilt": 8, "zoom_delta": 20, "roll_deg": 4, "speed_preset": "fast", "builtin": True},
)

_IMAGE_EDIT_GAP_LABELS = {
    "missing_bytes": "素材文件不可用",
    "rights_unknown_or_restricted": "素材权利待确认或受限制",
    "rights_expired": "素材授权已到期",
    "rights_scope_mismatch": "素材授权不包含图片编辑",
    "media_deprecated": "素材已停用",
    "technical_check_failed": "素材技术检查未通过",
    "library_retired": "素材库条目已停用",
    "library_rights_revoked": "素材库许可已撤回",
    "library_license_expired": "素材库许可已到期",
    "library_purpose_not_allowed": "素材库许可不包含图片编辑",
    "library_source_rights_changed": "素材库来源权利已变化",
    "copy_source_rights_restricted": "来源权利已受限制",
    "copy_source_rights_expired": "来源授权已到期",
    "copy_source_rights_unknown": "来源权利待确认",
    "copy_source_rights_scope_mismatch": "来源授权不包含图片编辑",
}


class CanvasCoreOpsMixin:
    def _verified_canvas_image_source(self, conn, p, document, node_id, action_label):
        source = next((node for node in document["nodes"] if node["id"] == node_id), None)
        if not source or source["type"] != "image" or not source["media_id"]:
            raise ResourceError("请选择已固定图片的画布节点", "canvas_image_source_required")
        media, gaps = self._usable(conn, p, source["media_id"], "image_edit")
        gaps = [gap for gap in gaps if gap != "technical_check_missing"]
        if gaps:
            reason = "、".join(_IMAGE_EDIT_GAP_LABELS.get(gap, "来源或许可不可用") for gap in gaps)
            raise ResourceError(f"原图当前不可{action_label}：{reason}", "canvas_image_source_unusable")
        if media["modality"] != "image":
            raise ResourceError(f"{action_label}只接受图片", "canvas_image_source_required")
        return source, media

    @staticmethod
    def _assert_complete_image_probe(result, error_code):
        probe = result.get("probe", {})
        if (
            result.get("modality") != "image"
            or probe.get("sha256") != result.get("sha256")
            or probe.get("decode", {}).get("status") != "passed"
            or probe.get("decode", {}).get("mode") != "complete"
        ):
            raise ResourceError("派生图片缺少固定字节的完整解码检查", error_code)
        return probe

    def transform_canvas_image(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_image_source(conn, p, document, payload["node_id"], "编辑")
            in_place = bool(payload.get("in_place", False))
            if not in_place and (len(document["nodes"]) + 1 > 200 or len(document["edges"]) + 1 > 800):
                raise ResourceError("编辑输出超过画布节点或连线数量上限", "canvas_transform_capacity")
            result, normalized_settings, title_suffix = build(media)
            probe = self._assert_complete_image_probe(result, "canvas_transform_output_unverified")
            registered = self._register_media(
                conn,
                project,
                {
                    **result,
                    "rights": "unknown",
                    "source": {
                        "kind": "canvas-image-transform",
                        "content": {
                            "canvas_version_id": version["id"],
                            "source_media_id": media["id"],
                            "source_sha256": media["sha256"],
                            "operation": payload["operation"],
                            "settings": normalized_settings,
                        },
                    },
                },
                actor,
            )
            self.record_media_check(
                p,
                {
                    "media_id": registered["id"],
                    "blob_sha256": registered["sha256"],
                    "checker": "canvas-transform-output-decode",
                    "criteria_version": "1",
                    "outcome": "pass",
                    "report": {"source": "local-storage-complete-decode", "probe": probe},
                },
                actor=actor,
                _transaction=(conn, project),
                **kw,
            )
            group_name = payload.get("group_name") if payload.get("group_name") is not None else source.get("group", "")
            if in_place:
                source["media_id"] = registered["id"]
                source["job_id"] = None
                if group_name:
                    source["group"] = group_name
                node_ids = [source["id"]]
            else:
                key = "transform-" + new_id()
                node_ids = [key]
                document["nodes"].append({
                    "id": key,
                    "type": "image",
                    "title": f"{source['title']} · {title_suffix}"[:200],
                    "x": min(100000, source["x"] + 300),
                    "y": source["y"],
                    "text": "",
                    "params": {},
                    "group": group_name or "",
                    "media_id": registered["id"],
                    "job_id": None,
                })
                document["edges"].append({
                    "id": "derive-" + new_id(),
                    "source": source["id"],
                    "target": key,
                    "port": "derived_from",
                })
            operation = self.create_media_operation(
                p,
                {
                    "operation_type": "image-canvas-transform",
                    "recipe_version": "canvas-transform/v1",
                    "tool": "vsc-local-image-transform",
                    "tool_version": "1",
                    "parameters": {
                        "canvas_version_id": version["id"],
                        "source_sha256": media["sha256"],
                        "operation": payload["operation"],
                        "settings": normalized_settings,
                        "output_count": 1,
                    },
                    "inputs": [{"media_id": media["id"], "role": "source"}],
                    "outputs": [{"media_id": registered["id"], "role": "transformed"}],
                },
                actor=actor,
                _transaction=(conn, project),
                **kw,
            )
            saved = self._insert_canvas_version(
                conn, project, canvas, {"title": version["title"], "document": document}, actor, version
            )
            return dict(saved, node_ids=node_ids, media_ids=[registered["id"]], operation_id=operation["id"])

        return self._mutate(project_id, "transform_canvas_image", payload, actor=actor, callback=work, **kw)

    def capture_canvas_panorama(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_image_source(conn, p, document, payload["node_id"], "全景截图")
            expected_count = {"current": 1, "four": 4, "twelve": 12}[payload["mode"]]
            if len(document["nodes"]) + expected_count > 200 or len(document["edges"]) + expected_count > 800:
                raise ResourceError("全景截图数量超过画布节点或连线数量上限", "canvas_panorama_capacity")
            prepared = build(media)
            if len(prepared) != expected_count:
                raise ResourceError("全景截图输出数量与所选模式不符", "canvas_panorama_output_mismatch")
            group_name = payload.get("group_name") if payload.get("group_name") is not None else source.get("group", "")
            if payload["mode"] in {"four", "twelve"} and not str(group_name or "").strip():
                group_name = "全景截图"
            node_ids, media_ids = [], []
            for index, item in enumerate(prepared):
                result, view_meta = item["staged"], item["view"]
                probe = self._assert_complete_image_probe(result, "canvas_panorama_output_unverified")
                registered = self._register_media(
                    conn,
                    project,
                    {
                        **result,
                        "rights": "unknown",
                        "source": {
                            "kind": "canvas-panorama-capture",
                            "content": {
                                "canvas_version_id": version["id"],
                                "source_media_id": media["id"],
                                "source_sha256": media["sha256"],
                                "mode": payload["mode"],
                                "yaw": view_meta["yaw"],
                                "pitch": view_meta["pitch"],
                                "fov": view_meta["fov"],
                                "label": view_meta["label"],
                            },
                        },
                    },
                    actor,
                )
                self.record_media_check(
                    p,
                    {
                        "media_id": registered["id"],
                        "blob_sha256": registered["sha256"],
                        "checker": "canvas-panorama-output-decode",
                        "criteria_version": "1",
                        "outcome": "pass",
                        "report": {"source": "local-storage-complete-decode", "probe": probe},
                    },
                    actor=actor,
                    _transaction=(conn, project),
                    **kw,
                )
                key = "pano-" + new_id()
                node_ids.append(key)
                media_ids.append(registered["id"])
                capture_meta = {
                    "baseYaw": payload["yaw"],
                    "basePitch": payload["pitch"],
                    "offsetYaw": view_meta.get("offset", 0),
                    "yaw": view_meta["yaw"],
                    "pitch": view_meta["pitch"],
                    "fov": view_meta["fov"],
                    "mode": payload["mode"],
                    "index": index,
                    "width": view_meta.get("width"),
                    "height": view_meta.get("height"),
                    "label": view_meta["label"],
                }
                document["nodes"].append({
                    "id": key,
                    "type": "image",
                    "title": f"{source['title']} · {view_meta['label']}"[:200],
                    "x": min(100000, source["x"] + 320 + (index % 4) * 280),
                    "y": min(100000, source["y"] + (index // 4) * 230),
                    "text": "",
                    "params": {"panoramaCapture": json.dumps(capture_meta, ensure_ascii=False, separators=(",", ":"))},
                    "group": group_name or "",
                    "media_id": registered["id"],
                    "job_id": None,
                })
                document["edges"].append({
                    "id": "derive-" + new_id(),
                    "source": source["id"],
                    "target": key,
                    "port": "derived_from",
                })
            operation = self.create_media_operation(
                p,
                {
                    "operation_type": "image-panorama-capture",
                    "recipe_version": "canvas-panorama/v1",
                    "tool": "vsc-local-panorama-capture",
                    "tool_version": "1",
                    "parameters": {
                        "canvas_version_id": version["id"],
                        "source_sha256": media["sha256"],
                        "mode": payload["mode"],
                        "yaw": payload["yaw"],
                        "pitch": payload["pitch"],
                        "fov": payload["fov"],
                        "output_count": expected_count,
                    },
                    "inputs": [{"media_id": media["id"], "role": "source"}],
                    "outputs": [{"media_id": mid, "role": "view"} for mid in media_ids],
                },
                actor=actor,
                _transaction=(conn, project),
                **kw,
            )
            saved = self._insert_canvas_version(
                conn, project, canvas, {"title": version["title"], "document": document}, actor, version
            )
            return dict(saved, node_ids=node_ids, media_ids=media_ids, operation_id=operation["id"])

        return self._mutate(project_id, "capture_canvas_panorama", payload, actor=actor, callback=work, **kw)

    def _place_derived_images(self, conn, project, canvas, version, document, source, media, prepared, *, actor, kw, group_name, operation_type, tool, parameters, error_code):
        p = project["id"]
        if len(document["nodes"]) + len(prepared) > 200 or len(document["edges"]) + len(prepared) > 800:
            raise ResourceError("派生图片超过画布节点或连线数量上限", error_code)
        node_ids, media_ids = [], []
        for index, item in enumerate(prepared):
            result = item["staged"]
            probe = self._assert_complete_image_probe(result, error_code)
            registered = self._register_media(
                conn, project,
                {**result, "rights": "unknown", "source": {"kind": operation_type, "content": {
                    "canvas_version_id": version["id"], "source_media_id": media["id"] if media else None,
                    "source_sha256": media["sha256"] if media else None, "role": item.get("role"), "label": item.get("label"),
                }}},
                actor,
            )
            self.record_media_check(p, {
                "media_id": registered["id"], "blob_sha256": registered["sha256"],
                "checker": operation_type, "criteria_version": "1", "outcome": "pass",
                "report": {"source": "local-storage-complete-decode", "probe": probe},
            }, actor=actor, _transaction=(conn, project), **kw)
            key = item.get("key_prefix", "layer") + "-" + new_id()
            node_ids.append(key)
            media_ids.append(registered["id"])
            document["nodes"].append({
                "id": key, "type": "image",
                "title": str(item.get("title") or "派生图片")[:200],
                "x": min(100000, (source["x"] if source else 80) + 300 + (index % 4) * 280),
                "y": min(100000, (source["y"] if source else 80) + (index // 4) * 230),
                "text": "", "params": item.get("params") or {}, "group": group_name or "",
                "media_id": registered["id"], "job_id": None,
            })
            if source:
                document["edges"].append({"id": "derive-" + new_id(), "source": source["id"], "target": key, "port": "derived_from"})
        op_params = dict(parameters or {})
        if media:
            op_params.setdefault("source_sha256", media["sha256"])
        op_params.setdefault("output_count", len(media_ids))
        operation = self.create_media_operation(p, {
            "operation_type": operation_type, "recipe_version": operation_type + "/v1",
            "tool": tool, "tool_version": "1", "parameters": op_params,
            "inputs": [{"media_id": media["id"], "role": "source"}] if media else [],
            "outputs": [{"media_id": mid, "role": "derived"} for mid in media_ids],
        }, actor=actor, _transaction=(conn, project), **kw)
        saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
        return dict(saved, node_ids=node_ids, media_ids=media_ids, operation_id=operation["id"], credits=0, charged=False)

    def separate_canvas_layers(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_image_source(conn, p, document, payload["node_id"], "图层分离")
            prepared = build(media)
            snapshot = prepared["snapshot"]
            rows = []
            for item in prepared["foregrounds"]:
                rows.append({"staged": item["staged"], "role": "foreground", "label": item["label"], "title": item["title"], "key_prefix": "layer", "params": {"layer_separation": snapshot, "layer_role": "foreground", "layer_id": item["id"]}})
            rows.append({"staged": prepared["background"]["staged"], "role": "background", "label": "背景修补", "title": prepared["background"]["title"], "key_prefix": "layer", "params": {"layer_separation": snapshot, "layer_role": "background"}})
            return self._place_derived_images(
                conn, project, canvas, version, document, source, media, rows, actor=actor, kw=kw,
                group_name=payload.get("group_name") or source.get("group") or "图层分离",
                operation_type="image-layer-separation", tool="vsc-local-layer-separation",
                parameters={"canvas_version_id": version["id"], "source_sha256": media["sha256"], "selection_count": len(prepared["foregrounds"]), "credits": 0},
                error_code="canvas_layer_output_unverified",
            )
        return self._mutate(project_id, "separate_canvas_layers", payload, actor=actor, callback=work, **kw)

    def compose_canvas_layers(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            node_ids = tuple(item["node_id"] for item in payload["layers"])
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=node_ids, actor=actor)
            sources = []
            for item in payload["layers"]:
                source, media = self._verified_canvas_image_source(conn, p, document, item["node_id"], "图层合成")
                sources.append((source, media, item))
            staged, label = build(sources)
            anchor = sources[0][0]
            placed = self._place_derived_images(
                conn, project, canvas, version, document, anchor, sources[0][1],
                [{"staged": staged, "role": "composition", "label": label, "title": f"{anchor['title']} · 免费合成"[:200], "key_prefix": "compose", "params": {"layer_composition": "free", "credits": 0}}],
                actor=actor, kw=kw, group_name=payload.get("group_name") or anchor.get("group") or "",
                operation_type="image-layer-composition", tool="vsc-local-layer-composition",
                parameters={"canvas_version_id": version["id"], "layer_count": len(sources), "credits": 0, "charged": False},
                error_code="canvas_layer_output_unverified",
            )
            return placed
        return self._mutate(project_id, "compose_canvas_layers", payload, actor=actor, callback=work, **kw)

    def stitch_canvas_images(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=tuple(payload["node_ids"]), actor=actor)
            sources = []
            for node_id in payload["node_ids"]:
                sources.append(self._verified_canvas_image_source(conn, p, document, node_id, "拼合"))
            staged = build([media for _source, media in sources])
            anchor = sources[0][0]
            title = "长图拼合" if payload["mode"] == "long" else "宫格拼合"
            return self._place_derived_images(
                conn, project, canvas, version, document, anchor, sources[0][1],
                [{"staged": staged, "role": "stitch", "label": title, "title": f"{anchor['title']} · {title}"[:200], "key_prefix": "stitch", "params": {"stitch_mode": payload["mode"]}}],
                actor=actor, kw=kw, group_name=payload.get("group_name") if payload.get("group_name") is not None else (anchor.get("group") or ""),
                operation_type="image-stitch", tool="vsc-local-image-stitch",
                parameters={"canvas_version_id": version["id"], "mode": payload["mode"], "source_count": len(sources), "credits": 0},
                error_code="canvas_stitch_output_unverified",
            )
        return self._mutate(project_id, "stitch_canvas_images", payload, actor=actor, callback=work, **kw)

    def _verified_canvas_typed_source(self, conn, p, document, node_id, node_type, action_label):
        source = next((node for node in document["nodes"] if node["id"] == node_id), None)
        label = "音频" if node_type == "audio" else "视频"
        if not source or source["type"] != node_type or not source.get("media_id"):
            raise ResourceError(f"请选择已固定{label}的画布节点", "canvas_av_source_required")
        media, gaps = self._usable(conn, p, source["media_id"], node_type)
        gaps = [gap for gap in gaps if gap != "technical_check_missing"]
        if gaps:
            raise ResourceError(f"原素材当前不可{action_label}", "canvas_av_source_unusable")
        if media["modality"] != node_type:
            raise ResourceError(f"{action_label}只接受{label}", "canvas_av_source_required")
        return source, media

    def process_canvas_audio(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_typed_source(conn, p, document, payload["node_id"], "audio", "处理")
            if len(document["nodes"]) + 1 > 200 or len(document["edges"]) + 1 > 800:
                raise ResourceError("音频处理输出超过画布节点或连线数量上限", "canvas_audio_process_capacity")
            result, meta = build(media)
            if result.get("modality") != "audio" or type(result.get("duration_ms")) is not int or result["duration_ms"] <= 0:
                raise ResourceError("派生音频缺少实测时长", "canvas_audio_output_unverified")
            operation_name = payload["operation"]
            registered = self._register_media(
                conn, project,
                {**result, "rights": "unknown", "source": {"kind": "canvas-audio-process", "content": {
                    "canvas_version_id": version["id"], "source_media_id": media["id"], "source_sha256": media["sha256"],
                    "operation": operation_name, "start_seconds": meta.get("start_seconds"), "end_seconds": meta.get("end_seconds"),
                    "speed": meta.get("speed"), "filter": meta.get("filter"),
                }}},
                actor,
            )
            self.record_media_check(p, {
                "media_id": registered["id"], "blob_sha256": registered["sha256"],
                "checker": "canvas-audio-output-probe", "criteria_version": "1", "outcome": "pass",
                "report": {"source": "local-ffmpeg", "duration_ms": result["duration_ms"], "meta": meta},
            }, actor=actor, _transaction=(conn, project), **kw)
            key = "audio-" + new_id()
            if operation_name == "clip":
                title = f"{source['title']} · 裁剪音频"
                params = {"vsc_operation": "audio_clip", "leftClipTime": meta.get("start_seconds"), "rightClipTime": meta.get("end_seconds")}
            else:
                speed = meta.get("speed")
                speed_text = str(int(speed)) if isinstance(speed, (int, float)) and abs(float(speed) - round(float(speed))) < 1e-9 else f"{float(speed):.2f}".rstrip("0").rstrip(".")
                title = f"{source['title']} · 变速音频 {speed_text}x"
                params = {"vsc_operation": "audio_speed", "playback_rate": float(speed)}
            document["nodes"].append({
                "id": key, "type": "audio", "title": title[:200],
                "x": min(100000, source["x"] + 300), "y": source["y"], "text": "",
                "params": params, "group": source.get("group") or "", "media_id": registered["id"], "job_id": None,
            })
            document["edges"].append({"id": "derive-" + new_id(), "source": source["id"], "target": key, "port": "derived_from"})
            operation = self.create_media_operation(p, {
                "operation_type": "audio-canvas-process", "recipe_version": "canvas-audio-process/v1",
                "tool": "vsc-local-ffmpeg", "tool_version": "1",
                "parameters": {"canvas_version_id": version["id"], "source_sha256": media["sha256"], **{k: meta.get(k) for k in ("operation", "start_seconds", "end_seconds", "speed", "filter", "source_duration_ms", "output_duration_ms")}},
                "inputs": [{"media_id": media["id"], "role": "source"}],
                "outputs": [{"media_id": registered["id"], "role": "processed"}],
            }, actor=actor, _transaction=(conn, project), **kw)
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, node_ids=[key], media_ids=[registered["id"]], operation_id=operation["id"],
                        output_duration_ms=result["duration_ms"], source_duration_ms=meta.get("source_duration_ms"))

        return self._mutate(project_id, "process_canvas_audio", payload, actor=actor, callback=work, **kw)

    def capture_canvas_video_frame(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_typed_source(conn, p, document, payload["node_id"], "video", "截帧")
            if len(document["nodes"]) + 1 > 200 or len(document["edges"]) + 1 > 800:
                raise ResourceError("视频截帧输出超过画布节点或连线数量上限", "canvas_frame_capacity")
            result, meta = build(media)
            probe = self._assert_complete_image_probe(result, "canvas_frame_output_unverified")
            labels = {"first": "截取首帧", "current": "截取当前帧", "last": "截取尾帧"}
            registered = self._register_media(
                conn, project,
                {**result, "rights": "unknown", "source": {"kind": "canvas-video-frame", "content": {
                    "canvas_version_id": version["id"], "source_media_id": media["id"], "source_sha256": media["sha256"],
                    "frame": meta["frame"], "time_seconds": meta.get("time_seconds"),
                }}},
                actor,
            )
            self.record_media_check(p, {
                "media_id": registered["id"], "blob_sha256": registered["sha256"],
                "checker": "canvas-frame-output-decode", "criteria_version": "1", "outcome": "pass",
                "report": {"source": "local-storage-complete-decode", "probe": probe, "frame": meta["frame"]},
            }, actor=actor, _transaction=(conn, project), **kw)
            key = "frame-" + new_id()
            params = {"vsc_frame_mode": meta["frame"]}
            if meta["frame"] == "current" and meta.get("time_seconds") is not None:
                params["vsc_frame_time"] = round(float(meta["time_seconds"]), 3)
            document["nodes"].append({
                "id": key, "type": "image", "title": f"{source['title']} · {labels[meta['frame']]}"[:200],
                "x": min(100000, source["x"] + 300), "y": source["y"], "text": "",
                "params": params, "group": source.get("group") or "", "media_id": registered["id"], "job_id": None,
            })
            document["edges"].append({"id": "derive-" + new_id(), "source": source["id"], "target": key, "port": "derived_from"})
            operation = self.create_media_operation(p, {
                "operation_type": "image-canvas-frame", "recipe_version": "canvas-video-frame/v1",
                "tool": "vsc-local-ffmpeg", "tool_version": "1",
                "parameters": {"canvas_version_id": version["id"], "source_sha256": media["sha256"], "frame": meta["frame"], "time_seconds": meta.get("time_seconds")},
                "inputs": [{"media_id": media["id"], "role": "source"}],
                "outputs": [{"media_id": registered["id"], "role": "frame"}],
            }, actor=actor, _transaction=(conn, project), **kw)
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, node_ids=[key], media_ids=[registered["id"]], operation_id=operation["id"], source_duration_ms=meta.get("source_duration_ms"))

        return self._mutate(project_id, "capture_canvas_video_frame", payload, actor=actor, callback=work, **kw)

    def apply_canvas_video_script(self, project_id, payload, *, build, actor, **kw):
        def plain_params(value):
            import math
            if not isinstance(value, dict):
                return {}
            out = {}
            for key, item in value.items():
                if len(out) >= 40 or not isinstance(key, str) or not key or len(key) > 100:
                    continue
                if isinstance(item, bool) or item is None:
                    out[key] = item
                elif isinstance(item, int):
                    out[key] = item
                elif isinstance(item, float) and math.isfinite(item):
                    out[key] = item
                elif isinstance(item, str) and len(item) <= 2000:
                    out[key] = item
            return out

        def work(conn, project):
            from vsc.assets.canvas_video_ops import source_ids_for
            p = project["id"]
            operation_name = payload.get("operation")
            if operation_name == "multi_video_edit":
                canvas, version = self._canvas_version(conn, project, payload.get("canvas_id"))
                if version["version"] != payload.get("canvas_revision"):
                    raise Conflict("画布版本已变化，请返回画布刷新后重试", "canvas_media_edit_version_changed")
            canvas, version, document = self._canvas_current(conn, project, payload)
            anchor_id = payload.get("node_id")
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(anchor_id,), actor=actor)
            entries = []
            for node_id in source_ids_for(operation_name, payload.get("settings") or {}, anchor_id):
                node = next((item for item in document["nodes"] if item["id"] == node_id), None)
                if node is None:
                    raise ResourceError("画布节点不存在", "canvas_video_script_node")
                media = None
                if node.get("media_id") and node["type"] in {"image", "video", "audio"}:
                    media, gaps = self._usable(conn, p, node["media_id"], node["type"])
                    gaps = [gap for gap in gaps if gap != "technical_check_missing"]
                    if gaps:
                        raise ResourceError("原素材当前不可处理", "canvas_av_source_unusable")
                    if media["modality"] != node["type"]:
                        raise ResourceError("素材类型与节点不一致", "canvas_av_source_required")
                entries.append({"node": node, "media": media})
            outputs = build(entries)
            if not isinstance(outputs, list) or not outputs:
                raise ResourceError("视频脚本操作没有可写入的结果", "canvas_video_script_empty")
            extra_edges = sum(len(item.get("source_ids") or []) for item in outputs)
            if len(document["nodes"]) + len(outputs) > 200 or len(document["edges"]) + extra_edges > 800:
                raise ResourceError("视频脚本输出超过画布节点或连线数量上限", "canvas_video_script_capacity")
            anchor = next((item for item in document["nodes"] if item["id"] == anchor_id), None)
            origin_x = anchor["x"] if anchor else 80
            origin_y = anchor["y"] if anchor else 80
            group = (anchor or {}).get("group") or ""
            node_ids, media_ids, media_outputs = [], [], []
            for index, item in enumerate(outputs):
                kind = item.get("kind")
                if kind not in {"text", "image", "video", "audio"}:
                    raise ResourceError("视频脚本结果类型无效", "canvas_video_script_empty")
                key = "vst-" + new_id()
                committed = item.get("committed")
                media_id = None
                if committed:
                    if kind == "image":
                        self._assert_complete_image_probe(committed, "canvas_video_script_output_unverified")
                    elif kind == "video" and (committed.get("modality") != "video" or type(committed.get("duration_ms")) is not int or committed["duration_ms"] <= 0):
                        raise ResourceError("派生视频缺少实测时长", "canvas_video_script_output_unverified")
                    registered = self._register_media(conn, project, {
                        **committed, "rights": "unknown",
                        "source": {"kind": "canvas-video-script", "content": {
                            "canvas_version_id": version["id"], "operation": operation_name, "meta": item.get("meta") or {},
                        }},
                    }, actor)
                    self.record_media_check(p, {
                        "media_id": registered["id"], "blob_sha256": registered["sha256"],
                        "checker": "canvas-video-script-output", "criteria_version": "1", "outcome": "pass",
                        "report": {"source": "local-ffmpeg", "operation": operation_name},
                    }, actor=actor, _transaction=(conn, project), **kw)
                    media_id = registered["id"]
                    media_ids.append(media_id)
                    media_outputs.append({"media_id": media_id, "role": "derived"})
                text = item.get("text") or ""
                if not isinstance(text, str):
                    text = ""
                document["nodes"].append({
                    "id": key, "type": kind, "title": str(item.get("title") or "视频脚本结果")[:200] or "视频脚本结果",
                    "x": min(100000, origin_x + 320), "y": min(100000, origin_y + index * 210),
                    "text": text[:50000], "params": plain_params(item.get("params")), "group": group,
                    "media_id": media_id, "job_id": None,
                })
                for source_id in item.get("source_ids") or []:
                    if any(node["id"] == source_id for node in document["nodes"]):
                        document["edges"].append({"id": "derive-" + new_id(), "source": source_id, "target": key, "port": item.get("port") or "derived_from"})
                node_ids.append(key)
            operation = None
            if media_outputs:
                operation = self.create_media_operation(p, {
                    "operation_type": "canvas-video-script", "recipe_version": "canvas-video-script/v1",
                    "tool": "vsc-local-ffmpeg", "tool_version": "1",
                    "parameters": {"canvas_version_id": version["id"], "operation": operation_name},
                    "inputs": [{"media_id": entry["media"]["id"], "role": "source"} for entry in entries if entry.get("media")],
                    "outputs": media_outputs,
                }, actor=actor, _transaction=(conn, project), **kw)
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, node_ids=node_ids, media_ids=media_ids, operation_id=None if operation is None else operation["id"])

        return self._mutate(project_id, "apply_canvas_video_script", payload, actor=actor, callback=work, **kw)

    def replace_canvas_node_media(self, project_id, payload, actor, **kw):
        from .copy_lineage import assert_copy_source
        from .media_recycle import recycled_ids

        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            target = next((node for node in document["nodes"] if node["id"] == payload["node_id"]), None)
            if not target or target["type"] not in {"image", "video", "audio"}:
                raise ResourceError("请选择图片、视频或音频节点进行素材替换", "canvas_replace_target_invalid")
            media_id = checked_id(payload["media_id"])
            if media_id in set(conn.execute(recycled_ids(p)).scalars()):
                raise ResourceError("目标素材已在回收站中，请先恢复后再替换", "canvas_replace_media_recycled", 409)
            media = self._media(conn, p, media_id)
            if media["modality"] != target["type"]:
                raise ResourceError("替换素材类型必须与节点类型一致", "canvas_media_type")
            assert_copy_source(self, conn, p, media_id)
            gaps = []
            lifecycle = self._latest(conn, S.media_lifecycle_decisions, p, "media_id", media_id)
            if lifecycle and lifecycle["outcome"] == "deprecate":
                gaps.append("media_deprecated")
            checks = conn.execute(
                select(S.media_checks)
                .where(S.media_checks.c.project_id == p, S.media_checks.c.media_id == media_id)
                .order_by(S.media_checks.c.project_revision.desc(), S.media_checks.c.id)
            ).mappings()
            latest = {}
            for check in checks:
                latest.setdefault((check["checker"], check["criteria_version"]), check)
            if any(check["outcome"] != "pass" for check in latest.values()):
                gaps.append("technical_check_failed")
            grid = self._grid_parent(conn, p, media_id)
            if grid:
                _, parents = self._usable(conn, p, grid[0], "image_edit")
                gaps.extend("grid_source_" + gap for gap in parents if gap != "technical_check_missing")
            if gaps:
                raise ResourceError("替换素材当前不可用于画布：" + ", ".join(gaps), "canvas_replace_media_unavailable")
            if not any(loc["available"] for loc in media["locations"]):
                raise ResourceError("替换素材没有可用存储副本", "canvas_replace_media_unavailable")
            target["media_id"] = media["id"]
            target["job_id"] = None
            if payload.get("title"):
                target["title"] = payload["title"].strip()[:200]
            saved = self._insert_canvas_version(
                conn, project, canvas, {"title": version["title"], "document": document}, actor, version
            )
            return dict(saved, node_id=target["id"], media_id=media["id"])

        return self._mutate(project_id, "replace_canvas_node_media", payload, actor=actor, callback=work, **kw)

    def list_canvas_agent_sessions(self, project_id, canvas_id, *, include_archived=False):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            self._access_require(conn, p, "read")
            canvas = self._one(conn, S.creative_canvases, p, canvas_id)
            from .project_management import filter_management_rows
            if not filter_management_rows(conn, p, S.creative_canvases, [canvas]):
                raise ResourceError("画布所属对象已回收", "object_recycled", 409)
            sessions = list(
                conn.execute(
                    select(S.canvas_agent_sessions)
                    .where(S.canvas_agent_sessions.c.project_id == p, S.canvas_agent_sessions.c.canvas_id == canvas_id)
                    .order_by(S.canvas_agent_sessions.c.created_at.desc())
                ).mappings()
            )
            if not sessions:
                return clean({"items": [], "revision": project["revision"]})
            session_ids = [row["id"] for row in sessions]
            state_map = {
                row["session_id"]: dict(row)
                for row in conn.execute(
                    select(S.canvas_agent_session_states).where(
                        S.canvas_agent_session_states.c.project_id == p,
                        S.canvas_agent_session_states.c.session_id.in_(session_ids),
                    )
                ).mappings()
            }
            queue_rows = list(
                conn.execute(
                    select(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.session_id.in_(session_ids),
                        S.canvas_agent_queue_items.c.status.in_(("queued", "steered", "editing")),
                    )
                    .order_by(
                        (S.canvas_agent_queue_items.c.status == "steered").desc(),
                        S.canvas_agent_queue_items.c.ordinal.asc(),
                        S.canvas_agent_queue_items.c.created_at.asc(),
                    )
                ).mappings()
            )
            queues_by_session = {}
            for q in queue_rows:
                queues_by_session.setdefault(q["session_id"], []).append(dict(q))
            output = []
            for session in sessions:
                st = state_map.get(session["id"])
                archived = bool(st["archived"]) if st else False
                if archived and not include_archived:
                    continue
                ids = conn.execute(
                    select(S.canvas_agent_turns.c.id)
                    .where(S.canvas_agent_turns.c.project_id == p, S.canvas_agent_turns.c.session_id == session["id"])
                    .order_by(S.canvas_agent_turns.c.created_at)
                ).scalars()
                effective_title = st["title"] if st else session["title"]
                output.append(
                    dict(
                        session,
                        title=effective_title,
                        original_title=session["title"],
                        archived=archived,
                        auto_approve=bool(st["auto_approve"]) if st else False,
                        queue=queues_by_session.get(session["id"], []),
                        turns=[self._canvas_agent_turn(conn, project, i) for i in ids],
                    )
                )
            return clean({"items": output, "revision": project["revision"]})

    def update_canvas_agent_session_state(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas = self._one(conn, S.creative_canvases, p, payload["canvas_id"])
            self._require_canvas_edit(conn, p, canvas, actor=actor)
            session = self._one(conn, S.canvas_agent_sessions, p, payload["session_id"])
            if session["canvas_id"] != canvas["id"]:
                raise ResourceError("会话不属于当前画布", "canvas_agent_session_scope")
            existing = conn.execute(
                select(S.canvas_agent_session_states).where(
                    S.canvas_agent_session_states.c.project_id == p,
                    S.canvas_agent_session_states.c.session_id == session["id"],
                )
            ).mappings().first()
            next_title = payload["title"].strip() if "title" in payload and payload["title"] is not None else (existing["title"] if existing else session["title"])
            next_archived = payload["archived"] if "archived" in payload and payload["archived"] is not None else (bool(existing["archived"]) if existing else False)
            next_auto = payload["auto_approve"] if "auto_approve" in payload and payload["auto_approve"] is not None else (bool(existing["auto_approve"]) if existing else False)
            now = datetime.now(timezone.utc)
            conn.execute(
                pg_insert(S.canvas_agent_session_states)
                .values(
                    project_id=p,
                    session_id=session["id"],
                    title=next_title,
                    archived=next_archived,
                    auto_approve=next_auto,
                    updated_by=actor,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["project_id", "session_id"],
                    set_={
                        "title": next_title,
                        "archived": next_archived,
                        "auto_approve": next_auto,
                        "updated_by": actor,
                        "updated_at": now,
                    },
                )
            )
            return {
                "session_id": session["id"],
                "canvas_id": canvas["id"],
                "title": next_title,
                "archived": next_archived,
                "auto_approve": next_auto,
            }

        return self._mutate(project_id, "update_canvas_agent_session_state", payload, actor=actor, callback=work, **kw)

    def mutate_canvas_agent_queue(self, project_id, payload, actor, **kw):
        from vsc.production.canvas_agent import SKILLS

        def work(conn, project):
            p = project["id"]
            canvas = self._one(conn, S.creative_canvases, p, payload["canvas_id"])
            self._require_canvas_edit(conn, p, canvas, actor=actor)
            session = self._one(conn, S.canvas_agent_sessions, p, payload["session_id"])
            if session["canvas_id"] != canvas["id"]:
                raise ResourceError("会话不属于当前画布", "canvas_agent_session_scope")
            action = payload["action"]
            now = datetime.now(timezone.utc)
            if action == "enqueue":
                skill_id = payload.get("skill_id", "vsc-script")
                mode = payload.get("mode", "manual")
                message = (payload.get("message") or "").strip()
                if not message or len(message) > 6000 or skill_id not in SKILLS or mode not in {"manual", "auto_drafts"}:
                    raise ResourceError("入队消息需要有效文本、已装技能与模式", "invalid_agent_queue_item")
                active_count = conn.scalar(
                    select(func.count())
                    .select_from(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.session_id == session["id"],
                        S.canvas_agent_queue_items.c.status.in_(("queued", "steered")),
                    )
                )
                if (active_count or 0) >= 20:
                    raise ResourceError("单个会话待发送队列最多保留 20 条消息", "agent_queue_limit")
                ordinal = conn.scalar(
                    select(func.coalesce(func.max(S.canvas_agent_queue_items.c.ordinal), -1) + 1).where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.session_id == session["id"],
                    )
                )
                item_id = new_id()
                conn.execute(
                    insert(S.canvas_agent_queue_items).values(
                        project_id=p,
                        id=item_id,
                        session_id=session["id"],
                        ordinal=int(ordinal or 0),
                        message=message,
                        skill_id=skill_id,
                        mode=mode,
                        status="queued",
                        created_by=actor,
                        created_at=now,
                        updated_at=now,
                    )
                )
                row = dict(self._one(conn, S.canvas_agent_queue_items, p, item_id))
                return {"item": row, "action": "enqueue"}

            item = self._one(conn, S.canvas_agent_queue_items, p, payload.get("queue_item_id"))
            if item["session_id"] != session["id"]:
                raise ResourceError("队列消息不属于当前会话", "agent_queue_item_scope")
            if action == "steer":
                if item["status"] not in {"queued", "steered", "editing"}:
                    raise Conflict("该队列消息已处理或已取消", "agent_queue_item_closed")
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="steered", ordinal=0, updated_at=now)
                )
                return {"item": dict(item, status="steered", ordinal=0), "action": "steer"}
            if action == "take_for_edit":
                if item["status"] not in {"queued", "steered"}:
                    raise Conflict("该队列消息不可取回编辑", "agent_queue_item_closed")
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="editing", updated_at=now)
                )
                return {"item": dict(item, status="editing"), "action": "take_for_edit"}
            if action == "cancel":
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="cancelled", updated_at=now)
                )
                return {"item": dict(item, status="cancelled"), "action": "cancel"}
            if action == "mark_dispatched":
                turn = self._one(conn, S.canvas_agent_turns, p, payload.get("turn_id"))
                if turn["session_id"] != session["id"]:
                    raise ResourceError("关联轮次不属于当前会话", "agent_queue_item_scope")
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="dispatched", dispatched_turn_id=turn["id"], updated_at=now)
                )
                return {"item": dict(item, status="dispatched", dispatched_turn_id=turn["id"]), "action": "mark_dispatched"}
            raise ResourceError("未知队列操作", "invalid_agent_queue_action")

        return self._mutate(project_id, "mutate_canvas_agent_queue", payload, actor=actor, callback=work, **kw)

    def list_camera_motion_templates(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            self._access_require(conn, p, "read")
            custom = [
                dict(row, builtin=False)
                for row in conn.execute(
                    select(S.canvas_camera_motion_templates)
                    .where(
                        S.canvas_camera_motion_templates.c.project_id == p,
                        S.canvas_camera_motion_templates.c.archived.is_(False),
                    )
                    .order_by(
                        S.canvas_camera_motion_templates.c.favorite.desc(),
                        S.canvas_camera_motion_templates.c.updated_at.desc(),
                    )
                ).mappings()
            ]
            return clean({
                "builtin": [deepcopy(item) for item in BUILTIN_CAMERA_MOTIONS],
                "custom": custom,
                "revision": project["revision"],
            })

    def mutate_camera_motion_template(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            self._access_require(conn, p, "edit")
            action = payload["action"]
            now = datetime.now(timezone.utc)
            if action == "create":
                item_id = new_id()
                conn.execute(
                    insert(S.canvas_camera_motion_templates).values(
                        project_id=p,
                        id=item_id,
                        name=payload["name"].strip(),
                        prompt_fragment=payload["prompt_fragment"].strip(),
                        horizontal_pan=int(payload.get("horizontal_pan", 0)),
                        vertical_tilt=int(payload.get("vertical_tilt", 0)),
                        zoom_delta=int(payload.get("zoom_delta", 0)),
                        roll_deg=int(payload.get("roll_deg", 0)),
                        speed_preset=payload.get("speed_preset", "normal"),
                        favorite=bool(payload.get("favorite", False)),
                        archived=False,
                        created_by=actor,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return {"item": dict(self._one(conn, S.canvas_camera_motion_templates, p, item_id), builtin=False), "action": "create"}
            row = self._one(conn, S.canvas_camera_motion_templates, p, payload.get("template_id"))
            if action == "favorite":
                fav = bool(payload["favorite"])
                conn.execute(
                    update(S.canvas_camera_motion_templates)
                    .where(
                        S.canvas_camera_motion_templates.c.project_id == p,
                        S.canvas_camera_motion_templates.c.id == row["id"],
                    )
                    .values(favorite=fav, updated_at=now)
                )
                return {"item": dict(row, favorite=fav, builtin=False), "action": "favorite"}
            if action == "delete":
                conn.execute(
                    update(S.canvas_camera_motion_templates)
                    .where(
                        S.canvas_camera_motion_templates.c.project_id == p,
                        S.canvas_camera_motion_templates.c.id == row["id"],
                    )
                    .values(archived=True, updated_at=now)
                )
                return {"item": dict(row, archived=True, builtin=False), "action": "delete"}
            raise ResourceError("未知运镜模板操作", "invalid_camera_motion_action")

        return self._mutate(project_id, "mutate_camera_motion_template", payload, actor=actor, callback=work, **kw)
