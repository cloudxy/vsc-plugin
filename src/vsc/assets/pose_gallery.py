"""Local reference galleries: costumes, poses and portraits for the character studio.

The datasets and images stay in the ignored ``assets/pose-gallery`` directory of the
workspace; nothing here is packaged.  Items keep the original Chinese field names so
the browser recipe, prompt builder and ComfyUI workflow receive the same structure
as the upstream gallery.  Relative ``thumbs/`` and ``img/`` paths are resolved by the
media endpoint, while remote gallery URLs stay untouched.
"""
from __future__ import annotations

import json
import random
import threading
from collections import Counter
from pathlib import Path

PAGE_SIZE = 24
MAX_LIMIT = 120
GALLERY_DIR = "pose-gallery"
MEDIA_PREFIXES = ("thumbs/", "img/")
MEDIA_SUFFIXES = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
NSFW_POSE_SYSTEMS = frozenset({"全身单人・性感系", "双人缠绵"})
NSFW_COSTUME_CATEGORIES = frozenset({"内衣・睡衣", "性感穿搭"})
POSE_LINE_ORDER = ("全身单人・标准系", "上半身单人", "全身单人・性感系", "双人缠绵")
ANGLES = ("正面", "俯视", "仰视", "侧面", "斜侧")
COSTUME_TOPS = ("现实", "二次元")
COSTUME_SOURCES = (
    {"id": "gia", "label": "ギア · 写实服装", "top": "现实", "url": "https://ai-costume-gallery.pages.dev/",
     "notice": "ギア（@giaaibusi）AI 服装参考。"},
    {"id": "shisei", "label": "Shisei · 中国历代", "top": "现实", "url": "https://github.com/wquguru/shisei",
     "notice": "wquguru 的 AI 生成服装参考，CC0；请标注来源。并非专业历史服饰复原。"},
    {"id": "gia-anime", "label": "ギア · 动漫服装", "top": "二次元", "url": "https://ai-costume-anime-gallery.pages.dev/",
     "notice": "仅收录元数据，图片由ギア原站提供；使用请遵守原站说明。"},
    {"id": "charadb", "label": "たき AI · CharaDB", "top": "二次元", "url": "https://github.com/taki-ttt/charadb/blob/main/LICENSE",
     "notice": "仅供参考，须遵守原作者限制（禁止真人、未成年人用途及图片再分发）；请阅读来源条款。"},
)
COSTUME_FILES = ("costume-zh.json", "costume-shisei-zh.json", "costume-gia-anime-zh.json", "costume-anime-zh.json")
_lock = threading.Lock()
_cache: dict = {}


def gallery_root(repository: Path) -> Path:
    return Path(repository) / "assets" / GALLERY_DIR


def _signature(paths):
    sig = []
    for path in paths:
        try:
            stat = path.stat()
            sig.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            sig.append((str(path), None, None))
    return tuple(sig)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _cached(key, paths, build):
    sig = _signature(paths)
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] == sig:
            return entry[1]
    value = build()
    with _lock:
        _cache[key] = (sig, value)
    return value


def _tokens(q) -> list:
    return [t for t in str(q or "").lower().split() if t][:8]


def _matches(text: str, tokens) -> bool:
    return all(t in text for t in tokens)


def _bounds(offset, limit):
    if isinstance(offset, bool) or isinstance(limit, bool):
        raise ValueError("分页参数无效")
    offset, limit = int(offset), int(limit)
    if offset < 0 or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("分页参数无效")
    return offset, limit


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _page(rows, offset, limit):
    window = rows[offset:offset + limit]
    nxt = offset + limit if offset + limit < len(rows) else None
    return [_public(r) for r in window], nxt


# --------------------------------------------------------------------------- costumes

def _legacy_costumes(repository: Path):
    from vsc.assets.costume_gallery import cached_costumes
    items, _ = cached_costumes(Path(repository) / "assets")
    rows = []
    for item in items:
        image = item.get("image") or ""
        rows.append({
            "id": item["id"], "source": "gia", "一级分类": "现实", "分类": item.get("category") or "其他",
            "服装名称": item.get("label") or item.get("title") or item["id"], "标签": [],
            "关键词": item.get("keywords") or "", "缩略图": image, "预览图": image, "原图": image,
            "来源": "本地服饰", "来源地址": "", "检索": f"{item['id']} {item.get('keywords') or ''}",
        })
    return rows


