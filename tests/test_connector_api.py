import tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.exchanges import Exchanges
class ReadyFixture:
    def handlers(self):return {}
    def preflight(self):return {'ready':True,'checks':[]}
class ConnectorApiTests(unittest.TestCase):
    def test_scoped_page_and_receipt_api(self):
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'db',Path(t)/'out')
            with TestClient(create_app(store,ReadyFixture(),False)) as c:
                s=c.post('/api/connector/sessions').json();scope=s['project_id']
                self.assertEqual(c.get(s['url']).status_code,200)
                self.assertEqual(c.get('/story-video/projects/not-a-scope/production').status_code,404)
                request={'idea':'A test','voice_id':'test','duration_seconds':8}
                headers={'Idempotency-Key':'once','X-Connector-Scope':scope}
                j=c.post('/api/jobs',json=request,headers=headers).json()['id']
                self.assertEqual(c.post('/api/jobs',json=request,headers=headers).json()['id'],j)
                self.assertEqual(c.post('/api/jobs',json=request,headers={**headers,'Idempotency-Key':'new'}).status_code,409)
                self.assertEqual(len(store.list()),1)
                ex=Exchanges(store)
                with self.assertRaises(TimeoutError):ex.request(j,'protocol fixture',lambda:None,timeout=.001)
                base=f'/api/v1/projects/{scope}/runs/{scope}/chatgpt-exchanges';item=c.get(base).json()['items'][0]
                receipt=base+'/'+item['id']
                self.assertFalse(c.get(receipt).json()['accepted'])
                self.assertEqual(c.post(receipt+'/response',json={'expected_version':1,'response_text':'{}'},headers={'Origin':'https://untrusted.invalid'}).status_code,403)
                self.assertTrue(c.post(receipt+'/response',json={'expected_version':1,'response_text':'{}'}).json()['accepted'])
                self.assertTrue(c.get(receipt).json()['accepted'])
                self.assertEqual(c.get(base).json()['items'],[])
if __name__=='__main__':unittest.main()
