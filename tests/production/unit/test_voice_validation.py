"""Voice rules and injected protocol failures need no database project."""
import io
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

from support.paths import SCRIPTS  # noqa: F401
import consistency
import vsc_volc_provider as provider


class VoiceValidation(unittest.TestCase):
    def test_pronunciation_terms_are_versioned_and_unique(self):
        bible = {"project_id": "fixture", "entities": [{"id": "char", "kind": "character", "name": "Character",
            "identity": ["face"], "variants": {"default": "same"}, "references": [],
            "voice": {"engine": "doubao_speech", "voice": "fixture_voice", "rights": "owned",
                      "pronunciations": [{"term": "A", "spoken": "ei"}, {"term": "A", "spoken": "ah"}]}}]}
        self.assertTrue(any("词条不得重复" in error for error in consistency.bible_errors(bible)))
        bible["entities"][0]["voice"]["pronunciations"].pop()
        self.assertEqual(consistency.bible_errors(bible), [])

    def test_audio_provider_reports_key_permission_without_retry(self):
        binding = {"line_id": "L1", "entity_id": "char", "voice": {
            "engine": "doubao_speech", "voice": "fixture_voice", "resource_id": "seed-tts-2.0"}}
        adapter = provider.VolcArkAudioProvider("seed-tts-2.0", Path("unused-project"), "J-abc", binding,
                                               {"format": "wav", "sample_rate": 24000})
        denied = urllib.error.HTTPError(provider.speech.ENDPOINTS["agent-plan"], 403, "denied", {}, io.BytesIO())
        with patch.object(provider.speech, "api_key", return_value="offline-test-key"), \
                patch.object(provider.speech, "open_stream", side_effect=denied) as stream:
            with self.assertRaisesRegex(provider.VolcAdapterError, "没有豆包语音合成的权限，请自行核对"):
                adapter._request({"req_params": {}}, "seed-tts-2.0")
        stream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
