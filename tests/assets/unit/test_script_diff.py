"""Structural screenplay diff: pure functions, no database."""
import unittest

from vsc.assets.script_diff import compare_documents

BEFORE = {"scenes": [
    {"id": "SC1", "estimated_duration_ms": 4000,
     "actions": [{"id": "A1", "text": "他停下脚步"}],
     "dialogue": [{"id": "L1", "speaker": "char", "text": "明天再来"}], "silence": []},
    {"id": "SC2", "estimated_duration_ms": 3000,
     "actions": [{"id": "A2", "text": "她离开"}], "dialogue": [], "silence": [{"id": "S1", "text": "长静默"}]}]}


class ScriptDiffTest(unittest.TestCase):
    def test_identical_documents_have_no_changes(self):
        result = compare_documents(BEFORE, BEFORE)
        self.assertFalse(result["changed"])
        self.assertEqual(result["lines"], [])

    def test_text_speaker_scene_and_order_changes_are_reported(self):
        after = {"scenes": [
            {"id": "SC2", "estimated_duration_ms": 3000,
             "actions": [{"id": "A2", "text": "她转身离开"}], "dialogue": [], "silence": [{"id": "S1", "text": "长静默"}]},
            {"id": "SC1", "estimated_duration_ms": 6000,
             "actions": [{"id": "A1", "text": "他停下脚步"}, {"id": "A3", "text": "回头"}],
             "dialogue": [{"id": "L1", "speaker": "narrator", "text": "今晚我等你"}], "silence": []},
            {"id": "SC3", "estimated_duration_ms": 1000, "actions": [], "dialogue": [], "silence": []}]}
        result = compare_documents(BEFORE, after)
        self.assertTrue(result["changed"])
        self.assertEqual(result["scenes"]["added"], ["SC3"])
        self.assertEqual(result["scenes"]["moved"], ["SC2", "SC1"])
        by_field = {(row["scene_id"], row["line_id"], row.get("field")): row for row in result["lines"]}
        self.assertEqual(by_field[("SC1", "L1", "text")]["after"], "今晚我等你")
        self.assertEqual(by_field[("SC1", "L1", "speaker")]["after"], "narrator")
        self.assertEqual(by_field[("SC1", None, "estimated_duration_ms")]["after"], 6000)
        self.assertEqual(by_field[("SC2", "A2", "text")]["change"], "changed")
        self.assertEqual(by_field[("SC2", "A2", "text")]["before"], "她离开")
        self.assertEqual(by_field[("SC1", "A3", None)]["change"], "added")

    def test_removal_and_empty_baseline(self):
        removed = compare_documents(BEFORE, {"scenes": [BEFORE["scenes"][0]]})
        self.assertEqual(removed["scenes"]["removed"], ["SC2"])
        self.assertEqual([row["line_id"] for row in removed["lines"]], ["A2", "S1"])
        fresh = compare_documents(None, BEFORE)
        self.assertTrue(fresh["changed"])
        self.assertEqual(fresh["scenes"]["added"], ["SC1", "SC2"])


if __name__ == "__main__":
    unittest.main()
