import tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store

class DummyPipeline:
    def handlers(self): return {}
    def preflight(self): return {'ready': False, 'checks': []}

class SystemAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'db', Path(self.temp.name) / 'out')
        self.pipeline = DummyPipeline()
        self.app = create_app(self.store, self.pipeline, False)
        self.client = TestClient(self.app, base_url='http://localhost:8877')

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_system_status(self):
        res = self.client.get('/api/system/status')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('status'), 'running')
        self.assertEqual(data.get('port'), 8877)
        self.assertEqual(data.get('active_jobs'), 0)

    def test_foreign_host_rejected(self):
        res = self.client.get('/api/system/status', headers={'Host': 'evil.com'})
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/api/system/stop', json={}, headers={'Host': 'evil.com'})
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/api/system/restart', json={}, headers={'Host': 'evil.com'})
        self.assertEqual(res.status_code, 403)

    @patch('subprocess.Popen')
    def test_system_stop_and_restart_when_idle(self, mock_popen):
        res = self.client.post('/api/system/stop', json={})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('ok'))
        self.assertEqual(mock_popen.call_count, 1)
        self.assertNotIn(' -Force',mock_popen.call_args.args[0][-1])

        res = self.client.post('/api/system/restart', json={})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('ok'))
        self.assertEqual(mock_popen.call_count, 2)
        self.assertNotIn(' -Force',mock_popen.call_args.args[0][-1])

    @patch('subprocess.Popen')
    def test_system_stop_blocked_by_active_jobs_unless_force(self, mock_popen):
        # Create an active job in the store
        self.store.create({'idea': 'active job', 'voice_id': 'voice', 'duration_seconds': 10, 'image_provider': 'flow'}, 'key1')
        # Without force, it should be 409
        res = self.client.post('/api/system/stop', json={})
        self.assertEqual(res.status_code, 409)
        self.assertIn('tác vụ đang chạy', res.json().get('detail', ''))
        mock_popen.assert_not_called()

        # With force=True, it succeeds
        res = self.client.post('/api/system/stop', json={'force': True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('ok'))
        self.assertEqual(mock_popen.call_count, 1)
        self.assertIn(' -Force',mock_popen.call_args.args[0][-1])

if __name__ == '__main__':
    unittest.main()
