"""Local snapshot of the LibTV 创作精选 catalog and each canvas process.

The panel reads files captured into the workspace. It does not call LibTV.
"""
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "vsc.featured-showcase/v1"
UUID = re.compile(r"^[0-9a-fA-F]{16,64}$")
PAGE_LIMIT = 20
LOCAL_MEDIA = "/featured-showcase-media/"
MEDIA_NAME = re.compile(r"^[0-9a-f]{64}(?:\.[a-z0-9]{1,8})?$")
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+")
LOCAL_MEDIA_IN_TEXT = re.compile(r"/featured-showcase-media/[^\s\"'<>]+")
MEDIA_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".mp4", ".webm", ".mov", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".ogg")
_media_hits = {}


def showcase_root(override=None):
    if override:
        return Path(override)
    env = os.environ.get("VSC_FEATURED_SHOWCASE_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "vsc").is_dir():
            return parent / "assets" / "featured-showcase"
    return Path.cwd() / "assets" / "featured-showcase"


def _empty():
    return {"schema": SCHEMA, "tags": [], "feeds": {}, "cards": {}}


def load_catalog(root):
    path = Path(root) / "catalog.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    if not isinstance(data.get("cards"), dict) or not isinstance(data.get("feeds"), dict):
        return None
    return data


def _card(catalog, identity, root):
    raw = catalog["cards"].get(identity)
    if not isinstance(raw, dict):
        return None
    card = dict(raw)
    card["processReady"] = bool(card.get("snapshotId")) and (Path(root) / "processes" / f"{identity}.json.gz").is_file()
    card["processAvailable"] = bool(card.get("snapshotId"))
    return localize_value(root, card)


def list_works(root, tag_id="0", query="", offset=0, limit=PAGE_LIMIT):
    root = Path(root)
    catalog = load_catalog(root)
    if catalog is None:
        return {"ready": False, "tags": [], "items": [], "total": 0, "offset": 0, "limit": PAGE_LIMIT, "hasMore": False}
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = min(60, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = PAGE_LIMIT
    tag_key = str(tag_id or "0")
    if tag_key not in catalog["feeds"] and tag_key != "0":
        tag_key = "0"
    identities = [item for item in catalog["feeds"].get(tag_key, []) if item in catalog["cards"]]
    needle = str(query or "").strip().casefold()
    if needle:
        matched = []
        for identity in identities:
            card = catalog["cards"][identity]
            haystack = " ".join(str(card.get(key) or "") for key in ("name", "description", "nickname")).casefold()
            if needle in haystack:
                matched.append(identity)
        identities = matched
    page = identities[offset:offset + limit]
    items = [card for card in (_card(catalog, identity, root) for identity in page) if card]
    tags = []
    for tag in catalog.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        key = str(tag.get("id"))
        tags.append({
            "id": tag.get("id"),
            "code": tag.get("code") or "",
            "label": tag.get("label") or "",
            "count": len(catalog["feeds"].get(key, [])),
        })
    return {
        "ready": True,
        "tags": tags,
        "items": items,
        "total": len(identities),
        "offset": offset,
        "limit": limit,
        "hasMore": offset + limit < len(identities),
    }


def _number(value, default=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _media_url(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item:
                return item
    return ""


def media_digest(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def media_suffix(url):
    path = urlsplit(url).path.lower()
    for ext in MEDIA_SUFFIXES:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ""


def sniff_suffix(header):
    sample = bytes(header[:16])
    if sample.startswith(b"\x89PNG"):
        return ".png"
    if sample.startswith(b"\xff\xd8"):
        return ".jpg"
    if sample.startswith(b"GIF8"):
        return ".gif"
    if sample.startswith(b"RIFF") and sample[8:12] == b"WEBP":
        return ".webp"
    if len(sample) >= 8 and sample[4:8] == b"ftyp":
        return ".mp4"
    if sample.startswith(b"ID3") or sample[:2] == b"\xff\xfb":
        return ".mp3"
    if sample.startswith(b"OggS"):
        return ".ogg"
    if sample.startswith(b"RIFF") and sample[8:12] == b"WAVE":
        return ".wav"
    return ".bin"


def resolve_media_name(root, name):
    if not isinstance(name, str) or MEDIA_NAME.fullmatch(name) is None:
        return None
    digest = name.split(".", 1)[0]
    path = Path(root) / "media" / digest[:2] / name
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


def find_media(root, url):
    key = (str(Path(root)), url)
    cached = _media_hits.get(key)
    if cached is not None and cached.is_file() and cached.stat().st_size > 0:
        return cached
    digest = media_digest(url)
    folder = Path(root) / "media" / digest[:2]
    if not folder.is_dir():
        return None
    for child in folder.iterdir():
        if child.is_file() and child.name.startswith(digest) and MEDIA_NAME.fullmatch(child.name) and child.stat().st_size > 0:
            _media_hits[key] = child
            return child
    return None


def media_paths(root, url, suffix=None):
    chosen = suffix or media_suffix(url) or ".bin"
    if chosen == ".jpeg":
        chosen = ".jpg"
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", chosen or ""):
        chosen = ".bin"
    digest = media_digest(url)
    folder = Path(root) / "media" / digest[:2]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}{chosen}", folder / f".{digest}.part"


def store_media(root, url, payload, suffix=None):
    body = bytes(payload)
    if not body:
        raise ValueError("empty media")
    chosen = suffix or media_suffix(url) or sniff_suffix(body)
    target, temporary = media_paths(root, url, chosen)
    temporary.write_bytes(body)
    temporary.replace(target)
    _media_hits[(str(Path(root)), url)] = target
    return target


def localize_url(root, url, drop_missing=True):
    text = url.strip()
    if text.startswith(LOCAL_MEDIA):
        ready = resolve_media_name(root, text[len(LOCAL_MEDIA):].split("?", 1)[0]) is not None
        return text if ready or not drop_missing else ""
    if text.startswith(("http://", "https://")):
        found = find_media(root, text)
        if found is not None:
            return f"{LOCAL_MEDIA}{found.name}"
        return "" if drop_missing else text
    return url


def localize_string(root, value, drop_missing=True):
    if "http://" not in value and "https://" not in value and LOCAL_MEDIA not in value:
        return value
    if URL_IN_TEXT.fullmatch(value) or LOCAL_MEDIA_IN_TEXT.fullmatch(value):
        return localize_url(root, value, drop_missing)
    localized = URL_IN_TEXT.sub(lambda match: localize_url(root, match.group(0), drop_missing), value)
    return LOCAL_MEDIA_IN_TEXT.sub(lambda match: localize_url(root, match.group(0), drop_missing), localized)


def localize_value(root, value, drop_missing=True):
    if isinstance(value, str):
        return localize_string(root, value, drop_missing)
    if isinstance(value, list):
        return [localize_value(root, item, drop_missing) for item in value]
    if isinstance(value, dict):
        return {key: localize_value(root, item, drop_missing) for key, item in value.items()}
    return value


def _references(params):
    mixed = params.get("mixedList")
    groups = [("mixed", mixed)] if isinstance(mixed, list) and mixed else [
        ("image", params.get("imageList")),
        ("video", params.get("videoList")),
        ("audio", params.get("audioList")),
    ]
    seen = set()
    refs = []
    for kind, items in groups:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            node_id = item.get("nodeId")
            if not isinstance(node_id, str) or not node_id or node_id in seen:
                continue
            seen.add(node_id)
            refs.append({"nodeId": node_id, "label": item.get("label") or "", "kind": kind})
    return refs


def _settings(params):
    raw = params.get("settings")
    if not isinstance(raw, dict):
        return {}
    kept = {}
    for key in ("ratio", "resolution", "duration", "enableSound"):
        value = raw.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            kept[key] = value
    return kept


def project_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        snapshot = {}
    raw_nodes = [node for node in snapshot.get("nodes") or [] if isinstance(node, dict) and isinstance(node.get("id"), str)]
    drafted = []
    for node in raw_nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        position = node.get("position") if isinstance(node.get("position"), dict) else {}
        measured = node.get("measured") if isinstance(node.get("measured"), dict) else {}
        task = data.get("taskInfo") if isinstance(data.get("taskInfo"), dict) else {}
        width = node.get("width") if isinstance(node.get("width"), (int, float)) else measured.get("width")
        height = node.get("height") if isinstance(node.get("height"), (int, float)) else measured.get("height")
        children = data.get("childNodeIds") if node.get("type") == "group" and isinstance(data.get("childNodeIds"), list) else []
        drafted.append({
            "id": node["id"],
            "type": node.get("type") or data.get("type") or "",
            "name": data.get("name") or "",
            "action": data.get("action") or "",
            "parentId": node.get("parentId") if isinstance(node.get("parentId"), str) else "",
            "x": _number(position.get("x")),
            "y": _number(position.get("y")),
            "width": _number(width, 280 if node.get("type") != "group" else 640),
            "height": _number(height, 160 if node.get("type") != "group" else 420),
            "url": _media_url(data.get("url")),
            "poster": data.get("poster") if isinstance(data.get("poster"), str) else "",
            "prompt": params.get("prompt") if isinstance(params.get("prompt"), str) else "",
            "model": params.get("model") if isinstance(params.get("model"), str) else "",
            "modeType": params.get("modeType") if isinstance(params.get("modeType"), str) else "",
            "settings": _settings(params),
            "taskStatus": task.get("status") if isinstance(task.get("status"), int) else None,
            "groupColor": data.get("groupColor") if isinstance(data.get("groupColor"), str) else "",
            "childIds": [item for item in children if isinstance(item, str)],
            "refs": _references(params),
        })
    by_id = {node["id"]: node for node in drafted}
    cache = {}

    def absolute(node, stack):
        if node["id"] in cache:
            return cache[node["id"]]
        parent = by_id.get(node["parentId"])
        if parent is None or node["id"] in stack:
            point = (node["x"], node["y"])
        else:
            px, py = absolute(parent, stack | {node["id"]})
            point = (px + node["x"], py + node["y"])
        cache[node["id"]] = point
        return point

    for node in drafted:
        node["x"], node["y"] = absolute(node, frozenset())
    edges = []
    for edge in snapshot.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("source"), edge.get("target")
        if source in by_id and target in by_id:
            edges.append({"id": edge.get("id") or f"{source}-{target}", "source": source, "target": target})
    return {"nodes": drafted, "edges": edges, "savedAt": snapshot.get("savedAt")}


def read_process(root, template_uuid):
    if not isinstance(template_uuid, str) or UUID.fullmatch(template_uuid) is None:
        raise FileNotFoundError(template_uuid)
    root = Path(root)
    path = root / "processes" / f"{template_uuid}.json.gz"
    if not path.is_file():
        raise FileNotFoundError(template_uuid)
    record = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(record, dict):
        raise FileNotFoundError(template_uuid)
    catalog = load_catalog(root)
    card = _card(catalog, template_uuid, root) if catalog else None
    payload = {
        "card": card or {"templateUuid": template_uuid, "name": record.get("name") or "", "snapshotId": record.get("snapshotId")},
        "name": record.get("name") or (card or {}).get("name") or "",
        "description": record.get("description") or "",
        "finalOutput": record.get("finalOutput") or (card or {}).get("finalOutput") or "",
        "coverUrl": record.get("coverUrl") or "",
        "nickname": record.get("nickname") or "",
        "playCount": record.get("playCount"),
        "viewCreationProcessCount": record.get("viewCreationProcessCount"),
        "copyCanvasCount": record.get("copyCanvasCount"),
        "process": project_snapshot(record.get("snapshot")),
    }
    return localize_value(root, payload)
