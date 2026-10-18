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
    from vsc.story import consistency as consistency
    from tools.maintenance.vendor_sync import ROOT, VENDOR
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
LINE_START_PUNCTUATION = "，。！？；：、,.!?;:…)]}）】》」』”’"


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
        if char in ".,:：" and previous.isdigit() and following.isdigit():
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
    if strict:
        errors.extend(check_overlaps([(begin, end, index) for index, (begin, end, _) in enumerate(entries, 1)]))
    if strict and errors:
        raise SubtitleError(errors)
    return entries


def _srt_seconds(value):
    match = re.fullmatch(r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


PHRASE = re.compile(r"(?:\d+(?:[.,:：/]\d+)+|[^，。！？；：、,.!?;:…])+[，。！？；：、,.!?;:…]*|[，。！？；：、,.!?;:…]+")


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
        # Keep a closing mark (including both halves of an ellipsis) with the
        # preceding character. A character-only split can strand punctuation
        # on a line by itself even when the next line has ample room.
        units = []
        for char in re.findall(_KEEP_TOKEN.pattern + r"|.", token):
            if char in LINE_START_PUNCTUATION and units:
                units[-1] += char
            else:
                units.append(char)
        lines, current = [], ""
        for unit in units:
            candidate = current + unit
            if width(candidate) <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = unit
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
        if lines[index] and lines[index][0] in LINE_START_PUNCTUATION:
            previous = lines[index - 1]
            anchor = len(previous) - 1
            while anchor > 0 and previous[anchor] in LINE_START_PUNCTUATION:
                anchor -= 1
            candidate = previous[anchor:] + lines[index]
            if anchor > 0 and width(candidate) <= max_width:
                lines[index], lines[index - 1] = candidate, previous[:anchor]
    return [line.strip() for line in lines if line.strip()]


# ---------- B4-01：显示派生与交付前纯检查（预览/烧录/导出共用） ----------

# 数字、小数、百分号、常见单位与间距标记整体保留，不因无标点化破坏语义。
_KEEP_TOKEN = re.compile(r"[+\-−]?\d+(?:[.,:：/]\d+)*(?:[%‰])?|[A-Za-z]+(?:/\d+(?:[.,]\d+)?)?")
_DISPLAY_DROP = "，。！？；：、“”‘’（）()【】[]《》〈〉…—·,.!?;:\"'"

def display_text(line):
    """显示文本：中文对白/旁白去掉句读标点，数字、单位、拉丁词整体保义（B4-01）。

    不改原稿：这只是派生视图，烧录、预览与导出使用同一结果。
    """
    if not isinstance(line, str):
        raise SubtitleError(["显示文本必须是字符串"])
    output = []
    cursor = 0
    for token in _KEEP_TOKEN.finditer(line):
        output.append(line[cursor:token.start()].translate(str.maketrans("", "", _DISPLAY_DROP)))
        output.append(token.group())
        cursor = token.end()
    output.append(line[cursor:].translate(str.maketrans("", "", _DISPLAY_DROP)))
    return "".join(output).strip()


def check_overlaps(items):
    """相邻 cue 重叠/乱序检查；items 为 [(start_seconds, end_seconds, id), ...]。"""
    errors, previous = [], None
    for start, end, identifier in items:
        if end <= start:
            errors.append(f"字幕 {identifier} 结束不晚于开始")
        if previous is not None and start < previous[1] - 1e-6:
            errors.append(f"字幕 {identifier} 与 {previous[2]} 重叠或乱序")
        previous = (start, end, identifier)
    return errors


def check_coverage(subtitle_texts, script_texts):
    """按原稿顺序消耗字幕文本；一次出现不能抵扣多句相同台词。"""
    corpus = re.sub(r"\s+", "", "".join(display_text(text) for text in subtitle_texts))
    missing, cursor = [], 0
    for index, text in enumerate(script_texts):
        shown = re.sub(r"\s+", "", display_text(text))
        if shown:
            position = corpus.find(shown, cursor)
            if position < 0:
                missing.append({"index": index, "text": text, "display": shown})
            else:
                cursor = position + len(shown)
    return missing


class _UnitFont:
    """无字体环境的等宽近似：CJK 全宽 1 单位，拉丁/数字/空白 0.5 单位。"""
    def getbbox(self, value):
        width = sum(1.0 if ord(char) > 0x2E7F else 0.5 for char in value)
        return (0, 0, width, 1)


def check_layout(text, font, max_width, max_lines=2):
    """行数/宽度纯检查（与烧录同一 wrap 规则），供预览与导出在渲染前复用。"""
    lines = wrap_text(display_text(text), font or _UnitFont(), max_width)
    return {"lines": len(lines), "ok": len(lines) <= max_lines, "rendered": lines}


MAX_WIDTH_RATIO = 0.82
MAX_LINES = 2


def layout_font(style, width):
    """Load the actual delivery font; a missing renderer is never a font pass."""
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(style["font"]), style["font_size"])
    except (ImportError, OSError, KeyError, TypeError, ValueError) as exc:
        raise SubtitleError(["字幕实际字体排版未验证：" + str(exc)]) from exc
    padding = int(style["font_size"] * (0.4 if style.get("rounded") else 0.6)) if style.get("background") else 0
    return font, max(1, int(width * MAX_WIDTH_RATIO) - 2 * padding - 2 * int(style["stroke_width"]))


