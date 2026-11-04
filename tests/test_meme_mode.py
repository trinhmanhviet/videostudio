"""Meme video mode: catalog, script validation, pipeline dispatch and a real (short) render."""
import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from videostudio import meme_pipeline
from videostudio.core import validate_request
from videostudio.meme_catalog import PROCEDURAL, load_catalog
from videostudio.meme_script import MemeScriptError, beat_range, build_prompt, to_checkpoint, validate

FFMPEG = shutil.which('ffmpeg')


def beat(**kw):
    base = {'line': 'Tôi đi làm muộn', 'shot': 'wide', 'pose': 'stand_talk', 'bg': 'room_day', 'motion': 'pop', 'sfx': 'pop', 'fx': []}
    base.update(kw)
    return base


def story(n=8):
    beats = [beat(line=f'Câu chuyện số {i} rất là buồn cười') for i in range(n)]
    beats[1] = beat(shot='close', face='shock', pose=None, fx=['exclaim'], motion='punch')
    beats[2] = beat(shot='insert', prop='money', pose=None, bg='rays_yellow')
    beats[3] = beat(shot='medium', pose='open_arms', partner='arms_crossed')
    return {'title': 'Thử', 'hook': 'Lần đầu đi phỏng vấn', 'payoff': 'Cái kết bất ngờ', 'music_prompt': 'happy ukulele', 'beats': beats}


