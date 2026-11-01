"""User timing and explicit media contracts, without generated-content claims."""
import copy
import unittest

import support.paths
from vsc.production.creative_tools import normalize_draft, compile_mv, music_edit, parse_lrc


class CreativeToolContractTests(unittest.TestCase):
    def test_lrc_preserves_timing_intro_and_rejects_ambiguous_offsets(self):
        rows = parse_lrc("[ti:Fixture]\n[00:01.5]hello\n[00:03.00]world", 5000)
        self.assertEqual([(r["start_ms"], r["end_ms"]) for r in rows], [(0, 1500), (1500, 3000), (3000, 5000)])
        for invalid in ("[offset:50]\n[00:01]test", "[00:60]bad", "[00:01]one\n[00:01]two", "plain lyrics", "[00:06]late"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_lrc(invalid, 5000)

    def test_mv_compiles_user_segments_and_does_not_invent_beats(self):
        audio = dict(id="audio", sha256="a" * 64, duration_ms=4000)
        draft = normalize_draft(dict(tool="mv", episode_id="episode", prompt="Visual", lyrics="plain lyrics"))
        with self.assertRaises(ValueError):
            compile_mv(draft, audio)
        draft["segments"] = [dict(start_ms=0, end_ms=2000, lyrics="one", prompt="Close"), dict(start_ms=2000, end_ms=4000, lyrics="two")]
        plan = compile_mv(draft, audio)
        self.assertEqual([s["prompt"] for s in plan["shots"]], ["Close", "Visual"])
        self.assertFalse(plan["generated_video"])
        draft["segments"][1]["start_ms"] = 2100
        with self.assertRaises(ValueError):
            compile_mv(draft, audio)

    def test_music_full_audio_stays_separate_from_interval_and_original_switch(self):
        source, audio = dict(id="video", duration_ms=10000), dict(id="music", duration_ms=201000)
        draft = normalize_draft(dict(tool="music_mix", episode_id="episode", music_start_ms=2000,
            music_end_ms=6000, audio_in_ms=3000, keep_original=False))
        result = music_edit(draft, source, audio)
        self.assertEqual(result["clips"][0]["out_frame"], 240)
        self.assertTrue(result["clips"][0]["muted"])
        self.assertEqual((result["audio"][0]["in_frame"], result["audio"][0]["out_frame"], result["audio"][0]["at_frame"]), (72, 168, 48))
        draft["keep_original"] = True
        result = music_edit(draft, source, audio)
        self.assertFalse(result["clips"][0]["muted"])
        self.assertEqual(result["audio"][0]["volume"], .7)
        self.assertEqual(audio["duration_ms"], 201000)
        draft["music_end_ms"] = 11000
        with self.assertRaises(ValueError):
            music_edit(draft, source, audio)

    def test_ranges_and_modes_reject_unbounded_or_credential_inputs(self):
        from vsc.assets.resource_service import ResourceError
        base = dict(tool="segment_remake", episode_id="episode", ranges=[dict(start_ms=100, end_ms=200), dict(start_ms=250, end_ms=300)])
        self.assertEqual(normalize_draft(base)["ranges"], base["ranges"])
        for patch in (dict(ranges=[dict(start_ms=100, end_ms=200), dict(start_ms=199, end_ms=300)]),
                      dict(keep_original="false"), dict(dimensions=["video", "unknown"]), dict(duration_ms=True)):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                normalize_draft(dict(copy.deepcopy(base), **patch))
        with self.assertRaises(ResourceError):
            normalize_draft(dict(base, params={"api_key": "not-a-real-key"}))
