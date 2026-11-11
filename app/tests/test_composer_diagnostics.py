import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.exchanges import Exchanges

class ComposerDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_are_local_bounded_and_bound_to_bridge_job_and_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db',Path(tmp)/'out')
            with TestClient(create_app(store,SimpleNamespace(handlers=lambda:{}),False)) as client:
                ex=Exchanges(store);root=ex.scope();other=ex.scope()
                job,_=store.create({'idea':'fixture','voice_id':'test','duration_seconds':8},'once',root)
                identifier=ex.enqueue(root,'fixture immutable prompt')
                url='/api/jobs/'+job['id']+'/composer-diagnostics'
                payload={'request_id':identifier,'version':1,'attempt':1,'diagnostic':{'expected_length':6134,'actual_length':6141,'first_diff':1591,'actual_context':'x'*2000,'raw_prompt':'DO NOT SAVE'}}
                self.assertEqual(client.post(url,json=payload,headers={'X-Connector-Scope':other}).status_code,403)
                self.assertEqual(client.post(url,json=payload,headers={'X-Connector-Scope':root,'Origin':'https://untrusted.invalid'}).status_code,403)
                response=client.post(url,json=payload,headers={'X-Connector-Scope':root})
                self.assertEqual(response.status_code,200,response.text)
                file=Path(job['output'])/response.json()['filename'];saved=json.loads(file.read_text(encoding='utf8'))
                self.assertEqual(saved['diagnostic']['first_diff'],1591)
                self.assertLessEqual(len(saved['diagnostic']['actual_context']),512)
                self.assertNotIn('raw_prompt',saved['diagnostic'])
                self.assertEqual(store.get(job['id'])['checkpoints'],{})
