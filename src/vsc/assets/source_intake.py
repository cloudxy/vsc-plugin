"""Local, bounded source extraction and auditable screenplay structure proposals.

Source bytes are data. No parser executes document instructions, invokes a
provider, invents stable objects, or makes creative/rights approval decisions.
"""
import hashlib
import io
import re
import shutil
import subprocess
import zipfile
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from vsc.assets.resource_service import ResourceError

PARSER_VERSION = "vsc-local-source/1"
SCHEMA_VERSION = "vsc.source-structure/1"
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 2_000_000
FORMATS = ("paste", "txt", "md", "docx", "pdf", "xlsx", "image", "audio", "video", "unknown")


def source_evidence_uri(value):
    """An optional external locator, never a title or a filesystem read request."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise ResourceError("evidence_uri 必须为有效 URI；来源名称请填写 title", "invalid_evidence_uri")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ResourceError("evidence_uri 格式无效", "invalid_evidence_uri") from exc
    if not parsed.scheme or not (parsed.netloc or parsed.path) or (parsed.scheme in {"http", "https", "s3"} and not parsed.netloc):
        raise ResourceError("evidence_uri 必须包含合法协议与地址", "invalid_evidence_uri")
    return value


def source_intake_capabilities():
    pdf = bool(shutil.which("pdftotext"))
    rows = []
    for fmt in FORMATS:
        available = fmt in ("paste", "txt", "md", "docx", "xlsx") or (fmt == "pdf" and pdf)
        limitations = {"xlsx": "必须明确 sheet 及列映射；公式只读取已有缓存值",
            "pdf": "仅文本 PDF；扫描页需要另配 OCR", "image": "未配置 OCR",
            "audio": "未配置 ASR", "video": "未配置 ASR", "unknown": "只登记来源，不支持解析",
            "docx": "提取正文段落和表格；不提取嵌入图、批注或文本框",
            "txt": "UTF-8/UTF-16 BOM，其他编码须明确指定", "md": "保留原始 Markdown 文本"}.get(fmt, "本地文本")
        rows.append({"format": fmt, "registration": True, "available": available,
                     "extractor": "pdftotext" if fmt == "pdf" and pdf else "stdlib" if available else None,
                     "limitation": limitations})
    return {"parser_version": PARSER_VERSION, "schema_version": SCHEMA_VERSION, "formats": rows,
            "paid_services": False, "automatic_approval": False, "max_source_bytes": MAX_SOURCE_BYTES}


def source_bytes(payload):
    if isinstance(payload.get("content"), str):
        raw = payload["content"].encode("utf-8")
    else:
        raise ResourceError("需要粘贴文本或文件内容", "source_content_required")
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ResourceError("来源必须为非空且不超过 10 MiB", "source_size_limit")
    return raw


def source_format(payload):
    fmt = payload.get("format")
    if fmt is None:
        suffix = PurePosixPath(str(payload.get("filename", ""))).suffix.lower().lstrip(".")
        fmt = suffix or ("paste" if "content" in payload else "unknown")
    return fmt if fmt in FORMATS else "unknown"


def _zip(raw):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        if sum(entry.file_size for entry in archive.infolist()) > 40 * 1024 * 1024:
            raise ResourceError("解压后文档超过限制", "source_size_limit")
        return archive
    except (zipfile.BadZipFile, OSError) as exc:
        raise ResourceError("文档不是有效的 Office 文件", "invalid_document") from exc


def _xml(archive, name):
    try:
        raw = archive.read(name)
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ResourceError("不允许带外部实体的 XML", "invalid_document")
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError) as exc:
        raise ResourceError("文档缺少必要结构或 XML 已损坏", "invalid_document") from exc


def _docx(raw):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    result = []
    with _zip(raw) as archive:
        root = _xml(archive, "word/document.xml")
        body = root.find("w:body", ns)
        if body is None:
            raise ResourceError("DOCX 缺少正文", "invalid_document")
        paragraph = 0
        for child in body:
            if child.tag.endswith("}p"):
                paragraph += 1
                result.append(("".join(t.text or "" for t in child.findall(".//w:t", ns)),
                               {"kind": "paragraph", "paragraph": paragraph}))
            elif child.tag.endswith("}tbl"):
                for row_no, row in enumerate(child.findall("w:tr", ns), 1):
                    for cell_no, cell in enumerate(row.findall("w:tc", ns), 1):
                        text = "\n".join("".join(t.text or "" for t in p.findall(".//w:t", ns)) for p in cell.findall("w:p", ns))
                        result.append((text, {"kind": "table_cell", "table_after_paragraph": paragraph, "row": row_no, "column": cell_no}))
    return result


def _xlsx(raw, mapping):
    if not isinstance(mapping, dict) or not mapping.get("sheet") or not isinstance(mapping.get("columns"), dict):
        raise ResourceError("XLSX 需要明确 sheet 与 columns（scene/text/speaker/kind）映射", "column_mapping_required")
    columns = mapping["columns"]
    if not columns.get("text") or any(key not in {"scene", "text", "speaker", "kind"} for key in columns):
        raise ResourceError("XLSX 列映射需要 text，且只能包含 scene/text/speaker/kind", "invalid_column_mapping")
    if any(not isinstance(c, str) or not re.fullmatch(r"[A-Z]{1,3}", c) for c in columns.values()):
        raise ResourceError("XLSX 列须使用 A、B 等列字母", "invalid_column_mapping")
    start = mapping.get("start_row", 2)
    if type(start) is not int or start < 1:
        raise ResourceError("start_row 必须是正整数", "invalid_column_mapping")
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    result = []
    with _zip(raw) as archive:
        workbook = _xml(archive, "xl/workbook.xml")
        rels = _xml(archive, "xl/_rels/workbook.xml.rels")
        sheet = next((s for s in workbook.findall("s:sheets/s:sheet", ns) if s.get("name") == mapping["sheet"]), None)
        if sheet is None:
            raise ResourceError("XLSX 指定工作表不存在", "invalid_column_mapping")
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = next((r.get("Target") for r in rels if r.get("Id") == rid), "")
        path = "xl/" + target if not target.startswith("/") else target.lstrip("/")
        if ".." in PurePosixPath(path).parts or not path.startswith("xl/"):
            raise ResourceError("工作表关系越界", "invalid_document")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(t.text or "" for t in si.findall(".//s:t", ns)) for si in _xml(archive, "xl/sharedStrings.xml").findall("s:si", ns)]
        for row in _xml(archive, path).findall("s:sheetData/s:row", ns):
            number = int(row.get("r", "0"))
            if number < start:
                continue
            cells = {}
            for cell in row.findall("s:c", ns):
                coordinate = cell.get("r", "")
                value = cell.findtext("s:v", "", ns)
                if cell.get("t") == "s":
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError) as exc:
                        raise ResourceError("XLSX 字符串索引无效", "invalid_document") from exc
                elif cell.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//s:t", ns))
                cells[re.sub(r"\d", "", coordinate)] = value
            fields = {key: cells.get(column, "") for key, column in columns.items()}
            if fields["text"].strip():
                result.append((fields["text"], {"kind": "cell", "sheet": mapping["sheet"],
                    "cell": columns["text"] + str(number), "row": number, "mapped_fields": fields}))
    return result


def extract_source(raw, fmt, parameters=None):
    """Return exact extracted text plus resolvable paragraph/page/cell ranges."""
    parameters = parameters or {}
    if not isinstance(parameters, dict):
        raise ResourceError("解析参数必须为对象", "invalid_payload")
    if fmt in ("paste", "txt", "md"):
        encoding = parameters.get("encoding") or ("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        try:
            original = raw.decode(encoding)
        except (UnicodeError, LookupError) as exc:
            raise ResourceError("文本编码不可读，请明确正确编码", "source_encoding_error") from exc
        anchors, cursor = [], 0
        for i, chunk in enumerate(original.splitlines(keepends=True), 1):
            line = chunk.rstrip("\r\n")
            if line.strip():
                anchors.append({"anchor_key": "P" + str(len(anchors) + 1), "start_char": cursor,
                    "end_char": cursor + len(line), "locator": {"kind": "line", "line": i}, "text": line})
            cursor += len(chunk)
        if not original.strip():
            raise ResourceError("没有可提取文本", "empty_extraction")
        if "\x00" in original or len(original) > MAX_EXTRACTED_CHARS:
            raise ResourceError("提取正文超过限制或含空字符", "source_size_limit")
        return {"text": original, "text_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "anchors": anchors, "layout": {"format": fmt, "encoding": encoding}, "warnings": []}
    elif fmt == "docx":
        segments = _docx(raw)
    elif fmt == "xlsx":
        segments = _xlsx(raw, parameters.get("column_mapping"))
    elif fmt == "pdf":
        executable = shutil.which("pdftotext")
        if not executable:
            raise ResourceError("未安装 PDF 文本提取器", "extractor_unavailable")
        try:
            completed = subprocess.run([executable, "-layout", "-enc", "UTF-8", "-", "-"], input=raw,
                                       capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ResourceError("PDF 文本提取失败或超时", "extraction_failed") from exc
        if completed.returncode:
            raise ResourceError("PDF 文本提取失败（可能加密或已损坏）", "extraction_failed")
        pages = completed.stdout.decode("utf-8").split("\f")
        segments = [(line, {"kind": "page_line", "page": page, "line": n})
                    for page, text in enumerate(pages, 1) for n, line in enumerate(text.splitlines(), 1)]
        blank_pages = [i for i, page in enumerate(pages[:-1] if pages[-1] == "" else pages, 1) if not page.strip()]
        if blank_pages:
            raise ResourceError("PDF 含无可提取文字页，需要 OCR；页 " + ",".join(map(str, blank_pages)), "ocr_required")
    else:
        raise ResourceError("此格式未配置可用提取器；来源已保留", "extractor_unavailable")
    text, anchors, cursor = [], [], 0
    for value, locator in segments:
        if not value.strip():
            continue
        if "\x00" in value:
            raise ResourceError("来源含无法用于文本解析的空字符", "invalid_document")
        anchors.append({"anchor_key": "P" + str(len(anchors) + 1), "start_char": cursor,
                        "end_char": cursor + len(value), "locator": locator, "text": value})
        text.append(value)
        cursor += len(value) + 1
        if cursor > MAX_EXTRACTED_CHARS:
            raise ResourceError("提取正文超过限制", "source_size_limit")
    joined = "\n".join(text)
    if not joined.strip():
        raise ResourceError("没有可提取文本；扫描文案需要 OCR", "ocr_required" if fmt == "pdf" else "empty_extraction")
    return {"text": joined, "text_sha256": hashlib.sha256(joined.encode()).hexdigest(),
            "anchors": anchors, "layout": {"format": fmt, "encoding": parameters.get("encoding")}, "warnings": []}


def structure_proposal(extractions):
    """Produce local structure for explicit human mapping, without name merges."""
    scenes, current, warnings, speakers = [], None, [], set()
    heading = re.compile(r"^(?:#{1,6}\s*)?(?:第.{1,12}场|场景\s*\d+|SC\d+|INT\.|EXT\.|内[景.]|外[景.])", re.I)
    for extraction in extractions:
        for anchor in extraction["anchors"]:
            text = anchor["text"].strip()
            fields = anchor["locator"].get("mapped_fields", {})
            label = fields.get("scene")
            if heading.match(text) or (label and (current is None or current["source_label"] != label)):
                current = {"key": "scene-" + str(len(scenes) + 1), "source_label": label or text,
                           "system_proposed": False, "units": []}
                scenes.append(current)
                if not fields:
                    continue
            if current is None:
                current = {"key": "scene-1", "source_label": "未标注场次", "system_proposed": True, "units": []}
                scenes.append(current)
                warnings.append("来源未标注场次；须明确映射到已有场，不自动创建默认部/序列")
            match = re.match(r"^([^：:\n]{1,40})[：:]\s*(.+)$", text)
            kind = fields.get("kind") or ("dialogue" if fields.get("speaker") or match else "action")
            speaker = fields.get("speaker") or (match.group(1).strip() if match else None)
            value = fields.get("text") or (match.group(2) if match else text)
            if kind not in ("action", "dialogue", "narration", "silence"):
                warnings.append("未知行类型须校对: " + kind)
                kind = "action"
            if speaker in ("旁白", "画外音", "NARRATOR") and not fields.get("kind"):
                kind = "narration"
            if kind == "dialogue" and speaker:
                speakers.add(speaker)
            current["units"].append({"key": "U" + str(sum(len(s["units"]) for s in scenes) + 1),
                "kind": kind, "speaker_text": speaker if kind == "dialogue" else None, "text": value,
                "anchor_id": anchor["id"], "source_id": extraction["source_id"]})
    labels = [scene["source_label"] for scene in scenes]
    if len(labels) != len(set(labels)):
        warnings.append("存在重复场号；保留为独立场次，须明确映射，不能按名称合并")
    return {"schema_version": SCHEMA_VERSION, "scenes": scenes, "speaker_names": sorted(speakers),
            "warnings": warnings, "automatic_approval": False, "required_mapping": ["scene_mapping", "speaker_mapping", "durations_ms"]}


def render_structured_body(document):
    lines = []
    for scene in document.get("scenes", []):
        lines.append(scene.get("source_label") or str(scene["id"]))
        units = [unit for key in ("actions", "dialogue", "silence") for unit in scene.get(key, [])]
        for unit in sorted(units, key=lambda unit: unit.get("source_order", 0)):
            text = unit.get("text", unit.get("purpose", "静默"))
            lines.append((str(unit.get("speaker_label") or unit["speaker"]) + "：" if unit.get("speaker") else "") + text)
    return "\n".join(lines)
