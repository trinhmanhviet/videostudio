import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from videostudio.core import PermanentError
from videostudio.providers import Pipeline


class ExtensionRoutingTests(unittest.TestCase):
    def test_chatgpt_job_uses_selected_extension_transport_without_cdp(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.context = SimpleNamespace(job='extension-job', text_provider='chatgpt')
        pipeline.exchanges = SimpleNamespace(request=Mock(return_value={'ok': True}))
        response = SimpleNamespace(status_code=200, json=lambda: {'ok': True, 'data': {'wrong_transport': True}})
        with patch.dict('os.environ', {'VS_LLM_TRANSPORT': 'extension'}), patch('httpx.post', return_value=response) as post:
            self.assertEqual(pipeline.llm_json('hello', lambda: None), {'ok': True})
            post.assert_not_called()
            pipeline.exchanges.request.assert_called_once()
            self.assertGreaterEqual(pipeline.exchanges.request.call_args.kwargs['timeout'], 800)

    def test_extension_api_rejects_gemini_before_allocating_a_job(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        from videostudio.core import Store
        class Ready:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'jobs.sqlite3',Path(tmp)/'out')
            with TestClient(create_app(store,Ready(),False)) as client, patch.dict('os.environ',{'VS_LLM_TRANSPORT':'extension'}):
                response=client.post('/api/jobs',headers={'Idempotency-Key':'wrong-provider'},json={'idea':'test','voice_id':'test','duration_seconds':8,'text_provider':'gemini'})
                self.assertEqual(response.status_code,422)
                self.assertIn('ChatGPT',response.json()['detail'])
                self.assertEqual(store.list(),[])

    def test_extension_never_silently_routes_gemini_to_dedicated_browser(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.context = SimpleNamespace(job='extension-job', text_provider='gemini')
        with patch.dict('os.environ', {'VS_LLM_TRANSPORT': 'extension'}), patch('httpx.post') as post:
            with self.assertRaisesRegex(PermanentError, 'ChatGPT'):
                pipeline.llm_json('hello', lambda: None)
            post.assert_not_called()

    def test_duplicate_smoke_click_returns_conflict_and_preserves_one_request(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        from videostudio.core import Store
        class Ready:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'jobs.sqlite3',Path(tmp)/'out')
            with TestClient(create_app(store,Ready(),False),raise_server_exceptions=False) as client:
                scope=client.post('/api/connector/sessions').json()['project_id']
                path='/api/connector/smoke/'+scope
                self.assertEqual(client.post(path).status_code,200)
                self.assertEqual(client.post(path).status_code,409)
                from videostudio.exchanges import Exchanges
                self.assertEqual(len(Exchanges(store).pending(scope)['items']),1)


if __name__ == '__main__':
    unittest.main()
