#!/usr/bin/env python3
"""VSC 字幕烧录：把已批准的 SRT 烧进视频，生成带字幕的版本。

  burn VIDEO SRT --output OUT [--bible ASSET-BIBLE.json] [--font FONT] [--font-size N] [--color C] [--stroke-color C]
                              [--stroke-width N] [--position bottom|top|center|custom] [--custom-position P]
                              [--background C] [--rounded]

样式依次取自：命令行参数 > 资产库的 subtitle_style（--bible）> 默认值。资产库中的相对字体路径按工作流根目录解析。
默认字体是 noto-sans-sc 的 NotoSansSC-Bold.otf；也可指定任何本机字体文件，字体的使用权由用户负责。
本机 ffmpeg 不一定带 libass，因此每条字幕先由 Pillow 按字体实际宽度换行并画成透明图，再用 ffmpeg 按时间段叠加；
位置与换行规则见 subtitles.py。Pillow 由 uv 在独立进程中按 PILLOW 固定的版本运行，VSC 自身代码只用标准库。
音轨原样复制，视频以 H.264 重新编码。
"""
from vsc.bootstrap import repository_root, script_path
import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from vsc.story import consistency as consistency
from vsc.post import subtitles as subtitles
from tools.maintenance.vendor_sync import ROOT, VENDOR, installed_problem, locked_source

PILLOW = "pillow==11.3.0"
FONT_SOURCE = "noto-sans-sc"
DEFAULT_FONT = VENDOR / FONT_SOURCE / "Sans" / "SubsetOTF" / "SC" / "NotoSansSC-Bold.otf"
POSITIONS = consistency.POSITIONS
DEFAULT_STYLE = subtitles.DEFAULT_STYLE
MAX_WIDTH_RATIO = 0.82
MAX_LINES = 2


class BurnError(RuntimeError):
    """输入无效或运行环境未就绪。"""


def resolve_style(bible_path=None, overrides=None):
    """默认值 ← 资产库 subtitle_style ← 显式参数；返回 (样式, 来源)。"""
    try:
        return subtitles.resolve_style(bible_path, overrides)
    except ValueError as exc:
        raise BurnError(str(exc)) from exc


def probe_video(video):
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration:format=duration", "-of", "json", str(video)],
                            capture_output=True, text=True, timeout=60)
    metadata = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
    streams = metadata.get("streams")
    if not streams:
        raise BurnError(f"无法读取视频画幅：{video}")
    try:
        duration = float(streams[0].get("duration") or metadata.get("format", {}).get("duration"))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid duration")
    except (TypeError, ValueError) as exc:
        raise BurnError("无法确认视频时长，字幕交付未验证") from exc
    return streams[0]["width"], streams[0]["height"], duration


def probe_size(video):
    return probe_video(video)[:2]


def placement(position, custom, video_height, image_height):
    """与 MoneyPrinterTurbo 一致：底部留 5%，顶部留 5%，custom 为距顶部的百分比。"""
    if position == "bottom":
        return video_height * (1 - subtitles.SAFE_MARGIN) - image_height
    if position == "top":
        return video_height * subtitles.SAFE_MARGIN
    if position == "custom":
        return (video_height - image_height) * custom / 100
    return (video_height - image_height) / 2


