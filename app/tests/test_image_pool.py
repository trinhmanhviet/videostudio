import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from videostudio import image_pool
from videostudio.core import validate_request
from videostudio.image_pool import add_picture, compose, load_pool, match, save_pool

POOL = 'a' * 32


def jpeg(width=800, height=600, color=(200, 40, 40)):
    data = io.BytesIO()
    picture = Image.new('RGB', (width, height), color)
    for x in range(0, width, 40):  # some detail, so it is not a flat colour
        picture.paste((20, 20, 20), (x, 0, x + 10, height))
    picture.save(data, format='JPEG')
    return data.getvalue()


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_only_real_pictures_of_a_useful_size_join_the_pool(self):
        self.assertIsNone(add_picture(POOL, b'not a picture', 'x', 'y', 'web', 1, root=self.root))
        self.assertIsNone(add_picture(POOL, jpeg(200, 150), 'tiny', 'y', 'web', 2, root=self.root))
        self.assertIsNone(add_picture(POOL, jpeg(2000, 300), 'banner', 'y', 'web', 3, root=self.root))
        kept = add_picture(POOL, jpeg(), 'Jensen Huang trên sân khấu', 'https://example.com/a', 'web', 4, root=self.root)
        self.assertEqual(kept['file'], 'pool/web-04.jpg')
        save_pool(POOL, [kept, {'file': '../../outside.jpg', 'mo_ta': 'x'}], root=self.root)
        self.assertEqual([p['mo_ta'] for p in load_pool(POOL, root=self.root)], ['Jensen Huang trên sân khấu'])
        with self.assertRaises(ValueError):
            load_pool('../x', root=self.root)

    def test_scene_image_keeps_the_whole_photo_on_a_blurred_background(self):
        source = self.root / 'tall.jpg'
        source.write_bytes(jpeg(600, 900))
        target = self.root / 'scene.png'
        compose(source, target)
        with Image.open(target) as picture:
            self.assertEqual(picture.size, (1920, 1080))
            self.assertNotEqual(picture.getpixel((5, 540)), (0, 0, 0))   # the sides are the blurred photo, not black bars

    def test_chatgpt_picks_pictures_and_a_bad_answer_falls_back_to_round_robin(self):
        scenes = [{'narration': f'câu {i}', 'visual_prompt': 'p'} for i in range(5)]
        pictures = [{'mo_ta': 'a'}, {'mo_ta': 'b'}]
        self.assertEqual(match(scenes, pictures, lambda prompt: {'chon': [1, 0, 1, 0, 1]}), ([1, 0, 1, 0, 1], 'chatgpt'))
        for bad in ({'chon': [0, 1]}, {'chon': [0, 1, 2, 0, 1]}, {}, None):
            self.assertEqual(match(scenes, pictures, lambda prompt, bad=bad: bad), ([0, 1, 0, 1, 0], 'round_robin'))

        def broken(prompt):
            raise RuntimeError('ChatGPT down')
        self.assertEqual(match(scenes, pictures, broken)[1], 'round_robin')

    def test_requests_name_their_pool(self):
        base = {'idea': 'x', 'voice_id': 'v', 'duration_seconds': 60}
        self.assertEqual(validate_request({**base, 'image_provider': 'pool', 'image_pool': POOL})['image_pool'], POOL)
        for bad in ({'image_provider': 'pool'}, {'image_provider': 'comfy', 'image_pool': POOL}, {'image_provider': 'pool', 'image_pool': 'x'}):
            with self.assertRaises(ValueError):
                validate_request({**base, **bad})


class UnverifiedResearchScriptTests(unittest.TestCase):
    def test_links_the_model_lists_without_any_source_document_do_not_fail_the_script(self):
        """A Facebook idea carries links; ChatGPT research keeps no documents to check them against (2026-11-16)."""
        from unittest.mock import Mock
        from videostudio.providers import Pipeline
        p = Pipeline.__new__(Pipeline)
        script = {'narration': 'Jensen Huang rời ghế CEO?', 'source_paths': ['https://nvidianews.nvidia.com/news/x'],
                  'scenes': [{'narration': 'Jensen Huang rời ghế CEO?', 'visual_prompt': 'A keynote stage.'}]}
        p.llm_json = Mock(return_value=script)
        job = {'request': {'image_provider': 'pool', 'image_pool': POOL, 'duration_seconds': 30, 'idea': 'Jensen Huang'},
               'checkpoints': {'plan': {}, 'research': {'sources': []}}}
        self.assertEqual(p._script_draft(job, lambda: None, [])['source_paths'], [])
        # with source documents, a link that is not one of them still fails, as before
        job['checkpoints']['research']['sources'] = [{'path': 'doc-1.txt', 'text': 'x'}]
        p.llm_json = Mock(return_value={**script, 'source_paths': ['https://elsewhere.example/x']})
        with self.assertRaisesRegex(ValueError, 'Unattributed'):
            p._script_draft(job, lambda: None, [])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(image_pool, 'ROOT', self.tmp / 'posts')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out = self.tmp / 'out'
        self.out.mkdir()
        self.job = {'id': 'job-1', 'output': str(self.out), 'request': {'image_provider': 'pool', 'image_pool': POOL},
                    'checkpoints': {'speech': {'duration_seconds': 9.0, 'scenes': [
                        {'narration': f'cảnh {i}', 'visual_prompt': f'p{i}', 'duration': 3.0} for i in range(3)]}}}
        from videostudio.providers import Pipeline
        self.run = lambda owner: Pipeline._pool_images(owner, self.job, lambda: None)

    def fill(self, count):
        entries = [add_picture(POOL, jpeg(color=(40 * i, 90, 160)), f'ảnh {i}', f'https://example.com/{i}', 'web', i) for i in range(1, count + 1)]
        save_pool(POOL, entries)

    def test_scenes_get_real_pictures_chosen_by_chatgpt_and_reuse_them_on_retry(self):
        self.fill(3)
        owner = types.SimpleNamespace(store=None, _images=mock.Mock())
        with mock.patch('videostudio.story_editor.ask_chatgpt', return_value={'chon': [2, 0, 1]}) as ask:
            result = self.run(owner)
            self.run(owner)  # retry: the saved choice and pictures are reused
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(result['image_provider'], 'pool')
        self.assertEqual(len(result['scenes']), 3)
        self.assertEqual(sum(s['duration'] for s in result['scenes']), 9.0)
        saved = json.loads((self.out / 'images-0000.checkpoint.json').read_text(encoding='utf-8'))
        self.assertEqual((saved['provider'], saved['source'], saved['mo_ta']), ('pool', 'pool/web-03.jpg', 'ảnh 3'))
        self.assertIn('https://example.com/1', result['image_sources'])
        owner._images.assert_not_called()
        # the pool grew (pictures fetched later): the scenes are matched again, not with the old choice
        self.fill(4)
        with mock.patch('videostudio.story_editor.ask_chatgpt', return_value={'chon': [3, 1, 0]}) as again:
            self.run(owner)
        self.assertEqual(again.call_count, 1)

    def test_too_few_pictures_draw_the_scenes_instead(self):
        self.fill(2)
        owner = types.SimpleNamespace(store=None, _images=mock.Mock(return_value={'image_provider': 'comfy'}))
        self.assertEqual(self.run(owner), {'image_provider': 'comfy'})
        drawn = owner._images.call_args.args[0]['request']
        self.assertEqual((drawn['image_provider'], drawn['flow_batch_size']), ('comfy', 1))


if __name__ == '__main__':
    unittest.main()
