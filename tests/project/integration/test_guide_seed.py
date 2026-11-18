"""GuideStore.seed_from_markdown: board placement, intro section, inline images."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
import support.paths

HAS_DB = True
try:
    from sqlalchemy import MetaData, create_engine, text
    from vsc.adapters.persistence.postgres.schema_guide import install_guide_schema
    from vsc.assets.guide_store import GuideStore
except Exception:  # noqa: BLE001
    HAS_DB = False


def test_database_url():
    if os.environ.get("VSC_TEST_DATABASE_URL"):
        return os.environ["VSC_TEST_DATABASE_URL"]
    try:
        from vsc.configuration import get_settings
        return get_settings().get("TEST_DATABASE_URL")
    except Exception:  # noqa: BLE001
        return None


@unittest.skipUnless(HAS_DB and test_database_url(), "requires configured isolated PostgreSQL")
class GuideSeedTests(unittest.TestCase):
    def setUp(self):
        self.schema = f"guide_seed_{uuid.uuid4().hex[:10]}"
        self.admin = create_engine(test_database_url(), pool_pre_ping=True)
        with self.admin.connect() as c:
            c.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            c.commit()
        self.engine = create_engine(
            test_database_url(), pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={self.schema}"})
        metadata = MetaData(schema=self.schema)
        install_guide_schema(metadata)
        metadata.create_all(self.engine)
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO guide_boards (id, slug, title) "
                           "VALUES (:id, 'plaza', '学习广场')"), {"id": str(uuid.uuid4())})
        self.store = GuideStore(self.engine)

    def tearDown(self):
        with self.admin.connect() as c:
            c.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            c.commit()
        self.engine.dispose()
        self.admin.dispose()

    def seed(self, md_text, board_slug="plaza", **kw):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "article.md"
            path.write_text(md_text, "utf-8")
            return self.store.seed_from_markdown(
                slug=kw.pop("slug", "liblib-test"), title=kw.pop("title", "测试文章"),
                md_path=path, board_slug=board_slug,
                description="摘要", cover="/creation-guide-media/liblib/t/cover.png", **kw)

    def test_seed_places_on_board_with_intro_callout_and_inline_images(self):
        md = (
            "> 涉及功能：画布\n\n导语第一段。\n\n"
            "## 第一节\n\n> 第一节提示\n\n正文一\n\n![](/creation-guide-media/liblib/t/a.png)\n\n带提示的正文。\n\n"
            "### 子节\n\n子节正文\n\n![](/creation-guide-media/liblib/t/b.png)\n"
        )
        self.seed(md)
        docs = self.store.list_documents()
        self.assertEqual([d["board_slug"] for d in docs], ["plaza"])
        self.assertEqual(docs[0]["description"], "摘要")
        self.assertEqual(docs[0]["cover_media"], "/creation-guide-media/liblib/t/cover.png")
        data = self.store.get_document("liblib-test")
        levels = [(s["level"], s["title"], s["section_key"]) for s in data["sections"]]
        self.assertEqual([l[0] for l in levels], [0, 2, 3])
        self.assertEqual(levels[0][2], "introduction")
        self.assertEqual(data["sections"][0]["callout"], "涉及功能：画布")
        self.assertIn("导语第一段", data["sections"][0]["body"])
        h2 = data["sections"][1]
        self.assertEqual(h2["callout"], "第一节提示")
        self.assertIn("带提示的正文", h2["body"])
        h3 = data["sections"][2]
        self.assertEqual(h3["parent_id"], h2["id"])
        self.assertEqual([i["media_url"] for i in data["images"]],
                         ["/creation-guide-media/liblib/t/a.png", "/creation-guide-media/liblib/t/b.png"])

    def test_reseed_replaces_sections_and_images_without_duplicates(self):
        self.seed("## 一\n\n正文")
        self.seed("## 一\n\n正文\n\n## 二\n\n更多")
        data = self.store.get_document("liblib-test")
        self.assertEqual(len(self.store.list_documents()), 1)
        self.assertEqual([s["title"] for s in data["sections"]], ["一", "二"])

    def test_unknown_board_fails_closed(self):
        with self.assertRaises(ValueError):
            self.seed("## 一\n\n正文", board_slug="no-such-board")


if __name__ == "__main__":
    unittest.main()
