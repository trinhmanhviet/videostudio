import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from videostudio.core import Cancelled
from videostudio.providers import FlowBlocked, FlowSignedOut, Pipeline, UncertainDeliveryError

MAI = 'A 30-year-old slim woman with a short red bob, a green raincoat and black rubber boots.'


def picture(path, color=(40, 90, 120)):
    image = Image.new('RGB', (1376, 768), color)
    ImageDraw.Draw(image).rectangle((100, 100, 500, 400), fill=(240, 240, 240))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


class FlowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.p = Pipeline.__new__(Pipeline)
        self.p.comfy = 'http://127.0.0.1:8188'
        self.flow_calls, self.comfy_calls, self.plan, self.portraits = [], [], {}, []

        def flow(provider, j, i, prompt, path, check, **kwargs):
            self.flow_calls.append(i)
            action = self.plan.get(i, 'ok')
            if action == 'blocked':
                raise FlowBlocked('Flow vẫn bị chặn: ảnh vẫn lỗi sau 1 lần thử lại')
            if action == 'signed_out':
                raise FlowSignedOut('needs sign-in')
            if action == 'uncertain':
                raise UncertainDeliveryError('uncertain')
            picture(path, (10 + i, 90, 120))
            return {'task_id': f'flow-{i}', 'request_id': None, 'media_id': 'media', 'project_url': 'https://flow.google.com/project/x'}
        self.p._browser_scene_image = flow

        def graph(j, u, i, prefix, refs, check):
            self.comfy_calls.append((i, sorted(refs)))
            return {'4': {'inputs': {'prompt': 'p'}}}, [r['portrait_sha256'] for r in refs.values()]
        self.p._comfy_scene_graph = graph
        self.p.comfy_asset = lambda j, kind, graph, path, check: picture(path, (200, 90, 20))
        self.p._comfy_character_references = lambda j, items, check: {items[0]['character_ids'][0]: {
            'character_id': items[0]['character_ids'][0], 'name': 'Mai', 'portrait_path': 'comfy.png', 'portrait_sha256': 'comfy-sha'}}

        def ensure(pipeline, job, reference, check):
            self.portraits.append(reference['name'])
            return {**reference, 'portrait_path': 'flow.png', 'portrait_sha256': 'flow-sha'}, []
        patcher = patch('videostudio.flow_reference_assets.ensure_portrait', ensure)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, n=12, folder=None):
        out = Path(folder or self.out)
        out.mkdir(parents=True, exist_ok=True)
        items = [{'visual_prompt': f'Close-up {k}: Mai grips the door. Mai: {MAI}', 'character_ids': ['mai'], 'duration': 3.0} for k in range(n)]
        return {'id': str(uuid.uuid4()), 'output': str(out), 'events': [], 'request': {'image_provider': 'flow', 'flow_batch_size': 1},
                'checkpoints': {'plan': {'characters': [{'character_id': 'mai', 'name': 'Mai', 'description': MAI}]},
                                'speech': {'scenes': items, 'duration_seconds': 3.0 * n}}}

    refs = {'mai': {'character_id': '11111111-2222-3333-4444-555555555555', 'name': 'char_mai',
                    'project_url': 'https://flow.google.com/project/x', 'task_id': '99999999-2222-3333-4444-555555555555'}}

    def run_job(self, j):
        items = j['checkpoints']['speech']['scenes']
        return self.p._flow_sequential_images(j, lambda: None, self.refs, [], 'native_flow_characters', items)

    def providers(self, j):
        return [json.loads((Path(j['output']) / f'images-{i:04}.checkpoint.json').read_text(encoding='utf8'))['provider']
                for i in range(len(j['checkpoints']['speech']['scenes']))]

    def test_flow_draws_every_scene_when_it_is_not_blocked(self):
        j = self.job()
        result = self.run_job(j)
        self.assertEqual(self.providers(j), ['flow'] * 12)
        self.assertEqual((self.comfy_calls, result['flow_scenes'], result['comfy_scenes']), ([], 12, 0))

    def test_blocked_scene_goes_to_comfy_with_four_more_then_flow_is_tried_again(self):
        self.plan = {2: 'blocked'}
        j = self.job()
        self.run_job(j)
        self.assertEqual(self.providers(j), ['flow', 'flow'] + ['comfy'] * 5 + ['flow'] * 5)
        self.assertEqual([c[0] for c in self.comfy_calls], [2, 3, 4, 5, 6])
        # Flow was not touched during the five ComfyUI scenes and is used again from scene 8 on.
        self.assertEqual(self.flow_calls, [0, 1, 2, 7, 8, 9, 10, 11])
        state = json.loads((Path(j['output']) / 'flow-routing.json').read_text(encoding='utf8'))
        self.assertEqual((state['mode'], state['strikes']), ('flow', 0))

    def test_blocked_again_after_coming_back_leaves_the_rest_of_the_video_to_comfy(self):
        self.plan = {2: 'blocked', 7: 'blocked'}
        j = self.job()
        self.run_job(j)
        self.assertEqual(self.providers(j), ['flow', 'flow'] + ['comfy'] * 10)
        self.assertEqual(self.flow_calls, [0, 1, 2, 7])  # never asked again after the second block
        state = json.loads((Path(j['output']) / 'flow-routing.json').read_text(encoding='utf8'))
        self.assertEqual(state['mode'], 'comfy_final')

    def test_the_next_video_starts_with_flow_again(self):
        self.plan = {0: 'blocked', 5: 'blocked'}
        first = self.job(8, self.out / 'a')
        self.run_job(first)
        self.assertEqual(json.loads((Path(first['output']) / 'flow-routing.json').read_text(encoding='utf8'))['mode'], 'comfy_final')
        self.plan, self.flow_calls = {}, []
        second = self.job(4, self.out / 'b')
        self.run_job(second)
        self.assertEqual(self.providers(second), ['flow'] * 4)

    def test_flow_needing_sign_in_sends_the_rest_to_comfy_at_once(self):
        self.plan = {1: 'signed_out'}
        j = self.job(6)
        self.run_job(j)
        self.assertEqual(self.providers(j), ['flow'] + ['comfy'] * 5)
        self.assertEqual(self.flow_calls, [0, 1])

    def test_comfy_uses_the_portrait_flow_made_and_falls_back_to_its_own(self):
        self.plan = {0: 'blocked'}
        j = self.job(3)
        self.run_job(j)
        self.assertEqual(self.portraits, ['char_mai'])  # fetched once, reused by the next scenes
        self.assertTrue(all(refs == ['mai'] for _, refs in self.comfy_calls))
        saved = json.loads((Path(j['output']) / 'images-0000.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual(saved['comfy_reference_portraits'], ['flow-sha'])
        self.assertTrue(saved['hybrid_fallback'])

        def broken(*args, **kwargs):
            raise UncertainDeliveryError('Flow reference download failed')
        with patch('videostudio.flow_reference_assets.ensure_portrait', broken):
            other = self.job(2, self.out / 'c')
            self.plan = {0: 'blocked'}
            self.run_job(other)
        saved = json.loads((Path(other['output']) / 'images-0000.checkpoint.json').read_text(encoding='utf8'))
        self.assertEqual(saved['comfy_reference_portraits'], ['comfy-sha'])

    def test_finished_scenes_are_reused_and_an_uncertain_flow_result_is_not_replaced(self):
        j = self.job(4)
        self.run_job(j)
        self.flow_calls.clear()
        self.run_job(j)
        self.assertEqual(self.flow_calls, [])  # nothing is drawn twice
        self.plan = {0: 'uncertain'}
        fresh = self.job(2, self.out / 'd')
        with self.assertRaises(UncertainDeliveryError):
            self.run_job(fresh)
        self.assertEqual(self.comfy_calls, [])  # an unclear Flow result never becomes a second picture elsewhere

    def test_cancel_passes_through(self):
        def cancelled(*args, **kwargs):
            raise Cancelled()
        self.p._browser_scene_image = cancelled
        with self.assertRaises(Cancelled):
            self.run_job(self.job(2, self.out / 'e'))


if __name__ == '__main__':
    unittest.main()
