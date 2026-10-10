#!/usr/bin/env python3
"""剪映草稿写入器：在 NarratoAI 的 uv 环境中运行，由 jianying_export.py 调用，不直接面向用户。

输入是 jianying_export.py 生成的 JSON；用 NarratoAI 固定版本的草稿构件组装多轨草稿并写入剪映草稿目录，
最后输出一行 JSON：{"draft_path": ..., "folder": ...}。
"""
import json
import os
import sys
import time
import uuid

# uv run --directory 把工作目录设为 NarratoAI 根目录；脚本自身目录不在那里，需显式加入导入路径。
sys.path.insert(0, os.getcwd())

from app.models.schema import VideoClipParams  # noqa: E402
from app.services import jianying_draft_builder as jd  # noqa: E402


def main(payload_path):
    with open(payload_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    root, name = payload["drafts_root"], payload["name"]
    folder, draft_path = jd._create_unique_draft_path(root, name)
    os.makedirs(draft_path, exist_ok=False)
    for relative in jd.DRAFT_PACKAGE_DIRECTORIES:
        os.makedirs(os.path.join(draft_path, *relative.split("/")), exist_ok=True)
    draft_id = uuid.uuid4().hex
    draft = jd._create_draft_template(draft_id, name, root, payload["width"], payload["height"])
    used, copied, durations, metadata, materials = set(), {}, {}, {}, {}

    video_tracks = []
    for item in payload["video"]:
        material = materials.get(item["path"])
        if material is None:
            duration_us, width, height = jd._get_video_metadata_ffprobe(item["path"], metadata)
            relative = jd._register_asset(item["path"], draft_path, "assets/video", f"video_{len(materials) + 1}.mp4", used, copied)
            material = jd._create_video_material(relative, duration_us, width, height)
            draft["materials"]["videos"].append(material)
            materials[item["path"]] = material
        while len(video_tracks) <= item["track"]:
            video_tracks.append(jd._create_track("video", f"视频轨道{len(video_tracks) + 1}"))
        video_tracks[item["track"]]["segments"].append(jd._create_video_segment(
            material["id"], item["source_start_us"], item["duration_us"], item["start_us"], item["volume"]))

    audio_tracks = []
    for item in payload["audio"]:
        duration_us = jd._seconds_to_microseconds(jd._get_cached_media_duration(item["path"], durations))
        extension = os.path.splitext(item["path"])[1] or ".wav"
        relative = jd._register_asset(item["path"], draft_path, "assets/audio", f"audio_{len(audio_tracks) + 1}{extension}", used, copied)
        material = jd._create_audio_material(relative, duration_us)
        draft["materials"]["audios"].append(material)
        segment = jd._create_audio_segment(material["id"], item["duration_us"], item["start_us"], item["volume"])
        segment["source_timerange"]["start"] = item["source_start_us"]
        track = jd._create_track("audio", item["id"])
        track["segments"].append(segment)
        audio_tracks.append(track)

    draft["tracks"] = video_tracks + audio_tracks
    end_us = max(item["start_us"] + item["duration_us"] for item in payload["video"] + payload["audio"])
    if payload.get("srt"):
        end_us = max(end_us, jd._add_subtitle_track_from_srt(draft, payload["srt"], VideoClipParams()))
    draft["canvas_config"]["width"], draft["canvas_config"]["height"] = payload["width"], payload["height"]
    draft["duration"] = end_us
    draft["update_time"] = int(time.time() * jd.MICROSECONDS)
    asset_size = sum(os.path.getsize(path) for path in copied if os.path.exists(path))
    jd._write_plaintext_draft_files(root, draft_path, name, draft_id, draft, asset_size)
    print(json.dumps({"draft_path": draft_path, "folder": folder}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
