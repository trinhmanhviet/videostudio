import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from videostudio.providers import Pipeline, UncertainDeliveryError
from videostudio.core import PermanentError


class CDPPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.p=Pipeline(SimpleNamespace(root=Path(self.tmp.name)))
        self.p.context=threading.local();self.p.context.job='job-a'
        self.p.exchanges=MagicMock()
    def tearDown(self):self.tmp.cleanup()
    def test_job_id_and_csrf_header_are_sent_to_cdp(self):
        response=SimpleNamespace(status_code=200,json=lambda:{'ok':True,'data':{'done':True}},raise_for_status=lambda:None)
        with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'cdp'}),patch('httpx.post',return_value=response) as post:
            self.assertEqual(self.p.llm_json('hello',lambda:None),{'done':True})
            self.assertEqual(post.call_args.kwargs['json']['job_id'],'job-a')
            self.assertEqual(post.call_args.kwargs['headers']['X-VS-Client'],'videostudio')
    def test_uncertain_response_is_retryable_but_never_falls_back_to_extension(self):
        response=SimpleNamespace(status_code=409,json=lambda:{'ok':False,'code':'delivery_indeterminate','error':'retained'})
        with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'cdp'}),patch('httpx.post',return_value=response):
            with self.assertRaises(UncertainDeliveryError):self.p.llm_json('hello',lambda:None)
        self.p.exchanges.request.assert_not_called()
    def test_remote_daemon_url_is_refused(self):
        with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'cdp','VS_CDP_DAEMON_URL':'https://remote.invalid'}),patch('httpx.post') as post:
            with self.assertRaises(PermanentError):self.p.llm_json('hello',lambda:None)
            post.assert_not_called()

    def test_socket_alone_never_creates_acceptance(self):
        with patch.dict('os.environ',{'VS_CDP_JOURNAL':str(Path(self.tmp.name)/'journal.db')}):
            self.assertFalse(self.p.accepted_cdp())
    def test_only_correlated_acceptance_job_counts_as_smoke(self):
        from videostudio.cdp_requests import RequestJournal
        path=Path(self.tmp.name)/'journal.db';j=RequestJournal(path)
        a=j.prepare('ordinary-job','test');j.complete(a['id'],{'connection_test':'videostudio','ok':True})
        with patch.dict('os.environ',{'VS_CDP_JOURNAL':str(path)}):
            self.assertFalse(self.p.accepted_cdp())
            a=j.prepare('__acceptance__','test');j.accept(a['id'],{'request_id':a['id'],'result':{'connection_test':'videostudio','ok':True}})
            self.assertTrue(self.p.accepted_cdp())

if __name__=='__main__':unittest.main()