def compile_cues(items, *, duration=None, script_texts=None, font=None, max_width=None, style=None, height=None):
    """Compile display cues without inventing or redistributing supplied timecodes.

    Text coverage is optional evidence, distinct from audio alignment. None of
    these interfaces receives adopted audio/line alignment, so it stays unverified.
    """
    items = list(items)
    errors = []
    for index, (begin, end, original) in enumerate(items, 1):
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (begin, end)) or begin < 0 or end <= begin:
            errors.append(f"第 {index} 条字幕时码无效")
        elif duration is not None and end > duration + 0.001:
            errors.append(f"第 {index} 条字幕超出成片时长")
        if not isinstance(original, str) or not original.strip():
            errors.append(f"第 {index} 条字幕缺少文字")
    if errors:
        raise SubtitleError(errors)
    errors.extend(check_overlaps([(begin, end, index) for index, (begin, end, _) in enumerate(items, 1)]))
    if script_texts is not None:
        if not isinstance(script_texts, (list, tuple)) or any(not isinstance(value, str) for value in script_texts):
            errors.append("字幕原稿必须是字符串数组")
        else:
            errors.extend(f"原稿第 {row['index'] + 1} 句字幕缺字或缺失：{row['display']}"
                          for row in check_coverage([item[2] for item in items], script_texts))
    compiled = []
    for index, (begin, end, original) in enumerate(items, 1):
        shown = display_text(original)
        if not shown:
            errors.append(f"第 {index} 条字幕显示文本为空")
        if font is not None and max_width is not None:
            lines = wrap_text(shown, font, max_width)
            widths = [font.getbbox(line)[2] - font.getbbox(line)[0] for line in lines]
            if len(lines) > MAX_LINES or any(value > max_width for value in widths):
                errors.append(f"第 {index} 条字幕超过 {MAX_LINES} 行或安全宽度；须按真实语音停顿提供分段时码")
            if style is not None and height is not None:
                ascent, descent = font.getmetrics()
                image_height = len(lines) * (ascent + descent) + max(0, len(lines) - 1) * int(style["font_size"] * .25) + 2 * int(style["font_size"] * .35) + 2 * int(style["stroke_width"])
                if image_height > height * (1 - 2 * SAFE_MARGIN):
                    errors.append(f"第 {index} 条字幕超出画幅安全高度；须调整已批准字体或分段时码")
            shown = "\n".join(lines)
        compiled.append((begin, end, shown))
    if errors:
        raise SubtitleError(errors)
    return {"cues": compiled, "checks": {"timecodes": "supplied_preserved", "overlaps": "passed",
            "text_coverage": "passed" if script_texts is not None else "not_checked",
            "font_layout": "passed" if font is not None and max_width is not None else "not_checked",
            "line_binding": "not_verified", "audio_alignment": "not_verified"}}


