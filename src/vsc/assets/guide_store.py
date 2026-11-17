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
                "SELECT id, slug, title, description, cover_media, version, updated_at "
                "FROM guide_documents ORDER BY slug"
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
            return {
                "document": dict(doc),
                "sections": [dict(r) for r in sections],
                "images": [dict(r) for r in images],
            }

    # ── Seed from markdown ──

    def seed_from_markdown(self, slug: str, title: str, md_path: Path,
                           images_dir: Path = None, cover: str = ""):
        """Parse a markdown file into guide_documents + guide_sections + guide_images."""
        md = md_path.read_text("utf-8")
        doc_id = str(uuid.uuid4())

        with self._session() as s:
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
                    "UPDATE guide_documents SET title=:t, updated_at=now() WHERE id=:id"
                ), {"t": title, "id": doc_id})
            else:
                s.execute(sql_text(
                    "INSERT INTO guide_documents (id, slug, title, cover_media) "
                    "VALUES (:id, :slug, :t, :cover)"
                ), {"id": doc_id, "slug": slug, "t": title, "cover": cover})

            # Parse sections
            sort = 0
            h2_count = 0
            current_h3_parent = None
            current_callout = ""

            lines = md.split("\n")
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("### "):
                    h2_count_h3 = sort
                    sec_id = str(uuid.uuid4())
                    sec_title = line[4:].strip()
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("#"):
                        body_lines.append(lines[i])
                        i += 1
                    body = "\n".join(body_lines).strip()
                    callout = ""
                    if body.startswith(">"):
                        parts = body.split("\n", 1)
                        callout_line = parts[0].lstrip("> ")
                        callout = callout_line
                        body = parts[1].strip() if len(parts) > 1 else ""
                    s.execute(sql_text(
                        "INSERT INTO guide_sections (id, document_id, parent_id, section_key, level, title, body, callout, sort_order) "
                        "VALUES (:id, :doc, :parent, :key, 3, :t, :body, :callout, :sort)"
                    ), {"id": sec_id, "doc": doc_id, "parent": current_h3_parent,
                        "key": f"s3-{h2_count}-{sort}", "t": sec_title,
                        "body": body, "callout": callout, "sort": sort})
                    sort += 1
                elif line.startswith("## "):
                    sec_id = str(uuid.uuid4())
                    sec_title = line[3:].strip()
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("#"):
                        body_lines.append(lines[i])
                        i += 1
                    body = "\n".join(body_lines).strip()
                    callout = ""
                    if body.startswith(">"):
                        parts = body.split("\n", 1)
                        callout = parts[0].lstrip("> ")
                        callout = callout_line
                        body = parts[1].strip() if len(parts) > 1 else ""
                    s.execute(sql_text(
                        "INSERT INTO guide_sections (id, document_id, parent_id, section_key, level, title, body, callout, sort_order) "
                        "VALUES (:id, :doc, NULL, :key, 2, :t, :body, :callout, :sort)"
                    ), {"id": sec_id, "doc": doc_id,
                        "key": f"s2-{h2_count}", "t": sec_title,
                        "body": body, "callout": callout, "sort": sort})
                    current_h3_parent = sec_id
                    h2_count += 1
                    sort += 1
                else:
                    i += 1

            # Import images
            if images_dir and images_dir.is_dir():
                img_sort = 0
                for img_path in sorted(images_dir.iterdir()):
                    if img_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                        s.execute(sql_text(
                            "INSERT INTO guide_images (id, document_id, filename, alt_text, media_url, sort_order) "
                            "VALUES (:id, :doc, :fn, :alt, :url, :sort)"
                        ), {"id": str(uuid.uuid4()), "doc": doc_id,
                            "fn": img_path.name, "alt": img_path.stem,
                            "url": f"/creation-guide-media/{img_path.name}",
                            "sort": img_sort})
                        img_sort += 1

            s.commit()
        return doc_id
