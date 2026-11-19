"""Import captured LibTV academy articles into the 学习广场 guide board.

Input is a capture directory with articles/<articleUuid>.json (fields:
title/summary/tags/contentMd/cover/canvasUrl) and media/<name> bytes captured
from the academy pages. The tool projects each article into local guide
markdown plus media files under the guides asset root, then seeds the plaza
board through GuideStore. Capture sources and media bytes stay private local
inputs; only the projection runs here, with no network access.

Usage:
    python tools/maintenance/guide_import_liblib.py --capture-dir <dir> [--dry-run]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from vsc.configuration import get_config  # noqa: E402

# articleUuid -> slug, ordered by the academy reading order.
ARTICLES = {
    "01a0d2362f7a7267bf58f4cb881b2e07": "liblib-canvas-nodes",
    "01a1871cb8c37637a91b4fd0e83ab73f": "liblib-15-exclusive",
    "01a1ced95ec677ac9c401f2273573fb9": "liblib-seedream55",
    "01a168058f6a776da6aa6e5b433e6ac3": "liblib-kling40",
    "01a0d247fa5572ce981ebfa79cd86fbc": "liblib-seedance",
    "01a0d23d8e597ae581acd80e36ef576b": "liblib-slash-shortcuts",
    "01a0d23eb3d97128872f196e1f56ec34": "liblib-image-node",
    "01a0d242d6e47b048f2a384f93f8e23f": "liblib-video-node",
    "01a0d243a69f72b482bce925fe2cb03b": "liblib-audio-node",
    "01a0d23c16477468aeb9a41755b6d420": "liblib-workflow",
    "01a0d2449b4d746f8330a4e55ae1be11": "liblib-image-generator",
    "01a0d2456af572bd8354dce139d68872": "liblib-video-generator",
    "01a0d2463a39705baeffb9070227dc83": "liblib-script-node",
    "01a0d24709f37af79589c9dbaa5303f1": "liblib-3d-director",
}

VIDEO_EXT = (".mp4", ".webm")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")


def guides_root() -> Path:
    media = get_config("VSC_MEDIA_ROOT")
    if isinstance(media, str) and media.strip():
        base = Path(media).expanduser().parent / "guides"
        if base.is_dir():
            return base
    return ROOT / "assets" / "guides"


def local_name(url: str) -> str:
    """Stable on-disk name: basename with a lowercased extension.

    QuickTime .mov captures are remuxed to .mp4 on capture, so their
    references are remapped here for browser playback.
    """
    name = url.split("/")[-1].split("?")[0]
    stem, _, ext = name.rpartition(".")
    if not stem:
        return name
    ext = ext.lower()
    if ext == "mov":
        ext = "mp4"
    return f"{stem}.{ext}"


def place_media(src: Path, url_prefix: str, name: str) -> str:
    """Copy a captured media file into the guides tree; return its site URL."""
    ext = Path(name).suffix.lower()
    sub = "videos" if ext in VIDEO_EXT else "images"
    dest_dir = guides_root() / sub / "liblib" / url_prefix
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if not dest.exists():
        shutil.copyfile(src, dest)
    return f"/creation-guide-media/liblib/{url_prefix}/{name}"


def convert_markdown(md: str, slug: str, media_dir: Path) -> str:
    """Rewrite academy HTML media tags into local markdown references."""
    lookup = {}

    def media_ref(url: str) -> str:
        if url not in lookup:
            src = media_dir / local_name(url)
            if not src.is_file():
                raise FileNotFoundError(f"missing captured media: {url} -> {src}")
            lookup[url] = place_media(src, slug, local_name(url))
        return lookup[url]

    def img_repl(match: re.Match) -> str:
        return "![](" + media_ref(match.group(1)) + ")"

    def video_repl(match: re.Match) -> str:
        name = Path(local_name(match.group(1))).name
        return f"[video:{name}]({media_ref(match.group(1))})"

    md = re.sub(r'<img\s+[^>]*src="([^"]+)"[^>]*/?>', img_repl, md)
    md = re.sub(r'<video\s+[^>]*src="([^"]+)"[^>]*>.*?</video>', video_repl, md, flags=re.S)
    # layout-only wrappers carry no content of their own
    md = re.sub(r"<p[^>]*>", "", md)
    md = re.sub(r"</p>", "", md)
    return md


def import_article(data: dict, capture_dir: Path, store=None, dry_run: bool = False) -> dict:
    article_id = data["articleUuid"]
    slug = ARTICLES[article_id]
    md = convert_markdown(data.get("contentMd") or "", slug, capture_dir / "media")
    cover_url = ""
    if data.get("cover"):
        cover_src = capture_dir / "media" / local_name(data["cover"])
        if cover_src.is_file():
            cover_url = place_media(cover_src, slug, local_name(data["cover"]))
    if data.get("canvasUrl"):
        md += f"\n\n---\n\n**在线示例画布**：[在 LibTV 中打开]({data['canvasUrl']})\n"
    if data.get("summary"):
        md = "> " + data["summary"] + "\n\n" + md

    md_dir = guides_root() / "liblib"
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{slug}.md"
    md_path.write_text(md, "utf-8")
    stats = {
        "slug": slug,
        "title": data["title"],
        "images": md.count("!["),
        "videos": md.count("[video:"),
        "h2": len(re.findall(r"(?m)^## ", md)),
        "h3": len(re.findall(r"(?m)^### ", md)),
        "cover": bool(cover_url),
    }
    if not dry_run:
        store.seed_from_markdown(slug=slug, title=data["title"], md_path=md_path,
                                 cover=cover_url, board_slug="plaza",
                                 description=data.get("summary") or "")
    return stats


FEATURE_NEWS = "feature_news.json"


def import_highlights(capture_dir: Path, store=None, dry_run: bool = False) -> list:
    """Project the captured feature-news list into 亮点功能 video cards.

    Input is feature_news.json (the /api/feature-news/version/list response):
    each version lists feature cards with a name, description, intro video and
    an optional experience link. Media bytes must already sit in media/ under
    the capture root; they are copied into the guides tree like article media.
    """
    data = json.loads((capture_dir / FEATURE_NEWS).read_text("utf-8"))
    stats = []
    for version in ((data.get("data") or {}).get("list") or []):
        version_no = version.get("versionNo") or ""
        for feature in version.get("features") or []:
            feature_id = feature.get("id")
            if feature_id is None:
                continue
            media_url = feature.get("mediaUrl") or ""
            video_media = ""
            if media_url:
                src = capture_dir / "media" / local_name(media_url)
                if not src.is_file():
                    raise FileNotFoundError(f"missing captured media: {media_url} -> {src}")
                video_media = place_media(src, "highlights", local_name(media_url))
            link_url = feature.get("linkUrl") or ""
            if not link_url.startswith(("http://", "https://")):
                link_url = ""
            record = {
                "slug": f"liblib-feature-{feature_id}",
                "title": feature.get("name") or f"亮点 {feature_id}",
                "description": feature.get("description") or "",
                "video": video_media,
                "link": link_url,
                "button": feature.get("buttonText") or "" if link_url else "",
                "version": version_no,
                "online": feature.get("onlineDate") or "",
                "sort": feature.get("sortOrder") or 0,
            }
            stats.append(record)
            if not dry_run:
                store.upsert_highlight(
                    slug=record["slug"], title=record["title"],
                    description=record["description"], video_media=record["video"],
                    link_url=record["link"], button_text=record["button"],
                    version_no=record["version"],
                    online_date=record["online"] or None,
                    sort_order=record["sort"])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--highlights", action="store_true",
                        help="also import 亮点功能 video cards from feature_news.json")
    args = parser.parse_args()

    capture_dir = args.capture_dir.resolve()
    article_files = sorted((capture_dir / "articles").glob("*.json"))
    known = [f for f in article_files if f.stem in ARTICLES]
    unknown = [f for f in article_files if f.stem not in ARTICLES]
    if unknown:
        raise SystemExit("unmapped articles (add slugs first): " +
                         ", ".join(f.stem for f in unknown))

    store = None
    if not args.dry_run:
        from sqlalchemy import create_engine
        from vsc.assets.guide_store import GuideStore
        store = GuideStore(create_engine(get_config("VSC_DATABASE_URL"), pool_pre_ping=True))

    for path in known:
        data = json.loads(path.read_text("utf-8"))
        stats = import_article(data, capture_dir, store=store, dry_run=args.dry_run)
        print("ok" if not args.dry_run else "dry", stats["slug"], "|",
              stats["h2"], "h2 /", stats["h3"], "h3 /", stats["images"], "img /",
              stats["videos"], "video / cover:", stats["cover"], "|", stats["title"])

    if args.highlights:
        if not (capture_dir / FEATURE_NEWS).is_file():
            raise SystemExit(f"missing {FEATURE_NEWS} in capture dir")
        for record in import_highlights(capture_dir, store=store, dry_run=args.dry_run):
            print("ok" if not args.dry_run else "dry", record["slug"], "|",
                  "v" + record["version"], "|", record["online"], "|",
                  "video:", bool(record["video"]), "|", record["title"])


if __name__ == "__main__":
    main()
