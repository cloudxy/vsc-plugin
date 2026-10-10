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


def parse_srt(text):
    """解析 SRT 为 [(开始秒, 结束秒, 文本)]；跳过无效块。"""
    entries = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None or index + 1 >= len(lines):
            continue
        try:
            begin, end = (_srt_seconds(part) for part in lines[index].split("-->", 1))
        except ValueError:
            continue
        if end > begin:
            entries.append((begin, end, "\n".join(lines[index + 1:])))
    return entries


def _srt_seconds(value):
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        raise ValueError(value)
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


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
