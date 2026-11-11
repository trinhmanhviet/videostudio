import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store
from videostudio.exchanges import Exchanges

class BridgeDismissTests(unittest.TestCase):
 def test_only_owned_terminal_job_is_removed_from_manager_and_files_survive(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'db',Path(tmp)/'out')
   with TestClient(create_app(store,SimpleNamespace(handlers=lambda:{}),False)) as c:
    ex=Exchanges(store);root=ex.scope();other=ex.scope();j,_=store.create({'idea':'test','voice_id':'test','duration_seconds':8},'one',root)
    target=Path(j['output'])/'keep.txt';target.write_text('keep');url=f'/api/connector/bridges/{root}/jobs/{j["id"]}'
    self.assertEqual(c.post(url+'/dismiss').status_code,409)
    with store.db() as db:db.execute("UPDATE jobs SET state='failed' WHERE id=?",(j['id'],))
    self.assertEqual(c.post(url.replace(root,other)+'/dismiss').status_code,404)
    self.assertEqual(c.post(url+'/dismiss',headers={'Origin':'https://untrusted.invalid'}).status_code,403)
    result=c.post(url+'/dismiss');self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['dismissed'])
    self.assertEqual(c.get(f'/api/connector/bridges/{root}/sessions').json()['items'],[])
    self.assertTrue(c.get(url).json()['dismissed']);self.assertTrue(target.is_file());self.assertEqual(c.post(url+'/dismiss').status_code,200)
    smoke=ex.enqueue_smoke(root);self.assertEqual(ex.bridge_pending(root)['items'][0]['id'],smoke)
