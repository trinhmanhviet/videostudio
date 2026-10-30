import importlib.util
import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from videostudio.core import Cancelled, PermanentError
from videostudio.providers import Pipeline, image_graph
from videostudio import gpu


GB = 1024 ** 3


class ComfyResourceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(SimpleNamespace(root=self.root))
        self.pipeline.gpu_ownership = self.root / 'gpu.json'
        self.path = self.root / 'image.png'
        self.graph = image_graph('test', 1, 'videostudio/test/image')
        self.calls = []
        self.free_vram = [16 * GB]
        self.busy = False
        self.free_failures = []
        self.stats_failures = []
        self.empty_first_stats = False
        self.real_client = httpx.Client

    def tearDown(self):
        self.temp.cleanup()

    def handle(self, request):
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if path == '/queue':
            running = [[1, 'foreign']] if self.busy else []
            return httpx.Response(200, json={'queue_running': running, 'queue_pending': []})
        if path == '/system_stats':
            if self.empty_first_stats:
                self.empty_first_stats = False
                return httpx.Response(200, json={'devices': []})
            if self.stats_failures and self.stats_failures.pop(0):
                raise httpx.ConnectError('Comfy crashed', request=request)
            free = self.free_vram.pop(0) if len(self.free_vram) > 1 else self.free_vram[0]
            return httpx.Response(200, json={'devices': [{'vram_free': free, 'torch_vram_total': 0}]})
        if path == '/free':
            self.assertEqual(json.loads(request.content), {'unload_models': True, 'free_memory': True})
            if self.free_failures and self.free_failures.pop(0):
                raise httpx.ReadError('Comfy crashed while unloading', request=request)
            return httpx.Response(200, json={})
        if path == '/prompt':
            return httpx.Response(200, json={'prompt_id': 'owned'})
        if path == '/history/owned':
            return httpx.Response(200, json={'owned': {
                'prompt': [1, 'owned', self.graph], 'status': {'status_str': 'success'},
                'outputs': {'8': {'images': [{'type': 'output', 'subfolder': 'videostudio/test', 'filename': 'image_0001.png'}]}}
            }})
        if path == '/view':
            return httpx.Response(200, content=b'validated-owned-output')
        if path.startswith('/history/'):
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})

    def call(self, *, strict=False, check=lambda: None):
        transport = httpx.MockTransport(self.handle)
        with patch('videostudio.providers.httpx.Client', side_effect=lambda **kw: self.real_client(**kw, transport=transport)):
            return self.pipeline.comfy_asset({'id': 'job', 'output': str(self.root)}, 'images', self.graph, self.path, check, strict_resume=strict)

    def test_low_vram_frees_then_rechecks_physical_memory_before_submit(self):
        self.free_vram = [GB, 12 * GB]
        value = self.call()
        first_free = self.calls.index(('POST', '/free'))
        prompt = self.calls.index(('POST', '/prompt'))
        self.assertIn(('GET', '/system_stats'), self.calls[first_free + 1:prompt])
        self.assertEqual(value['prompt_id'], 'owned')
        self.assertEqual(self.calls.count(('POST', '/free')), 2)

    def test_free_does_not_lower_threshold_or_reuse_stale_headroom(self):
        self.free_vram = [GB, GB]
        with patch('videostudio.gpu.headroom', side_effect=[(GB, False), (16 * GB, True)]):
            with self.assertRaisesRegex(RuntimeError, 'Insufficient free VRAM'):
                self.call()
        self.assertEqual(self.calls.count(('POST', '/free')), 1)
        self.assertNotIn(('POST', '/prompt'), self.calls)

    def test_empty_initial_stats_can_recover_to_real_devices_after_free(self):
        self.empty_first_stats = True
        value = self.call()
        self.assertEqual(value['prompt_id'], 'owned')

    def test_busy_queue_never_frees_or_submits(self):
        self.busy = True
        with self.assertRaisesRegex(RuntimeError, 'busy with other work'):
            self.call()
        self.assertNotIn(('POST', '/free'), self.calls)
        self.assertNotIn(('POST', '/prompt'), self.calls)

    def test_free_disconnect_recovers_once_and_rechecks_vram(self):
        self.free_vram = [GB, 12 * GB]
        self.free_failures = [True, False]
        with patch('videostudio.gpu.recover_comfy') as recover:
            value = self.call()
        recover.assert_called_once()
        self.assertEqual(value['prompt_id'], 'owned')
        self.assertEqual(self.calls.count(('POST', '/prompt')), 1)

    def test_stats_disconnect_after_free_also_recovers(self):
        self.free_vram = [GB, 12 * GB]
        self.stats_failures = [False, True, False]
        with patch('videostudio.gpu.recover_comfy') as recover:
            self.call()
        recover.assert_called_once()

    def test_second_free_disconnect_does_not_start_second_recovery_and_keeps_asset(self):
        self.free_vram = [GB, 12 * GB]
        self.free_failures = [True, True]
        with patch('videostudio.gpu.recover_comfy') as recover:
            value = self.call()
        recover.assert_called_once()
        self.assertTrue(self.path.is_file())
        self.assertIn('error', value['comfy_cleanup'])
        self.assertEqual(json.loads((self.root / 'images-receipt.json').read_text())['prompt_id'], 'owned')

    def test_post_output_recovery_failure_is_recorded_without_losing_asset(self):
        self.free_failures = [True]
        with patch('videostudio.gpu.recover_comfy', side_effect=RuntimeError('Comfy process still alive')):
            value = self.call()
        self.assertTrue(self.path.is_file())
        self.assertIn('Comfy process still alive', value['comfy_cleanup']['error'])
        self.assertEqual(value['comfy_cleanup'], json.loads((self.root / 'images-receipt.json').read_text())['comfy_cleanup'])

    def test_foreign_work_starting_after_download_skips_cleanup(self):
        original = self.handle
        def handle(request):
            result = original(request)
            if request.url.path == '/view':
                self.busy = True
            return result
        self.handle = handle
        value = self.call()
        self.assertNotIn(('POST', '/free'), self.calls)
        self.assertEqual(value['comfy_cleanup']['skipped'], 'queue_busy')

    def test_strict_scene_never_frees_or_recovers_even_when_vram_low(self):
        self.free_vram = [GB]
        with patch('videostudio.gpu.recover_comfy') as recover:
            with self.assertRaisesRegex(RuntimeError, 'Insufficient free VRAM'):
                self.call(strict=True)
        recover.assert_not_called()
        self.assertNotIn(('POST', '/free'), self.calls)

    def test_cancellation_during_recovery_propagates_and_preserves_download(self):
        self.free_failures = [True]
        with patch('videostudio.gpu.recover_comfy', side_effect=Cancelled()):
            with self.assertRaises(Cancelled):
                self.call()
        self.assertTrue(self.path.is_file())

    def test_missing_bulk_receipt_never_resubmits_after_restart(self):
        (self.root / 'images-receipt.json').write_text(json.dumps({'prompt_id': 'lost'}))
        with self.assertRaises(PermanentError):
            self.call()
        self.assertNotIn(('POST', '/prompt'), self.calls)

    def test_uncertain_prompt_post_is_not_retried_or_recovered(self):
        original = self.handle
        def handle(request):
            result = original(request)
            if request.url.path == '/prompt':
                raise httpx.ReadError('Submission outcome is unknown', request=request)
            return result
        self.handle = handle
        with patch('videostudio.gpu.recover_comfy') as recover:
            with self.assertRaises(httpx.ReadError):self.call()
            with self.assertRaises(PermanentError):self.call()
        recover.assert_not_called()
        self.assertEqual(self.calls.count(('POST', '/prompt')), 1)
        self.assertEqual(json.loads((self.root / 'images-receipt.json').read_text()), {'state': 'submitting'})

    def test_cached_asset_retains_cleanup_failure_without_network(self):
        self.path.write_bytes(b'owned')
        cleanup = {'error': 'Comfy recovery refused'}
        (self.root / 'images-receipt.json').write_text(json.dumps({'prompt_id': 'owned', 'comfy_cleanup': cleanup}))
        self.assertEqual(self.call()['comfy_cleanup'], cleanup)
        self.assertFalse(self.calls)

    def test_cached_asset_still_obeys_cancellation(self):
        self.path.write_bytes(b'owned')
        (self.root / 'images-receipt.json').write_text(json.dumps({'prompt_id': 'owned'}))
        with self.assertRaises(Cancelled):self.call(check=Mock(side_effect=Cancelled()))
        self.assertFalse(self.calls)


