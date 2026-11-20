"""The episode script limit matches the composer counter."""
import unittest

from vsc.assets.resource_service import ResourceError
from vsc.production.intelligent_production import normalize_document


class IntelligentScriptLimitTests(unittest.TestCase):
    def document(self, script):
        return {'script_text': script, 'template_key': 'cinematic', 'template_text': '固定模板'}

    def test_ten_thousand_characters_are_accepted(self):
        saved = normalize_document(self.document('剧' * 10000))
        self.assertEqual(len(saved['script_text']), 10000)

    def test_longer_episode_script_is_rejected(self):
        with self.assertRaises(ResourceError):
            normalize_document(self.document('剧' * 10001))
