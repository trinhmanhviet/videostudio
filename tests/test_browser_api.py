import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store

class Fixture:
    def handlers(self):return {}
    def preflight(self):return {'ready':False,'checks':[]}

class BrowserAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.client=TestClient(create_app(Store(Path(self.tmp.name)/'db',Path(self.tmp.name)/'out'),Fixture(),False))
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def test_status_only_proxies_passive_get(self):
        with patch('httpx.get',return_value=SimpleNamespace(status_code=200,json=lambda:{'connected':False,'ready':False})) as get:
            r=self.client.get('/api/browser/status')
            self.assertEqual(r.status_code,200);self.assertFalse(r.json()['ready'])
            self.assertTrue(get.call_args.args[0].endswith('/api/status'))
    def test_cross_origin_start_refused_without_daemon_call(self):
        with patch('httpx.post') as post:
            self.assertEqual(self.client.post('/api/browser/start',headers={'Origin':'https://evil.example'}).status_code,403)
            post.assert_not_called()
    def test_start_uses_protected_daemon_and_not_extension(self):
        with patch('httpx.post',return_value=SimpleNamespace(status_code=200,json=lambda:{'connected':True,'ready':False})) as post:
            self.assertEqual(self.client.post('/api/browser/start').status_code,200)
            self.assertEqual(post.call_args.kwargs['headers']['X-VS-Client'],'videostudio')
    def test_frontend_no_auto_redirect_to_extension_scope(self):
        body=self.client.get('/').text
        self.assertNotIn('location.replace(s.url)',body)
        self.assertIn('browserStart',body)

if __name__=='__main__':unittest.main()
