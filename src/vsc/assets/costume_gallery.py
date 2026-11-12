"""Official costume browser for the 服饰 class.

The category order and search synonyms follow the public costume gallery
behavior observed at ai-costume-gallery.pages.dev. Image bytes stay in the
local assets tree. That site forbids bulk download and redistribution, so
this module never fetches remote costume files.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

CATEGORIES = ("春", "夏", "秋", "冬", "内衣", "派对", "泳装", "性感")
PAGE_SIZE = 120
MAX_PAGE = 2000
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
SYNONYMS = {
    "黒": "black", "黑": "black", "ブラック": "black", "白": "white", "ホワイト": "white",
    "赤": "red", "红": "red", "レッド": "red", "ピンク": "pink", "粉": "pink",
    "青": "blue", "蓝": "blue", "ブルー": "blue", "紺": "navy", "藏青": "navy", "ネイビー": "navy",
    "茶": "brown", "棕": "brown", "ブラウン": "brown", "ベージュ": "beige", "米色": "beige",
    "アイボリー": "ivory", "乳白": "ivory", "グレー": "grey", "灰": "grey", "绿": "green", "緑": "green",
    "グリーン": "green", "黄": "yellow", "イエロー": "yellow", "オレンジ": "orange", "橙": "orange",
    "紫": "purple", "パープル": "purple", "ラベンダー": "lavender", "ミント": "mint", "クリーム": "cream",
    "金": "gold", "ゴールド": "gold", "银": "silver", "銀": "silver", "シルバー": "silver",
    "カーキ": "khaki", "ボルドー": "burgundy", "酒红": "burgundy", "オリーブ": "olive",
    "ドレス": "dress", "ワンピース": "dress", "连衣裙": "dress", "裙子": "skirt", "スカート": "skirt",
    "夹克": "jacket", "ジャケット": "jacket", "大衣": "coat", "コート": "coat", "毛衣": "sweater",
    "セーター": "sweater", "开衫": "cardigan", "カーディガン": "cardigan", "衬衫": "shirt",
    "ブラウス": "blouse", "シャツ": "shirt", "裤子": "pants", "パンツ": "pants", "牛仔裤": "jeans",
    "ジーンズ": "jeans", "短裤": "shorts", "ショートパンツ": "shorts", "靴子": "boots", "ブーツ": "boots",
    "运动鞋": "sneakers", "スニーカー": "sneakers", "凉鞋": "sandals", "サンダル": "sandals",
    "高跟鞋": "heels", "ヒール": "heels", "乐福鞋": "loafers", "ローファー": "loafers",
    "包": "bag", "包袋": "bag", "バッグ": "bag", "帽子": "hat", "ハット": "hat", "围巾": "scarf",
    "围巾儿": "scarf", "マフラー": "muffler", "项链": "necklace", "ネックレス": "necklace",
    "蕾丝": "lace", "レース": "lace", "牛仔": "denim", "デニム": "denim", "缎面": "satin",
    "サテン": "satin", "皮革": "leather", "皮": "leather", "レザー": "leather", "革": "leather",
    "针织": "knit", "ニット": "knit", "泳装": "swimsuit", "水着": "swimsuit", "比基尼": "bikini",
    "ビキニ": "bikini", "卫衣": "hoodie", "パーカー": "hoodie", "马甲": "vest", "ベスト": "vest",
    "迷你": "mini", "ミニ": "mini", "中长": "midi", "ミディ": "midi", "长款": "maxi", "マキシ": "maxi",
    "百褶": "pleated", "プリーツ": "pleated", "波点": "polka-dot", "水玉": "polka-dot", "ドット": "polka-dot",
    "丝带": "ribbon", "リボン": "ribbon", "荷叶边": "frill", "フリル": "frill", "网纱": "mesh",
    "メッシュ": "mesh", "雪纺": "chiffon", "シフォン": "chiffon", "丝绒": "velvet", "ベルベット": "velvet",
    "皮草": "fur", "ファー": "fur", "羊毛": "wool", "ウール": "wool", "太阳镜": "sunglasses",
    "サングラス": "sunglasses", "吊带": "camisole", "キャミソール": "camisole",
}


def load_costumes(assets_root: Path):
    """Return catalog rows and the id-to-file map for generated flats on disk.

    Older 服装 setting sheets stay in their own folders. This browser only
    lists the seasonal flats under assets/服饰, ordered newest-ingested first.
    """
    root = Path(assets_root)
    entries, files = [], {}
    for category in CATEGORIES:
        _take(root / "服饰" / category, category, entries, files)
    entries.sort(key=lambda entry: (-entry[0], -entry[1]))
    return [entry[2] for entry in entries], files


def costume_page(items, category="", query="", offset=0, limit=PAGE_SIZE):
    if category not in ("", *CATEGORIES):
        raise ValueError("服饰分类无效")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("分页参数无效")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE:
        raise ValueError("分页参数无效")
    matched = [item for item in items if _hit(item, category, query)]
    page = matched[offset:offset + limit]
    next_offset = offset + limit if offset + limit < len(matched) else None
    counts = {name: 0 for name in CATEGORIES}
    for item in items:
        if item["category"] in counts:
            counts[item["category"]] += 1
    return {
        "categories": [{"name": name, "count": counts[name]} for name in CATEGORIES],
        "total_all": len(items),
        "total": len(matched),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "items": page,
    }


def costume_file(files, item_id):
    path = files.get(item_id)
    if path is None or not path.is_file():
        return None
    return path


def _ingested_ns(resolved: Path, sidecar: dict) -> int:
    for key in ("ingested_at", "created_at"):
        raw = str(sidecar.get(key) or "").strip()
        if raw:
            try:
                return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1_000_000_000)
            except ValueError:
                pass
    try:
        return resolved.stat().st_mtime_ns
    except OSError:
        return 0


def _take(folder, category, entries, files, label=""):
    if not folder.is_dir():
        return
    root = folder.resolve()
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or path.name.startswith("."):
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_file():
            continue
        sidecar = _sidecar(path)
        declared = str(sidecar.get("服饰分类") or "").strip()
        item_category = declared if declared in CATEGORIES else category
        name = str(sidecar.get("name") or path.stem)
        item_id = _unique(path.stem, files)
        keywords = _keywords(name, sidecar)
        entries.append((
            _ingested_ns(resolved, sidecar),
            len(entries),
            {
                "id": item_id,
                "title": name,
                "category": item_category,
                "label": item_category or label or "服饰",
                "keywords": keywords,
                "image": "/api/v1/asset-center/costumes/" + item_id + "/content",
            },
        ))
        files[item_id] = resolved


def _unique(stem, files):
    if stem not in files:
        return stem
    number = 2
    while f"{stem}-{number}" in files:
        number += 1
    return f"{stem}-{number}"


def _sidecar(path: Path):
    candidate = path.with_suffix(".json")
    if not candidate.is_file():
        return {}
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _keywords(name, sidecar):
    raw = sidecar.get("关键词", sidecar.get("keywords", ""))
    if isinstance(raw, list):
        extra = " ".join(str(part) for part in raw)
    else:
        extra = str(raw or "")
    return " ".join(part for part in (name, extra) if part).strip()


def _hit(item, category, query):
    """Match the observed gallery: every word must hit, and 白 maps onto white."""
    if category and item["category"] != category:
        return False
    text = str(query or "").strip().lower()
    if not text:
        return True
    keys = item["keywords"].lower().split()
    identity = item["id"].lower()
    title = item["title"].lower()
    for word in text.split():
        english = SYNONYMS.get(word, word).lower()
        if (word in identity or english in identity or word in item["category"] or word in item["label"]
                or word in title or any(token.startswith(english) or token.startswith(word) for token in keys)):
            continue
        return False
    return True
