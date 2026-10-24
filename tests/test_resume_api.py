import tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
class Fake:
 def handlers(self):return {}
 def preflight(self):return {'ready':True,'checks':[]}
class ResumeApiTests(unittest.TestCase):
 def test_old_connector_cannot_consume_recovery_allowance(self):
  with tempfile.TemporaryDirectory() as t:
   s=Store(Path(t)/'db',Path(t)/'out')
   with TestClient(create_app(s,Fake(),False)) as c:
    scope=c.post('/api/connector/sessions').json()['run_id'];headers={'Idempotency-Key':'one','X-Connector-Scope':scope}
    j=c.post('/api/jobs',headers=headers,json={'idea':'test','voice_id':'chosen','duration_seconds':12}).json()['id'];s.cancel(j)
    self.assertEqual(c.post('/api/jobs/'+j+'/resume',headers=headers).status_code,409)
    self.assertEqual(s.get(j)['state'],'cancelled')
    c.post('/api/connector/status/'+scope,json={'build':'0.1.24','stage':'idle','enabled':False})
    self.assertEqual(c.post('/api/jobs/'+j+'/resume',headers=headers).status_code,409)
    c.post('/api/connector/status/'+scope,json={'build':'0.1.25','stage':'idle','enabled':False})
    self.assertEqual(c.post('/api/jobs/'+j+'/resume',headers=headers).status_code,200)
    self.assertEqual(s.get(j)['state'],'queued');self.assertFalse(s.get(j)['cancel'])
if __name__=='__main__':unittest.main()
