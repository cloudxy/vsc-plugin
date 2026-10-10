#!/usr/bin/env python3
"""VSC 剪映草稿导出：把已批准的 vsc.remotion-render-plan/v1 时间线写成可在剪映中继续精剪的草稿。

  export PLAN --project PROJECT [--media-root DIR] [--name NAME] [--drafts-root DIR] [--dry-run]

计划中 source 相对 --media-root 解析（默认是计划文件所在目录）。视频按起始帧放在视频轨（重叠时另起一轨），
每个音频片段单独一条音频轨，caption/text 写成字幕轨。剪映草稿构件来自本机固定版本的 NarratoAI，素材会复制进草稿。

剪映草稿是非官方公开的格式，可能随剪映版本失效；导出后须在剪映中打开核验。淡入淡出、音量关键帧和图片片段
无法迁移，逐条写入导出记录，交由剪辑师在剪映中重做。写入前备份剪映的 root_meta_info.json。本脚本不批准产物。
"""
import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import remotion_plan
from vendor_sync import VENDOR, installed_problem, locked_source

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ID = "narratoai"
WRITER = Path(__file__).resolve().parent / "jianying_writer.py"
DEFAULT_DRAFTS_ROOT = Path.home() / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
FADE_KEYS = ("fade_in_frames", "fade_out_frames", "audio_fade_in_frames", "audio_fade_out_frames")
FORMAT_NOTE = "剪映草稿为非官方公开格式（NarratoAI 明文草稿构件），可能随剪映版本失效；须在剪映中打开核验。"


class ExportError(RuntimeError):
    """计划、素材或上游环境不满足导出条件。"""


def srt_time(seconds):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def draft_payload(plan, media_root):
    """把时间线计划映射为剪映写入器的输入；返回 (payload, 未迁移项)。"""
    errors = remotion_plan.validate(plan)
    if errors:
        raise ExportError("时间线计划无效：" + "；".join(errors))
    composition = plan["composition"]
    fps = remotion_plan.frame_rate(composition["fps"])

    def us(frames):
        return round(frames * 1_000_000 / fps)

    video, audio, captions, dropped, missing = [], [], [], [], []
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
            item = {"id": label, "path": str(path), "start_us": us(start), "duration_us": us(length),
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
            captions.append((start / fps, (start + length) / fps, segment["text"]))
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
    payload = {"width": composition["width"], "height": composition["height"], "video": video, "audio": audio}
    return payload, captions, dropped


def write_srt(captions, path):
    blocks = [f"{index}\n{srt_time(begin)} --> {srt_time(end)}\n{text}\n" for index, (begin, end, text) in enumerate(captions, 1)]
    path.write_text("\n".join(blocks), "utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_writer(payload_path, vendor_root=VENDOR, run=subprocess.run):
    narrato = vendor_root / SOURCE_ID
    uv = shutil.which("uv")
    if not uv:
        raise ExportError("需要 uv：https://docs.astral.sh/uv/")
    result = run([uv, "run", "--frozen", "--directory", str(narrato), "python", str(WRITER), str(payload_path)],
                 capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ExportError(f"剪映写入失败（exit {result.returncode}）：{(result.stderr or result.stdout).strip()[-500:]}")
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise ExportError("剪映写入器没有输出结果")


def export(plan_path, project, media_root=None, name=None, drafts_root=DEFAULT_DRAFTS_ROOT, dry_run=False, vendor_root=VENDOR, run=subprocess.run):
    plan_path, project = Path(plan_path).resolve(), Path(project).resolve()
    if not (project / "vsc.json").is_file():
        raise ExportError(f"不是 VSC 项目：{project}")
    try:
        plan = remotion_plan.load_plan(plan_path)
    except ValueError as exc:
        raise ExportError(str(exc)) from exc
    payload, captions, dropped = draft_payload(plan, Path(media_root or plan_path.parent))
    name = name or f"VSC-{plan['composition']['id']}"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output = project / "07-后期" / "剪映草稿" / f"{name}-{stamp}"
    summary = {"video": len(payload["video"]), "video_tracks": len({item["track"] for item in payload["video"]}),
               "audio_tracks": len(payload["audio"]), "captions": len(captions)}
    if dry_run:
        return None, {"summary": summary, "dropped": dropped}
    problem = installed_problem(locked_source(SOURCE_ID), vendor_root)
    if problem:
        raise ExportError(problem)
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
        write_srt(captions, subtitle)
    payload_path = output / "草稿输入.json"
    payload.update(name=name, drafts_root=str(drafts_root), srt=str(subtitle) if subtitle else None)
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    result = run_writer(payload_path, vendor_root, run)
    record = {
        "kind": "剪映草稿导出",
        "note": FORMAT_NOTE,
        "plan": {"path": str(plan_path), "sha256": sha256(plan_path), "composition": plan["composition"]["id"]},
        "adapter": {"source": SOURCE_ID, "revision": locked_source(SOURCE_ID)["revision"]},
        "draft": result,
        "summary": summary,
        "dropped": dropped,
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
    command.add_argument("--drafts-root", default=str(DEFAULT_DRAFTS_ROOT), help="剪映草稿根目录")
    command.add_argument("--dry-run", action="store_true", help="只检查映射与未迁移项，不写草稿")
    args = parser.parse_args()
    try:
        output, record = export(args.plan, args.project, args.media_root, args.name, args.drafts_root, args.dry_run)
    except ExportError as exc:
        raise SystemExit(f"错误：{exc}")
    summary = record["summary"]
    print(f"JIANYING: 视频 {summary['video']} 段/{summary['video_tracks']} 轨，音频 {summary['audio_tracks']} 轨，字幕 {summary['captions']} 条"
          + ("（dry-run，未写入）" if output is None else f" → {record['draft']['draft_path']}"))
    for item in record["dropped"]:
        print(f"  未迁移：{item}")
    if output is not None:
        print(f"导出记录：{output / '导出记录.json'}")
        print("注意：" + FORMAT_NOTE)


if __name__ == "__main__":
    main()