def render(job_path):
    """在带 Pillow 的 uv 环境中运行：把每条字幕画成透明 PNG，并算出叠加位置。"""
    from PIL import Image, ImageDraw, ImageFont

    job = json.loads(Path(job_path).read_text("utf-8"))
    style, width, height = job["style"], job["width"], job["height"]
    font = ImageFont.truetype(style["font"], style["font_size"])
    ascent, descent = font.getmetrics()
    line_height = max(1, ascent + descent)
    interline = int(style["font_size"] * 0.25)
    stroke = int(style["stroke_width"])
    background = style.get("background")
    pad_x = int(style["font_size"] * (0.4 if style.get("rounded") else 0.6)) if background else 0
    pad_y = int(style["font_size"] * 0.35)
    safe_width = int(width * MAX_WIDTH_RATIO)
    max_width = max(1, safe_width - 2 * pad_x - 2 * stroke)
    for index, cue in enumerate(job["cues"]):
        lines = subtitles.wrap_text(cue["text"], font, max_width) or [cue["text"]]
        widths = [font.getbbox(line)[2] - font.getbbox(line)[0] for line in lines]
        if len(lines) > MAX_LINES or any(line[0] in subtitles.LINE_START_PUNCTUATION for line in lines if line) or max(widths) > max_width:
            raise subtitles.SubtitleError([f"第 {index + 1} 条字幕无法排入 {MAX_LINES} 行／画幅宽度 {MAX_WIDTH_RATIO:.0%}；请在 SRT 中按语音停顿拆成多条并核对时码，或调整已批准字幕样式"])
        image_width = max(widths) + 2 * pad_x + 2 * stroke
        image_height = len(lines) * line_height + (len(lines) - 1) * interline + 2 * pad_y + 2 * stroke
        image = Image.new("RGBA", (image_width, image_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if background:
            radius = max(8, int(style["font_size"] * 0.4)) if style.get("rounded") else 0
            fill = Image.new("RGBA", (1, 1), background).getpixel((0, 0))[:3] + ((140 if style.get("rounded") else 255),)
            draw.rounded_rectangle((0, 0, image_width - 1, image_height - 1), radius=radius, fill=fill)
        y = pad_y + stroke
        for line, line_width in zip(lines, widths):
            draw.text(((image_width - line_width) / 2, y), line, font=font, fill=style["color"],
                      stroke_width=stroke, stroke_fill=style["stroke_color"])
            y += line_height + interline
        path = Path(job["directory"]) / f"cue-{index:04d}.png"
        image.save(path)
        cue.update(png=str(path), lines=lines, x=int((width - image_width) / 2),
                   y=int(placement(style["position"], style["custom_position"], height, image_height)))
    Path(job_path).write_text(json.dumps(job, ensure_ascii=False), "utf-8")


def overlay_command(video, cues, output):
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(video)]
    for cue in cues:
        command += ["-i", cue["png"]]
    chain, previous = [], "0:v"
    for index, cue in enumerate(cues, 1):
        label = f"v{index}"
        chain.append(f"[{previous}][{index}:v]overlay=x={cue['x']}:y={cue['y']}:enable='between(t,{cue['start']:.3f},{cue['end']:.3f})'[{label}]")
        previous = label
    return command + ["-filter_complex", ";".join(chain), "-map", f"[{previous}]", "-map", "0:a?",
                      "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", str(output)]


def burn(video, srt, output, style, run=subprocess.run):
    video, srt, output = Path(video).resolve(), Path(srt).resolve(), Path(output).resolve()
    if output.exists():
        raise BurnError(f"拒绝覆盖已有文件：{output}")
    if style["position"] not in POSITIONS:
        raise BurnError("--position 必须是 " + "/".join(POSITIONS))
    font = Path(style["font"]) if style.get("font") else DEFAULT_FONT
    if not style.get("font"):
        problem = installed_problem(locked_source(FONT_SOURCE))
        if problem:
            raise BurnError(problem)
    if not font.is_file():
        raise BurnError(f"字体不存在：{font}")
    width, height, duration = probe_video(video)
    try:
        entries = subtitles.parse_srt(srt.read_text("utf-8-sig"), strict=True, duration=duration)
        subtitles.resolve_style(overrides=style)
    except ValueError as exc:
        raise BurnError(str(exc)) from exc
    cues = [{"start": begin, "end": end, "text": text} for begin, end, text in entries]
    if not cues:
        raise BurnError(f"SRT 没有有效字幕：{srt}")
    uv = shutil.which("uv")
    if not uv:
        raise BurnError("需要 uv：https://docs.astral.sh/uv/")
    with tempfile.TemporaryDirectory() as temp:
        job_path = Path(temp) / "job.json"
        job = {"directory": temp, "width": width, "height": height, "cues": cues, "style": {**style, "font": str(font)}}
        job_path.write_text(json.dumps(job, ensure_ascii=False), "utf-8")
        result = run([uv, "run", "--no-project", "--python", "3.12", "--with", PILLOW, "python", str(script_path("subtitle_burn.py")), "render", str(job_path)],
                     capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise BurnError(f"字幕渲染失败：{(result.stderr or result.stdout).strip()[-500:]}")
        rendered = json.loads(job_path.read_text("utf-8"))["cues"]
        output.parent.mkdir(parents=True, exist_ok=True)
        result = run(overlay_command(video, rendered, output), capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise BurnError(f"ffmpeg 叠加失败：{result.stderr.strip()[-500:]}")
    return {"output": str(output), "cues": len(rendered), "font": str(font), "size": [width, height]}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "render":
        try:
            render(sys.argv[2])
        except subtitles.SubtitleError as exc:
            raise SystemExit(f"错误：{exc}") from exc
        return
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("burn", help="把 SRT 烧进视频")
    command.add_argument("video")
    command.add_argument("srt")
    command.add_argument("--output", required=True)
    command.add_argument("--bible", help="vsc.asset-bible/v1 资产库，取其 subtitle_style")
    command.add_argument("--font", help="字体文件")
    command.add_argument("--font-size", type=int)
    command.add_argument("--color")
    command.add_argument("--stroke-color")
    command.add_argument("--stroke-width", type=float)
    command.add_argument("--position", choices=POSITIONS)
    command.add_argument("--custom-position", type=float, help="position=custom 时距顶部的百分比")
    command.add_argument("--background", help="字幕底色，如 #000000")
    command.add_argument("--rounded", action="store_true", default=None, help="半透明圆角底")
    args = parser.parse_args()
    overrides = {"font": args.font, "font_size": args.font_size, "color": args.color, "stroke_color": args.stroke_color,
                 "stroke_width": args.stroke_width, "position": args.position, "custom_position": args.custom_position,
                 "background": args.background, "rounded": args.rounded}
    try:
        style, source = resolve_style(args.bible, overrides)
        result = burn(args.video, args.srt, args.output, style)
    except BurnError as exc:
        raise SystemExit(f"错误：{exc}")
    print(f"SUBTITLES BURNED: {result['cues']} 条，字体 {Path(result['font']).name}，样式来源 {source} → {result['output']}")


if __name__ == "__main__":
    main()
