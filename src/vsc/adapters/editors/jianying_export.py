#!/usr/bin/env python3
"""VSC 剪映草稿导出：把已批准的 vsc.remotion-render-plan/v1 时间线写成可在剪映中继续精剪的草稿。

  export PLAN --project PROJECT [--media-root DIR] [--name NAME] [--drafts-root DIR] [--dry-run]

计划中 source 相对 --media-root 解析（默认是计划文件所在目录）。视频按起始帧放在视频轨（重叠时另起一轨），
每个音频片段单独一条音频轨，caption/text 写成字幕轨，素材复制进草稿。草稿构件见 src/vsc/adapters/editors/jianying_draft.py。

剪映草稿是非官方公开的格式，可能随剪映版本失效；导出后须在剪映中打开核验。淡入淡出、音量关键帧和图片片段
无法迁移，逐条写入导出记录，交由剪辑师在剪映中重做。写入前备份剪映的 root_meta_info.json。本脚本不批准产物。
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from vsc.adapters.editors import jianying_draft as jd
from vsc.post import remotion_plan as remotion_plan
from vsc.post import subtitles as subtitles

DEFAULT_DRAFTS_ROOT = Path.home() / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
FADE_KEYS = ("fade_in_frames", "fade_out_frames", "audio_fade_in_frames", "audio_fade_out_frames")
FORMAT_NOTE = "剪映草稿为非官方公开格式，可能随剪映版本失效；须在剪映中打开核验。"
SUPPORTED_FPS = (24, 25, 30)


class ExportError(RuntimeError):
    """计划、素材或上游环境不满足导出条件。"""


def draft_payload(plan, media_root, subtitle_style=None, *, script_texts=None, formal_subtitles=False):
    """把时间线计划映射为剪映写入器的输入；返回 (payload, 未迁移项)。"""
    errors = remotion_plan.validate(plan)
    if errors:
        raise ExportError("时间线计划无效：" + "；".join(errors))
    composition = plan["composition"]
    fps = remotion_plan.frame_rate(composition["fps"])
    if fps not in SUPPORTED_FPS or isinstance(composition["fps"], dict):
        raise ExportError("剪映导出仅支持整数 24/25/30 fps；分数与其他帧率尚未验证，拒绝导出")
    try:
        style, _ = subtitles.resolve_style(overrides={**plan.get("subtitle_style", {}), **(subtitle_style or {})})
        if style.get("font") and not Path(style["font"]).is_absolute():
            style["font"] = str(Path(media_root) / style["font"])
        compiled, _ = remotion_plan.compile_subtitles(plan, style, script_texts=script_texts, require_font=True,
            media_root=media_root, formal_subtitles=formal_subtitles)
    except (OSError, ValueError) as exc:
        raise ExportError(str(exc)) from exc
    if style.get("background") or style.get("rounded"):
        raise ExportError("剪映导出尚不支持字幕背景/圆角样式，拒绝静默丢失")

    def us(frames):
        return round(frames * 1_000_000 / fps)

    video, audio, captions, dropped, missing = [], [], compiled["cues"], [], []
    track_ends = []
    for segment in sorted(plan["segments"], key=lambda item: (item["from_frame"], item["id"])):
        kind, start, length = segment["kind"], segment["from_frame"], segment["duration_in_frames"]
        label = segment["id"]
        if kind in ("video", "audio"):
            path = (Path(media_root) / segment["source"]).resolve()
            if not path.is_file():
                missing.append(f"{label}：{segment['source']}")
                continue
            volume = 0.0 if segment.get("muted") else float(segment.get("volume", 1.0))
            item = {"id": label, "path": str(path), "start_us": us(start), "duration_us": us(start + length) - us(start),
                    "source_start_us": us(segment.get("source_in_frame", 0)), "volume": volume}
            if kind == "video":
                track = next((index for index, end in enumerate(track_ends) if end <= start), len(track_ends))
                if track == len(track_ends):
                    track_ends.append(0)
                track_ends[track] = start + length
                video.append({**item, "track": track})
            else:
                audio.append(item)
        elif kind in ("caption", "text"):
            pass  # Display text and original timecodes come from the shared compiler.
        else:
            dropped.append(f"{label}：{kind} 片段未迁移（剪映草稿构件只支持视频、音频与字幕）")
            continue
        for key in FADE_KEYS:
            if segment.get(key):
                dropped.append(f"{label}：{key}={segment[key]} 未迁移，需在剪映中重做")
        if segment.get("volume_keyframes"):
            dropped.append(f"{label}：{len(segment['volume_keyframes'])} 个音量关键帧未迁移，需在剪映中重做")
    if missing:
        raise ExportError("素材不存在：" + "；".join(missing))
    if not video:
        raise ExportError("计划中没有可导出的视频片段")
    cursor, black = 0, []
    for start, end in sorted((s["from_frame"], s["from_frame"] + s["duration_in_frames"]) for s in plan["segments"] if s["kind"] == "video"):
        if start > cursor:
            black.append([cursor, start])
        cursor = max(cursor, end)
    if cursor < composition["duration_in_frames"]:
        black.append([cursor, composition["duration_in_frames"]])
    if black and (composition["width"] % 2 or composition["height"] % 2):
        raise ExportError("显式黑场编码需要偶数画幅尺寸，当前规格不支持")
    payload = {"width": composition["width"], "height": composition["height"], "fps": int(fps),
               "duration_us": us(composition["duration_in_frames"]), "duration_in_frames": composition["duration_in_frames"],
               "black_intervals_frames": black, "subtitle_style": style, "subtitle_checks": compiled["checks"], "video": video, "audio": audio}
    return payload, captions, dropped


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_draft(payload):
    """在剪映草稿根目录写入多轨草稿，返回 {"draft_path", "folder"}。"""
    root, name = payload["drafts_root"], payload["name"]
    if payload.get("fps") not in SUPPORTED_FPS or not isinstance(payload.get("duration_us"), int) or payload["duration_us"] <= 0:
        raise ExportError("草稿输入缺少受支持的 fps 或固定总时长")
    folder, draft_path = jd._create_unique_draft_path(root, name)
    os.makedirs(draft_path, exist_ok=False)
    for relative in jd.DRAFT_PACKAGE_DIRECTORIES:
        os.makedirs(os.path.join(draft_path, *relative.split("/")), exist_ok=True)
    draft_id = uuid.uuid4().hex
    draft = jd._create_draft_template(draft_id, name, root, payload["width"], payload["height"])
    draft["fps"] = float(payload["fps"])
    draft["canvas_config"]["background"] = {"type": "color", "color": "#000000"}
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

    for index, (start, end) in enumerate(payload.get("black_intervals_frames", [])):
        relative = f"assets/video/vsc-black-{index + 1}.mp4"
        target = Path(draft_path) / relative
        try:
            result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                     f"color=c=black:s={payload['width']}x{payload['height']}:r={payload['fps']}",
                                     "-frames:v", str(end - start), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(target)],
                                    capture_output=True, text=True, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExportError(f"显式黑场编码未完成：{exc}") from exc
        if result.returncode:
            raise ExportError("显式黑场编码失败：" + result.stderr[-500:])
        start_us, end_us = (round(frame * 1_000_000 / payload["fps"]) for frame in (start, end))
        material = jd._create_video_material(relative, end_us - start_us, payload["width"], payload["height"])
        draft["materials"]["videos"].append(material)
        video_tracks[0]["segments"].append(jd._create_video_segment(material["id"], 0, end_us - start_us, start_us, 0))

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
    end_us = payload["duration_us"]
    if payload.get("srt"):
        style = payload.get("subtitle_style") or subtitles.DEFAULT_STYLE
        if style.get("font"):
            if not Path(style["font"]).is_file():
                raise ExportError(f"字幕字体不存在：{style['font']}")
            font_path = jd._register_asset(style["font"], draft_path, "assets/fonts", Path(style["font"]).name, used, copied)
            style = {**style, "font": jd._to_draft_material_path(font_path)}
        params = jd.SubtitleStyle(font_size=style["font_size"], text_fore_color=style["color"], stroke_color=style["stroke_color"],
                                  stroke_width=style["stroke_width"], subtitle_position=style["position"], custom_position=style["custom_position"], font=style.get("font"))
        jd._add_subtitle_track_from_srt(draft, payload["srt"], params, strict=True, duration=end_us / 1_000_000)
    draft["canvas_config"]["width"], draft["canvas_config"]["height"] = payload["width"], payload["height"]
    draft["duration"] = end_us
    draft["update_time"] = int(time.time() * jd.MICROSECONDS)
    asset_size = sum(path.stat().st_size for path in (Path(draft_path) / "assets").rglob("*") if path.is_file())
    jd._write_plaintext_draft_files(root, draft_path, name, draft_id, draft, asset_size)
    return {"draft_path": draft_path, "folder": folder}


def export(plan_path, project, media_root=None, name=None, drafts_root=DEFAULT_DRAFTS_ROOT, dry_run=False, bible=None, *, script_texts=None, formal_subtitles=False):
    plan_path, project = Path(plan_path).resolve(), Path(project).resolve()
    if not (project / "vsc.json").is_file():
        raise ExportError(f"不是 VSC 项目：{project}")
    try:
        plan = remotion_plan.load_plan(plan_path)
        if isinstance(plan, dict) and plan.get("format") == "vsc.timeline/v1":
            plan = plan.get("render_plan")
    except ValueError as exc:
        raise ExportError(str(exc)) from exc
    try:
        bible_bytes = Path(bible).read_bytes() if bible else None
        style, style_source = subtitles.resolve_style(bible, plan.get("subtitle_style"))
        if bible and Path(bible).read_bytes() != bible_bytes:
            raise ValueError("资产库在字幕样式解析过程中变更，请重试")
    except ValueError as exc:
        raise ExportError(str(exc)) from exc
    payload, captions, dropped = draft_payload(plan, Path(media_root or plan_path.parent), style, script_texts=script_texts, formal_subtitles=formal_subtitles)
    warnings = [FORMAT_NOTE]
    if captions:
        warnings.append("字幕字体、字号与安全区采用共享样式映射；剪映排版与烧录器的像素结果仍须逐版本人工回看")
    name = name or f"VSC-{plan['composition']['id']}"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output = project / "07-后期" / "剪映草稿" / f"{name}-{stamp}"
    summary = {"video": len(payload["video"]), "video_tracks": len({item["track"] for item in payload["video"]}),
               "audio_tracks": len(payload["audio"]), "captions": len(captions)}
    if dry_run:
        return None, {"summary": summary, "dropped": dropped, "warnings": warnings, "fps": payload["fps"], "duration_us": payload["duration_us"], "subtitle_checks": payload["subtitle_checks"]}
    drafts_root = Path(drafts_root)
    if not drafts_root.is_dir():
        raise ExportError(f"剪映草稿目录不存在：{drafts_root}（用 --drafts-root 指定）")
    output.mkdir(parents=True)
    backup = None
    if (drafts_root / "root_meta_info.json").is_file():
        backup = output / "root_meta_info.json.backup"
        shutil.copyfile(drafts_root / "root_meta_info.json", backup)
    subtitle = None
    if captions:
        subtitle = output / "字幕.srt"
        subtitle.write_text(subtitles.to_srt(captions), "utf-8")
    payload_path = output / "草稿输入.json"
    payload.update(name=name, drafts_root=str(drafts_root), srt=str(subtitle) if subtitle else None)
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    result = build_draft(payload)
    record = {
        "kind": "剪映草稿导出",
        "note": FORMAT_NOTE,
        "plan": {"path": str(plan_path), "sha256": sha256(plan_path), "composition": plan["composition"]["id"]},
        "builder": "src/vsc/adapters/editors/jianying_draft.py",
        "draft": result,
        "summary": summary,
        "dropped": dropped,
        "warnings": warnings,
        "fps": payload["fps"], "duration_us": payload["duration_us"], "black_intervals_frames": payload["black_intervals_frames"],
        "subtitle_style": {"source": style_source, "resolved": style, "bible_sha256": hashlib.sha256(bible_bytes).hexdigest() if bible_bytes is not None else None},
        "subtitle_checks": payload["subtitle_checks"],
        "root_meta_backup": str(backup.relative_to(project)) if backup else None,
        "exported_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (output / "导出记录.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return output, record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("export", help="导出剪映草稿")
    command.add_argument("plan")
    command.add_argument("--project", required=True)
    command.add_argument("--media-root", help="source 的解析根目录，默认是计划文件所在目录")
    command.add_argument("--name", help="草稿名称，默认 VSC-<composition.id>")
    command.add_argument("--bible", help="共享资产库 subtitle_style")
    command.add_argument("--script-texts", help="固定原稿 JSON 字符串数组；核对缺字，不代表音频对齐")
    command.add_argument("--formal-subtitles", action="store_true", help="要求批准台词行/采用音频/实测时码固定包")
    command.add_argument("--drafts-root", default=str(DEFAULT_DRAFTS_ROOT), help="剪映草稿根目录")
    command.add_argument("--dry-run", action="store_true", help="只检查映射与未迁移项，不写草稿")
    args = parser.parse_args()
    try:
        output, record = export(args.plan, args.project, args.media_root, args.name, args.drafts_root, args.dry_run, args.bible,
                                script_texts=subtitles.read_script_texts(args.script_texts) if args.script_texts else None, formal_subtitles=args.formal_subtitles)
    except (ExportError, OSError, ValueError) as exc:
        raise SystemExit(f"错误：{exc}")
    summary = record["summary"]
    print(f"JIANYING: 视频 {summary['video']} 段/{summary['video_tracks']} 轨，音频 {summary['audio_tracks']} 轨，字幕 {summary['captions']} 条"
          + ("（dry-run，未写入）" if output is None else f" → {record['draft']['draft_path']}"))
    for item in record["dropped"]:
        print(f"  未迁移：{item}")
    for warning in record.get("warnings", []):
        print("  警告：" + warning)
    if output is not None:
        print(f"导出记录：{output / '导出记录.json'}")
        print("注意：" + FORMAT_NOTE)


if __name__ == "__main__":
    main()
