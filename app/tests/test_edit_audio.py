"""Local synthesis and decoded-waveform checks; never contact a model/service."""
import array
import copy
import importlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
import wave

from videostudio.core import digest
from videostudio.media import probe, run

ROOT = Path(__file__).resolve().parents[2] / 'data' / 'test-tmp'
ROOT.mkdir(parents=True, exist_ok=True)


def tone(path, seconds=2, frequency=440, amplitude=.15, split=None):
    rate = 16000
    values = array.array('h', (int(32767 * amplitude * math.sin(2 * math.pi *
        (frequency if split is None or i / rate < split[0] else split[1]) * i / rate))
        for i in range(round(rate * seconds))))
    with wave.open(str(path), 'wb') as handle:
        handle.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        handle.writeframes(values.tobytes())
    return {'path': str(path), 'sha256': digest(path), 'kind': 'audio', 'duration': seconds}


def samples(path, start=0, duration=None):
    args = ['ffmpeg', '-v', 'error', '-i', str(path), '-ss', str(start)]
    if duration is not None:
        args += ['-t', str(duration)]
    values = array.array('f')
    values.frombytes(run(args + ['-ar', '16000', '-ac', '1', '-f', 'f32le', '-'], lambda: None))
    return values


def rms(values):
    return math.sqrt(sum(value * value for value in values) / max(1, len(values)))