def read_script_texts(path):
    import json
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, list) or any(not isinstance(text, str) for text in value):
        raise SubtitleError(["字幕原稿文件必须为 JSON 字符串数组"])
    return value


PACKAGE_FORMAT = "vsc.subtitle-package/v1"
MEASUREMENT_METHODS = {"forced_alignment", "provider_word_timestamps", "manual_waveform", "pcm_activity_scan"}


def content_digest(value):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal_package(package):
    """Integrity of an exported projection; this does not create an approval."""
    return {**package, "package_sha256": content_digest({k: v for k, v in package.items() if k != "package_sha256"})}


def measurement_errors(measurement, *, line_key, audio_sha256, start_ms, end_ms):
    errors = []
    if not isinstance(measurement, dict):
        return ["缺少真实时码测量记录"]
    if measurement.get("method") not in MEASUREMENT_METHODS or not measurement.get("version") or not isinstance(measurement.get("evidence"), dict) or not measurement["evidence"]:
        errors.append("测量方法/版本/方法证据缺失；不接受按文字均分时长")
    if (measurement.get("line_key"), measurement.get("audio_media_sha256"), measurement.get("start_ms"), measurement.get("end_ms")) != (line_key, audio_sha256, start_ms, end_ms):
        errors.append("测量记录与台词行、采用音频或时码不一致")
    return errors


