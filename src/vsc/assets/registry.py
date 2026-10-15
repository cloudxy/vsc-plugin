"""Media registration, source relationships and human usage decisions."""
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from vsc.adapters.persistence.sqlite import series as db
from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure
from vsc.project.state import project_lock
from vsc.production.context import (SeriesError, stamp, sha256, series_state,
    build_shot_context, covered_script_units, MEDIA_ROLES, RIGHTS, MODALITIES)

def import_media(project, media_id, source, modality, rights, origin, parents=(), relation=None,
                 parameters=None, job_id=None, original_uri=None):
    series_state(project)
    if not media_id or not media_id.replace("-", "").replace("_", "").isalnum():
        raise SeriesError("媒体 ID 只能包含字母、数字、连字符和下划线")
    if modality not in MODALITIES or rights not in RIGHTS or not origin.strip():
        raise SeriesError("媒体类别、权属和来源必须明确")
    source = Path(source)
    if not source.is_file() or source.is_symlink():
        raise SeriesError("来源媒体不存在或是符号链接")
    try:
        probe = LocalProbeAdapter().probe(source)
    except ProbeFailure as exc:
        raise SeriesError(f"媒体校验失败（{exc.code}）：{exc}") from None
    needed_stream = "video" if modality in ("image", "video") else "audio"
    if not any(stream.get("codec_type") == needed_stream for stream in probe["streams"]):
        raise SeriesError(f"声明为 {modality}，但媒体缺少 {needed_stream} 流")
    if modality == "image" and probe.get("duration_seconds") and probe["duration_seconds"] > 1:
        raise SeriesError("image 素材包含较长时长，须按 video 导入")
    digest_value = sha256(source)
    root = Path(project).resolve()
    storage = root / ".vsc-media"
    storage.mkdir(exist_ok=True)
    if storage.is_symlink():
        raise SeriesError("媒体存储不能是符号链接")
    suffix = source.suffix.lower()
    if len(suffix) > 12 or any(ch not in ".abcdefghijklmnopqrstuvwxyz0123456789" for ch in suffix):
        raise SeriesError("媒体扩展名无效")
    target = storage / (digest_value + suffix)
    with project_lock(root):
        with db.connect(root) as connection:
            old = connection.execute("SELECT sha256,path,modality FROM media_assets WHERE id=?", (media_id,)).fetchone()
            if old:
                linked = job_id and connection.execute("SELECT 1 FROM generated_assets WHERE job_id=? AND media_id=?",
                    (job_id, media_id)).fetchone()
                old_path = (root / old["path"]).resolve()
                if (not linked or old["sha256"] != digest_value or old["modality"] != modality
                        or not old_path.is_relative_to(root) or not old_path.is_file()
                        or sha256(old_path) != digest_value):
                    raise SeriesError("媒体 ID 已存在且无法核对为同一任务产物")
                return {"media_id": media_id, "sha256": digest_value, "path": old["path"]}
            for parent in parents:
                if not connection.execute("SELECT 1 FROM media_assets WHERE id=?", (parent,)).fetchone():
                    raise SeriesError(f"派生来源不存在：{parent}")
            if parents and not relation:
                raise SeriesError("派生素材须说明 --relation")
            if job_id:
                job = connection.execute("SELECT modality,status FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
                ancillary = job and job["modality"] == "video" and modality == "image"
                if not job or job["status"] != "succeeded" or (job["modality"] != modality and not ancillary):
                    raise SeriesError("生成素材须关联已成功且模态一致的任务")
            if original_uri and ("?" in original_uri or "#" in original_uri):
                raise SeriesError("原始 URI 不可包含签名参数或片段")
            if target.exists():
                if target.is_symlink() or sha256(target) != digest_value:
                    raise SeriesError("同摘要存储路径无法核实")
            else:
                fd, temporary = tempfile.mkstemp(dir=storage, prefix=".incoming-")
                try:
                    with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
                        shutil.copyfileobj(inp, out)
                        out.flush(); os.fsync(out.fileno())
                    if sha256(temporary) != digest_value or sha256(source) != digest_value:
                        raise SeriesError("导入期间媒体发生变化")
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            connection.execute("INSERT INTO media_assets VALUES (?,?,?,?,?,?,?,?)",
                (media_id, digest_value, str(target.relative_to(root)), modality, rights, origin,
                 db.canonical({"source_name": source.name, "probe": {key: value for key, value in probe.items() if key != "path"}}), stamp()))
            for parent in parents:
                connection.execute("INSERT INTO asset_derivations VALUES (?,?,?,?)",
                    (media_id, parent, relation, db.canonical(parameters or {})))
            if job_id:
                connection.execute("INSERT INTO generated_assets VALUES (?,?,?,?,?,?)",
                    (job_id, media_id, modality, original_uri, db.canonical({"origin": origin}), stamp()))
    return {"media_id": media_id, "sha256": digest_value, "path": str(target.relative_to(root))}


def decide_media_rights(project, media_id, rights, by, reason):
    """Record a human rights decision before a generated candidate can be bound."""
    series_state(project)
    if rights not in RIGHTS or not by.strip() or not reason.strip():
        raise SeriesError("媒体权属决定须有有效分类、选择人和理由")
    root = Path(project).resolve()
    with project_lock(root), db.connect(root) as connection:
        row = connection.execute("SELECT path,sha256,rights FROM media_assets WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise SeriesError("媒体 ID 不存在")
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path) != row["sha256"]:
            raise SeriesError("媒体文件或 SHA 已失效")
        if row["rights"] == rights:
            raise SeriesError("媒体权属未变化")
        connection.execute("UPDATE media_assets SET rights=? WHERE id=?", (rights, media_id))
        connection.execute("INSERT INTO approval_decisions VALUES (?,?,?,?,?,?)",
            ("media-rights:" + uuid.uuid4().hex, "media_rights", media_id, rights, by,
             db.canonical({"previous": row["rights"], "reason": reason, "at": stamp()})))


def bind_media(project, binding_id, target_id, media_id, role, variant=None):
    state = series_state(project)
    objects = {item["id"]: item for item in state["objects"]}
    if objects.get(target_id, {}).get("kind") not in ("asset", "shot"):
        raise SeriesError("媒体只能绑定已登记 asset 或 shot")
    if role not in MEDIA_ROLES:
        raise SeriesError("未知媒体用途角色")
    expected_modality = ("video" if role == "video_take" else "audio" if role in
                         ("dialogue_dry", "voice_sample", "ambience", "music", "sfx") else "image")
    if role in ("video_take", "dialogue_dry") and objects[target_id]["kind"] != "shot":
        raise SeriesError("视频候选与对白干声只能绑定镜头")
    if role == "dialogue_dry":
        context = build_shot_context(project, target_id)
        _, covered_units = covered_script_units(project, target_id)
        if not isinstance(variant, str) or variant not in covered_units or not any(
                line.get("id") == variant for line in context["script_scene"].get("dialogue", [])):
            raise SeriesError("对白干声须用 variant 指明当前镜头覆盖的已批准台词行 ID")
    if role in ("first_frame", "last_frame", "identity_face", "costume", "location_master", "location_view", "composition", "prop") and objects[target_id]["kind"] == "shot" and role not in ("first_frame", "last_frame", "composition", "prop"):
        raise SeriesError("镜头只允许绑定首尾帧、构图或道具图；身份与地点须绑定 asset")
    with project_lock(Path(project)):
        with db.connect(project) as connection:
            media = connection.execute("SELECT modality FROM media_assets WHERE id=?", (media_id,)).fetchone()
            if not media:
                raise SeriesError("媒体 ID 不存在")
            if media["modality"] != expected_modality:
                raise SeriesError(f"{role} 需要 {expected_modality} 素材")
            if role == "dialogue_dry":
                origin = connection.execute("SELECT j.request FROM generated_assets g "
                    "JOIN generation_jobs j ON j.id=g.job_id WHERE g.media_id=?", (media_id,)).fetchone()
                if origin and json.loads(origin["request"])["logical_request"].get("script_line_ids") != [variant]:
                    raise SeriesError("干声生成任务绑定的台词行与选片行不一致")
            connection.execute("INSERT INTO media_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                (binding_id, target_id, role, variant, media_id, "draft", None, None, stamp()))


def decide_binding(project, binding_id, status, by, reason):
    series_state(project)
    if status not in ("approved", "rejected") or not by.strip() or not reason.strip():
        raise SeriesError("决定必须写状态、真实选择人和理由")
    with project_lock(Path(project)):
        with db.connect(project) as connection:
            row = connection.execute("SELECT b.status,b.target_id,b.role,b.variant,m.rights,m.path,m.sha256 FROM media_bindings b "
                "JOIN media_assets m ON m.id=b.media_id WHERE b.id=?", (binding_id,)).fetchone()
            if not row or row["status"] != "draft":
                raise SeriesError("只能决定未审阅的媒体绑定")
            if status == "approved":
                others = connection.execute("SELECT id,variant FROM media_bindings WHERE target_id=? AND role=? "
                    "AND status='approved'", (row["target_id"], row["role"])).fetchall()
                if any(other["variant"] is None or row["variant"] is None or other["variant"] == row["variant"]
                       for other in others):
                    raise SeriesError("同一用途已有适用的批准素材；先人工退役旧绑定")
                if row["rights"] not in ("owned", "licensed"):
                    raise SeriesError("媒体权属未确认，不能批准用于制作")
                path = Path(project) / row["path"]
                if not path.is_file() or sha256(path) != row["sha256"]:
                    raise SeriesError("媒体文件或 SHA 已失效")
            connection.execute("UPDATE media_bindings SET status=?,actor=?,reason=? WHERE id=?",
                               (status, by, reason, binding_id))
            connection.execute("INSERT INTO media_binding_decisions VALUES (?,?,?,?,?,?)",
                ("BD-" + uuid.uuid4().hex, binding_id, status, by, reason, stamp()))


def retire_binding(project, binding_id, by, reason):
    series_state(project)
    if not by.strip() or not reason.strip():
        raise SeriesError("退役须记录真实选择人和理由")
    with project_lock(Path(project)):
        with db.connect(project) as connection:
            row = connection.execute("SELECT status FROM media_bindings WHERE id=?", (binding_id,)).fetchone()
            if not row or row["status"] != "approved":
                raise SeriesError("只能退役已批准的素材绑定")
            connection.execute("UPDATE media_bindings SET status='retired',actor=?,reason=? WHERE id=?",
                (by, reason, binding_id))
            connection.execute("INSERT INTO media_binding_decisions VALUES (?,?,?,?,?,?)",
                ("BD-" + uuid.uuid4().hex, binding_id, "retired", by, reason, stamp()))