def load_costumes(repository: Path):
    root = gallery_root(repository)
    paths = [root / "data" / name for name in COSTUME_FILES]

    def build():
        rows, seen = [], set()
        primary = _read(paths[0], None)
        if not isinstance(primary, list):
            source_rows = [(_legacy_costumes(repository), "gia")]
            mode = "legacy"
        else:
            source_rows = [(primary, "gia")] + [(_read(p, []), None) for p in paths[1:]]
            mode = "pose-gallery"
        meta = {s["id"]: s for s in COSTUME_SOURCES}
        for data, default_source in source_rows:
            if not isinstance(data, list):
                continue
            for raw in data:
                if not isinstance(raw, dict) or not raw.get("id") or raw["id"] in seen:
                    continue
                item = dict(raw)
                source = item.get("source") or default_source or "gia"
                item["source"] = source
                item.setdefault("一级分类", meta.get(source, {}).get("top", "现实"))
                item.setdefault("来源", meta.get(source, {}).get("label", source))
                item.setdefault("来源地址", meta.get(source, {}).get("url", ""))
                item.setdefault("标签", [])
                item.setdefault("预览图", item.get("原图") or item.get("缩略图") or "")
                item["敏感"] = bool(item.get("敏感")) or item.get("分类") in NSFW_COSTUME_CATEGORIES
                item["_text"] = " ".join(str(x) for x in (
                    item.get("检索"), item["id"], item.get("服装名称"), item.get("关键词"), item.get("日文名称"),
                    " ".join(item.get("标签") or []))).lower()
                seen.add(item["id"])
                rows.append(item)
        return {"items": rows, "by_id": {r["id"]: r for r in rows}, "mode": mode}

    legacy_dir = Path(repository) / "assets" / "服饰"
    return _cached(("costumes", str(root)), paths + [legacy_dir], build)


def costume_page(repository, *, top="", source="", category="", tag="", q="", safe=True,
                 offset=0, limit=PAGE_SIZE):
    offset, limit = _bounds(offset, limit)
    if top and top not in COSTUME_TOPS:
        raise ValueError("一级分类无效")
    data = load_costumes(repository)
    pool = [r for r in data["items"] if not (safe and r["敏感"])]
    hidden = len(data["items"]) - len(pool)
    in_top = [r for r in pool if not top or r["一级分类"] == top]
    sources = Counter(r["source"] for r in in_top)
    in_source = [r for r in in_top if not source or r["source"] == source]
    categories = Counter(r.get("分类") or "其他" for r in in_source)
    in_category = [r for r in in_source if not category or r.get("分类") == category]
    tag_counts = Counter(t for r in in_category for t in (r.get("标签") or []) if t)
    tokens = _tokens(q)
    rows = [r for r in in_category if (not tag or tag in (r.get("标签") or [])) and _matches(r["_text"], tokens)]
    items, nxt = _page(rows, offset, limit)
    return {
        "items": items, "total": len(rows), "total_all": len(pool), "offset": offset, "limit": limit,
        "next_offset": nxt, "hidden_sensitive_count": hidden, "dataset_mode": data["mode"],
        "tops": [{"name": t, "count": sum(1 for r in pool if r["一级分类"] == t)} for t in COSTUME_TOPS],
        "sources": [dict(s, count=sources.get(s["id"], 0)) for s in COSTUME_SOURCES if sources.get(s["id"])],
        "categories": [{"name": n, "count": c} for n, c in categories.items()],
        "tags": [{"name": n, "count": c} for n, c in tag_counts.most_common(120)],
    }


# --------------------------------------------------------------------------- poses

