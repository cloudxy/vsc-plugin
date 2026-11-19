"""Guide document repository: DB-backed CRUD with seed-from-markdown."""
import re
import uuid
from pathlib import Path

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session


class GuideStore:
    def __init__(self, engine):
        self.engine = engine

    def _session(self):
        return Session(self.engine)

    # ── Read ──

    def list_documents(self):
        with self._session() as s:
            rows = s.execute(sql_text(
                "SELECT d.id, d.slug, d.title, d.description, d.cover_media, d.version, "
                "d.updated_at, b.slug AS board_slug "
                "FROM guide_documents d "
                "LEFT JOIN guide_boards b ON b.id = d.board_id "
                "ORDER BY d.slug"
            )).mappings().all()
            return [dict(r) for r in rows]

    def list_boards(self):
        with self._session() as s:
            rows = s.execute(sql_text(
                "SELECT id, slug, title, summary, sort_order "
                "FROM guide_boards ORDER BY sort_order, title"
            )).mappings().all()
            return [dict(r) for r in rows]

    def get_document(self, slug: str):
        with self._session() as s:
            doc = s.execute(sql_text(
                "SELECT * FROM guide_documents WHERE slug=:slug"
            ), {"slug": slug}).mappings().first()
            if not doc:
                return None
            sections = s.execute(sql_text(
                "SELECT * FROM guide_sections WHERE document_id=:doc_id "
                "ORDER BY sort_order"
            ), {"doc_id": doc["id"]}).mappings().all()
            images = s.execute(sql_text(
                "SELECT * FROM guide_images WHERE document_id=:doc_id "
                "ORDER BY sort_order"
            ), {"doc_id": doc["id"]}).mappings().all()
            replies = s.execute(sql_text(
                "SELECT id, body, author_label, created_at FROM guide_replies "
                "WHERE document_id=:doc_id ORDER BY created_at, id"
            ), {"doc_id": doc["id"]}).mappings().all()
            return {
                "document": dict(doc),
                "sections": [dict(r) for r in sections],
                "images": [dict(r) for r in images],
                "replies": [dict(r) for r in replies],
            }

    # ── Seed from markdown ──

    def seed_from_markdown(self, slug: str, title: str, md_path: Path,
                           images_dir: Path = None, cover: str = "",
                           board_slug: str = None, description: str = ""):
        """Parse a markdown file into guide_documents + guide_sections + guide_images.

        Text before the first heading becomes an untitled introduction section.
        Images referenced as ![alt](/creation-guide-media/...) are registered in
        guide_images in reading order; images_dir registration is kept for
        callers that store pictures without inline references.
        """
        md = md_path.read_text("utf-8")
        doc_id = str(uuid.uuid4())

        with self._session() as s:
            board_id = None
            if board_slug:
                board = s.execute(sql_text(
                    "SELECT id FROM guide_boards WHERE slug=:slug"
                ), {"slug": board_slug}).first()
                if not board:
                    raise ValueError(f"guide board not found: {board_slug}")
                board_id = board[0]

            # Upsert document
            existing = s.execute(sql_text(
                "SELECT id FROM guide_documents WHERE slug=:slug"
            ), {"slug": slug}).first()
            if existing:
                doc_id = existing[0]
                s.execute(sql_text(
                    "DELETE FROM guide_sections WHERE document_id=:doc_id"
                ), {"doc_id": doc_id})
                s.execute(sql_text(
                    "DELETE FROM guide_images WHERE document_id=:doc_id"
                ), {"doc_id": doc_id})
                s.execute(sql_text(
                    "UPDATE guide_documents SET title=:t, description=:descr, "
                    "cover_media=:cover, board_id=:board, updated_at=now() WHERE id=:id"
                ), {"t": title, "descr": description, "cover": cover,
                    "board": board_id, "id": doc_id})
            else:
                s.execute(sql_text(
                    "INSERT INTO guide_documents (id, slug, title, description, cover_media, board_id) "
                    "VALUES (:id, :slug, :t, :descr, :cover, :board)"
                ), {"id": doc_id, "slug": slug, "t": title, "descr": description,
                    "cover": cover, "board": board_id})

            # Parse sections
            sort = 0
            h2_count = 0
            current_h3_parent = None

            def insert_section(level, section_key, sec_title, body, parent):
                nonlocal sort
                callout = ""
                if body.startswith(">"):
                    parts = body.split("\n", 1)
                    callout = parts[0].lstrip("> ")
                    body = parts[1].strip() if len(parts) > 1 else ""
                s.execute(sql_text(
                    "INSERT INTO guide_sections (id, document_id, parent_id, section_key, level, title, body, callout, sort_order) "
                    "VALUES (:id, :doc, :parent, :key, :level, :t, :body, :callout, :sort)"
                ), {"id": str(uuid.uuid4()), "doc": doc_id, "parent": parent,
                    "key": section_key, "level": level, "t": sec_title,
                    "body": body, "callout": callout, "sort": sort})
                sort += 1

            lines = md.split("\n")
            i = 0
            intro_lines = []
            while i < len(lines):
                line = lines[i]
                if line.startswith("### "):
                    sec_title = line[4:].strip().replace("**", "")
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("#"):
                        body_lines.append(lines[i])
                        i += 1
                    insert_section(3, f"s3-{h2_count}-{sort}", sec_title,
                                   "\n".join(body_lines).strip(), current_h3_parent)
                elif line.startswith("## "):
                    if intro_lines:
                        insert_section(0, "introduction", "",
                                       "\n".join(intro_lines).strip(), None)
                        intro_lines = []
                    sec_title = line[3:].strip().replace("**", "")
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("#"):
                        body_lines.append(lines[i])
                        i += 1
                    insert_section(2, f"s2-{h2_count}", sec_title,
                                   "\n".join(body_lines).strip(), None)
                    # keep the inserted h2 id as parent for following h3 sections
                    row = s.execute(sql_text(
                        "SELECT id FROM guide_sections WHERE document_id=:doc AND sort_order=:sort"
                    ), {"doc": doc_id, "sort": sort - 1}).first()
                    current_h3_parent = row[0] if row else None
                    h2_count += 1
                else:
                    if sort == 0 and line.strip():
                        intro_lines.append(line)
                    i += 1
            if intro_lines:
                insert_section(0, "introduction", "",
                               "\n".join(intro_lines).strip(), None)

            # Import images: inline references first (reading order), then directory
            img_sort = 0
            seen_urls = set()
            for alt, url in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", md):
                if url.startswith("/creation-guide-media/") and url not in seen_urls:
                    seen_urls.add(url)
                    s.execute(sql_text(
                        "INSERT INTO guide_images (id, document_id, filename, alt_text, media_url, sort_order) "
                        "VALUES (:id, :doc, :fn, :alt, :url, :sort)"
                    ), {"id": str(uuid.uuid4()), "doc": doc_id,
                        "fn": url.rsplit("/", 1)[-1], "alt": alt,
                        "url": url, "sort": img_sort})
                    img_sort += 1
            if images_dir and images_dir.is_dir():
                for img_path in sorted(images_dir.iterdir()):
                    url = f"/creation-guide-media/{img_path.name}"
                    if img_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg") \
                            and url not in seen_urls:
                        seen_urls.add(url)
                        s.execute(sql_text(
                            "INSERT INTO guide_images (id, document_id, filename, alt_text, media_url, sort_order) "
                            "VALUES (:id, :doc, :fn, :alt, :url, :sort)"
                        ), {"id": str(uuid.uuid4()), "doc": doc_id,
                            "fn": img_path.name, "alt": img_path.stem,
                            "url": url, "sort": img_sort})
                        img_sort += 1

            s.commit()
        return doc_id

    # ── Highlight features ──

    HIGHLIGHT_FIELDS = ("title", "description", "video_media", "link_url", "button_text",
                        "version_no", "online_date", "sort_order")

    def list_highlights(self):
        """Feature video cards for the plaza, newest online date first."""
        with self._session() as s:
            rows = s.execute(sql_text(
                "SELECT id, slug, title, description, video_media, link_url, button_text, "
                "version_no, online_date, sort_order, updated_at "
                "FROM guide_highlights "
                "ORDER BY online_date DESC NULLS LAST, sort_order, slug"
            )).mappings().all()
            return [dict(r) for r in rows]

    def upsert_highlight(self, slug: str, title: str, **fields):
        """Insert or update one highlight card keyed by slug; returns the row id."""
        unknown = set(fields) - set(self.HIGHLIGHT_FIELDS)
        if unknown:
            raise ValueError(f"unknown highlight fields: {', '.join(sorted(unknown))}")
        values = {"id": str(uuid.uuid4()), "slug": slug, "title": title}
        for name in self.HIGHLIGHT_FIELDS:
            if name in fields:
                value = fields[name]
                if name == "online_date":
                    value = value if value else None
                values[name] = value
        with self._session() as s:
            row = s.execute(sql_text(
                "INSERT INTO guide_highlights (id, slug, title, description, video_media, "
                "link_url, button_text, version_no, online_date, sort_order) VALUES "
                "(:id, :slug, :title, :descr, :video, :link, :btn, :ver, CAST(:online AS date), :sort) "
                "ON CONFLICT (slug) DO UPDATE SET title=:title, description=:descr, "
                "video_media=:video, link_url=:link, button_text=:btn, version_no=:ver, "
                "online_date=CAST(:online AS date), sort_order=:sort, updated_at=now() "
                "RETURNING id"
            ), {"id": values["id"], "slug": slug, "title": title,
                "descr": values.get("description", ""), "video": values.get("video_media", ""),
                "link": values.get("link_url", ""), "btn": values.get("button_text", ""),
                "ver": values.get("version_no", ""), "online": values.get("online_date"),
                "sort": values.get("sort_order", 0)}).first()
            s.commit()
            return row[0]
