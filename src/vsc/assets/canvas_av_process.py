"""Local FFmpeg audio clip/speed and video frame extraction. No paid APIs."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from vsc.assets.resource_service import ResourceError

QUOTE_EXTRA_KEYS = frozenset({
    "audio_mode", "voice_id", "music_style", "lyrics_chars", "camera_motion_id",
    "seed_sample_rate", "seed_format", "seed_speed", "seed_pitch", "seed_volume",
})
AUDIO_MODES = frozenset({"description", "lyrics", "soundtrack"})
SEED_RATES = frozenset({8000, 16000, 24000, 48000})
SEED_FORMATS = frozenset({"mp3", "wav"})


def _fail(message):
    raise ResourceError(message, "invalid_canvas_quote")


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def canvas_quote_extras(payload):
    """Validate generator quote fields owned by the audio/video mode bar."""
    if not isinstance(payload, dict):
        _fail("实时报价参数无效")
    extras = {}
    if "audio_mode" in payload and payload["audio_mode"] not in (None, ""):
        mode = payload["audio_mode"]
        if mode not in AUDIO_MODES:
            _fail("音频生成模式无效")
        extras["audio_mode"] = mode
    if "voice_id" in payload and payload["voice_id"] not in (None, ""):
        voice = payload["voice_id"]
        if not isinstance(voice, str) or len(voice) > 64 or "\x00" in voice:
            _fail("音色标识无效")
        extras["voice_id"] = voice
    if "music_style" in payload and payload["music_style"] not in (None, ""):
        style = payload["music_style"]
        if not isinstance(style, str) or len(style) > 200 or "\x00" in style:
            _fail("音乐风格无效")
        extras["music_style"] = style
    if "lyrics_chars" in payload and payload["lyrics_chars"] is not None:
        chars = payload["lyrics_chars"]
        if type(chars) is not int or not 0 <= chars <= 2000:
            _fail("歌词字数须为 0–2000 的整数")
        extras["lyrics_chars"] = chars
    if "camera_motion_id" in payload and payload["camera_motion_id"] not in (None, ""):
        motion = payload["camera_motion_id"]
        if not isinstance(motion, str) or len(motion) > 80 or "\x00" in motion:
            _fail("运镜模板标识无效")
        extras["camera_motion_id"] = motion
    if "seed_sample_rate" in payload and payload["seed_sample_rate"] is not None:
        rate = payload["seed_sample_rate"]
        if type(rate) is not int or rate not in SEED_RATES:
            _fail("采样率须为 8000、16000、24000 或 48000")
        extras["seed_sample_rate"] = rate
    if "seed_format" in payload and payload["seed_format"] not in (None, ""):
        fmt = payload["seed_format"]
        if fmt not in SEED_FORMATS:
            _fail("音频格式须为 mp3 或 wav")
        extras["seed_format"] = fmt
    if "seed_speed" in payload and payload["seed_speed"] is not None:
        speed = payload["seed_speed"]
        if not _finite(speed) or not 0.5 <= float(speed) <= 2:
            _fail("语速须在 0.5–2 之间")
        extras["seed_speed"] = float(speed)
    if "seed_pitch" in payload and payload["seed_pitch"] is not None:
        pitch = payload["seed_pitch"]
        if type(pitch) is not int or not -12 <= pitch <= 12:
            _fail("声调须为 -12–12 的整数")
        extras["seed_pitch"] = pitch
    if "seed_volume" in payload and payload["seed_volume"] is not None:
        volume = payload["seed_volume"]
        if not _finite(volume) or not 0.5 <= float(volume) <= 2:
            _fail("音量须在 0.5–2 之间")
        extras["seed_volume"] = float(volume)
    return extras


def lyrics_quote_prompt(chars):
    count = chars if type(chars) is int and chars > 0 else 1
    return "词" * min(2000, count)


def atempo_chain(rate):
    """Build an atempo chain. Each stage stays inside ffmpeg's 0.5–2.0 limit."""
    if not _finite(rate) or not 0.1 <= float(rate) <= 4.0:
        raise ResourceError("变速倍率须在 0.1 至 4.0 之间", "invalid_canvas_audio_process")
    remaining = float(rate)
    parts = []
    while remaining > 2.0 + 1e-9:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(_atempo_token(remaining))
    return ",".join(parts)


