"""Official catalog labels are derived from the stored role tag."""
import unittest

from vsc.assets.official_taxonomy import (
    LOCATION_ALIASES, PROP_ALIASES, PROP_TYPES, SCENE_TYPES, SPACES,
    character_tags, classify_location, classify_prop, presentation,
)


class OfficialTaxonomyTests(unittest.TestCase):
    def test_character_tags_split_roles_and_skip_age_gender_labels(self):
        self.assertEqual(character_tags("安保 / 护卫"), ["安保", "护卫"])
        self.assertEqual(character_tags("医生"), ["医生"])
        for label in ("青年女", "中年男", "幼年女", "少年男", "老年女", "壮年男"):
            self.assertEqual(character_tags(label), [], label)
        shown = presentation("character", "安保 / 青年女")
        self.assertEqual(shown["role_tags"], ["安保"])
        self.assertEqual(shown["scene_type"], "")
        self.assertEqual(shown["prop_type"], "")

    def test_location_uses_structured_tags_then_known_names(self):
        self.assertEqual(classify_location("住宅 / 室内"), ("住宅", "室内"))
        self.assertEqual(classify_location("其他 / 半室外"), ("其他", "半室外"))
        self.assertEqual(classify_location("未标注"), ("未识别", "未识别"))
        self.assertEqual(classify_location("其他"), ("其他", "未识别"))
        self.assertEqual(classify_location("没有这种场景"), ("未识别", "未识别"))
        for name, pair in LOCATION_ALIASES.items():
            self.assertEqual(classify_location(name), pair, name)
            self.assertIn(pair[0], SCENE_TYPES)
            self.assertIn(pair[1], SPACES)
        scene, space = presentation("location", "街巷")["scene_type"], presentation("location", "街巷")["space"]
        self.assertEqual((scene, space), ("其他", "室外"))

    def test_prop_types_keep_the_closed_set_and_map_old_names(self):
        for name in PROP_TYPES:
            self.assertEqual(classify_prop(name), name)
        for name, target in PROP_ALIASES.items():
            self.assertEqual(classify_prop(name), target, name)
            self.assertIn(target, PROP_TYPES)
        self.assertEqual(classify_prop("茶具"), "其他")
        self.assertEqual(classify_prop("长枪 / 礼仪"), "武器")
        self.assertEqual(presentation("prop", "虎")["prop_type"], "其他")
        self.assertEqual(presentation("voice", "环境声")["role_tags"], [])


if __name__ == "__main__":
    unittest.main()
