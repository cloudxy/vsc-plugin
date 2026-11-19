"""GuideStore.upsert_highlight/list_highlights: feature video cards roundtrip."""
import os
import unittest
import uuid
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
class GuideHighlightTests(unittest.TestCase):
    def setUp(self):
        self.schema = f"guide_highlights_{uuid.uuid4().hex[:10]}"
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
        self.store = GuideStore(self.engine)

    def tearDown(self):
        with self.admin.connect() as c:
            c.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            c.commit()
        self.engine.dispose()
        self.admin.dispose()

    def test_upsert_then_reseed_updates_same_row(self):
        self.store.upsert_highlight(
            slug="liblib-feature-23", title="Seedance 2.5 Flash首发",
            description="生成速度提升一倍", video_media="/creation-guide-media/liblib/highlights/a.mp4",
            link_url="https://www.liblib.tv/canvas?x=1", button_text="去体验",
            version_no="1.5.1", online_date="2026-11-13", sort_order=1)
        self.store.upsert_highlight(
            slug="liblib-feature-25", title="Seedream 5.5",
            description="像素级可控编辑", video_media="/creation-guide-media/liblib/highlights/b.mp4",
            version_no="1.5.1", online_date="2026-11-13", sort_order=2)
        self.store.upsert_highlight(
            slug="liblib-feature-9", title="旧版本亮点",
            video_media="/creation-guide-media/liblib/highlights/c.mp4",
            version_no="1.4.0", online_date="2026-09-01", sort_order=1)

        rows = self.store.list_highlights()
        self.assertEqual([r["slug"] for r in rows],
                         ["liblib-feature-23", "liblib-feature-25", "liblib-feature-9"])
        self.assertEqual(rows[0]["button_text"], "去体验")
        self.assertTrue(rows[0]["link_url"].startswith("https://"))
        self.assertEqual(str(rows[0]["online_date"]), "2026-11-13")

        # reseed with changed fields updates the same slug instead of duplicating
        self.store.upsert_highlight(
            slug="liblib-feature-23", title="Seedance 2.5 Flash首发（更新）",
            description="生成速度提升一倍", video_media="/creation-guide-media/liblib/highlights/a2.mp4",
            version_no="1.5.1", online_date="2026-11-13", sort_order=1)
        rows = self.store.list_highlights()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["title"], "Seedance 2.5 Flash首发（更新）")
        self.assertEqual(rows[0]["video_media"], "/creation-guide-media/liblib/highlights/a2.mp4")

    def test_empty_online_date_sorts_last_and_blank_fields_default(self):
        self.store.upsert_highlight(slug="hl-undated", title="未标注上线日期")
        self.store.upsert_highlight(slug="hl-dated", title="已标注",
                                    online_date="2026-11-01", sort_order=1)
        rows = self.store.list_highlights()
        self.assertEqual([r["slug"] for r in rows], ["hl-dated", "hl-undated"])
        self.assertEqual(rows[1]["description"], "")
        self.assertEqual(rows[1]["online_date"], None)

    def test_unknown_field_fails_closed(self):
        with self.assertRaises(ValueError):
            self.store.upsert_highlight(slug="hl-x", title="x", no_such_field="y")


if __name__ == "__main__":
    unittest.main()