def load_poses(repository: Path):
    root = gallery_root(repository)
    paths = [root / "data" / "pose-zh.json"]

    def build():
        items = [dict(r) for r in _read(paths[0], []) if isinstance(r, dict) and r.get("id")]
        for item in items:
            item["_text"] = f"{item.get('姿势名称', '')} {item['id']} {item.get('分类', '')} {item.get('姿势编号', '')} {item.get('体系', '')}".lower()
        raw_lines = list(dict.fromkeys(i.get("体系", "") for i in items))
        lines = sorted(raw_lines, key=lambda x: POSE_LINE_ORDER.index(x) if x in POSE_LINE_ORDER else 99)
        groups, by_key = [], {}
        for item in items:
            key = f"{item.get('体系', '')}|{item.get('姿势编号') or item['id']}"
            group = by_key.get(key)
            if group is None:
                group = {"key": key, "system": item.get("体系", ""), "number": item.get("姿势编号", ""),
                         "name": item.get("姿势名称", ""), "category": item.get("分类", ""), "items": []}
                by_key[key] = group
                groups.append(group)
            group["items"].append(item)
        for group in groups:
            first = {}
            for item in group["items"]:
                first.setdefault(item.get("角度"), item)
            order = [first[a] for a in ANGLES if a in first]
            order += [i for i in group["items"] if i not in order]
            group["items"] = order
        groups.sort(key=lambda g: (lines.index(g["system"]) if g["system"] in lines else 99, str(g["number"])))
        return {"items": items, "groups": groups, "lines": lines, "by_id": {i["id"]: i for i in items}}

    return _cached(("poses", str(root)), paths, build)


def pose_page(repository, *, view="group", system="", category="", angle="", q="", safe=True,
              offset=0, limit=PAGE_SIZE):
    offset, limit = _bounds(offset, limit)
    if view not in {"group", "single"}:
        raise ValueError("视图模式无效")
    data = load_poses(repository)
    if safe and system in NSFW_POSE_SYSTEMS:
        system = ""
    items = [i for i in data["items"] if not (safe and i.get("体系") in NSFW_POSE_SYSTEMS)]
    lines = [line for line in data["lines"] if not (safe and line in NSFW_POSE_SYSTEMS)]
    line_items = [i for i in items if not system or i.get("体系") == system]
    categories = sorted({i.get("分类") for i in line_items if i.get("分类")})
    tokens = _tokens(q)

    def ok(item):
        return (not angle or item.get("角度") == angle) and _matches(item["_text"], tokens)

    payload = {"view": view, "offset": offset, "limit": limit, "total_poses": len(data["items"]),
               "hidden_sensitive_count": len(data["items"]) - len(items),
               "systems": [{"name": line, "count": sum(1 for i in items if i.get("体系") == line)} for line in lines],
               "categories": categories, "angles": list(ANGLES)}
    if view == "group":
        groups = [g for g in data["groups"]
                  if not (safe and g["system"] in NSFW_POSE_SYSTEMS)
                  and (not system or g["system"] == system)
                  and (not category or g["category"] == category)
                  and any(ok(i) for i in g["items"])]
        window = groups[offset:offset + limit]
        payload.update(items=[dict(g, items=[_public(i) for i in g["items"]]) for g in window],
                       total=len(groups), total_groups=len(groups),
                       next_offset=offset + limit if offset + limit < len(groups) else None)
    else:
        rows = [i for i in line_items if (not category or i.get("分类") == category) and ok(i)]
        page, nxt = _page(rows, offset, limit)
        payload.update(items=page, total=len(rows), next_offset=nxt)
    return payload


# --------------------------------------------------------------------------- portraits

def load_portraits(repository: Path):
    root = gallery_root(repository)
    paths = [root / "data" / "portrait-zh.json", root / "data" / "portrait-meta-zh.json"]

    def build():
        items = [dict(r) for r in _read(paths[0], []) if isinstance(r, dict) and r.get("id")]
        for item in items:
            item["_text"] = " ".join(str(item.get(k) or "") for k in ("检索", "id", "标题", "发型名称", "发长", "分区")).lower()
        meta = _read(paths[1], {}) or {}
        sections = meta.get("分区列表") or list(dict.fromkeys(i.get("分区") for i in items if i.get("分区")))
        lengths = meta.get("发长列表") or list(dict.fromkeys(i.get("发长") for i in items if i.get("发长")))
        return {"items": items, "sections": sections, "lengths": lengths, "by_id": {i["id"]: i for i in items}}

    return _cached(("portraits", str(root)), paths, build)


