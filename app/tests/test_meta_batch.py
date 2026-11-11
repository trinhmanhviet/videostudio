import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from videostudio.core import PermanentError, validate_request
from videostudio.providers import MetaQuotaExhausted
from videostudio.providers import Pipeline

MAI = 'A 30-year-old slim woman with a short red bob, a green raincoat and black rubber boots.'
TUAN = 'A heavy-set 50-year-old man with a shaved head, a grey suit and round glasses.'


def scene(k, ids):
    looks = ' '.join(f'{n}: {d}' for n, d in (('Mai', MAI), ('Tuấn', TUAN)) if n.lower().replace('ấ', 'a') in ids or n == 'Mai' and 'mai' in ids)
    return {'visual_prompt': f'Realistic documentary, vertical 9:16. | Mai: {MAI} | Close-up {k}: Mai grips the door handle. {looks}',
            'character_ids': ids, 'duration': 3.0}


def picture(path, color):
    image = Image.new('RGB', (1024, 576), color)
    ImageDraw.Draw(image).rectangle((100, 100, 400, 300), fill=(250, 250, 250))
    image.save(path)


class MetaBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.p = Pipeline.__new__(Pipeline)
        self.posts, self.singles = [], []
        self.short = None

        def post(payload, check):
            self.posts.append(payload)
            folder = self.out / 'daemon' / payload['batch_id']; folder.mkdir(parents=True, exist_ok=True)
            count = payload['count'] if self.short is None else min(self.short, payload['count'])
            images = []
            for k in range(count):
                f = folder / f'img-{k}.png'
                picture(f, ((len(self.posts) * 50 + k * 20) % 255, 80, 120))
                images.append({'file_path': str(f), 'sha256': 'x'})
            return {'batch_id': payload['batch_id'], 'url': 'https://meta.ai/prompt/abc', 'images': images}
        self.p._meta_batch_post = post

        def single(provider, j, i, prompt, path, check):
            self.singles.append(i)
            picture(path, (10, 200, 30))
            return {'task_id': f'single-{i}', 'request_id': None}
        self.p._browser_scene_image = single

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, n=10):
        items = [scene(k, ['mai', 'tuan'] if k % 2 else ['mai']) for k in range(n)]
        return {'id': '11111111-2222-3333-4444-555555555555', 'output': str(self.out), 'events': [],
                'request': {'image_provider': 'meta', 'meta_batch_size': 8},
                'checkpoints': {'plan': {'visual_style': 'Realistic documentary photography, vertical 9:16, Guangxi 2007.',
                                         'characters': [{'character_id': 'mai', 'name': 'Mai', 'description': MAI},
                                                        {'character_id': 'tuan', 'name': 'Tuấn', 'description': TUAN}]},
                                'speech': {'scenes': items, 'duration_seconds': 3.0 * n}}}

    def test_request_defaults_meta_to_batches_and_rejects_it_elsewhere(self):
        base = {'idea': 'x', 'voice_id': 'preset:test', 'duration_seconds': 45}
        self.assertEqual(validate_request({**base, 'image_provider': 'meta'})['meta_batch_size'], 8)
        self.assertEqual(validate_request({**base, 'image_provider': 'meta', 'meta_batch_size': 1})['meta_batch_size'], 1)
        self.assertEqual(validate_request({**base, 'image_provider': 'comfy'})['meta_batch_size'], 1)
        with self.assertRaises(ValueError):
            validate_request({**base, 'image_provider': 'comfy', 'meta_batch_size': 8})

    def test_portraits_then_scenes_in_batches_of_eight_with_references(self):
        result = self.p._meta_batch_images(self.job(10), lambda: None)
        portraits, *scenes = self.posts
        self.assertEqual(portraits['count'], 2)
        self.assertEqual(portraits['references'], [])
        self.assertEqual([s['count'] for s in scenes], [8, 2])
        for s in scenes:
            self.assertNotIn('\n', s['prompt'])
            self.assertIn('Photo A:', s['prompt'])
            self.assertIn('image 1 is Mai', s['prompt'])
            self.assertEqual(len(s['references']), 2)
            self.assertEqual(s['prompt'].count(MAI), 0)  # looks come from the portraits
            self.assertNotIn('9:16', s['prompt'])
        self.assertEqual(len(result['scenes']), 10)
        self.assertEqual(result['reference_mode'], 'meta_batch_portraits')
        saved = json.loads((self.out / 'images-0009.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual((saved['provider'], saved['meta_batch_index']), ('meta', 1))
        # A retry reuses every finished picture and portrait: nothing is sent again.
        self.posts.clear()
        self.p._meta_batch_images(self.job(10), lambda: None)
        self.assertEqual(self.posts, [])

    def test_an_incomplete_batch_is_resent_scene_by_scene_with_references(self):
        # Meta returned 5 of 8: which picture is which is unknown, so none of them is used.
        self.short = 5
        self.p._meta_batch_images(self.job(8), lambda: None)
        portraits, batch, *alone = self.posts
        self.assertEqual(batch['count'], 8)
        self.assertEqual([a['count'] for a in alone], [1] * 8)
        self.assertTrue(all(a['references'] for a in alone))
        self.assertEqual(self.singles, [])
        saved = json.loads((self.out / 'images-0006.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual(saved['meta_batch'], alone[6]['batch_id'])

    def test_scene_refused_even_alone_falls_back_to_plain_prompt(self):
        original = self.p._meta_batch_post

        def refuse_scenes(payload, check):
            if 'character reference photos' in payload['prompt']:
                return original(payload, check)
            return None  # Meta refused: the batch and every scene sent alone
        self.p._meta_batch_post = refuse_scenes
        self.p._meta_batch_images(self.job(3), lambda: None)
        self.assertEqual(self.singles, [0, 1, 2])

    def refuse(self, softened_ok=False, comfy_ok=False):
        original = self.p._meta_batch_post

        def post(payload, check):
            if 'character reference photos' in payload['prompt']:
                return original(payload, check)
            if softened_ok and 'shadow on the wall' in payload['prompt']:
                return original(payload, check)
            return None
        self.p._meta_batch_post = post

        def single(provider, j, i, prompt, path, check):
            self.singles.append(i)
            raise PermanentError('Meta AI trả lời chữ, không tạo ảnh')
        self.p._browser_scene_image = single
        self.p.llm_json = lambda prompt, check: {'visual_prompt': 'The shadow on the wall beside the door.'}
        self.comfy_calls = []
        if comfy_ok:
            self.p.comfy = 'http://127.0.0.1:8188'
            self.p._comfy_scene_graph = lambda j, u, i, prefix, refs, check: (self.comfy_calls.append((i, sorted(refs))) or {'4': {'inputs': {'prompt': 'p'}}}, [])
            self.p.comfy_asset = lambda j, kind, graph, path, check: picture(path, (90, 90, 90))

    def test_refused_scene_is_told_by_implication_then_sent_again(self):
        self.refuse(softened_ok=True)
        self.p._meta_batch_images(self.job(2), lambda: None)
        saved = json.loads((self.out / 'images-0001.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual(saved['substitute'], 'softened')
        self.assertIn('shadow on the wall', saved['submitted_prompt'])
        self.assertEqual(self.singles, [0, 1])

    def test_comfy_draws_what_meta_refuses_with_the_meta_portraits(self):
        self.refuse(comfy_ok=True)
        self.p._meta_batch_images(self.job(2), lambda: None)
        self.assertEqual(self.comfy_calls, [(0, ['mai', 'tuan']), (1, ['mai', 'tuan'])])
        saved = json.loads((self.out / 'images-0000.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual(saved['substitute'], 'comfy')

    def test_unmakeable_scene_borrows_the_nearest_picture_and_the_video_goes_on(self):
        drawing = self.p._meta_batch_post
        self.refuse()
        # Only scene 0 can be drawn (alone); the batch and scenes 1-2 are refused everywhere.
        self.p._meta_batch_post = lambda payload, check: drawing(payload, check) if 'character reference photos' in payload['prompt'] or (payload['count'] == 1 and 'Close-up 0' in payload['prompt']) else None
        result = self.p._meta_batch_images(self.job(3), lambda: None)
        self.assertEqual(len(result['scenes']), 3)
        saved = json.loads((self.out / 'images-0002.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual((saved['substitute'], saved['substitute_from_scene']), ('neighbor', 0))

    def test_no_credits_for_references_resends_the_batch_in_words(self):
        drawing = self.p._meta_batch_post

        def post(payload, check):
            if payload['references']:
                raise MetaQuotaExhausted('Meta AI hết lượt tạo ảnh: You reached your limit')
            return drawing(payload, check)
        self.p._meta_batch_post = post
        self.p._meta_batch_images(self.job(10), lambda: None)
        portraits, first, second = self.posts
        self.assertEqual((first['count'], second['count']), (8, 2))
        self.assertEqual((first['references'], second['references']), ([], []))
        self.assertIn('People: Mai: ' + MAI, first['prompt'])
        self.assertEqual(self.singles, [])

    def test_no_credits_at_all_draws_every_scene_with_comfy_using_the_portraits(self):
        drawing = self.p._meta_batch_post
        self.p._meta_batch_post = lambda payload, check: drawing(payload, check) if 'character reference photos' in payload['prompt'] else (_ for _ in ()).throw(MetaQuotaExhausted('no credits'))
        self.comfy_calls = []
        self.p.comfy = 'http://127.0.0.1:8188'
        self.p._comfy_scene_graph = lambda j, u, i, prefix, refs, check: (self.comfy_calls.append(i) or {'4': {'inputs': {'prompt': 'p'}}}, [])
        self.p.comfy_asset = lambda j, kind, graph, path, check: picture(path, (90, 90, 90))
        self.p.llm_json = lambda prompt, check: self.fail('no rewrite when Meta has no credits')
        self.p._meta_batch_images(self.job(3), lambda: None)
        self.assertEqual(self.comfy_calls, [0, 1, 2])
        self.assertEqual(self.singles, [])
        self.assertEqual(len(self.posts), 1)  # only the portraits went to Meta

    def test_scene_text_keeps_the_moment_only(self):
        text = Pipeline._meta_scene_text(scene(3, ['mai']))
        self.assertTrue(text.startswith('Close-up 3: Mai grips the door handle.'))
        self.assertNotIn(MAI, text)



class MetaDeclineReceiptTests(unittest.TestCase):
    def test_a_declined_batch_is_recorded_so_it_is_never_asked_about_again(self):
        import asyncio
        from videostudio.cdp_meta import MetaImages
        with tempfile.TemporaryDirectory() as tmp:
            meta = MetaImages(None, Path(tmp))
            batch = '11111111-2222-3333-4444-555555555555'
            meta._batch_dir(batch).mkdir(parents=True)
            (meta._batch_dir(batch) / 'sent.json').write_text('{}', encoding='utf8')
            data = asyncio.run(meta._save_batch(batch, [], 'https://meta.ai/prompt/x', 1))
            self.assertEqual((data['images'], data['complete']), ([], False))
            self.assertEqual(meta._batch_done(batch), data)
            self.assertFalse((meta._batch_dir(batch) / 'sent.json').exists())

    def test_single_picture_wait_returns_the_picture_or_reports_a_decline(self):
        import asyncio
        from unittest.mock import patch
        import videostudio.cdp_meta as cdp_meta

        class Page(cdp_meta.MetaImages):
            def __init__(self, frames):
                self.frames, self.polls = frames, 0

            async def _images(self, session):
                self.polls += 1
                return self.frames(self.polls)

            async def _state(self, session):
                return {'url': '', 'reply': ''}

        async def instant(_):
            return None
        url = 'https://scontent.x.fbcdn.net/a.jpg'
        with patch.object(cdp_meta.asyncio, 'sleep', instant):
            found, _ = asyncio.run(Page(lambda n: [] if n < 3 else [(url, 1, 1)])._wait_image(None, set(), 30))
            self.assertEqual(found, [(url, 1, 1)])
            with patch.object(cdp_meta, 'NO_PICTURE_AFTER', -1), self.assertRaises(cdp_meta.ImageRejected):
                asyncio.run(Page(lambda n: [])._wait_image(None, set(), 30))

if __name__ == '__main__':
    unittest.main()
