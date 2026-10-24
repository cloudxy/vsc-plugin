"""Overlay geometry uses the same frame protocol as the original compositor."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from PIL import Image
from vsc.post import remotion_plan as R
from vsc.adapters.media.qa import gaps


def overlay_plan(sha='0' * 64):
    return {'format': R.FORMAT, 'project_id': 'synthetic-overlay',
        'composition': {'id': 'Overlay', 'width': 320, 'height': 240, 'fps': 25, 'duration_in_frames': 50},
        'segments': [{'id': 'base', 'kind': 'image', 'source': 'base.png', 'source_shot_id': 'SH', 'from_frame': 0, 'duration_in_frames': 50},
            {'id': 'plate', 'kind': 'image', 'source': 'plate.png', 'source_shot_id': 'SH', 'source_sha256': sha,
                'from_frame': 10, 'duration_in_frames': 25, 'overlay': {'x': 20, 'y': 20, 'width': 64, 'height': 48,
                    'alpha': .5, 'layer': 1, 'blend_mode': 'normal',
                    'motion': {'to': {'x': 220, 'y': 80}, 'easing': 'ease_in'}}}]}


class OverlayRulesTest(unittest.TestCase):
    def test_original_mix_uses_sequence_base_offset_when_plate_starts_earlier(self):
        from support.fixtures.handoffs import Fixture
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            sound = fixture.register('vsc.sound_plan', {'format':'vsc.sound-cue-sheet/v1','sequence_id':'SQ2',
                'duration_ms':1000,'ambience_beds':[{'id':'AMB','start_ms':0,'end_ms':1000}], 'music_cues':[], 'boundaries':[]})
            timeline = copy.deepcopy(fixture.timeline_data)
            plate = fixture.media('plate.png',b'fixed timing-only fixture; no media/render claim')
            timeline['render_plan']['segments'].extend([
                {'id':'EARLY','kind':'image','source':plate['path'],'source_shot_id':'SH2','source_sha256':plate['sha256'],
                    'from_frame':0,'duration_in_frames':12,'overlay':{'x':0,'y':0,'width':16,'height':16,'alpha':1,'layer':1,'blend_mode':'normal'}},
                {'id':'AUDIO','kind':'audio','source':'bed.wav','from_frame':24,'duration_in_frames':24}])
            timeline['bindings'].append({'segment_id':'AUDIO','selected_item_id':'BED','sha256':'1'*64,
                'purpose':'ambience','usage_rights':'owned','audio_role':'ambience','cue_id':'AMB'})
            timeline['sound_plans']=[fixture.ref(sound)]
            def errors(document):
                artifact = fixture.register('vsc.timeline',document,[fixture.selected,sound])
                mix = fixture.base('mix',timeline=fixture.ref(artifact),sound_plans=[fixture.ref(sound)],
                    layers=[{'segment_id':'AUDIO','cue_id':'AMB','sound_plan':fixture.ref(sound),'audio_role':'ambience'}],boundaries=[])
                item = fixture.register('vsc.mix',mix,[artifact,sound])
                return fixture.errors(mix,item)
            self.assertEqual(errors(timeline), [], 'SQ2 Cue zero starts at base V2 frame24, independent of early plate')
            shifted = copy.deepcopy(timeline)
            shifted['render_plan']['segments'][-1]['from_frame'] = 0
            self.assertTrue(any('覆盖不足' in message for message in errors(shifted)), 'plate-relative audio must fail original mix coverage')

    def test_invalid_geometry_curve_sha_kind_and_duration_are_rejected(self):
        value = overlay_plan(); self.assertEqual(R.validate(value), [])
        mutations = [lambda s: s.update(kind='video'), lambda s: s.pop('source_sha256'),
            lambda s: s['overlay'].update(alpha=float('nan')), lambda s: s['overlay'].update(x=-1),
            lambda s: s['overlay'].update(width=400), lambda s: s['overlay'].update(layer=0),
            lambda s: s['overlay'].update(blend_mode='unknown'),
            lambda s: s['overlay']['motion'].update(easing='spring_unbounded'),
            lambda s: s['overlay']['motion']['to'].update(x=300), lambda s: s.update(duration_in_frames=0),
            lambda s: s.update(from_frame=40), lambda s: s['overlay'].update(mask='unsupported')]
        for mutate in mutations:
            invalid = copy.deepcopy(value); mutate(invalid['segments'][1])
            with self.subTest(value=invalid): self.assertTrue(R.validate(invalid))
        self.assertEqual(gaps([value['segments'][1]], 50), [[0, 50]], 'a transparent plate cannot fill a missing base shot')

    def test_generated_frame_math_matches_shared_geometry_at_key_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); Image.new('RGBA', (16, 16), (255, 0, 0, 128)).save(root / 'plate.png')
            value = overlay_plan(hashlib.sha256((root / 'plate.png').read_bytes()).hexdigest())
            source = root / 'plan.json'; source.write_text(json.dumps(value)); output = root / 'engine'
            R.scaffold(value, output, plan_path=source)
            for easing in R.OVERLAY_EASINGS:
                segment = copy.deepcopy(value['segments'][1]); segment['overlay']['motion']['easing'] = easing
                frames = [0, 6, 12, 24]
                code = f"const m=await import({json.dumps((output/'src/timing.ts').as_uri())});const s={json.dumps(segment)};console.log(JSON.stringify({json.dumps(frames)}.map(f=>m.overlayAtFrame(s,f))));"
                actual = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', code], text=True))
                for frame, row in zip(frames, actual):
                    expected = R.overlay_at_frame(segment, frame)
                    self.assertAlmostEqual(row['x'], expected['x']); self.assertAlmostEqual(row['y'], expected['y'])
                self.assertEqual(actual[0]['x'], 20); self.assertEqual(actual[-1]['x'], 220)

    def test_missing_or_changed_plate_fails_before_scaffold_and_fixed_bytes_are_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); value = overlay_plan(); source = root / 'plan.json'; source.write_text(json.dumps(value))
            with self.assertRaises(ValueError): R.scaffold(value, root / 'missing', plan_path=source)
            self.assertFalse((root / 'missing').exists())
            Image.new('RGBA', (16, 16), (255, 0, 0, 128)).save(root / 'plate.png')
            with self.assertRaisesRegex(ValueError, 'SHA'): R.scaffold(value, root / 'tampered', plan_path=source)
            self.assertFalse((root / 'tampered').exists())
            value['segments'][1]['source_sha256'] = hashlib.sha256((root / 'plate.png').read_bytes()).hexdigest()
            source.write_text(json.dumps(value)); result = R.scaffold(value, root / 'valid', plan_path=source)
            self.assertEqual(result['overlay_sources'][0]['sha256'], value['segments'][1]['source_sha256'])
            self.assertEqual((root / 'valid/public/plate.png').read_bytes(), (root / 'plate.png').read_bytes())
