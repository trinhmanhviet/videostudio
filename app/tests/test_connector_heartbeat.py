import tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
class Fake:
 def handlers(self):return {}
 def preflight(self):return {'ready':False,'checks':[]}
class HeartbeatTests(unittest.TestCase):
 def test_non_owner_cannot_replace_active_same_scope(self):
  with tempfile.TemporaryDirectory() as t:
   s=Store(Path(t)/'db',Path(t)/'out')
   with TestClient(create_app(s,Fake(),False)) as c:
    scope=c.post('/api/connector/sessions').json()['run_id'];url='/api/connector/status/'+scope
    active={'build':'0.1.24','stage':'imported','connected':True,'enabled':True}
    self.assertTrue(c.post(url,json=active).json()['recorded'])
    self.assertFalse(c.post(url,json={**active,'stage':'other_run','enabled':False}).json()['recorded'])
    self.assertEqual(c.get('/api/connector/status').json()['items'][0]['status'],active)
if __name__=='__main__':unittest.main()
