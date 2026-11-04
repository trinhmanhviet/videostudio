"""Comfy image models stay loaded across one images stage and are unloaded once at its end."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from videostudio.providers import Pipeline, image_graph

GB = 1024 ** 3


class ComfyStageHoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(SimpleNamespace(root=self.root))
        self.pipeline.gpu_ownership = self.root / 'gpu.json'
        self.job = {'id': 'job', 'output': str(self.root)}
        self.calls = []
        self.vram_free = 16 * GB
        self.busy = False
        self.graphs = {}
        self.real_client = httpx.Client

    def tearDown(self):
        self.temp.cleanup()

    def handle(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        if path == '/queue':
            running = [[1, 'foreign']] if self.busy else []
            return httpx.Response(200, json={'queue_running': running, 'queue_pending': []})
        if path == '/system_stats':
            return httpx.Response(200, json={'devices': [{'vram_free': self.vram_free, 'torch_vram_total': 0}]})
        if path == '/free':
            return httpx.Response(200, json={})
        if path == '/prompt':
            graph = json.loads(request.content)['prompt']
            pid = 'p%d' % (len(self.graphs) + 1)
            self.graphs[pid] = graph
            return httpx.Response(200, json={'prompt_id': pid})
        if path.startswith('/history/'):
            pid = path.rsplit('/', 1)[1]
            graph = self.graphs.get(pid)
            if not graph:
                return httpx.Response(200, json={})
            folder, name = graph['8']['inputs']['filename_prefix'].rsplit('/', 1)
            return httpx.Response(200, json={pid: {
                'prompt': [1, pid, graph], 'status': {'status_str': 'success'},
                'outputs': {'8': {'images': [{'type': 'output', 'subfolder': folder, 'filename': name + '_00001_.png'}]}}}})
        if path == '/view':
            return httpx.Response(200, content=b'scene-image')
        return httpx.Response(404, json={})

    def client(self):
        transport = httpx.MockTransport(self.handle)
        return patch('videostudio.providers.httpx.Client', side_effect=lambda **kw: self.real_client(**kw, transport=transport))

    def scene(self, index):
        kind = f'images-{index:04}'
        graph = image_graph('scene %d' % index, index, 'videostudio/job-' + kind)
        return self.pipeline.comfy_asset(self.job, kind, graph, self.root / (kind + '.png'), lambda: None)

    def test_scenes_in_one_stage_never_unload_between_images(self):
        self.pipeline._comfy_hold = 'job'
        with self.client():
            first = self.scene(0)
            # Our own loaded models now occupy VRAM: a fresh check would unload them again.
            self.vram_free = GB
            second = self.scene(1)
            third = self.scene(2)
        self.assertNotIn(('POST', '/free'), self.calls)
        self.assertEqual(self.calls.count(('POST', '/prompt')), 3)
        self.assertEqual(self.calls.count(('GET', '/system_stats')), 1)
        for value in (first, second, third):
            self.assertEqual(value['comfy_cleanup'], {'deferred': 'images_stage_end'})
        receipt = json.loads((self.root / 'images-0001-receipt.json').read_text())
        self.assertEqual(receipt['comfy_cleanup'], {'deferred': 'images_stage_end'})
        self.assertEqual(self.pipeline._comfy_resident, 'job')

    def test_first_scene_still_frees_when_vram_is_short_before_anything_is_loaded(self):
        self.pipeline._comfy_hold = 'job'
        self.vram_free = GB
        with self.client():
            with self.assertRaisesRegex(RuntimeError, 'Insufficient free VRAM'):
                self.scene(0)
        self.assertEqual(self.calls.count(('POST', '/free')), 1)
        self.assertNotIn(('POST', '/prompt'), self.calls)

    def test_outside_images_stage_each_asset_still_unloads(self):
        with self.client():
            value = self.scene(0)
        self.assertEqual(self.calls.count(('POST', '/free')), 1)
        self.assertTrue(value['comfy_cleanup']['freed'])
        self.assertIsNone(getattr(self.pipeline, '_comfy_resident', None))

    def test_release_frees_once_after_last_scene(self):
        self.pipeline._comfy_resident = 'job'
        with self.client():
            self.assertEqual(self.pipeline.release_held_comfy(self.job), {'freed': True})
            self.assertIsNone(self.pipeline.release_held_comfy(self.job))
        self.assertEqual(self.calls, [('GET', '/queue'), ('POST', '/free')])

    def test_release_never_unloads_under_foreign_work(self):
        self.pipeline._comfy_resident = 'job'
        self.busy = True
        with self.client():
            self.assertEqual(self.pipeline.release_held_comfy(self.job), {'skipped': 'queue_busy'})
        self.assertNotIn(('POST', '/free'), self.calls)
        self.assertIsNone(self.pipeline._comfy_resident)

    def test_release_is_noop_when_nothing_was_loaded(self):
        with self.client():
            self.assertIsNone(self.pipeline.release_held_comfy(self.job))
        self.assertFalse(self.calls)

    def test_images_stage_holds_during_run_and_releases_on_success_and_failure(self):
        seen = []
        def run(job, check):
            seen.append(self.pipeline._comfy_hold)
            return {'scenes': []}
        self.pipeline._images = Mock(side_effect=run)
        self.pipeline.release_held_comfy = Mock()
        self.assertEqual(self.pipeline.images(self.job, lambda: None), {'scenes': []})
        self.assertEqual(seen, ['job'])
        self.pipeline.release_held_comfy.assert_called_once_with(self.job, 'images')
        self.assertIsNone(self.pipeline._comfy_hold)
        self.pipeline._images = Mock(side_effect=RuntimeError('scene failed'))
        with self.assertRaises(RuntimeError):
            self.pipeline.images(self.job, lambda: None)
        self.assertEqual(self.pipeline.release_held_comfy.call_count, 2)
        self.assertIsNone(self.pipeline._comfy_hold)

    def test_strict_scene_editor_requests_are_not_held(self):
        self.pipeline._comfy_hold = 'job'
        graph = image_graph('scene', 1, 'videostudio/job-images-scene-x')
        with self.client():
            self.pipeline.comfy_asset(self.job, 'images-scene-x', graph, self.root / 'x.png', lambda: None, strict_resume=True, skip_vram_check=True)
        self.assertIsNone(getattr(self.pipeline, '_comfy_resident', None))
        self.assertNotIn(('POST', '/free'), self.calls)


if __name__ == '__main__':
    unittest.main()
