"""Original post CLIs consume optional cue contracts and real offline bytes."""
import array
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from support.paths import ROOT
from vsc.post import sound_rules, remotion_plan as R, subtitle_burn as B, subtitles as S


def tone(path, frequency, seconds, amplitude=.12, sample_rate=48000):
    samples = array.array('h', (round(amplitude * 32767 * math.sin(2 * math.pi * frequency * n / sample_rate))
        for n in range(round(seconds * sample_rate))))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(sample_rate); output.writeframes(samples.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pcm(path):
    with wave.open(str(path), 'rb') as source:
        rate, channels = source.getframerate(), source.getnchannels()
        samples = array.array('h', source.readframes(source.getnframes()))
    return rate, [value / 32768 for value in samples[::channels]]


class SoundRulesIntegration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.music = tone(self.root / 'music.wav', 400, 3)
        self.voice = tone(self.root / 'voice.wav', 1200, .6, .02)
        self.sfx = tone(self.root / 'sfx.wav', 1600, .2, .08)
        source = self.root / 'owned-source.json'; source.write_text('{"origin":"synthetic generated fixture tones"}')
        evidence = {'path': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        self.sound = {'format': 'vsc.sound-cue-sheet/v1', 'project_id': 'fixture', 'sequence_id': 'SQ', 'duration_ms': 3000,
            'ambience_beds': [], 'boundaries': [], 'dialogue_cues': [{'id': 'D', 'start_ms': 800, 'end_ms': 1400,
                'line_id': 'L', 'text': 'Synthetic fixture', 'speaker': 'fixture', 'acting_choice': 'plain', 'lip_sync_intent': 'voiceover'}],
            'music_cues': [{'id': 'M', 'start_ms': 0, 'end_ms': 3000, 'narrative_function': 'leave dialogue space', 'emotion': 'calm',
                'intensity': 1, 'entry': 'start', 'exit': 'end', 'usage_rights': 'owned', 'stems': ['synthetic sine'],
                'bpm': 72, 'dynamics': 'p', 'instrumentation': ['synthetic tone'],
                'ducking': {'gain': .25, 'attack_ms': 100, 'release_ms': 200, 'dialogue_cue_ids': ['D']}}],
            'sfx_cues': [{'id': 'FX', 'start_ms': 2100, 'end_ms': 2300, 'purpose': 'one fixed effect', 'usage_rights': 'owned',
                'media': {'path': 'sfx.wav', 'sha256': self.sfx}, 'source_ref': evidence},
                {'id': 'QUIET', 'start_ms': 2400, 'end_ms': 2600, 'purpose': 'intentional no effect', 'silence': True}]}
        self.plan = {'format': 'vsc.timeline/v1', 'project_id': 'fixture', 'scope': 'EP', 'bindings': [
            {'segment_id': key, 'cue_id': cue, 'sha256': sha, 'audio_role': role} for key, cue, sha, role in
            [('music', 'M', self.music, 'music'), ('voice', 'D', self.voice, 'dialogue'), ('sfx', 'FX', self.sfx, 'sfx')]],
            'render_plan': {'format': R.FORMAT, 'project_id': 'fixture', 'composition': {'id': 'Test', 'width': 320, 'height': 240,
                'fps': 100, 'duration_in_frames': 300}, 'segments': [
                    {'id': 'visual', 'kind': 'image', 'source': 'unused.png', 'source_shot_id': 'SH', 'from_frame': 0, 'duration_in_frames': 300},
                    {'id': 'music', 'kind': 'audio', 'source': 'music.wav', 'from_frame': 0, 'duration_in_frames': 300},
                    {'id': 'voice', 'kind': 'audio', 'source': 'voice.wav', 'from_frame': 80, 'duration_in_frames': 60},
                    {'id': 'sfx', 'kind': 'audio', 'source': 'sfx.wav', 'from_frame': 210, 'duration_in_frames': 20}]}}

    def write_sound(self):
        path = self.root / 'sound.json'; path.write_text(json.dumps(self.sound))
        self.plan['sound_plans'] = [{'id': 'SOUND', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
        return path

    def test_sfx_optional_structure_and_original_sound_cli_reject_missing_ref_and_bad_intent(self):
        path = self.write_sound()
        command = [sys.executable, '-B', str(ROOT / 'scripts/project/state.py'), 'sound', 'validate', str(path)]
        valid = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        original = copy.deepcopy(self.sound)
        for mutate in (lambda: self.sound['sfx_cues'][0].pop('media'),
                       lambda: self.sound['sfx_cues'][0].update(end_ms=5000),
                       lambda: self.sound['music_cues'][0].update(bpm=0),
                       lambda: self.sound['music_cues'][0].update(dynamics='too loud'),
                       lambda: self.sound['music_cues'][0]['ducking'].update(dialogue_cue_ids=['missing'])):
            self.sound = copy.deepcopy(original); mutate(); path.write_text(json.dumps(self.sound))
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
        self.sound = copy.deepcopy(original); self.sound.pop('sfx_cues')
        self.sound['music_cues'][0] = {key: value for key, value in self.sound['music_cues'][0].items()
            if key not in {'bpm', 'dynamics', 'instrumentation', 'ducking'}}
        path.write_text(json.dumps(self.sound))
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_original_mix_audio_cli_consumes_sfx_and_declared_ducking_then_recovers(self):
        sound = self.write_sound()
        plan = self.root / 'timeline.json'; plan.write_text(json.dumps(self.plan))
        projected_path = self.root / 'timeline-envelope.json'
        projection = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/post/remotion_plan.py'), 'sound-envelope', str(plan),
            '--output', str(projected_path), '--sound-plan', 'SOUND=' + str(sound)], capture_output=True, text=True)
        self.assertEqual(projection.returncode, 0, projection.stdout + projection.stderr)
        self.assertEqual(json.loads(projection.stdout)['status'], 'draft_requires_original_review')
        projected = json.loads(projected_path.read_text())
        music = next(segment for segment in projected['render_plan']['segments'] if segment['id'] == 'music')
        self.assertTrue(music['volume_keyframes'])
        self.assertEqual(plan.read_text(), json.dumps(self.plan))
        output = self.root / 'mixed.wav'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/post/remotion_plan.py'), 'mix-audio', str(projected_path),
            '--media-root', str(self.root), '--output', str(output), '--sound-plan', 'SOUND=' + str(sound)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report['sources']), 3)
        self.assertEqual(report['human_listening'], 'not_reviewed')
        self.assertEqual(report['sound_intents'][0]['design_only']['bpm'], 72)
        rate, samples = read_pcm(output)
        def rms(start, end):
            part = samples[round(start * rate):round(end * rate)]
            return math.sqrt(sum(value * value for value in part) / len(part))
        self.assertLess(rms(.95, 1.25), rms(.2, .5) * .45)
        self.assertAlmostEqual(rms(1.8, 2), rms(.2, .5), delta=.005)
        def band(start, end, frequency):
            first, last = round(start * rate), round(end * rate)
            return abs(2 * sum(samples[n] * math.sin(2 * math.pi * frequency * n / rate) for n in range(first, last)) / (last - first))
        self.assertGreater(band(2.12, 2.25, 1600), .05)
        self.assertLess(band(1.8, 2, 1600), .002)
        self.assertEqual(plan.read_text(), json.dumps(self.plan), 'projection must not rewrite the fixed input')
        # Fixed sound source changes cannot be silently accepted.
        sound.write_text(sound.read_text() + ' ')
        failed = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/post/remotion_plan.py'), 'mix-audio', str(plan),
            '--media-root', str(self.root), '--output', str(self.root / 'bad.wav'), '--sound-plan', 'SOUND=' + str(sound)], capture_output=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.root / 'bad.wav').exists())

    def test_native_music_recipe_enters_original_sound_cli_then_actual_six_db_envelope(self):
        original = self.write_sound()
        selected = self.root / 'sound-recipe.json'
        command = [sys.executable, '-B', str(ROOT / 'scripts/project/state.py'), 'sound', 'apply-recipe', str(original),
            '--recipe', 'AR-music-open-quiet', '--cue', 'M', '--output', str(selected)]
        no_selection = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(no_selection.returncode, 0, 'recipe placeholder is not a real Cue selection')
        self.assertFalse(selected.exists())
        chosen = subprocess.run(command + ['--dialogue-cue', 'D'], capture_output=True, text=True)
        self.assertEqual(chosen.returncode, 0, chosen.stdout + chosen.stderr)
        record = json.loads(chosen.stdout)
        self.assertEqual(record['status'], 'draft_requires_original_validation_and_review')
        from vsc.knowledge.recipes import load, attributes
        recipe = next(row for row in load()['recipes'] if row['id'] == 'AR-music-open-quiet')
        self.assertEqual(record['recipe_ref'], attributes(recipe)['recipe'])
        sound = json.loads(selected.read_text())
        self.assertEqual(sound['music_cues'][0]['ducking']['dialogue_cue_ids'], ['D'])
        self.assertEqual(sound['music_cues'][0]['bpm'], 72)
        self.plan['sound_plans'][0]['sha256'] = hashlib.sha256(selected.read_bytes()).hexdigest()
        plan = self.root / 'recipe-timeline.json'; plan.write_text(json.dumps(self.plan))
        output = self.root / 'recipe-mix.wav'
        mixed = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/post/remotion_plan.py'), 'mix-audio', str(plan),
            '--media-root', str(self.root), '--output', str(output), '--sound-plan', 'SOUND=' + str(selected)], capture_output=True, text=True)
        self.assertEqual(mixed.returncode, 0, mixed.stdout + mixed.stderr)
        rate, samples = read_pcm(output)
        def music_amplitude(start, end):
            first, last = round(start * rate), round(end * rate)
            return abs(2 * sum(samples[n] * math.sin(2 * math.pi * 400 * n / rate) for n in range(first, last)) / (last - first))
        self.assertAlmostEqual(music_amplitude(.95, 1.25) / music_amplitude(.2, .5), 10 ** (-6 / 20), delta=.03)
        self.assertAlmostEqual(music_amplitude(2.6, 2.8) / music_amplitude(.2, .5), 1, delta=.03)
        self.assertEqual(json.loads(original.read_text()), self.sound, 'selected specification must preserve the original sound draft')