class AudioTests(unittest.TestCase):
    def audio(self):
        self.assertIsNotNone(importlib.util.find_spec('videostudio.edit_audio'),
                             'Chapter music/editor audio implementation is missing')
        return importlib.import_module('videostudio.edit_audio')

    def job(self, root):
        scenes = [dict(start=0, end=.75, duration=.75, chapter_index=1),
                  dict(start=.75, end=2, duration=1.25, chapter_index=1),
                  dict(start=2, end=5, duration=3, chapter_index=2)]
        return {'id': '12345678-0000-0000-0000-000000000000', 'output': str(root),
                'request': {'duration_seconds': 99, 'edit_preset': 'science'},
                'checkpoints': {'speech': {'duration_seconds': 5, 'scenes': scenes},
                    'script': {'scenes': copy.deepcopy(scenes), 'chapters': [
                        {'index': 1, 'title': 'Origins'}, {'index': 2, 'title': 'Discovery'}]},
                    'plan': {'music_prompt': 'Quiet instrumental documentary'}}}

    def test_sections_follow_measured_chapters_and_stable_ids(self):
        audio = self.audio()
        job = self.job(ROOT)
        sections = audio.music_sections(job, 'science')
        self.assertEqual([(s['start'], s['end'], s['chapter_index']) for s in sections],
                         [(0, 2, 1), (2, 5, 2)])
        self.assertEqual(sections, audio.music_sections(job, 'science'))
        self.assertEqual(len({s['id'] for s in sections}), 2)
        self.assertIn('Discovery', sections[1]['prompt'])
        for scene in job['checkpoints']['speech']['scenes']:
            scene.pop('chapter_index')
        job['checkpoints']['script'] = {'scenes': [{}, {}, {}]}
        self.assertEqual([(s['start'], s['end']) for s in audio.music_sections(job, 'science')], [(0, 5)])

    def test_procedural_library_is_non_silent_reproducible_and_licensed(self):
        audio = self.audio()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            first = audio.ensure_sfx_library(Path(folder) / 'a')
            second = audio.ensure_sfx_library(Path(folder) / 'b')
            self.assertEqual(set(first), {'sfx-whoosh', 'sfx-impact', 'sfx-chime', 'sfx-click'})
            for name, item in first.items():
                self.assertEqual(item['sha256'], second[name]['sha256'])
                self.assertEqual(item['sha256'], digest(item['path']))
                self.assertIn('CC0', item['license'])
                self.assertIn('procedural', item['source'])
                self.assertGreater(rms(samples(item['path'])), .003)
                self.assertLess(max(abs(x) for x in samples(item['path'])), .85)
            original = first['sfx-click']['sha256']
            Path(first['sfx-click']['path']).write_bytes(b'corrupt')
            self.assertEqual(audio.ensure_sfx_library(Path(folder) / 'a')['sfx-click']['sha256'], original)

    def test_sfx_defaults_are_sparse_semantic_accents(self):
        audio = self.audio()
        scenes = [dict(start=i, end=i+1, chapter_index=1 if i < 15 else 2) for i in range(30)]
        events = audio.default_sfx_events(scenes, [{'index': 1}, {'index': 2}], 'science')
        self.assertEqual([e['start'] for e in events], [0, 15])
        self.assertTrue(all(e['asset_id'] == 'sfx-chime' for e in events))
        self.assertTrue(all(0 < e['volume'] < .5 and e['end'] <= 30 for e in events))

    def test_generation_uses_chapters_and_reuses_durable_local_result(self):
        audio = self.audio()
        class Pipeline:
            ffmpeg = 'ffmpeg'
            ffprobe = 'ffprobe'
            calls = []
            def accepted_music(self):
                return True
            def comfy_asset(self, job, kind, graph, path, check):
                self.calls.append(kind)
                source = Path(path).with_suffix('.wav')
                tone(source, 5, 220 if len(self.calls) == 1 else 880)
                run(['ffmpeg', '-v', 'error', '-y', '-i', source, path], check)
                return {'path': str(path), 'assets': [{'path': str(path), 'sha256': digest(path)}]}
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            job = self.job(Path(folder))
            pipeline = Pipeline()
            result = audio.generate_chapter_music(pipeline, job, lambda: None)
            self.assertEqual(len(pipeline.calls), 2)
            self.assertEqual(len(result['sections']), 2)
            self.assertAlmostEqual(result['sections'][0]['end'] - result['sections'][1]['start'],
                                   result['crossfade_seconds'], places=5)
            self.assertAlmostEqual(result['sections'][1]['fade_in'], result['crossfade_seconds'], places=5)
            self.assertAlmostEqual(float(probe(result['path'])['format']['duration']), 5, delta=.05)
            early, late = samples(result['path'], .5, .2), samples(result['path'], 4.5, .2)
            crossings = lambda xs: sum((a < 0) != (b < 0) for a, b in zip(xs, xs[1:]))
            self.assertGreater(crossings(late), crossings(early) * 2)
            self.assertGreater(rms(late), .02)
            again = audio.generate_chapter_music(pipeline, job, lambda: None)
            self.assertEqual(len(pipeline.calls), 2)
            self.assertEqual(digest(again['path']), digest(result['path']))
            self.assertTrue(all(s['sha256'] == digest(s['path']) for s in result['sections']))

    def test_existing_checkpoint_preserved_and_explicit_mute_never_generates(self):
        audio = self.audio()
        class NoModel:
            ffmpeg = 'ffmpeg'
            ffprobe = 'ffprobe'
            def accepted_music(self):
                raise AssertionError('Muted/existing music must not access a model')
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            job = self.job(Path(folder))
            saved = {'path': tone(Path(folder) / 'old.wav', 5)['path'], 'existing': True}
            job['checkpoints']['music'] = saved
            self.assertEqual(audio.generate_chapter_music(NoModel(), job, lambda: None), saved)
            job['checkpoints'].pop('music')
            job['request']['music_enabled'] = False
            result = audio.generate_chapter_music(NoModel(), job, lambda: None)
            self.assertTrue(result['intentional_mute'])
            self.assertEqual(result['sections'], [])
            self.assertLess(rms(samples(result['path'])), 1e-6)

    def test_mix_honors_trim_timing_gain_fades_mute_and_cache(self):
        audio = self.audio()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            source = tone(root / 'source.wav', 2, 220, split=(.5, 880))
            plan = {'duration': 3, 'tracks': [{'id': 'sfx', 'kind': 'sfx'}], 'clips': [], 'music': [],
                'sfx': [dict(id='event', track_id='sfx', asset_id='tone', start=1, end=2,
                    source_start=.6, volume=.5, fade_in=.15, fade_out=.15, enabled=True),
                    dict(id='muted', track_id='sfx', asset_id='tone', start=0, end=3, muted=True)]}
            job = {'output': str(root), 'checkpoints': {}}
            output = root / 'mixed.wav'
            result = audio.mix_edit_audio(job, plan, {'tone': source}, output, lambda: None)
            self.assertLess(rms(samples(output, .1, .3)), 1e-5)
            middle = samples(output, 1.3, .2)
            self.assertAlmostEqual(rms(middle), .15 * .5 / math.sqrt(2), delta=.003)
            self.assertGreater(sum((a < 0) != (b < 0) for a,b in zip(middle,middle[1:])), 300)
            self.assertLess(rms(samples(output, 1, .04)), rms(middle) * .4)
            self.assertLess(rms(samples(output, 2.2, .3)), 1e-5)
            again = audio.mix_edit_audio(job, plan, {'tone': source}, output, lambda: None)
            self.assertTrue(again['reused'])
            plan['sfx'][0]['volume'] = .2
            changed = audio.mix_edit_audio(job, plan, {'tone': source}, output, lambda: None)
            self.assertFalse(changed['reused'])
            self.assertNotEqual(result['sha256'], changed['sha256'])
            self.assertEqual(source['sha256'], digest(source['path']))

    def test_mix_uses_original_narration_stem_and_ducks_music(self):
        audio = self.audio()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            assets = {'voice': tone(root / 'voice.wav', 1, 220, .3),
                      'music': tone(root / 'music.wav', 3, 880, .18)}
            plan = {'duration': 3, 'tracks': [{'id': 'n', 'kind': 'narration'}, {'id': 'm', 'kind': 'music'}],
                'clips': [dict(id='voice', kind='audio', track_id='n', asset_id='voice', start=1, end=2,
                               source_start=0, volume=1)],
                'music': [dict(id='music', track_id='m', asset_id='music', start=0, end=3, volume=1)], 'sfx': []}
            output = root / 'ducked.wav'
            result = audio.mix_edit_audio({'checkpoints': {}}, plan, assets, output, lambda: None)
            def magnitude(start, frequency):
                values = samples(output, start, .2)
                return 2 * abs(sum(x * complex(math.cos(2*math.pi*frequency*i/16000),
                    math.sin(2*math.pi*frequency*i/16000)) for i,x in enumerate(values))) / len(values)
            self.assertLess(magnitude(1.5, 880), magnitude(.4, 880) * .8)
            self.assertGreater(magnitude(1.5, 220), .2)
            self.assertLess(max(abs(x) for x in samples(output)), .96)
            plan['clips'][0]['volume'] = .25
            remixed = audio.mix_edit_audio({'checkpoints': {}}, plan, assets, output, lambda: None)
            self.assertNotEqual(result['sha256'], remixed['sha256'])
            self.assertLess(magnitude(1.5, 220), .09)

    def test_mixer_rejects_changed_attested_source_and_nonfinite_values(self):
        audio = self.audio()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            source = tone(root / 'source.wav')
            plan = {'duration': 2, 'tracks': [], 'clips': [], 'music': [],
                    'sfx': [{'id': 'e', 'asset_id': 's', 'start': 0, 'end': 2, 'volume': float('nan')}]}
            with self.assertRaises((ValueError, RuntimeError)):
                audio.mix_edit_audio({}, plan, {'s': source}, root / 'out.wav', lambda: None)
            plan['sfx'][0]['volume'] = 1
            Path(source['path']).write_bytes(b'changed')
            with self.assertRaises((ValueError, RuntimeError)):
                audio.mix_edit_audio({}, plan, {'s': source}, root / 'out.wav', lambda: None)

    def test_narration_global_gain_and_track_mute_are_effective(self):
        audio = self.audio()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            source = tone(root / 'voice.wav', 2, 220, .2)
            plan = {'duration': 2, 'tracks': [{'id': 'n', 'kind': 'narration', 'volume': .5}],
                    'narration': {'volume': .5, 'muted': False}, 'music': [], 'sfx': [],
                    'clips': [{'id': 'voice', 'kind': 'audio', 'track_id': 'n', 'asset_id': 'voice',
                               'start': 0, 'end': 2, 'volume': 1}]}
            output = root / 'mix.wav'
            audio.mix_edit_audio({}, plan, {'voice': source}, output, lambda: None)
            self.assertAlmostEqual(rms(samples(output, .2, .3)), .2*.25/math.sqrt(2), delta=.002)
            plan['narration']['muted'] = True
            audio.mix_edit_audio({}, plan, {'voice': source}, output, lambda: None)
            self.assertLess(rms(samples(output)), 1e-6)
            plan['narration']['muted'] = False
            plan['tracks'][0]['muted'] = True
            audio.mix_edit_audio({}, plan, {'voice': source}, output, lambda: None)
            self.assertLess(rms(samples(output)), 1e-6)

    def test_long_clip_batching_retains_timing_and_reuses_unchanged_narration(self):
        audio = self.audio()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            assets = {'voice': tone(root / 'voice.wav', 3, 220, .12),
                      'sfx': tone(root / 'sfx.wav', .04, 880, .1)}
            plan = {'duration': 3, 'tracks': [{'id': 'n', 'kind': 'narration'}, {'id': 's', 'kind': 'sfx'}],
                    'clips': [{'id': 'voice', 'kind': 'audio', 'track_id': 'n', 'asset_id': 'voice',
                               'start': 0, 'end': 3, 'volume': 1}], 'music': [],
                    'sfx': [dict(id=f'e{i}', track_id='s', asset_id='sfx', start=i*.1+.05,
                                 end=i*.1+.09, volume=.3) for i in range(25)]}
            output = root / 'mix.wav'
            audio.mix_edit_audio({}, plan, assets, output, lambda: None)
            cached = {str(p): p.stat().st_mtime_ns for p in (root/'audio-stems').glob('narration-*.wav')}
            self.assertTrue(cached)
            # The last event sits in a second FFmpeg batch; it must survive.
            values = samples(output, 2.455, .02)
            def component(freq):
                return abs(sum(x * complex(math.cos(2*math.pi*freq*i/16000),
                    math.sin(2*math.pi*freq*i/16000)) for i,x in enumerate(values))) / len(values)
            self.assertGreater(component(880), .008)
            plan['sfx'][0]['volume'] = .1
            audio.mix_edit_audio({}, plan, assets, output, lambda: None)
            self.assertEqual(cached, {str(p): p.stat().st_mtime_ns for p in (root/'audio-stems').glob('narration-*.wav')})

    def test_concurrent_library_requests_share_verified_files(self):
        audio = self.audio()
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(audio.ensure_sfx_library, [Path(folder)] * 4))
            self.assertEqual([item['sfx-whoosh']['sha256'] for item in results],
                             [results[0]['sfx-whoosh']['sha256']] * 4)
            manifest = Path(folder) / 'manifest.json'
            before = manifest.stat().st_mtime_ns
            audio.ensure_sfx_library(Path(folder))
            self.assertEqual(manifest.stat().st_mtime_ns, before)


if __name__ == '__main__':
    unittest.main()
