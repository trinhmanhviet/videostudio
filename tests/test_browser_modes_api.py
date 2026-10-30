import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store

class Fixture:
    def handlers(self):return {}
    def preflight(self):return {'ready':False,'checks':[]}

class BrowserModeAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db',Path(self.temp.name)/'out');self.pipeline=Fixture();self.app=create_app(self.store,self.pipeline,False)
        self.manager=self.app.state.browser_manager
        self.manager.open=Mock(return_value={'running':True,'mode':'clean'})
        self.manager.stop=Mock(return_value={'running':False,'mode':'closed'})
        self.manager.status=Mock(return_value={'running':False,'mode':'closed'})
        self.client=TestClient(self.app,base_url='http://localhost:8877')
    def tearDown(self):self.client.close();self.temp.cleanup()
    def test_open_clean_and_debug_use_only_fixed_profile_manager(self):
        for mode in ['clean','debug']:
            self.assertEqual(self.client.post('/api/browser/profile/open',json={'mode':mode}).status_code,200)
            self.manager.open.assert_called_with(mode)
    def test_passive_status_and_explicit_stop(self):
        self.assertEqual(self.client.get('/api/browser/profile').json()['mode'],'closed');self.manager.open.assert_not_called()
        self.assertEqual(self.client.post('/api/browser/profile/stop').status_code,200);self.manager.stop.assert_called_once()
    def test_foreign_origin_and_host_cannot_control_profile(self):
        self.assertEqual(self.client.post('/api/browser/profile/open',json={'mode':'clean'},headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.post('/api/browser/profile/stop',headers={'Host':'evil.test','Origin':'http://evil.test'}).status_code,403)
        self.manager.open.assert_not_called();self.manager.stop.assert_not_called()
    def test_invalid_mode_and_busy_video_are_actionable(self):
        self.assertEqual(self.client.post('/api/browser/profile/open',json={'mode':'private','profile':'other'}).status_code,422)
        self.manager.open.side_effect=ValueError('Đang có video chạy')
        self.assertEqual(self.client.post('/api/browser/profile/open',json={'mode':'clean'}).status_code,409)
    def test_clean_mode_rejects_new_flow_job_before_allocating_it(self):
        self.pipeline.preflight=lambda:{'ready':True,'checks':[]};self.manager.last_mode='clean'
        response=self.client.post('/api/jobs',json={'idea':'test','voice_id':'selected','duration_seconds':8,'image_provider':'flow'},headers={'Idempotency-Key':'clean-mode-job'})
        self.assertEqual(response.status_code,409);self.assertEqual(self.store.list(),[])

if __name__=='__main__':unittest.main()