class SubtitleSafeAreaIntegration(unittest.TestCase):
    def test_same_real_font_safe_rectangle_reaches_burn_remotion_and_editor_projection(self):
        from vsc.adapters.editors import jianying_export as J
        from PIL import Image
        self.assertTrue(B.DEFAULT_FONT.is_file(), 'real bundled delivery font required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'input.mp4'
            subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=640x360:d=2',
                '-r', '30', '-pix_fmt', 'yuv420p', str(video)], check=True)
            style = dict(S.DEFAULT_STYLE, font=str(B.DEFAULT_FONT), font_size=32)
            rules = {'subtitle': {'safe_area': {'top': .1, 'bottom': .25, 'left': .15, 'right': .1}, 'mixed_spacing': True,
                'max_cps': {'value': 20, 'level': 'error'}, 'min_cue_ms': {'value': 500, 'level': 'error'}}}
            plan = {'format': R.FORMAT, 'project_id': 'fixture', 'creative_rules': rules, 'subtitle_style': style,
                'composition': {'id': 'Safe', 'width': 640, 'height': 360, 'fps': 30, 'duration_in_frames': 60}, 'segments': [
                    {'id': 'visual', 'kind': 'video', 'source': 'input.mp4', 'source_shot_id': 'SH', 'from_frame': 0, 'duration_in_frames': 60, 'muted': True},
                    {'id': 'caption', 'kind': 'caption', 'from_frame': 0, 'duration_in_frames': 60, 'text': '使用AI模型3.14万元'}]}
            compiled, _ = R.compile_subtitles(plan, style, require_font=True)
            payload, captions, _ = J.draft_payload(plan, root)
            self.assertEqual(captions, compiled['cues'])
            self.assertEqual(payload['subtitle_checks']['safe_area'], compiled['checks']['safe_area'])
            self.assertTrue(payload['subtitle_transforms'])
            captured = {}
            def runner(command, **kwargs):
                if command[0].endswith('uv'):
                    B.render(command[-1]); captured.update(json.loads(Path(command[-1]).read_text()))
                    return subprocess.CompletedProcess(command, 0, '', '')
                return subprocess.run(command, **kwargs)
            burned = B.burn(video, None, root / 'burned.mp4', style, run=runner, render_plan=plan)
            self.assertEqual(burned['subtitle_checks']['safe_area'], compiled['checks']['safe_area'])
            cue = captured['cues'][0]
            self.assertGreaterEqual(cue['x'], 640 * .15 - 1)
            self.assertLessEqual(cue['y'] + compiled['measurements'][0]['height_px'], 360 * .75 + 1)
            image = root / 'frame.png'
            subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(root / 'burned.mp4'), '-frames:v', '1', str(image)], check=True)
            pixels = Image.open(image).convert('RGB')
            nonblack = [(x, y) for y in range(360) for x in range(640) if max(pixels.getpixel((x, y))) > 80]
            self.assertTrue(nonblack)
            self.assertLessEqual(max(y for _, y in nonblack), 360 * .75 + 1)
            self.assertGreaterEqual(min(x for x, _ in nonblack), 640 * .15 - 1)
            scaffold = R.scaffold(plan, root / 'remotion', strict_subtitles=True)
            self.assertEqual(scaffold['subtitle_checks']['safe_area'], compiled['checks']['safe_area'])
            self.assertIn('plan.creative_rules?.subtitle?.safe_area', (root / 'remotion/src/ShortDrama.tsx').read_text())
            wrong = copy.deepcopy(plan); wrong['creative_rules']['subtitle']['max_cps']['value'] = 1
            for consume in (lambda: R.compile_subtitles(wrong, style, require_font=True), lambda: J.draft_payload(wrong, root),
                            lambda: B.burn(video, None, root / 'rejected.mp4', style, run=runner, render_plan=wrong)):
                with self.assertRaises((ValueError, RuntimeError)):
                    consume()