class FreeComfyTests(unittest.TestCase):
    def test_free_posts_explicit_unload_and_checks_status(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(503)
        with httpx.Client(base_url='http://comfy/', transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                gpu.free_comfy(client)
        self.assertEqual(requests[0].url.path, '/free')
        self.assertEqual(json.loads(requests[0].content), {'unload_models': True, 'free_memory': True})

    def test_recovery_uses_bounded_hidden_launcher_helper_and_checks_cancellation(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (b'{"ready": true}', b'')
        process.poll.return_value = 0
        check = Mock()
        with patch('videostudio.gpu.subprocess.Popen', return_value=process) as start:
            gpu.recover_comfy('http://127.0.0.1:8188', check)
        self.assertIn('--expected-url', start.call_args.args[0])
        self.assertIn('http://127.0.0.1:8188', start.call_args.args[0])
        self.assertGreater(start.call_args.kwargs['creationflags'], 0)
        check.assert_called()

    def test_recovery_timeout_stops_only_helper_and_never_relaunches(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('helper', .25), (b'', b'')]
        process.poll.return_value = None
        with patch('videostudio.gpu.subprocess.Popen', return_value=process) as start, patch('videostudio.gpu.time.monotonic', side_effect=[0, 221]):
            with self.assertRaises(TimeoutError):gpu.recover_comfy('http://127.0.0.1:8188', lambda: None)
        start.assert_called_once()
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_recovery_cancellation_stops_only_helper(self):
        process = Mock()
        process.poll.return_value = None
        process.communicate.return_value = (b'', b'')
        with patch('videostudio.gpu.subprocess.Popen', return_value=process) as start:
            with self.assertRaises(Cancelled):gpu.recover_comfy('http://127.0.0.1:8188', Mock(side_effect=[None, Cancelled()]))
        start.assert_called_once()
        process.terminate.assert_called_once()

    def test_recovery_refusal_propagates_without_another_start(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (b'', b'Comfy listener/process present')
        process.poll.return_value = 1
        with patch('videostudio.gpu.subprocess.Popen', return_value=process) as start:
            with self.assertRaisesRegex(RuntimeError, 'listener/process present'):
                gpu.recover_comfy('http://127.0.0.1:8188', lambda: None)
        start.assert_called_once()


class RecoveryLauncherTests(unittest.TestCase):
    def launcher_module(self):
        source = Path(__file__).resolve().parents[1] / 'scripts' / 'start_comfy_recovery.py'
        self.assertIn("if __name__ == '__main__':", source.read_text(), 'Launcher must be import-safe before testing its absent-service guard')
        spec = importlib.util.spec_from_file_location('comfy_launcher_test', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_live_listener_or_process_refuses_duplicate_start(self):
        module = self.launcher_module()
        for state in ({'listening': True, 'comfy_process_ids': []}, {'listening': False, 'comfy_process_ids': [123]}, {}):
            with patch.object(module.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(state))), patch.object(module.subprocess, 'Popen') as start:
                with self.assertRaisesRegex(RuntimeError, 'refusing duplicate start'):
                    module.require_absent_service()
                start.assert_not_called()

    def test_launcher_hash_change_refuses_start(self):
        module = self.launcher_module()
        config = {'launcher': 'unread.bat', 'url': 'http://127.0.0.1:8188', 'sha256': 'changed'}
        with patch.object(module, 'CONFIG', Mock(read_text=Mock(return_value=json.dumps(config)))), patch.object(module, 'require_absent_service') as probe, patch.object(module.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'Launcher changed'):module.main(config['url'])
        probe.assert_not_called()
        start.assert_not_called()

    def test_other_comfy_url_never_starts_authorized_local_launcher(self):
        module = self.launcher_module()
        config = {'launcher': 'unread.bat', 'url': 'http://127.0.0.1:8188', 'sha256': module.AUTHORIZED_SHA256}
        with patch.object(module, 'CONFIG', Mock(read_text=Mock(return_value=json.dumps(config)))), patch.object(module.Path, 'read_bytes', return_value=b'launcher'), patch.object(module.hashlib, 'sha256', return_value=Mock(hexdigest=Mock(return_value=module.AUTHORIZED_SHA256))), patch.object(module, 'require_absent_service') as probe, patch.object(module.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'URL does not match'):module.main('http://127.0.0.1:8190')
        probe.assert_not_called()
        start.assert_not_called()