def _atempo_token(value):
    if abs(value - 2.0) < 1e-6:
        return "atempo=2.0"
    if abs(value - 0.5) < 1e-6:
        return "atempo=0.5"
    if abs(value - 1.0) < 1e-6:
        return "atempo=1.0"
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "atempo=" + text


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise ResourceError(f"本机未安装 {name}，无法处理音视频", "local_tool_unavailable")
    return path


def _run(args, timeout=60):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResourceError("本机处理工具缺失或超过时间上限；输入仍保留", "local_tool_unavailable") from exc
    if result.returncode:
        detail = (result.stderr or b"").decode("utf-8", "replace")[:300]
        raise ResourceError("固定素材无法按所选参数处理" + (f"：{detail}" if detail else ""), "local_tool_failed")
    return result.stdout


def probe_duration_seconds(path):
    raw = _run([
        _tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries", "format=duration", "-of", "json", str(path),
    ], 20)
    try:
        duration = float(json.loads(raw or b"{}")["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResourceError("无法读取媒体时长", "local_source_invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ResourceError("媒体时长无效", "local_source_invalid")
    return duration


def process_audio_bytes(content, *, operation, start_seconds=None, end_seconds=None, speed=None):
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise ResourceError("音频字节为空", "invalid_canvas_audio_process")
    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="vsc-canvas-audio-") as directory:
        root = Path(directory)
        source = root / "source.bin"
        source.write_bytes(bytes(content))
        source_duration = probe_duration_seconds(source)
        if operation == "clip":
            if not _finite(start_seconds) or not _finite(end_seconds):
                raise ResourceError("截取需要开始和结束秒数", "invalid_canvas_audio_process")
            start, end = float(start_seconds), float(end_seconds)
            if start < 0 or end <= start or end - start < 0.05:
                raise ResourceError("截取区间无效", "invalid_canvas_audio_process")
            if end > source_duration + 0.05:
                raise ResourceError("截取结束时间超出源音频时长", "invalid_canvas_audio_process")
            output = root / "canvas-audio-clip.wav"
            _run([
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                "-ss", f"{start:.6f}", "-to", f"{end:.6f}",
                "-vn", "-acodec", "pcm_s16le", str(output),
            ])
            filt = None
        elif operation == "speed":
            filt = atempo_chain(speed)
            output = root / "canvas-audio-speed.wav"
            _run([
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                "-vn", "-filter:a", filt, "-acodec", "pcm_s16le", str(output),
            ])
        else:
            raise ResourceError("音频处理仅支持截取和变速", "invalid_canvas_audio_process")
        out_duration = probe_duration_seconds(output)
        meta = {
            "operation": operation,
            "source_duration_ms": round(source_duration * 1000),
            "output_duration_ms": round(out_duration * 1000),
            "start_seconds": None if start_seconds is None else float(start_seconds),
            "end_seconds": None if end_seconds is None else float(end_seconds),
            "speed": None if speed is None else float(speed),
            "filter": filt,
        }
        return output.read_bytes(), meta


def extract_frame_bytes(content, *, frame, time_seconds=None):
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise ResourceError("视频字节为空", "invalid_canvas_frame")
    if frame not in {"first", "current", "last"}:
        raise ResourceError("截帧模式须为首帧、当前帧或尾帧", "invalid_canvas_frame")
    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="vsc-canvas-frame-") as directory:
        root = Path(directory)
        source = root / "source.bin"
        source.write_bytes(bytes(content))
        output = root / "canvas-frame.png"
        duration = probe_duration_seconds(source)
        args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        chosen = 0.0
        if frame == "last":
            args += ["-sseof", "-0.04", "-i", str(source)]
            chosen = duration
        elif frame == "current":
            if not _finite(time_seconds) or float(time_seconds) < 0:
                raise ResourceError("截取当前帧需要有效的时间点", "invalid_canvas_frame")
            chosen = float(time_seconds)
            if chosen > duration + 0.05:
                raise ResourceError("当前帧时间超出视频时长", "invalid_canvas_frame")
            args += ["-i", str(source), "-ss", f"{chosen:.6f}"]
        else:
            args += ["-i", str(source)]
        args += ["-frames:v", "1", "-an", str(output)]
        _run(args)
        data = output.read_bytes() if output.is_file() else b""
        if not data.startswith(b"\x89PNG"):
            raise ResourceError("未能提取视频帧", "local_frame_missing")
        return data, {
            "frame": frame,
            "time_seconds": chosen,
            "source_duration_ms": round(duration * 1000),
        }
