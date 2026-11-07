import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from videostudio.core import validate_request


class StudioInputTests(unittest.TestCase):
    def test_meme_input_mode_preserves_explicit_script_or_idea(self):
        request = dict(idea='Story',voice_id='voice',duration_seconds=30,workflow_mode='meme')
        for mode in ('script','idea'):
            self.assertEqual(validate_request(dict(request,meme_input_mode=mode))['meme_input_mode'],mode)
        for mode in ('unknown', [], None):
            with self.assertRaises(ValueError):
                validate_request(dict(request,meme_input_mode=mode))
        with self.assertRaises(ValueError):
            validate_request(dict(request,workflow_mode='research',meme_input_mode='script'))
        self.assertNotIn('meme_input_mode',validate_request(request))

    def test_editorial_style_is_a_real_request_field(self):
        request=dict(idea='Story',voice_id='voice',duration_seconds=30)
        self.assertEqual(validate_request(dict(request,content_style='case'))['content_style'],'case')
        with self.assertRaises(ValueError):validate_request(dict(request,content_style='unsupported'))

    def test_application_routes_and_normal_admission_are_connected(self):
        from videostudio.api import create_app
        from videostudio.core import Store
        class Pipeline:
            def handlers(self):return {}
            def preflight(self):return {'ready':True,'checks':[]}
        with tempfile.TemporaryDirectory() as tmp, patch('videostudio.api.Voices.selected',return_value={'id':'voice'}), patch.dict('os.environ',{'VS_LLM_TRANSPORT':'cdp'}):
            app=create_app(Store(Path(tmp)/'jobs.sqlite3',Path(tmp)/'out'),Pipeline(),False)
            with TestClient(app,base_url='http://127.0.0.1:8877') as client:
                for path in ('/','/resources','/studio-shell.css','/content-studio.js','/api/resources','/api/factory/queue','/api/publishing/channels','/api/publishing/schedules'):
                    self.assertEqual(client.get(path).status_code,200,path)
                body=dict(project='Fixture',style='case',input_mode='idea',defaults=dict(voice_id='voice',duration_seconds=30),items=['A case','Another case'])
                response=client.post('/api/factory/batches',json=body,headers={'Idempotency-Key':'batch-fixture'})
                self.assertEqual(response.status_code,201,response.text)
                self.assertEqual(len(app.state.store.list()),0)
                self.assertTrue(app.state.content_factory.tick())
                jobs=app.state.store.list()
                self.assertEqual(len(jobs),1)
                self.assertEqual(jobs[0]['request']['content_style'],'case')
                self.assertEqual(jobs[0]['request']['workflow_mode'],'research')
                self.assertFalse(app.state.content_factory.tick())
                denied=client.post('/api/publishing/youtube/config',json={},headers={'Origin':'https://foreign.invalid'})
                self.assertEqual(denied.status_code,403)
