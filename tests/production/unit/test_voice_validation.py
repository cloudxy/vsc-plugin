"""Voice rules and injected protocol failures need no database project."""
import io
import json
import tempfile
import wave
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

import vsc.story.consistency as consistency
import vsc.adapters.providers.volc_ark.provider as provider


class VoiceValidation(unittest.TestCase):
    def test_formal_factory_sends_the_reported_performance_controls(self):
        from vsc.adapters.providers.volc_ark.resource_factory import volc_ark_factory
        from vsc.adapters.providers import credentials
        from vsc.production.providers import AudioRequest
        from vsc.production.performance import performance_payload_coverage
        from types import SimpleNamespace
        binding={"line_id":"L1","voice":{"engine":provider.speech.PROVIDER,"voice":"fixture_voice"}}
        defaults={"speech_rate":20,"context_texts":["whisper"],"format":"wav","sample_rate":24000}
        model={"model_key":"seed-tts-2.0","default_params":defaults,
               "capabilities":{"performance_controls":{"rate":"speech_rate","delivery":"context_texts"}}}
        params={"controls":[{"field":"rate","model_default":"speech_rate","expected":20},
                            {"field":"delivery","model_default":"context_texts","expected":["whisper"]}]}
        with tempfile.TemporaryDirectory() as directory:
            adapter=volc_ark_factory({"id":"abc","provider_id":"volc_ark","modality":"audio","model":model,
                "provider":{"configuration":{},"base_url":credentials.PLAN_BASE,"auth_ref":credentials.KEY_ENV},
                "input_media":[],"request_payload":{"logical_request":{},"voice_binding":binding}},SimpleNamespace(root=Path(directory)))
            data=io.BytesIO()
            with wave.open(data,'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\0\0'*2400)
            captured=[]
            adapter.adapter.transport=lambda payload,resource:(captured.append(payload) or data.getvalue(),{})
            adapter.submit(AudioRequest('shot','dialogue_dry','a'*64,'Original spoken words',script_line_ids=('L1',)))
            payload=captured[0]
            self.assertEqual(json.loads(payload['req_params']['additions']),{'context_texts':['whisper']})
            self.assertEqual(payload['req_params']['text'],'Original spoken words')
            self.assertEqual([r['consumed'] for r in performance_payload_coverage(params,model,payload)['controls']],[True,True])

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