def package_cues(package, root, *, project_id=None, formal=True):
    """Verify a fixed package's snapshots/selected audio bytes, then derive cues.

    Approval decisions are captured by the PostgreSQL exporter, which reads the
    actual relations. Offline consumers verify that fixed evidence, not live
    approval state and not the semantic accuracy of an alignment algorithm.
    """
    import hashlib
    import json
    from collections import Counter
    errors = []
    if not isinstance(package, dict) or package.get("format") != PACKAGE_FORMAT:
        raise SubtitleError(["字幕包格式无效"])
    if package.get("package_sha256") != content_digest({k: v for k, v in package.items() if k != "package_sha256"}):
        errors.append("字幕包摘要已改变")
    if project_id is not None and package.get("project_id") != project_id:
        errors.append("字幕包项目范围不一致")
    scope_ids = set(package.get("scope_object_ids", []))
    if package.get("scope_episode_id") not in scope_ids:
        errors.append("字幕包分集范围与固定关系快照不一致")
    if formal and (package.get("status") != "verified" or package.get("gaps")):
        errors.append("正式字幕包缺少完整固定行/音频/实测时码依据")
    if formal and any(not package.get(key) for key in ("scripts", "lines", "audio_sources", "cues")):
        errors.append("正式字幕包不能缺少剧本行、采用音频或字幕Cue")
    fixed_artifacts = {}
    for snapshot in [package.get("timeline_artifact", {}), *package.get("cue_artifacts", [])]:
        if hashlib.sha256(snapshot.get("document_utf8", "").encode()).hexdigest() != snapshot.get("sha256") or not snapshot.get("approval_decision_id"):
            errors.append("时间线或声音Cue固定快照/批准凭据失效")
        fixed_artifacts[snapshot.get("id")] = snapshot
    scripts = {}
    for script in package.get("scripts", []):
        if hashlib.sha256(script.get("document_utf8", "").encode()).hexdigest() != script.get("sha256") or not script.get("approval_decision_id"):
            errors.append("批准剧本快照摘要或决定凭据不完整")
        scripts[script["id"]] = script
        document = json.loads(script["document_utf8"])
        if document.get("format") == "vsc.screenplay/v1":
            expected = [unit["id"] for scene in document.get("scenes", []) if scene["id"] in package.get("scope_scene_keys", [])
                for key in ("actions", "dialogue") for unit in scene.get(key, []) if key == "dialogue" or unit.get("kind") == "narration"]
        else:
            expected = [row["line_key"] for row in document.get("script_lines", []) if row.get("scene_id") in scope_ids and row.get("line_kind", "dialogue") in {"dialogue", "narration"}]
        actual = [line.get("line_key") for line in package.get("lines", []) if line.get("script_version_id") == script["id"]]
        if formal and sorted(expected) != sorted(actual):
            errors.append("字幕行未完整覆盖固定批准剧本范围")
    lines = {line["id"]: line for line in package.get("lines", [])}
    if len(lines) != len(package.get("lines", [])):
        errors.append("字幕包台词行身份重复")
    for line in lines.values():
        if line.get("scene_id") not in scope_ids:
            errors.append("字幕行超出固定分集范围")
        if line.get("script_version_id") not in scripts or line.get("script_version_sha256") != scripts[line["script_version_id"]]["sha256"]:
            errors.append("台词行与批准剧本版本不一致")
            continue
        document = json.loads(scripts[line["script_version_id"]]["document_utf8"])
        raw_lines = document.get("script_lines", [])
        if document.get("format") == "vsc.screenplay/v1":
            raw_lines = [unit for scene in document.get("scenes", []) for key in ("actions", "dialogue", "silence") for unit in scene.get(key, [])]
        candidates = [row for row in raw_lines if row.get("line_key", row.get("id")) == line.get("line_key")]
        if len(candidates) != 1 or candidates[0].get("text") != line.get("text"):
            errors.append("台词原文与固定批准剧本正文不一致")
    sources = {}
    root = Path(root).resolve()
    timeline_document = json.loads(package["timeline_artifact"]["document_utf8"])
    original_plan = timeline_document.get("render_plan")
    composition = (original_plan or timeline_document).get("composition", {})
    rate = composition.get("fps", 0)
    fps = rate["numerator"] / rate["denominator"] if isinstance(rate, dict) else rate
    if not fps:
        errors.append("固定时间线快照缺少真实帧率")
    receipt_path = root / "render-inputs.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text("utf-8"))
        if receipt.get("subtitle_package_sha256") != package["package_sha256"] or receipt.get("timeline_id") != package.get("timeline_id") or receipt.get("project_id") != package.get("project_id"):
            errors.append("字幕包与PG固定导出回执不一致")
    for source in package.get("audio_sources", []):
        relative = source.get("path", "")
        path = (root / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source.get("sha256"):
            errors.append("采用音频缺失或 SHA 已改变：" + str(source.get("media_id")))
        original_items = (original_plan or {}).get("segments", []) if original_plan else timeline_document.get("items", [])
        ordinal = source.get("item_ordinal")
        if type(ordinal) is not int or not 0 <= ordinal < len(original_items) or not fps:
            errors.append("采用音频缺少固定时间线片段身份")
        else:
            original = original_items[ordinal]
            if original_plan:
                selected = [row for row in timeline_document.get("bindings", []) if row.get("segment_id") == original.get("id") and row.get("sha256") == source["sha256"]]
                trim_in, trim_out = original.get("source_in_frame", 0), original.get("source_in_frame", 0) + original["duration_in_frames"]
                offset = original["from_frame"]
            else:
                selected = [row for row in original.get("media", []) if row.get("media_id") == source["media_id"] and row.get("binding_decision_id") == source["binding_decision_id"]]
                trim_in = selected[0]["source_in_frame"] if len(selected) == 1 else -1
                trim_out = selected[0]["source_out_frame"] if len(selected) == 1 else -1
                offset = original["offset_frame"]
            if len(selected) != 1 or any(abs(actual - expected * 1000 / fps) > .001 for actual, expected in [
                    (source["source_in_ms"], trim_in), (source["source_out_ms"], trim_out), (source["timeline_start_ms"], offset)]):
                errors.append("采用音频身份/裁切与批准时间线快照不一致")
        sources[source["item_id"]] = source
    result, counts = [], Counter()
    for cue in package.get("cues", []):
        line = lines.get(cue.get("line_id"))
        source = sources.get(cue.get("item_id"))
        if line is None or source is None:
            errors.append("字幕Cue引用了包范围外的行或采用音频")
            continue
        counts[line["id"]] += 1
        start, end = cue.get("source_start_ms"), cue.get("source_end_ms")
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            errors.append("字幕测量时码必须为真实源音频中的有效毫秒区间")
            continue
        if source.get("line_id") != line["id"] or cue.get("script_version_sha256") != line["script_version_sha256"] or cue.get("audio_media_sha256") != source["sha256"]:
            errors.append("字幕Cue的剧本或音频SHA不一致")
        if cue.get("source_text") != line.get("text") or not cue.get("approval_decision_id") or not cue.get("cue_artifact_sha256"):
            errors.append("字幕原文或声音Cue批准凭据不一致")
        snapshot = fixed_artifacts.get(cue.get("cue_artifact_id"), {})
        if snapshot.get("sha256") != cue.get("cue_artifact_sha256") or snapshot.get("approval_decision_id") != cue.get("approval_decision_id"):
            errors.append("字幕Cue版本与固定批准快照不一致")
        else:
            raw_cues = json.loads(snapshot["document_utf8"]).get("cues", [])
            raw = next((row for row in raw_cues if row.get("key") == cue.get("cue_key")), {})
            alignment = raw.get("parameters", {}).get("subtitle_alignment", {})
            if raw.get("scope_object_id") not in scope_ids or raw.get("line_id") != line["id"] or alignment.get("measurement") != cue.get("measurement") or alignment.get("script_version_sha256") != line["script_version_sha256"] or alignment.get("audio_media_sha256") != source["sha256"]:
                errors.append("字幕测量与已批准声音Cue正文不一致")
        errors.extend(measurement_errors(cue.get("measurement"), line_key=line["line_key"], audio_sha256=source["sha256"], start_ms=start, end_ms=end))
        if start < source["source_in_ms"] - .001 or end > source["source_out_ms"] + .001 or end > source["duration_ms"] + 1:
            errors.append("字幕实测区间超出采用音频裁切范围")
        begin = source["timeline_start_ms"] + start - source["source_in_ms"]
        finish = source["timeline_start_ms"] + end - source["source_in_ms"]
        if abs(begin - cue.get("start_ms", -1)) > .001 or abs(finish - cue.get("end_ms", -1)) > .001:
            errors.append("字幕时码与固定时间线映射不一致")
        result.append((begin / 1000, finish / 1000, line["text"]))
    if formal:
        for line in lines.values():
            if counts[line["id"]] != 1:
                errors.append("台词行必须恰有一次字幕覆盖：" + line["id"])
        if set(sources) != {cue.get("item_id") for cue in package.get("cues", [])}:
            errors.append("采用对白音频存在缺失或重复的字幕用料覆盖")
        for script_id in scripts:
            ordered = [line["id"] for line in sorted(lines.values(), key=lambda row: row["ordinal"]) if line["script_version_id"] == script_id]
            observed = [cue["line_id"] for cue in package.get("cues", []) if cue.get("line_id") in lines and lines[cue["line_id"]]["script_version_id"] == script_id]
            if ordered != observed:
                errors.append("字幕Cue顺序与固定批准台词行顺序不一致")
    if errors:
        raise SubtitleError(errors)
    compiled = compile_cues(result, duration=package["duration_ms"] / 1000)
    compiled["checks"].update(line_binding="verified" if package.get("status") == "verified" else "not_verified",
        audio_alignment="measured_timecodes_verified" if package.get("status") == "verified" else "not_verified",
        human_review="not_run", package_sha256=package["package_sha256"], text_coverage="line_ids_verified" if formal else "not_verified")
    return compiled


def caption_segments(package, fps):
    """Keep measured milliseconds; frame projection is an explicit render limit."""
    return [{"id": "subtitle-" + cue["cue_id"], "kind": "caption", "text": cue["source_text"],
             "from_frame": round(cue["start_ms"] * fps / 1000),
             "duration_in_frames": round(cue["end_ms"] * fps / 1000) - round(cue["start_ms"] * fps / 1000),
             "subtitle_start_ms": cue["start_ms"], "subtitle_end_ms": cue["end_ms"], "line_id": cue["line_id"]}
            for cue in package.get("cues", [])]
