"""Identity semantics remain distinct from cross-cutting browse categories."""
import unittest

from vsc.assets.specification import bible_errors
from vsc.assets.taxonomy import (BIBLE_KINDS, CATEGORIES, CATEGORY_BY_CODE, IDENTITY_KINDS,
    LEGACY_KIND_MAPPING, TOP_LEVEL_CATEGORIES, category_descendants, identity_categories)


class ResourceTaxonomyTests(unittest.TestCase):
    def test_kind_alignment_preserves_old_codes_and_independent_specifications(self):
        self.assertEqual(set(IDENTITY_KINDS), set(BIBLE_KINDS) | {"voice", "style", "costume"})
        for kind in IDENTITY_KINDS:
            self.assertEqual(LEGACY_KIND_MAPPING[kind], kind)
        for kind in ("creature", "vehicle", "object", "plant"):
            doc = {"project_id": "synthetic", "entities": [{"id": "fixture", "kind": kind,
                "name": "合成资源", "identity": [], "variants": {"default": "固定规格"}}]}
            self.assertEqual(bible_errors(doc), [], kind)
        with self.assertRaises(ValueError):
            identity_categories("unknown")

    def test_eleven_categories_are_unique_connected_and_not_execution_claims(self):
        self.assertEqual(len(TOP_LEVEL_CATEGORIES), 11)
        self.assertEqual(len(CATEGORY_BY_CODE), len(CATEGORIES))
        for row in CATEGORIES:
            if row["parent_code"]:
                self.assertIn(row["parent_code"], TOP_LEVEL_CATEGORIES)
                self.assertIn(row["code"], category_descendants(row["parent_code"]))
            self.assertNotIn("executor", row)
        self.assertIn("sound.voice", identity_categories("voice"))
        self.assertIn("character.voiceprint", identity_categories("voice"))
        self.assertNotIn("prop", identity_categories("creature"))
        with self.assertRaises(ValueError):
            category_descendants("arbitrary")


if __name__ == "__main__":
    unittest.main()
