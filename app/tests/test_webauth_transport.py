import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from videostudio.core import PermanentError
from videostudio.providers import Pipeline, UncertainDeliveryError


class WebAuthTests(unittest.TestCase):
    def pipeline(self):
        p=Pipeline.__new__(Pipeline)
        p.context=SimpleNamespace(job='job-1')
        return p

    def config(self, root, base='http://127.0.0.1:54321/v1'):
        path=Path(root)/'openclaw.json'
        path.write_text(json.dumps({'models':{'providers':{'webauth':{'baseUrl':base,'models':[{'id':'webauth-chatgpt-gpt'}]}}}}))
        return str(path)

    def test_sse_completion_and_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp)
            body='data: '+json.dumps({'choices':[{'delta':{'content':'{"ok":'}}]})+'\n\n'
            body+='data: '+json.dumps({'choices':[{'delta':{'content':'true}'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n'
            def handler(request):
                self.assertEqual(request.url.path,'/v1/chat/completions')
                self.assertEqual(json.loads(request.content)['model'],'webauth-chatgpt-gpt')
                self.assertTrue(json.loads(request.content)['stream'])
                return httpx.Response(200,headers={'content-type':'text/event-stream'},text=body)
            with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'webauth','VS_WEBAUTH_CONFIG':config}), patch('videostudio.providers.httpx.Client',return_value=httpx.Client(transport=httpx.MockTransport(handler))):
                self.assertEqual(self.pipeline().llm_json('prompt',lambda:None),{'ok':True})

    def test_missing_done_and_error_event_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp)
            for body in ('data: '+json.dumps({'choices':[{'delta':{'content':'{}'},'finish_reason':'stop'}]})+'\n\n',
                         'event: error\ndata: {"error":"denied"}\n\n',
                         'data: '+json.dumps({'choices':[{'delta':{'content':'{}'},'finish_reason':'length'}]})+'\n\ndata: [DONE]\n\n'):
                with self.subTest(body=body):
                    calls=[]
                    def handler(request):calls.append(request);return httpx.Response(200,headers={'content-type':'text/event-stream'},text=body)
                    with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'webauth','VS_WEBAUTH_CONFIG':config}),patch('videostudio.providers.httpx.Client',return_value=httpx.Client(transport=httpx.MockTransport(handler))):
                        with self.assertRaises((PermanentError,UncertainDeliveryError)):self.pipeline().llm_json('prompt',lambda:None)
                    self.assertEqual(len(calls),1)

    def test_invalid_json_content_and_non_sse_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp)
            for content_type,body in [('text/event-stream','data: '+json.dumps({'choices':[{'delta':{'content':'not json'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n'),('application/json','{}')]:
                with self.subTest(content_type=content_type):
                    transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':content_type},text=body))
                    with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'webauth','VS_WEBAUTH_CONFIG':config}),patch('videostudio.providers.httpx.Client',return_value=httpx.Client(transport=transport)):
                        with self.assertRaises(PermanentError):self.pipeline().llm_json('prompt',lambda:None)

    def test_untrusted_remote_config_rejected_before_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp,'https://remote.example/v1')
            with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'webauth','VS_WEBAUTH_CONFIG':config}):
                with self.assertRaises(PermanentError):self.pipeline().llm_json('prompt',lambda:None)

    def test_network_failure_after_submission_is_terminal_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp)
            calls=[]
            def handler(request):
                calls.append(request)
                raise httpx.ReadTimeout('lost response')
            with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'webauth','VS_WEBAUTH_CONFIG':config}), patch('videostudio.providers.httpx.Client',return_value=httpx.Client(transport=httpx.MockTransport(handler))):
                with self.assertRaisesRegex(PermanentError,'delivery uncertain'):
                    self.pipeline().llm_json('prompt',lambda:None)
            self.assertEqual(len(calls),1)

    def test_smoke_receipt_only_accepts_exact_completed_response(self):
        from videostudio.webauth import accepted_smoke, SMOKE_RESPONSE
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'smoke.json'
            with patch.dict('os.environ',{'VS_WEBAUTH_SMOKE':str(path)}):
                self.assertFalse(accepted_smoke())
                path.write_text(json.dumps({'response':{'connection_test':'wrong','ok':True}}))
                self.assertFalse(accepted_smoke())
                path.write_text(json.dumps({'response':SMOKE_RESPONSE,'model':'wrong'}))
                self.assertFalse(accepted_smoke())
                path.write_text(json.dumps({'response':SMOKE_RESPONSE,'model':'webauth-chatgpt-gpt','completed':True}))
                self.assertTrue(accepted_smoke())

    def test_research_mode_not_blocked_by_cdp_requirement(self):
        p=self.pipeline();p.preflight=lambda scope=None:{'ready':True,'checks':[]};p.voices=SimpleNamespace(selected=lambda _:None)
        p.llm_json=lambda prompt,check:{'title':'Title','visual_prompt':'Visual','music_prompt':'Music','research_context':{'summary':'Summary','facts':[],'uncertainties':[]}}
        with patch.dict('os.environ',{'VS_LLM_TRANSPORT':'webauth'}):self.assertEqual(p.plan({'id':'job-1','request':{'voice_id':'v','workflow_mode':'research','idea':'topic'}},lambda:None)['title'],'Title')

if __name__=='__main__':unittest.main()
