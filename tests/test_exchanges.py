import unittest,tempfile,threading,time,json
from pathlib import Path
from videostudio.core import Store
from videostudio.exchanges import Exchanges,parse_reply
class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name);self.store=Store(p/'db',p/'out');self.e=Exchanges(self.store);self.scope=self.e.scope();self.job,_=self.store.create({'idea':'test','voice_id':'test','duration_seconds':8},'test');self.e.bind(self.scope,self.job['id'])
    def tearDown(self):self.temp.cleanup()
    def test_immutable_request_resume_and_response_receipt(self):
        with self.assertRaises(TimeoutError):self.e.request(self.job['id'],'test prompt',lambda:None,timeout=.001)
        item=self.e.pending(self.scope)['items'][0]
        self.assertTrue(item['prompt'].startswith('YÊU CẦU STUDIO '+item['id']+'\n'))
        restarted=Exchanges(Store(self.store.path,self.store.outputs))
        self.assertEqual(restarted.pending(self.scope)['items'][0]['id'],item['id'])
        result=restarted.receive(self.scope,item['id'],1,'{"ok":true}')
        self.assertTrue(result['accepted']);self.assertEqual(self.e.request(self.job['id'],'test prompt',lambda:None),{'ok':True})
        self.assertEqual(self.e.pending(self.scope)['items'],[])
        self.assertTrue(self.e.receive(self.scope,item['id'],1,'{"ok": true}')['accepted'])
        with self.assertRaises(ValueError):self.e.receive(self.scope,item['id'],1,'{"ok": false}')
    def test_wrong_scope_cannot_import(self):
        with self.assertRaises(TimeoutError):self.e.request(self.job['id'],'test prompt',lambda:None,timeout=.001)
        item=self.e.pending(self.scope)['items'][0];other=self.e.scope()
        with self.assertRaises(KeyError):self.e.receive(other,item['id'],1,'{}')
        with self.assertRaises(ValueError):self.e.receive(self.scope,item['id'],2,'{}')
    def test_bad_json_rejected(self):
        for raw in ['{} {}','[]','{"a":1,"a":2}','{"v":NaN}']:
            with self.assertRaises(ValueError):parse_reply(raw)
    def test_scope_cannot_move_between_jobs(self):
        other,_=self.store.create({'idea':'other','voice_id':'test','duration_seconds':8},'other')
        with self.assertRaises(ValueError):self.e.bind(self.scope,other['id'])
if __name__=='__main__':unittest.main()
