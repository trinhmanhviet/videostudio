"""Synthetic memestudio regression tests; never synthesize speech or edit sample episodes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'memestudio' / 'engine'


def source_id(text, voice):
    return hashlib.sha256(json.dumps({'t': text, 'v': voice}, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def write_wav(path, seconds=0.3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * round(seconds * 48000))


class EpisodeFixture(unittest.TestCase):
    def setUp(self):
        (ROOT.parent / 'data' / 'test-tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='memestudio-test-', dir=ROOT.parent / 'data' / 'test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.episode = Path(self.temp.name)
        self.script = {
            'title': ['TEST', 'EPISODE'], 'payoff': ['TEST', 'END'],
            'narrator_voice': 'Narrator',
            'cast': {'bo': {'name': 'Bo', 'costume': 'ao_ba_ba_nau',
                            'acc': [], 'face': 'noi', 'voice': 'Father'}},
            'scenes': {'room': {'bg': 'bg_elevator', 'cast': ['bo']}},
            'beats': [
                {'scene': 'room', 'who': 'N', 'focus': 'bo', 'text': 'First narration.'},
                {'scene': 'room', 'who': 'N', 'focus': 'bo', 'text': 'Second narration.'},
                {'scene': 'room', 'who': 'bo', 'text': 'Character speaks.'},
            ],
        }
        self.voices = []
        for n, beat in enumerate(self.script['beats']):
            vid = 'Narrator' if beat['who'] == 'N' else 'Father'
            resolved = {'id': vid, 'kind': 'preset', 'available': True}
            wav = self.episode / 'assets' / 'voice' / f'{n:02}_{beat["who"]}.wav'
            write_wav(wav)
            ident = source_id(beat['text'], resolved)
            wav.with_suffix('.id').write_text(ident)
            self.voices.append({'n': n, 'who': beat['who'], 'voice': vid,
                                'file': wav.relative_to(self.episode).as_posix(),
                                'duration': 0.3, 'text': beat['text'],
                                'resolved_voice': resolved, 'source_id': ident,
                                'wav_sha256': hashlib.sha256(wav.read_bytes()).hexdigest()})
        self.save()

    def save(self):
        (self.episode / 'script.json').write_text(json.dumps(self.script), encoding='utf-8')
        (self.episode / 'voice.json').write_text(json.dumps(self.voices), encoding='utf-8')

    def run_engine(self, name='make_episode', *args):
        return subprocess.run([sys.executable, '-I', str(ENGINE / f'{name}.py'),
                               str(self.episode), *args], capture_output=True, text=True,
                              encoding='utf-8', timeout=30)

    def assert_stale(self):
        self.save()
        result = self.run_engine()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('make_voice.py', result.stdout)
        self.assertNotIn('Traceback', result.stderr)


class VoiceConsistencyTests(EpisodeFixture):
    def test_changed_text_with_same_count_and_speakers_is_rejected(self):
        self.script['beats'][0]['text'] = 'Changed narration.'
        self.assert_stale()

    def test_changed_cast_voice_is_rejected(self):
        self.script['cast']['bo']['voice'] = 'Another father'
        self.assert_stale()

    def test_changed_narrator_voice_is_rejected(self):
        self.script['narrator_voice'] = 'Another narrator'
        self.assert_stale()

    def test_changed_speaker_is_rejected(self):
        self.script['beats'][0]['who'] = 'bo'
        self.assert_stale()

    def test_reordered_voice_metadata_is_rejected(self):
        self.voices[0], self.voices[1] = self.voices[1], self.voices[0]
        self.assert_stale()

    def test_missing_wav_is_rejected_with_recovery_command(self):
        (self.episode / self.voices[0]['file']).unlink()
        self.assert_stale()

    def test_reordered_narration_is_rejected(self):
        self.script['beats'][0], self.script['beats'][1] = self.script['beats'][1], self.script['beats'][0]
        self.assert_stale()

    def test_legacy_metadata_is_rejected_with_recovery_command(self):
        for row in self.voices:
            for field in ('text', 'resolved_voice', 'source_id', 'wav_sha256'):
                row.pop(field)
        self.assert_stale()

    def test_missing_stamp_is_rejected_with_recovery_command(self):
        (self.episode / self.voices[0]['file']).with_suffix('.id').unlink()
        self.assert_stale()

    def test_changed_resolved_identity_is_rejected(self):
        self.voices[0]['resolved_voice']['id'] = 'Wrong voice'
        self.assert_stale()

    def test_corrupted_wav_is_rejected(self):
        with (self.episode / self.voices[0]['file']).open('ab') as wav:
            wav.write(b'corruption')
        self.assert_stale()

    def test_unchanged_sources_build_composition(self):
        result = self.run_engine()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.episode / 'index.html').is_file())

    def load_voice_module(self):
        spec = importlib.util.spec_from_file_location('memestudio_make_voice_test', ENGINE / 'make_voice.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'argv', ['make_voice.py', str(self.episode)]):
            spec.loader.exec_module(module)
        return module

    def test_refreshing_legacy_metadata_reuses_matching_cached_wavs(self):
        module = self.load_voice_module()
        for row in self.voices:
            for field in ('text', 'resolved_voice', 'source_id', 'wav_sha256'):
                row.pop(field)
        self.save()
        resolved = {'Narrator': {'id': 'Narrator', 'kind': 'preset', 'available': True},
                    'Father': {'id': 'Father', 'kind': 'preset', 'available': True}}
        with patch('videostudio.voices.Voices') as voices, patch.object(module, 'duration', return_value=0.3), \
                patch.object(module.subprocess, 'run') as worker:
            voices.return_value.selected.side_effect = resolved.__getitem__
            module.main()
        worker.assert_not_called()
        rows = json.loads((self.episode / 'voice.json').read_text(encoding='utf-8'))
        self.assertEqual(rows[0]['text'], self.script['beats'][0]['text'])
        self.assertEqual(rows[0]['resolved_voice'], resolved['Narrator'])
        self.assertEqual(rows[0]['source_id'], source_id(rows[0]['text'], rows[0]['resolved_voice']))
        self.assertEqual(self.run_engine().returncode, 0)
        self.assertEqual(self.run_engine('make_sfx').returncode, 0)

    def test_make_voice_resynthesizes_corruption_despite_matching_stamp(self):
        module = self.load_voice_module()
        with (self.episode / self.voices[0]['file']).open('ab') as wav:
            wav.write(b'corruption')
        resolved = {row['voice']: row['resolved_voice'] for row in self.voices}
        with patch('videostudio.voices.Voices') as voices, patch.object(module, 'duration', return_value=0.3), \
                patch.object(module.subprocess, 'run') as worker:
            voices.return_value.selected.side_effect = resolved.__getitem__
            module.main()
        self.assertEqual(worker.call_count, 1)


class AccessoryTests(EpisodeFixture):
    def test_missing_accessories_passes_check_and_composition(self):
        self.script['cast']['bo'].pop('acc')
        self.save()
        checked = self.run_engine('make_episode', '--check')
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        result = self.run_engine()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_accessories_build_composition(self):
        self.script['cast']['bo']['acc'] = ['mu_coi', 'rau_mep']
        self.save()
        result = self.run_engine()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SfxTests(EpisodeFixture):
    def test_zero_events_writes_stereo_pcm_silence_with_planned_duration(self):
        (self.episode / 'sfx.json').write_text(json.dumps({'duration': 1.25, 'events': []}))
        # The SFX command must create its output folder itself.
        module_spec = importlib.util.spec_from_file_location('memestudio_sfx_test', ENGINE / 'make_sfx.py')
        module = importlib.util.module_from_spec(module_spec)
        with patch.object(sys, 'argv', ['make_sfx.py', str(self.episode)]):
            module_spec.loader.exec_module(module)
        module.OUT = self.episode / 'new_assets' / 'sfx.wav'
        module.main()
        with wave.open(str(module.OUT)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (2, 2, 48000))
            self.assertEqual(wav.getnframes(), 60000)
            self.assertFalse(any(wav.readframes(wav.getnframes())))

    def test_existing_events_still_mix(self):
        (self.episode / 'sfx.json').write_text(json.dumps({'duration': 1.25, 'events': [
            {'asset': 'click', 't': 0.2, 'gain': 0.8}]}))
        result = self.run_engine('make_sfx')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with wave.open(str(self.episode / 'assets' / 'sfx.wav')) as wav:
            self.assertEqual(wav.getnframes(), 60000)
            self.assertTrue(any(wav.readframes(wav.getnframes())))


if __name__ == '__main__':
    unittest.main()
