import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from videostudio.core import Store
from videostudio.api import create_app


class VoiceIntegrationGuardTests(unittest.TestCase):
    def fixture(self, root):
        class Pipeline:
            def handlers(self): return {}
            def preflight(self): return {'ready':True,'checks':[]}
        store=Store(Path(root)/'jobs.sqlite3',Path(root)/'out')
        return store,create_app(store,Pipeline(),False)

    def test_existing_clone_route_never_starts_gpu_while_another_worker_holds_lease(self):
        with tempfile.TemporaryDirectory() as root, patch('videostudio.api.DATA_ROOT',Path(root)):
            store,app=self.fixture(root)
            self.assertTrue(store.lock('other-worker'))
            with TestClient(app,base_url='http://127.0.0.1:8877') as client, patch('subprocess.run',side_effect=AssertionError('Must not invoke media/GPU')) as run:
                response=client.post('/api/voices/clone',json={'name':'Fixture','audio_base64':base64.b64encode(b'x'*2000).decode()})
                self.assertEqual(response.status_code,409,response.text)
                run.assert_not_called()

    def test_voice_tasks_participate_in_system_idle_guard(self):
        with tempfile.TemporaryDirectory() as root:
            store,app=self.fixture(root)
            with store.db() as db:
                db.execute("INSERT INTO voice_studio_tasks(id,owner,idem,fingerprint,request,title,state,created,updated) VALUES('task','owner','key','hash','{}','Fixture','queued',1,1)")
            with TestClient(app,base_url='http://127.0.0.1:8877') as client:
                response=client.get('/api/system/status')
                self.assertEqual(response.status_code,200,response.text)
                self.assertGreater(response.json()['active_jobs'],0)


if __name__=='__main__': unittest.main()