def portrait_page(repository, *, section="", hair="", style="", hot=False, q="", offset=0, limit=PAGE_SIZE):
    offset, limit = _bounds(offset, limit)
    data = load_portraits(repository)
    items = data["items"]
    in_section = [i for i in items if not section or i.get("分区") == section]
    in_hair = [i for i in in_section if not hair or i.get("发长") == hair]
    styles = Counter(i.get("发型名称") for i in in_hair if i.get("发型名称"))
    tokens = _tokens(q)
    rows = [i for i in in_hair if (not style or i.get("发型名称") == style) and (not hot or i.get("热门"))
            and _matches(i["_text"], tokens)]
    page, nxt = _page(rows, offset, limit)
    return {
        "items": page, "total": len(rows), "total_all": len(items), "offset": offset, "limit": limit, "next_offset": nxt,
        "sections": [{"name": s, "count": sum(1 for i in items if i.get("分区") == s)} for s in data["sections"]],
        "hair_lengths": [{"name": h, "count": sum(1 for i in in_section if i.get("发长") == h)} for h in data["lengths"]],
        "hair_styles": [{"name": n, "count": c} for n, c in styles.most_common()],
        "hot_count": sum(1 for i in in_hair if i.get("热门")),
    }


# --------------------------------------------------------------------------- random

def _pick(rows, rng=random):
    return _public(rng.choice(rows)) if rows else None


def random_reference(repository, slot, *, scope="similar", current_id="", safe=True, rng=random):
    """Pick one replacement for a recipe slot from the full server-side pool."""
    if scope not in {"similar", "all"}:
        raise ValueError("换样范围无效")
    if slot == "portrait":
        data = load_portraits(repository)
        current = data["by_id"].get(current_id)
        if scope == "similar" and current_id and current is None:
            return None
        rows = [i for i in data["items"] if i["id"] != current_id and (
            scope == "all" or current is None or (i.get("分区") == current.get("分区") and i.get("发长") == current.get("发长")))]
    elif slot == "costume":
        data = load_costumes(repository)
        current = data["by_id"].get(current_id)
        if scope == "similar" and current_id and current is None:
            return None
        rows = [i for i in data["items"] if i["id"] != current_id and not (safe and i["敏感"]) and (
            scope == "all" or current is None or (i["source"] == current["source"] and i["一级分类"] == current["一级分类"]
                                                   and i.get("分类") == current.get("分类")))]
    elif slot == "pose":
        data = load_poses(repository)
        current = data["by_id"].get(current_id)
        if scope == "similar" and current_id and current is None:
            return None
        rows = [i for i in data["items"] if i["id"] != current_id and not (safe and i.get("体系") in NSFW_POSE_SYSTEMS) and (
            scope == "all" or current is None or (i.get("体系") == current.get("体系") and i.get("分类") == current.get("分类")))]
    else:
        raise ValueError("参考槽位无效")
    return _pick(rows, rng)


def random_recipe(repository, *, safe=True, rng=random):
    """Whole-recipe draw: realistic ギア costumes only, as in the upstream studio."""
    portraits = load_portraits(repository)["items"]
    costumes = [i for i in load_costumes(repository)["items"]
                if i["source"] == "gia" and i["一级分类"] == "现实" and not (safe and i["敏感"])]
    poses = [i for i in load_poses(repository)["items"] if not (safe and i.get("体系") in NSFW_POSE_SYSTEMS)]
    return {"portrait": _pick(portraits, rng), "costume": _pick(costumes, rng), "pose": _pick(poses, rng)}


# --------------------------------------------------------------------------- media

def media_file(repository, subpath: str):
    """Resolve a relative ``thumbs/`` or ``img/`` path strictly inside the gallery."""
    clean = str(subpath or "").replace("\\", "/")
    if not clean.startswith(MEDIA_PREFIXES) or not clean.isprintable():
        return None
    parts = clean.split("/")
    if any(not part or part.startswith(".") for part in parts):
        return None
    root = gallery_root(repository).resolve()
    path = (root / clean)
    if path.suffix.lower() not in MEDIA_SUFFIXES:
        return None
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def media_type(path: Path) -> str:
    return MEDIA_SUFFIXES.get(path.suffix.lower(), "application/octet-stream")
