import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from videostudio import media
from videostudio.core import PermanentError
from videostudio.providers import Pipeline, timeline_duration, flow_reference_enabled


class NaturalDurationTests(unittest.TestCase):
    def test_all_workflows_keep_natural_speech_despite_seconds_or_minutes_deviation(self):
        real_run = media.run
        for mode in (None, 'research', 'provided_narration'):
            for requested, measured in ((30, 35), (30, 210), (240, 60)):
                with self.subTest(mode=mode, requested=requested, measured=measured), tempfile.TemporaryDirectory() as tmp:
                    pipeline = Pipeline.__new__(Pipeline)
                    pipeline.voices = SimpleNamespace(selected=lambda voice: {'id': voice})
                    pipeline.speech_python = 'unused-model-runtime'
                    pipeline.speech_cache = tmp
                    pipeline.ffmpeg = 'ffmpeg'
                    pipeline.ffprobe = 'ffprobe'
                    pipeline.llm_json = Mock(side_effect=AssertionError('Duration guidance must not trigger a rewrite'))
                    script = {'narration': 'First line. Second line.', 'scenes': [
                        {'narration': 'First line.', 'visual_prompt': 'First scene'},
                        {'narration': 'Second line.', 'visual_prompt': 'Second scene'},
                    ]}
                    request = {'duration_seconds': requested, 'voice_id': 'unchanged-clone'}
                    if mode is not None:
                        request['workflow_mode'] = mode
                    job = {'id': 'test-job', 'output': tmp, 'request': request, 'checkpoints': {'script': script, 'research': {'sources': []}}}
                    commands = []

                    def synth_or_run(args, check, timeout=900):
                        commands.append([str(arg) for arg in args])
                        if '-m' not in args:
                            return real_run(args, check, timeout)
                        payload = json.loads(args[-1])
                        self.assertEqual(payload['voice']['id'], 'unchanged-clone')
                        samples = b''.join(struct.pack('<h', int(2000 * math.sin(2 * math.pi * 250 * i / 8000))) for i in range(8000))
                        with wave.open(payload['output'], 'wb') as wav:
                            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                            wav.writeframes((samples * math.ceil(measured / 2))[:int(measured / 2 * 8000) * 2])
                        return b''

                    with patch('videostudio.providers.run', side_effect=synth_or_run):
                        result = pipeline.speech(job, lambda: None)
                    self.assertAlmostEqual(result['duration_seconds'], measured, places=3)
                    self.assertEqual(result['duration_attempts'], 1)
                    self.assertEqual(result['final_narration'], script['narration'])
                    self.assertAlmostEqual(sum(u['duration'] for u in result['utterances']), measured, places=3)
                    self.assertTrue(all(u['start'] >= 0 and u['end'] > u['start'] for u in result['utterances']))
                    self.assertFalse(any('-t' in command or any('atempo' in arg for arg in command) for command in commands))
                    self.assertEqual(json.loads((Path(tmp) / 'final-script.json').read_text()), script)
                    self.assertEqual(timeline_duration({**job, 'checkpoints': {'speech': result}}), measured)
                    pipeline.llm_json.assert_not_called()

    def test_technical_speech_failures_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline.__new__(Pipeline)
            pipeline._speech_attempt = Mock(side_effect=PermanentError('Invalid narration audio stream'))
            pipeline.llm_json = Mock()
            job = {'output': tmp, 'request': {'duration_seconds': 30}, 'checkpoints': {'script': {'narration': 'Keep words.', 'scenes': []}}}
            with self.assertRaisesRegex(PermanentError, 'audio stream'):
                pipeline.speech(job, lambda: None)
            pipeline._speech_attempt.assert_called_once()
            pipeline.llm_json.assert_not_called()

    def test_nonfinite_or_empty_measured_timeline_is_invalid(self):
        for measured in (0, -1, float('inf'), float('nan'), True):
            with self.subTest(measured=measured), self.assertRaises(PermanentError):
                timeline_duration({'request': {'duration_seconds': 30}, 'checkpoints': {'speech': {'duration_seconds': measured}}})

    def test_verified_output_and_visual_audio_reuse_keep_original_effective_duration(self):
        job = {'request': {'duration_seconds': 30}, 'checkpoints': {'speech': {'duration_seconds': 28},
               'verify': {'verified': True, 'duration_seconds': 30}}}
        self.assertEqual(timeline_duration(job), 30)
        job['checkpoints'].pop('verify')
        job['checkpoints']['images'] = {'reuse_audio': {'path': 'original.mp4'}, 'scenes': [{'duration': 14}, {'duration': 16}]}
        self.assertEqual(timeline_duration(job), 30)

    def test_flow_reference_limit_uses_actual_timeline(self):
        for requested, measured, enabled in ((30, 310, False), (600, 120, True)):
            with self.subTest(measured=measured):
                job = {'request': {'image_provider': 'flow', 'duration_seconds': requested}, 'checkpoints': {'speech': {'duration_seconds': measured}}}
                self.assertEqual(flow_reference_enabled(job), enabled)

    def test_music_render_and_verification_receive_measured_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.ffmpeg = 'ffmpeg'
            pipeline.ffprobe = 'ffprobe'
            pipeline.accepted_music = lambda: True
            pipeline.comfy_asset = Mock(return_value={'assets': []})
            job = {'id': '11111111-1111-4111-8111-111111111111', 'output': tmp,
                   'request': {'duration_seconds': 600, 'workflow_mode': 'research'},
                   'checkpoints': {'plan': {'music_prompt': 'Quiet instrumental'},
                       'speech': {'duration_seconds': 35, 'path': 'speech.wav'},
                       'images': {'scenes': [{'path': 'scene.png', 'duration': 35}]},
                       'subtitles': {'path': 'captions.ass'}, 'music': {'path': 'music.wav'},
                       'render': {'video': 'video.mp4'}}}
            with patch('videostudio.providers.probe', return_value={'format': {'duration': '35'}}), patch('videostudio.providers.run', return_value=b''), patch('videostudio.music.normalize_music_levels', return_value={'path': 'music.wav', 'audio_quality': {}, 'raw_audio_quality': {}, 'assets': []}):
                pipeline.music(job, lambda: None)
            self.assertEqual(pipeline.comfy_asset.call_args.args[2]['5']['inputs']['seconds'], 35)
            with patch('videostudio.visual_quality.require_release', return_value={}), patch('videostudio.providers.render', return_value={}) as renderer:
                pipeline.render(job, lambda: None)
            self.assertEqual(renderer.call_args.args[5], 35)
            with patch('videostudio.visual_quality.require_release', return_value={}), patch('videostudio.providers.verify', return_value={}) as verifier, patch('videostudio.providers.run', return_value=b''), patch('videostudio.media.audio_report', return_value={}):
                pipeline.verify(job, lambda: None)
            self.assertEqual(verifier.call_args.args[1], 35)


class TechnicalDurationTests(unittest.TestCase):
    def test_verify_rejects_invalid_duration_and_missing_streams(self):
        valid = {'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920, 'avg_frame_rate': '30/1'}, {'codec_type': 'audio'}], 'format': {'duration': '35'}}
        for duration in ('0', '-1', 'nan', 'inf', '40'):
            with self.subTest(duration=duration), patch('videostudio.media.probe', return_value={**valid, 'format': {'duration': duration}}), patch('videostudio.media.asset', return_value={}):
                with self.assertRaises(PermanentError):
                    media.verify('unused.mp4', 35)
        with patch('videostudio.media.probe', return_value={**valid, 'streams': valid['streams'][:1]}):
            with self.assertRaises(PermanentError):
                media.verify('unused.mp4', 35)


if __name__ == '__main__':
    unittest.main()
