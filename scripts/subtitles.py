"""字幕断句、逐词时间聚合与排版。

移植自 MoneyPrinterTurbo（https://github.com/harry0703/MoneyPrinterTurbo，commit 7c80ca0b14407966a4fa3cc5bfc428868b186f5f）：
标点表与断句（app/models/const.py、app/utils/utils.py 的 split_string_by_punctuations）、逐词边界聚合为整句
（app/services/voice.py 的 _match_script_line、_build_subtitle_items_from_edge_cues）、语速换算
（convert_rate_to_percent）与按字体宽度换行（app/services/video.py 的 wrap_text）。VSC 的改动：改为不依赖
edge-tts/MoviePy 的纯函数，时间单位统一为秒；排版函数只在调用时才需要 Pillow；换行优先在句内标点后断开。上游的 MIT 许可声明如下，
随本文件保留：

MIT License

Copyright (c) 2024 Harry

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import math
import re
from pathlib import Path

DEFAULT_STYLE = {"font": None, "font_size": 60, "color": "#FFFFFF", "stroke_color": "#000000", "stroke_width": 1.5,
                 "position": "bottom", "custom_position": 70.0, "background": None, "rounded": False}
SAFE_MARGIN = 0.05


class SubtitleError(ValueError):
    """Strict delivery errors, including the original block locations."""
    def __init__(self, errors):
        self.errors = errors
        super().__init__("；".join(errors))


def resolve_style(bible_path=None, overrides=None):
    """Shared burn/export style resolution. Relative bible fonts use the workflow root."""
    import consistency
    from vendor_sync import ROOT, VENDOR
    style, source = dict(DEFAULT_STYLE), "default"
    if bible_path:
        bible = consistency.load(bible_path, consistency.BIBLE_FORMAT)
        problems = consistency.bible_errors(bible)
        if problems:
            raise SubtitleError(problems)
        if bible.get("subtitle_style"):
            style.update(bible["subtitle_style"])
            if style.get("font") and not Path(style["font"]).is_absolute():
                style["font"] = str(ROOT / style["font"])
            source = "bible"
    explicit = {key: value for key, value in (overrides or {}).items() if value is not None}
    unknown = set(explicit) - set(DEFAULT_STYLE)
    if unknown:
        raise SubtitleError(["未知字幕样式字段：" + ", ".join(sorted(unknown))])
    style.update(explicit)
    problems = consistency.style_errors({key: value for key, value in style.items() if value is not None})
    for key in ("font_size", "stroke_width", "custom_position"):
        value = style[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            problems.append(f"subtitle_style.{key} 必须是有限数值")
    if problems:
        raise SubtitleError(problems)
    if style["font"] is None:
        default_font = VENDOR / "noto-sans-sc/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf"
        if default_font.is_file():
            style["font"] = str(default_font)
    return style, source + ("+args" if explicit else "")

PUNCTUATIONS = ("?", ",", ".", "、", ";", ":", "!", "…", "？", "，", "。", "；", "：", "！", "...", "،", "؛", "؟")
LINE_START_PUNCTUATION = "，。！？；：、,.!?;:)]}）】》」』”’"


def split_by_punctuation(text):
    """按标点断成字幕短句；数字中的小数点与千分位逗号不断开。"""
    result, current = [], ""
    for index, char in enumerate(text):
        if char == "\n":
            result.append(current.strip())
            current = ""
            continue
        previous = text[index - 1] if index > 0 else ""
        following = text[index + 1] if index < len(text) - 1 else ""
        if char in ".," and previous.isdigit() and following.isdigit():
            current += char
        elif char in PUNCTUATIONS:
            result.append(current.strip())
            current = ""
        else:
            current += char
    result.append(current.strip())
    return [item for item in result if item]


def _normalized(text):
    return re.sub(r"[_\W]+", "", text)


def group_word_cues(cues, text):
    """把逐词时间 [(开始秒, 结束秒, 词)] 聚合为按剧本断句的字幕 [(开始, 结束, 句)]。

    只有每一句都与逐词结果对上才返回完整列表；对不上时返回 None，由调用方改用逐词字幕。
    """
    lines = split_by_punctuation(text)
    items, buffer, start = [], "", None
    for begin, end, word in cues:
        if start is None:
            start = begin
        buffer += word
        if len(items) < len(lines) and _normalized(buffer) == _normalized(lines[len(items)]):
            items.append((start, end, lines[len(items)]))
            buffer, start = "", None
    return items if len(items) == len(lines) and not _normalized(buffer) else None


def rate_to_percent(rate):
    """语速倍率转 edge-tts 需要的带符号百分比；无效值按正常语速处理。"""
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    if not math.isfinite(rate) or rate <= 0:
        rate = 1.0
    percent = round((rate - 1.0) * 100)
    return f"+{percent}%" if percent >= 0 else f"{percent}%"


def srt_time(seconds):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def to_srt(items):
    return "\n".join(f"{index}\n{srt_time(begin)} --> {srt_time(end)}\n{text}\n" for index, (begin, end, text) in enumerate(items, 1))


def parse_srt(text, strict=False, duration=None):
    """Preview skips invalid blocks. Strict delivery reports every bad block/range."""
    entries, errors = [], []
    if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
        raise SubtitleError(["字幕成片时长必须是有限正数"])
    for block_index, block in enumerate(re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")), 1):
        if not block.strip():
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        try:
            if index is None or index + 1 >= len(lines) or index not in {0, 1} or (index == 1 and not lines[0].isdigit()):
                raise ValueError("缺少有效时间行或字幕文字")
            begin, end = (_srt_seconds(part) for part in lines[index].split("-->", 1))
            if begin < 0 or end <= begin:
                raise ValueError("字幕起止时间无效")
            if duration is not None and end > duration + 0.001:
                raise ValueError(f"字幕结束 {end:.3f}s 超过成片 {duration:.3f}s")
            if any("-->" in line for line in lines[index + 1:]):
                raise ValueError("字幕块缺少分隔空行")
            entries.append((begin, end, "\n".join(lines[index + 1:])))
        except ValueError as exc:
            errors.append(f"SRT block {block_index}: {exc}")
    if strict and not entries and not errors:
        errors.append("SRT 没有有效字幕")
    if strict and errors:
        raise SubtitleError(errors)
    return entries


def _srt_seconds(value):
    match = re.fullmatch(r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


PHRASE = re.compile(r"[^，。！？；：、,.!?;:…]+[，。！？；：、,.!?;:…]*|[，。！？；：、,.!?;:…]+")


def _tokens(text):
    """空格分词；词内再按句内标点切成短语，短语之间不补空格。"""
    tokens = []
    for word in text.split(" "):
        pieces = PHRASE.findall(word) or [word]
        tokens.extend((" " if index == 0 else "", piece) for index, piece in enumerate(pieces))
    return tokens


def wrap_text(text, font, max_width):
    """按 Pillow 字体的实际宽度换行：优先在空格和句内标点后断开，短语超宽才按字符拆，闭合标点不落到行首。"""
    if "\n" in text:
        return [line for part in text.split("\n") for line in wrap_text(part, font, max_width)]

    def width(value):
        value = value.strip()
        if not value:
            return 0
        left, _, right, _ = font.getbbox(value)
        return right - left

    def split_long(token):
        lines, current = [], ""
        for char in token:
            candidate = current + char
            if width(candidate) <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = char
        if current:
            lines.append(current)
        return lines

    lines, current = [], ""
    for separator, token in _tokens(text):
        candidate = f"{current}{separator}{token}" if current else token
        if width(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if width(token) <= max_width:
            current = token
        else:
            pieces = split_long(token)
            lines.extend(pieces[:-1])
            current = pieces[-1]
    if current:
        lines.append(current)
    for index in range(1, len(lines)):
        if lines[index] and lines[index][0] in LINE_START_PUNCTUATION and len(lines[index - 1]) > 1:
            candidate = lines[index - 1][-1] + lines[index]
            if width(candidate) <= max_width:
                lines[index], lines[index - 1] = candidate, lines[index - 1][:-1]
    return [line.strip() for line in lines if line.strip()]
