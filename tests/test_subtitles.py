#!/usr/bin/env python3
"""subtitles.py 自测。运行：python3 tests/test_subtitles.py"""
import unittest

from _paths import SCRIPTS  # noqa: F401  被测模块位于 scripts/
import subtitles as SUB


class FixedWidthFont:
    """每个字符宽 10 像素，用来测换行规则而不依赖 Pillow。"""

    def getbbox(self, text):
        return (0, 0, 10 * len(text), 10)


class SplitAndGroupTest(unittest.TestCase):
    def test_punctuation_split_keeps_numbers_whole(self):
        self.assertEqual(SUB.split_by_punctuation("收费 2.5% 共 1,000 元。好吗？"), ["收费 2.5% 共 1,000 元", "好吗"])

    def test_word_cues_group_into_script_sentences(self):
        cues = [(0.1, 0.4, "今天"), (0.4, 0.8, "下雨"), (1.0, 1.3, "记得"), (1.3, 1.9, "带伞出门")]
        self.assertEqual(SUB.group_word_cues(cues, "今天下雨，记得带伞出门。"), [(0.1, 0.8, "今天下雨"), (1.0, 1.9, "记得带伞出门")])

    def test_unmatched_cues_return_none(self):
        self.assertIsNone(SUB.group_word_cues([(0, 1, "别的话")], "今天下雨。"))

    def test_rate_to_percent(self):
        self.assertEqual([SUB.rate_to_percent(value) for value in (1.0, 1.2, 0.9, 0, None, 1.004)], ["+0%", "+20%", "-10%", "+0%", "+0%", "+0%"])


class SrtTest(unittest.TestCase):
    def test_round_trip(self):
        items = [(0.2, 4.9, "第一句"), (3725.5, 3726.0, "两行\n字幕")]
        text = SUB.to_srt(items)
        self.assertIn("01:02:05,500 --> 01:02:06,000", text)
        self.assertEqual(SUB.parse_srt(text), items)

    def test_invalid_blocks_are_skipped(self):
        self.assertEqual(SUB.parse_srt("1\nbad time\n文字\n\n2\n00:00:02,000 --> 00:00:01,000\n倒序"), [])


class WrapTest(unittest.TestCase):
    def test_prefers_breaking_after_punctuation(self):
        lines = SUB.wrap_text("今天下雨，记得带伞出门，你听见了吗？", FixedWidthFont(), 130)
        self.assertEqual(lines, ["今天下雨，记得带伞出门，", "你听见了吗？"])

    def test_long_phrase_falls_back_to_characters(self):
        self.assertEqual(SUB.wrap_text("一二三四五六七八九十", FixedWidthFont(), 40), ["一二三四", "五六七八", "九十"])

    def test_closing_punctuation_never_starts_a_line(self):
        lines = SUB.wrap_text("一二三四五六七八。", FixedWidthFont(), 80)
        self.assertFalse(any(line[0] in SUB.LINE_START_PUNCTUATION for line in lines))

    def test_english_words_wrap_on_spaces(self):
        self.assertEqual(SUB.wrap_text("hold it tight", FixedWidthFont(), 80), ["hold it", "tight"])


if __name__ == "__main__":
    unittest.main()