class CatalogTests(unittest.TestCase):
    def test_catalog_files_exist_and_prompt_lists_every_id(self):
        catalog = load_catalog()
        self.assertGreaterEqual(len(catalog.ids('pose', 'half')), 30)
        self.assertEqual(len(catalog.ids('face')), 10)
        listing = catalog.describe_for_prompt()
        for ident, item in catalog.items.items():
            self.assertTrue(Path(item['path']).is_file(), ident)
            self.assertIn('- ' + ident + ':', listing)
        for ident in PROCEDURAL:
            self.assertEqual(catalog.background(ident, (72, 80)).size, (72, 80))

    def test_fingerprint_is_stable(self):
        self.assertEqual(load_catalog().fingerprint(), load_catalog().fingerprint())

    def test_new_drawings_are_imported_once_and_listed(self):
        from PIL import Image, ImageDraw
        from videostudio.meme_catalog import PACK, Catalog, refresh_library
        with tempfile.TemporaryDirectory() as folder:
            pack = Path(folder)
            (pack / 'new').mkdir()
            shutil.copytree(PACK / 'catalog' / 'panda', pack / 'catalog' / 'panda')
            shutil.copy(PACK / 'catalog' / 'panda.json', pack / 'catalog' / 'panda.json')
            sheet = Image.new('RGB', (900, 1400), (255, 0, 255))
            draw = ImageDraw.Draw(sheet)
            for i in range(8):
                x, y = 80 + (i % 2) * 450, 80 + (i // 2) * 330
                draw.ellipse([x, y, x + 250, y + 200], fill=(250, 250, 250), outline=(0, 0, 0), width=8)
            sheet.save(pack / 'new' / 'prop_food.png')
            Image.new('RGB', (300, 500), (90, 140, 200)).save(pack / 'new' / 'bg_beach_test.png')
            self.assertTrue(refresh_library(pack))
            self.assertFalse(refresh_library(pack))  # up to date: nothing to do
            catalog = Catalog(pack)
            self.assertEqual(catalog.kind('bubble_tea'), 'prop')
            self.assertIn('bg_beach_test', catalog.backgrounds)
            self.assertIn('- noodles:', catalog.describe_for_prompt())
            self.assertEqual(catalog.background('bg_beach_test', (72, 80)).size, (72, 80))


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.request = {'idea': 'phỏng vấn', 'duration_seconds': 20}

    def test_valid_story_normalizes(self):
        result = validate(story(), self.catalog, self.request)
        self.assertEqual(len(result['beats']), 8)
        self.assertEqual(result['beats'][1]['shot'], 'close')
        self.assertEqual(result['beats'][3]['partner'], 'arms_crossed')

    def test_unknown_ids_are_reported_in_strict_mode_and_repaired_when_lenient(self):
        bad = story()
        bad['beats'][0]['pose'] = 'dragon'
        bad['beats'][1]['face'] = None
        bad['beats'][2]['bg'] = 'mars'
        with self.assertRaises(MemeScriptError) as caught:
            validate(bad, self.catalog, self.request)
        self.assertIn('unknown pose "dragon"', str(caught.exception))
        self.assertIn('close shot needs a face', str(caught.exception))
        fixed = validate(bad, self.catalog, self.request, lenient=True)
        self.assertEqual(fixed['beats'][0]['pose'], 'stand_talk')
        self.assertEqual(fixed['beats'][1]['face'], 'talk')
        self.assertEqual(fixed['beats'][2]['bg'], 'room_day')  # unknown background keeps the previous one

    def test_beat_count_follows_duration(self):
        low, high, target = beat_range(60)
        self.assertEqual(target, 25)
        with self.assertRaises(MemeScriptError):
            validate(story(4), self.catalog, {'idea': 'x', 'duration_seconds': 60})

    def test_checkpoint_feeds_speech_stage(self):
        checkpoint = to_checkpoint(validate(story(), self.catalog, self.request), 'abc')
        self.assertEqual(len(checkpoint['scenes']), 8)
        self.assertEqual(checkpoint['scenes'][0]['narration_lines'], [checkpoint['scenes'][0]['narration']])
        self.assertEqual(checkpoint['meme']['hook'], 'Lần đầu đi phỏng vấn')

    def test_prompt_contains_catalog_and_feedback(self):
        prompt = build_prompt(self.request, self.catalog, ['beat 2: unknown fx'])
        self.assertIn('stand_talk', prompt)
        self.assertIn('unknown fx', prompt)

    def test_request_accepts_meme_mode_with_bounds(self):
        ok = validate_request({'idea': 'x', 'voice_id': 'v', 'duration_seconds': 60, 'workflow_mode': 'meme'})
        self.assertEqual(ok['workflow_mode'], 'meme')
        with self.assertRaises(ValueError):
            validate_request({'idea': 'x', 'voice_id': 'v', 'duration_seconds': 1200, 'workflow_mode': 'meme'})


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = {'id': 'job', 'output': self.temp.name, 'request': {'idea': 'phỏng vấn', 'duration_seconds': 20, 'workflow_mode': 'meme'},
                    'checkpoints': {}}

    def test_script_retries_with_feedback_then_accepts(self):
        bad = story()
        bad['beats'][0]['pose'] = 'dragon'
        pipeline = Mock()
        pipeline.llm_json.side_effect = [bad, story()]
        result = meme_pipeline.script(pipeline, self.job, lambda: None)
        self.assertEqual(pipeline.llm_json.call_count, 2)
        self.assertIn('dragon', pipeline.llm_json.call_args_list[1].args[0])
        self.assertEqual(len(result['scenes']), 8)
        self.assertTrue((Path(self.temp.name) / 'meme-script.json').is_file())
        # Resume reads the saved attempts instead of asking again.
        pipeline.llm_json.reset_mock()
        meme_pipeline.script(pipeline, self.job, lambda: None)
        pipeline.llm_json.assert_not_called()

    def test_script_falls_back_to_lenient_after_budget(self):
        bad = story()
        bad['beats'][0]['pose'] = 'dragon'
        pipeline = Mock()
        pipeline.llm_json.return_value = bad
        result = meme_pipeline.script(pipeline, self.job, lambda: None)
        self.assertEqual(result['scenes'][0]['meme']['pose'], 'stand_talk')

    def test_images_stage_checks_assets_without_generation(self):
        catalog = load_catalog()
        self.job['checkpoints']['script'] = to_checkpoint(validate(story(), catalog, self.job['request']), catalog.fingerprint())
        result = meme_pipeline.images(Mock(), self.job, lambda: None)
        self.assertEqual(result['image_provider'], 'meme_assets')
        self.assertIn('money', result['meme_assets']['sprites'])

    def test_music_uses_story_prompt(self):
        self.job['checkpoints'] = {'plan': {'music_prompt': 'old'}, 'script': {'meme': {'music_prompt': 'happy ukulele'}}}
        self.assertEqual(meme_pipeline.music_job(self.job)['checkpoints']['plan']['music_prompt'], 'happy ukulele')
        self.assertEqual(self.job['checkpoints']['plan']['music_prompt'], 'old')

    def test_provider_stages_dispatch_to_meme_mode(self):
        from videostudio.providers import Pipeline
        pipeline = Pipeline.__new__(Pipeline)
        result = pipeline.research(self.job, lambda: None)
        self.assertEqual(result['mode'], 'meme_no_research')


@unittest.skipUnless(FFMPEG, 'ffmpeg required')
class RenderTests(unittest.TestCase):
    def test_short_render_is_1080x1920_with_audio_and_reused(self):
        from videostudio.meme_render import render_meme
        catalog = load_catalog()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            script = to_checkpoint(validate(story(), catalog, {'idea': 'x', 'duration_seconds': 20}, lenient=True), catalog.fingerprint())
            scenes = script['scenes'][:4]
            rate, each = 16000, 0.6
            with wave.open(str(out / 'speech.wav'), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
                w.writeframes(b''.join(struct.pack('<h', int(6000 * math.sin(i / 8))) for i in range(int(rate * each * len(scenes)))))
            utterances = [{**s, 'start': i * each, 'end': (i + 1) * each} for i, s in enumerate(scenes)]
            job = {'id': 'j', 'output': folder, 'request': {'idea': 'x'},
                   'checkpoints': {'script': script, 'speech': {'path': str(out / 'speech.wav'), 'duration_seconds': each * len(scenes), 'utterances': utterances}}}
            result = render_meme(job, lambda: None, catalog)
            probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', result['video']]))
            video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (1080, 1920))
            self.assertTrue(any(s['codec_type'] == 'audio' for s in probe['streams']))
            self.assertAlmostEqual(float(probe['format']['duration']), 2.4, delta=0.1)
            self.assertTrue(render_meme(job, lambda: None, catalog).get('reused'))


if __name__ == '__main__':
    unittest.main()
