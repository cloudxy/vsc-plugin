"""Local snapshot of the LibTV 创作精选 catalog and each canvas process.

The panel reads files captured into the workspace. It does not call LibTV.
"""
import gzip
import hashlib
import json
import os
import re
import zlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "vsc.featured-showcase/v1"
PROJECTION_SCHEMA = "vsc.featured-showcase-projection/v2"
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
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    if not isinstance(data.get("cards"), dict) or not isinstance(data.get("feeds"), dict):
        return None
    return data


class ProcessSnapshotError(ValueError):
    """A present local snapshot is unreadable or structurally invalid."""

    def __init__(self, code, message, status_code=422, issues=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.issues = issues or []


def _card(catalog, identity, root, structure_status=None):
    raw = catalog["cards"].get(identity)
    if not isinstance(raw, dict):
        return None
    card = dict(raw)
    card["processAvailable"] = bool(card.get("snapshotId"))
    if not card["processAvailable"]:
        status = "unpublished"
    elif structure_status:
        status = structure_status
    elif not isinstance(identity, str) or UUID.fullmatch(identity) is None:
        status = "invalid"
    else:
        status = _cached_structure_status(*_structure_arguments(root, identity, card.get("snapshotId")))
    card["structureStatus"] = status
    card["processReady"] = status == "ready"
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
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        # Prompt text can contain unfinished links. They have no usable media
        # suffix; an invalid actual output is reported by its own fetch.
        return ""
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
    # mixedList is the combined input list, so its typed copies are not extra facts.
    mixed = params.get("mixedList")
    groups = [("mixed", "mixedList", mixed)] if isinstance(mixed, list) and mixed else [
        ("image", "imageList", params.get("imageList")),
        ("video", "videoList", params.get("videoList")),
        ("video", "videoListV2", params.get("videoListV2")),
        ("audio", "audioList", params.get("audioList")),
        ("text", "textList", params.get("textList")),
    ]
    refs = []
    for kind, field, items in groups:
        if not isinstance(items, list):
            continue
        candidates = [(index, item) for index, item in enumerate(items)
                      if isinstance(item, dict) and isinstance(item.get("nodeId"), str) and item["nodeId"]]
        order = params.get(field + "Order")
        ordered = []
        remaining = list(candidates)
        if isinstance(order, list):
            for token in order:
                for offset, (index, item) in enumerate(remaining):
                    if isinstance(token, dict):
                        match = token.get("nodeId") == item["nodeId"] and all(
                            token.get(key) == item.get(key, index if key == "index" else None)
                            for key in ("index", "slot") if key in token)
                    elif isinstance(token, int) and not isinstance(token, bool):
                        match = index == token
                    else:
                        match = token == item["nodeId"]
                    if match:
                        ordered.append(remaining.pop(offset))
                        break
        ordered.extend(remaining)
        for order_index, (index, item) in enumerate(ordered):
            ref = dict(item)
            ref.update({"nodeId": item["nodeId"], "label": item.get("label") or "", "kind": kind,
                        "list": field, "listIndex": index, "order": order_index})
            refs.append(ref)
    return refs


def _issue(code, **fields):
    return {"code": code, **fields}


def normalize_snapshot(snapshot):
    """Project the published nodeKey format without changing its source facts."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list) or not isinstance(snapshot.get("edges"), list):
        return snapshot
    nodes, converted = [], False
    for raw in snapshot["nodes"]:
        if not isinstance(raw, dict) or isinstance(raw.get("id"), str) or not isinstance(raw.get("nodeKey"), str) or not isinstance(raw.get("data"), str):
            nodes.append(raw)
            continue
        try:
            data = json.loads(raw["data"])
        except ValueError:
            nodes.append(raw)
            continue
        if not isinstance(data, dict):
            nodes.append(raw)
            continue
        data = dict(data)
        if "resourceMeta" not in data and isinstance(data.get("_resourceMeta"), dict):
            data["resourceMeta"] = data["_resourceMeta"]
        position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
        coordinates = {}
        for axis, field in (("x", "positionX"), ("y", "positionY")):
            try:
                coordinates[axis] = _number(float(position.get(field, 0)))
            except (TypeError, ValueError, OverflowError):
                coordinates[axis] = 0
        node = dict(raw)
        node.update(id=raw["nodeKey"], data=data, position=coordinates,
                    type=data.get("type") if isinstance(data.get("type"), str) else "legacy-" + str(raw.get("type", "unknown")),
                    parentId=raw.get("parentKey") or "", legacySource=raw)
        nodes.append(node)
        converted = True
    if not converted:
        return snapshot
    edges = []
    for raw in snapshot["edges"]:
        if isinstance(raw, dict) and raw.get("id") is None and isinstance(raw.get("connectionId"), (str, int)) and not isinstance(raw.get("connectionId"), bool):
            edge = dict(raw)
            edge["id"] = str(raw["connectionId"])
            edges.append(edge)
        else:
            edges.append(raw)
    return {**snapshot, "nodes": nodes, "edges": edges, "sourceSnapshotFormat": "legacy-node-key"}


def _validate_snapshot(snapshot):
    snapshot = normalize_snapshot(snapshot)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list) or not isinstance(snapshot.get("edges"), list):
        raise ProcessSnapshotError("invalid_snapshot", "创作过程结构无效：需要 nodes 和 edges 列表")
    nodes = snapshot["nodes"]
    by_id = {}
    issues = []
    invalid = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            invalid.append(_issue("invalid_node", nodeIndex=index))
            continue
        if node["id"] in by_id:
            invalid.append(_issue("duplicate_node_id", nodeId=node["id"]))
        by_id[node["id"]] = node
    finished = set()
    for node_id, node in by_id.items():
        parent_id = node.get("parentId")
        if parent_id is not None and not isinstance(parent_id, str):
            invalid.append(_issue("invalid_parent", nodeId=node_id))
        elif parent_id and parent_id not in by_id:
            issues.append(_issue("missing_parent", nodeId=node_id, parentId=parent_id))
        trail = []
        visiting = set()
        current = node_id
        while current in by_id and current not in finished:
            if current in visiting:
                invalid.append(_issue("parent_cycle", nodeIds=trail[trail.index(current):]))
                break
            visiting.add(current)
            trail.append(current)
            parent = by_id[current].get("parentId")
            current = parent if isinstance(parent, str) else ""
        finished.update(trail)
    seen_edges = set()
    for index, edge in enumerate(snapshot["edges"]):
        if not isinstance(edge, dict) or not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str):
            invalid.append(_issue("invalid_edge", edgeIndex=index))
            continue
        edge_id = edge.get("id")
        if edge_id is not None and not isinstance(edge_id, str):
            invalid.append(_issue("invalid_edge_id", edgeIndex=index))
            continue
        if edge_id and edge_id in seen_edges:
            issues.append(_issue("duplicate_edge_id", edgeId=edge_id))
        if edge_id:
            seen_edges.add(edge_id)
        missing = [key for key in ("source", "target") if edge[key] not in by_id]
        if missing:
            issues.append(_issue("dangling_edge", edgeId=edge_id, missing=missing,
                                 source=edge["source"], target=edge["target"]))
    if invalid:
        raise ProcessSnapshotError("invalid_snapshot", "创作过程包含无效节点、重复 ID 或父级循环", issues=invalid + issues)
    return issues


def _signature(path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size) if path.is_file() else None
    except OSError:
        return None


def _archive_path(root, identity, snapshot_id):
    version = str(snapshot_id or "")
    if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", version) is None:
        return None
    return Path(root) / "sources" / "process-detail" / f"{identity}-{version}.json"


def _structure_arguments(root, identity, snapshot_id=None):
    if not isinstance(identity, str) or UUID.fullmatch(identity) is None:
        raise FileNotFoundError(identity)
    path = Path(root) / "processes" / f"{identity}.json.gz"
    signature = _signature(path)
    if not snapshot_id and signature is not None:
        try:
            snapshot_id = _gzip_record(str(path), signature).get("snapshotId")
        except ProcessSnapshotError:
            pass
    archive = _archive_path(root, identity, snapshot_id)
    return (str(Path(root)), identity, str(snapshot_id or ""), signature,
            str(archive) if archive else "", _signature(archive) if archive else None)


def _load_structure(root, identity, snapshot_id=None):
    return _cached_structure(*_structure_arguments(root, identity, snapshot_id))


@lru_cache(maxsize=512)
def _cached_structure_status(*arguments):
    # Cards cache only a small validation result, not every complete canvas graph.
    try:
        _cached_structure(*arguments)
        return "ready"
    except FileNotFoundError:
        return "missing"
    except ProcessSnapshotError:
        return "invalid"


@lru_cache(maxsize=8)
def _gzip_record(path, signature):
    try:
        record = json.loads(gzip.decompress(Path(path).read_bytes()))
        if not isinstance(record, dict):
            raise ValueError("record must be an object")
        return record
    except (OSError, EOFError, ValueError, UnicodeError, zlib.error):
        raise ProcessSnapshotError("corrupt_snapshot", "本机创作过程归档损坏，请重新采集", 409) from None


@lru_cache(maxsize=8)
def _cached_structure(root, identity, expected_version, process_signature, archive_name, archive_signature):
    path = Path(root) / "processes" / f"{identity}.json.gz"
    record = None
    archive_error = None
    issues = []
    if process_signature is not None:
        try:
            record = _gzip_record(str(path), process_signature)
        except ProcessSnapshotError as error:
            archive_error = error
    if record and expected_version and str(record.get("snapshotId") or "") != expected_version:
        issues.append(_issue("source_version_mismatch", source="gzip", expectedSnapshotId=expected_version,
                             actualSnapshotId=record.get("snapshotId")))
    if archive_signature is not None:
        try:
            response = json.loads(Path(archive_name).read_text(encoding="utf-8"))
            detail = response.get("data", {}).get("detail") if isinstance(response, dict) else None
            if not isinstance(detail, dict):
                raise ValueError("missing detail")
            actual_version = str(detail.get("snapshotId") or "")
            actual_id = detail.get("templateUuid")
            if actual_version != expected_version or (actual_id and actual_id != identity):
                issues.append(_issue("source_version_mismatch", source="rawArchive", expectedSnapshotId=expected_version,
                                     actualSnapshotId=detail.get("snapshotId")))
            else:
                snapshot = detail.get("snapshotData")
                snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
                validation_issues = _validate_snapshot(snapshot)
                if archive_error:
                    issues.append(_issue("corrupt_fallback_archive", source="gzip"))
                merged = dict(record or {})
                merged.update({key: value for key, value in detail.items() if key != "snapshotData"})
                return merged, snapshot, issues + validation_issues, "rawArchive"
        except (OSError, ValueError, UnicodeError, AttributeError, ProcessSnapshotError) as error:
            issues.append(_issue("invalid_source_archive", source="rawArchive"))
            if isinstance(error, ProcessSnapshotError):
                issues.extend({**item, "source": "rawArchive"} for item in error.issues)
            if record is None and archive_error is None:
                if isinstance(error, ProcessSnapshotError):
                    raise error
                raise ProcessSnapshotError("corrupt_snapshot", "本机创作过程来源归档损坏，请重新采集", 409) from None
    if archive_error:
        raise archive_error
    if record is None:
        if archive_signature is not None:
            raise ProcessSnapshotError("source_version_mismatch", "本机创作过程来源版本不匹配", 409, issues)
        raise FileNotFoundError(identity)
    snapshot = record.get("snapshot")
    return record, snapshot, issues + _validate_snapshot(snapshot), "gzip"


def _output_items(data):
    if isinstance(data.get("outputs"), list) and data["outputs"]:
        return data["outputs"]
    raw = data.get("url")
    urls = raw if isinstance(raw, list) else [raw] if raw is not None else []
    # Keep empty positions as well: reference indices and a selected output refer to slots.
    return urls


def _thumbnail(root, media_id, thumbnails):
    value = thumbnails.get(media_id) if media_id else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("filename")
    if not isinstance(value, str):
        return ""
    name = value[len(LOCAL_MEDIA):].split("?", 1)[0] if value.startswith(LOCAL_MEDIA) else value
    return f"{LOCAL_MEDIA}{name}" if resolve_media_name(root, name) else ""


def _thumbnails(root):
    try:
        data = json.loads((Path(root) / "thumbnails.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def project_snapshot(snapshot, root=None, issues=None, thumbnails=None):
    snapshot = normalize_snapshot(snapshot)
    issues = list(_validate_snapshot(snapshot) if issues is None else issues)
    thumbnails = thumbnails or {}
    drafted = []
    for raw in snapshot["nodes"]:
        node = dict(raw)
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
        measured = raw.get("measured") if isinstance(raw.get("measured"), dict) else {}
        task = data.get("taskInfo") if isinstance(data.get("taskInfo"), dict) else {}
        resource_meta = data.get("resourceMeta", raw.get("resourceMeta", {}))
        width = raw.get("width") if isinstance(raw.get("width"), (int, float)) else measured.get("width")
        height = raw.get("height") if isinstance(raw.get("height"), (int, float)) else measured.get("height")
        outputs = []
        meta_items = resource_meta.get("items") if isinstance(resource_meta, dict) else []
        for index, value in enumerate(_output_items(data)):
            metadata = dict(value) if isinstance(value, dict) else {}
            url = value if isinstance(value, str) else metadata.get("url", "")
            url = url if isinstance(url, str) else ""
            if isinstance(meta_items, list) and index < len(meta_items) and isinstance(meta_items[index], dict):
                metadata = {**meta_items[index], **metadata}
            local = localize_url(root, url) if root is not None and url else ""
            local = local if local.startswith(LOCAL_MEDIA) else ""
            if url.startswith(LOCAL_MEDIA):
                name = url[len(LOCAL_MEDIA):].split("?", 1)[0]
                digest = name.split(".", 1)[0] if MEDIA_NAME.fullmatch(name) else ""
            else:
                digest = media_digest(url) if url.startswith(("http://", "https://")) else ""
            outputs.append({"index": index, "url": local, "status": "local" if local else "missing" if url else "empty",
                            "mediaId": digest, "metadata": metadata})
        selected = next((data[key] for key in ("selectedOutputIndex", "selectedIndex", "activeOutputIndex", "activeIndex", "currentIndex")
                         if isinstance(data.get(key), int) and not isinstance(data.get(key), bool)), 0)
        if outputs and (selected < 0 or selected >= len(outputs)):
            issues.append(_issue("invalid_selected_output", nodeId=raw["id"], index=selected))
            selected = 0
        primary = outputs[selected] if outputs else {}
        poster = localize_url(root, data.get("poster")) if root is not None and isinstance(data.get("poster"), str) else ""
        poster = poster if poster.startswith(LOCAL_MEDIA) else ""
        if not poster and root is not None:
            poster = _thumbnail(root, primary.get("mediaId"), thumbnails)
        children = data.get("childNodeIds") if isinstance(data.get("childNodeIds"), list) else []
        node.update({
            "id": raw["id"], "type": raw.get("type") or data.get("type") or "",
            "name": data.get("name") or "", "action": data.get("action") or "",
            "parentId": raw.get("parentId") if isinstance(raw.get("parentId"), str) else "",
            "relativePosition": {"x": _number(position.get("x")), "y": _number(position.get("y"))},
            "width": _number(width, 640 if raw.get("type") == "group" else 280),
            "height": _number(height, 420 if raw.get("type") == "group" else 160),
            "url": primary.get("url", ""), "poster": poster, "outputs": outputs, "selectedOutputIndex": selected,
            "mediaStatus": "local" if any(item["status"] == "local" for item in outputs) else "missing" if any(item["status"] == "missing" for item in outputs) else "empty",
            "params": params, "resourceMeta": resource_meta,
            "prompt": params.get("prompt") if isinstance(params.get("prompt"), str) else "",
            "model": params.get("model") if isinstance(params.get("model"), str) else "",
            "modeType": params.get("modeType") if isinstance(params.get("modeType"), str) else "",
            "settings": params.get("settings") if isinstance(params.get("settings"), dict) else {},
            "taskStatus": task.get("status") if isinstance(task.get("status"), int) else None,
            "groupColor": data.get("groupColor") if isinstance(data.get("groupColor"), str) else "",
            "childIds": [item for item in children if isinstance(item, str)], "refs": _references(params),
            "nodeHistory": data.get("nodeHistory"),
            "metadata": {key: value for key, value in data.items() if key not in ("url", "params", "resourceMeta")},
        })
        if "resourceMeta" in raw and "resourceMeta" in data:
            node["metadata"]["sourceResourceMeta"] = raw["resourceMeta"]
        if "metadata" in raw:
            node["metadata"]["sourceNodeMetadata"] = raw["metadata"]
        drafted.append(node)
    by_id = {node["id"]: node for node in drafted}
    absolute = {}
    for node in drafted:
        trail = []
        current = node
        while current and current["id"] not in absolute:
            trail.append(current)
            current = by_id.get(current["parentId"])
        x, y = absolute[current["id"]] if current else (0, 0)
        for member in reversed(trail):
            x += member["relativePosition"]["x"]
            y += member["relativePosition"]["y"]
            absolute[member["id"]] = (x, y)
    for node in drafted:
        node["x"], node["y"] = absolute[node["id"]]
        node["absolutePosition"] = {"x": node["x"], "y": node["y"]}
    media_nodes = [node for node in drafted if node["type"] in ("image", "video", "audio") or node["outputs"]]
    outputs = [item for node in media_nodes for item in node["outputs"]]
    local_outputs = sum(item["status"] == "local" for item in outputs)
    local_nodes = sum(node["mediaStatus"] == "local" for node in media_nodes)
    missing_nodes = sum(node["mediaStatus"] == "missing" for node in media_nodes)
    coverage = {"scope": "currentOutputs", "mediaNodes": len(media_nodes), "localMediaNodes": local_nodes,
                "missingMediaNodes": missing_nodes, "outputCount": len(outputs), "localOutputs": local_outputs,
                "status": "empty" if not any(item["status"] != "empty" for item in outputs) else "complete" if local_outputs == len(outputs) else "partial" if local_outputs else "missing"}
    projected = {**snapshot, "schema": PROJECTION_SCHEMA, "projectionVersion": 2,
                 "nodes": drafted, "edges": [dict(edge) for edge in snapshot["edges"]], "coverage": coverage, "issues": issues}
    return projected


def read_process(root, template_uuid):
    root = Path(root)
    catalog = load_catalog(root)
    raw_card = catalog["cards"].get(template_uuid) if catalog else None
    raw_card = raw_card if isinstance(raw_card, dict) else None
    if raw_card is not None and not raw_card.get("snapshotId"):
        raise ProcessSnapshotError("unpublished", "该创作过程尚未公开", 409)
    record, snapshot, issues, source = _load_structure(root, template_uuid, (raw_card or {}).get("snapshotId"))
    card = _card(catalog, template_uuid, root, "ready") if catalog else None
    payload = {
        "card": card or {"templateUuid": template_uuid, "name": record.get("name") or "", "snapshotId": record.get("snapshotId"),
                         "structureStatus": "ready", "processReady": True, "processAvailable": bool(record.get("snapshotId"))},
        "name": record.get("name") or (card or {}).get("name") or "",
        "description": record.get("description") or "", "finalOutput": record.get("finalOutput") or (card or {}).get("finalOutput") or "",
        "coverUrl": record.get("coverUrl") or "", "nickname": record.get("nickname") or "",
        "playCount": record.get("playCount"), "viewCreationProcessCount": record.get("viewCreationProcessCount"),
        "copyCanvasCount": record.get("copyCanvasCount"),
        "process": project_snapshot(snapshot, root, issues, _thumbnails(root)),
    }
    payload["process"]["source"] = {"kind": source, "snapshotId": record.get("snapshotId")}
    return localize_value(root, payload)
