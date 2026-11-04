"""Regression tests for the 2026-11-03 review fixes."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from videostudio.cdp_templates import fill_card_template
from videostudio.providers import Pipeline, image_graph

GB = 1024 ** 3


class FailedCardTemplateTests(unittest.TestCase):
    TEMPLATE = "t=tiles[INDEX];if(norm(t.innerText)!==TEXT||Math.abs(cx-X)>8||Math.abs(cy-Y)>8)return null"

    def test_card_text_with_placeholder_like_words_survives(self):
        text = 'Cảnh (X) và (Y), INDEX X) Y) TEXT'
        script = fill_card_template(self.TEMPLATE, 3, text, 120.5, 64)
        self.assertIn(json.dumps(text, ensure_ascii=False), script)
        self.assertIn('tiles[3]', script)
        self.assertIn('Math.abs(cx-120.5)>8', script)
        self.assertIn('Math.abs(cy-64)>8', script)

    def test_without_coordinates_only_index_and_text_are_filled(self):
        script = fill_card_template('a[INDEX]===TEXT', 0, 'X) Y)')
        self.assertEqual(script, 'a[0]==="X) Y)"')


class AutomaticEditRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline.__new__(Pipeline)
        self.pipeline.ffmpeg = 'ffmpeg'; self.pipeline.ffprobe = 'ffprobe'
        self.order = []
        self.pipeline.scene_editor = Mock(require_user_review=Mock(side_effect=lambda j: self.order.append('review') or {'status': 'not_checked'}))
        self.pipeline.store = Mock()
        self.job = {'id': 'job', 'output': str(self.root), 'request': {'edit_preset': 'documentary'},
                    'checkpoints': {'images': {'scenes': []}, 'render': {}}}

    def tearDown(self):
        self.temp.cleanup()

    def test_gates_run_first_and_any_editor_error_falls_back_to_legacy_render(self):
        legacy = RuntimeError('legacy renderer reached')
        service = Mock(automatic_snapshot=Mock(side_effect=KeyError('plan')))
        self.pipeline.edit_plan_service = service
        with patch('videostudio.visual_quality.require_release', side_effect=lambda *a: self.order.append('release')), \
             patch('videostudio.media.render_scenes', side_effect=legacy):
            with self.assertRaises(RuntimeError) as caught:
                self.pipeline.render(self.job, lambda: None)
        self.assertIs(caught.exception, legacy)
        self.assertEqual(self.order[:2], ['review', 'release'])
        service.automatic_snapshot.assert_called_once()
        logged = self.pipeline.store.log.call_args_list[0].args[2]
        self.assertIn('KeyError', logged)

    def test_review_gate_blocks_before_automatic_snapshot(self):
        self.pipeline.edit_plan_service = Mock()
        with patch('videostudio.visual_quality.require_release', side_effect=ValueError('needs review')):
            with self.assertRaisesRegex(ValueError, 'needs review'):
                self.pipeline.render(self.job, lambda: None)
        self.pipeline.edit_plan_service.automatic_snapshot.assert_not_called()

    def test_automatic_verify_reports_release_status_not_user_edit(self):
        self.job['checkpoints']['render'] = {'edit_plan_snapshot': 'plan.json', 'editing_source': 'automatic_defaults', 'assets': []}
        verified = {'verified': True, 'visual_quality': {'status': 'user_edit'}}
        with patch('videostudio.edit_render.verify_edit_render', return_value=dict(verified)), \
             patch('videostudio.visual_quality.require_release', return_value={'status': 'not_checked', 'scope': 'technical_only'}):
            result = self.pipeline.verify(self.job, lambda: None)
        self.assertEqual(result['visual_quality'], {'status': 'not_checked', 'scope': 'technical_only'})

    def test_user_edit_verify_keeps_user_edit_label(self):
        self.job['checkpoints']['images']['edit_plan_snapshot'] = 'plan.json'
        verified = {'verified': True, 'visual_quality': {'status': 'user_edit'}}
        with patch('videostudio.edit_render.verify_edit_render', return_value=verified), \
             patch('videostudio.visual_quality.require_release') as release:
            result = self.pipeline.verify(self.job, lambda: None)
        release.assert_not_called()
        self.assertEqual(result['visual_quality'], {'status': 'user_edit'})


class MusicStageHoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(SimpleNamespace(root=self.root))
        self.pipeline.gpu_ownership = self.root / 'gpu.json'
        self.pipeline.store = Mock()
        self.job = {'id': 'job', 'output': str(self.root)}
        self.calls = []; self.graphs = {}
        self.real_client = httpx.Client

    def tearDown(self):
        self.temp.cleanup()

    def handle(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        if path == '/queue':
            return httpx.Response(200, json={'queue_running': [], 'queue_pending': []})
        if path == '/system_stats':
            return httpx.Response(200, json={'devices': [{'vram_free': 16 * GB, 'torch_vram_total': 0}]})
        if path == '/free':
            return httpx.Response(200, json={})
        if path == '/prompt':
            pid = 'p%d' % (len(self.graphs) + 1); self.graphs[pid] = json.loads(request.content)['prompt']
            return httpx.Response(200, json={'prompt_id': pid})
        if path.startswith('/history/'):
            pid = path.rsplit('/', 1)[1]; graph = self.graphs.get(pid)
            if not graph:
                return httpx.Response(200, json={})
            folder, name = graph['8']['inputs']['filename_prefix'].rsplit('/', 1)
            return httpx.Response(200, json={pid: {'prompt': [1, pid, graph], 'status': {'status_str': 'success'},
                'outputs': {'8': {'audio': [{'type': 'output', 'subfolder': folder, 'filename': name + '_00001_.mp3'}]}}}})
        if path == '/view':
            return httpx.Response(200, content=b'music-part')
        return httpx.Response(404, json={})

    def test_music_parts_keep_models_and_free_once_at_stage_end(self):
        def parts(job, check):
            results = []
            for index in range(3):
                kind = f'music-scene-{index:04}'
                graph = image_graph('x', index, 'videostudio/job-' + kind)
                results.append(self.pipeline.comfy_asset(job, kind, graph, self.root / (kind + '.mp3'), check))
            return results
        self.pipeline._music = parts
        transport = httpx.MockTransport(self.handle)
        with patch('videostudio.providers.httpx.Client', side_effect=lambda **kw: self.real_client(**kw, transport=transport)):
            results = self.pipeline.music(self.job, lambda: None)
        self.assertEqual([r['comfy_cleanup'] for r in results], [{'deferred': 'music_stage_end'}] * 3)
        self.assertEqual(self.calls.count(('POST', '/prompt')), 3)
        self.assertEqual(self.calls.count(('POST', '/free')), 1)
        self.assertEqual(self.calls[-1], ('POST', '/free'))
        self.assertIsNone(self.pipeline._comfy_hold)
        self.assertEqual(self.pipeline.store.log.call_args.args[1], 'music')


if __name__ == '__main__':
    unittest.main()
