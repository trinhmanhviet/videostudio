"""Real isolated bridge receipts; external media prerequisites use fixture data."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videostudio.core import Store
from videostudio.exchanges import Exchanges
from videostudio.providers import Pipeline, image_graph, music_graph


class ExtensionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/'db', Path(self.tmp.name)/'out')
        self.ex = Exchanges(self.store)
        self.root = self.ex.scope()
        self.child = self.ex.scope()
        with self.store.db() as c:
            c.execute('INSERT INTO connector_bridge_memberships VALUES(?,?)', (self.child, self.root))

    def heartbeat(self, age=45, **overrides):
        status = {'build':'videostudio-extension-0.3.0', 'stage':'active', 'connected':True, 'enabled':True}
        status.update(overrides)
        with self.store.db() as c:
            c.execute('INSERT OR REPLACE INTO connector_status VALUES(?,?,?)', (self.root, json.dumps(status), time.time()-age))

    def accept_smoke(self):
        identifier = self.ex.enqueue_smoke(self.root)
        self.ex.receive(self.root, identifier, 1, '{"connection_test":"videostudio","ok":true}')
        return identifier

    def test_45_second_heartbeat_accepts_root_and_child_but_120_seconds_fails(self):
        self.accept_smoke()
        self.heartbeat()
        self.assertTrue(self.ex.accepted_extension(self.root))
        self.assertTrue(self.ex.accepted_extension(self.child))
        self.assertTrue(self.ex.bridge_supports_sessions(self.root))
        self.heartbeat(120)
        self.assertFalse(self.ex.accepted_extension(self.root))
        self.assertFalse(self.ex.accepted_extension(self.child))
        self.assertFalse(self.ex.bridge_supports_sessions(self.root))

    def test_latest_pending_smoke_does_not_reuse_older_accepted_smoke(self):
        self.accept_smoke()
        pending = self.ex.enqueue_smoke(self.root)
        self.heartbeat(error={'code':'MODE_UNCONFIRMED', 'reason':'Chat mode not confirmed'})
        status = self.ex.extension_status(self.child)
        self.assertEqual((status['scope'], status['bridge']), (self.child, self.root))
        self.assertTrue(status['heartbeat']['ready'])
        self.assertEqual(status['smoke']['status'], 'pending')
        self.assertEqual(status['smoke']['exchange_id'], pending)
        self.assertIn('Chat mode not confirmed', status['smoke']['reason'])
        self.assertFalse(status['ready'])
        self.assertFalse(self.ex.accepted_extension(self.child))
        self.ex.receive(self.root, pending, 1, '{"connection_test":"videostudio","ok":true}')
        self.assertTrue(self.ex.extension_status(self.child)['ready'])

    def test_missing_invalid_and_unsupported_states_have_distinct_diagnostics(self):
        status = self.ex.extension_status(self.root)
        self.assertEqual(status['smoke']['status'], 'missing')
        self.assertFalse(status['heartbeat']['present'])
        identifier = self.ex.enqueue_smoke(self.root)
        self.ex.receive(self.root, identifier, 1, '{"ok":true}')
        self.heartbeat(build='videostudio-extension-0.1.0')
        status = self.ex.extension_status(self.root)
        self.assertEqual(status['smoke']['status'], 'invalid')
        self.assertFalse(status['heartbeat']['supported_build'])
        self.assertFalse(status['ready'])
        with self.assertRaises(KeyError):
            self.ex.extension_status('unknown')


class ExtensionPreflightApiTests(unittest.TestCase):
    def test_worker_origin_is_allowed_only_for_known_scope_informational_heartbeat(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        fixture = SimpleNamespace(handlers=lambda:{})
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'VS_STORYFORGE_ROOT':tmp}):
            store = Store(Path(tmp)/'db', Path(tmp)/'out')
            with TestClient(create_app(store, fixture, False), base_url='http://127.0.0.1:8877') as client:
                scope = Exchanges(store).scope()
                url = '/api/connector/status/'+scope
                headers = {'Origin':'chrome-extension://'+'a'*32, 'X-VS-Client':'videostudio-extension'}
                self.assertEqual(client.post(url, json={}, headers=headers).status_code, 200)
                self.assertEqual(client.post('/api/connector/status/unknown', json={}, headers=headers).status_code, 404)
                self.assertEqual(client.post('/api/connector/smoke/'+scope, headers=headers).status_code, 403)
                self.assertEqual(client.post('/api/connector/sessions', headers=headers).status_code, 403)
                for invalid in ({'Origin':headers['Origin']}, {**headers,'Origin':'https://untrusted.invalid'}, {**headers,'Origin':'chrome-extension://invalid'}, {**headers,'Origin':'chrome-extension://'+'a'*32+'/path'}, {**headers,'Host':'untrusted.invalid'}):
                    self.assertEqual(client.post(url, json={}, headers=invalid).status_code, 403, invalid)
                same_origin = {'Origin':'http://127.0.0.1:8877'}
                self.assertEqual(client.post(url, json={}, headers=same_origin).status_code, 200)
                active = {'build':'videostudio-extension-0.3.0','stage':'active','connected':True,'enabled':True}
                client.post(url, json=active)
                with store.db() as c:
                    c.execute('UPDATE connector_status SET updated=? WHERE scope=?', (time.time()-45, scope))
                nonowner = client.post(url, json={**active,'stage':'other_run','enabled':False})
                self.assertFalse(nonowner.json()['recorded'])
                self.assertTrue(Exchanges(store).extension_status(scope)['heartbeat']['ready'])

    def test_root_and_child_gates_track_real_latest_receipt_and_heartbeat(self):
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'VS_LLM_TRANSPORT':'extension', 'VS_STORYFORGE_ROOT':tmp}):
            store = Store(Path(tmp)/'db', Path(tmp)/'out')
            voices = SimpleNamespace(root=Path(tmp), catalog=lambda:{'complete':True, 'warnings':[]})
            pipeline = Pipeline(voices)
            pipeline.speech_cache = tmp
            pipeline.accepted_music = lambda:True
            info = {n['class_type']:{} for n in list(image_graph('',1,'x').values())+list(music_graph('',8,1,'x').values())}
            for kind,key,values in [('UNETLoader','unet_name',['qwen_image_2.1_int8_convrot.safetensors']),('CLIPLoader','clip_name',['qwen3vl_8b_int8_convrot.safetensors','t5gemma_b_b_ul2.safetensors']),('VAELoader','vae_name',['qwen_image_2.1_vae_bf16.safetensors']),('CheckpointLoaderSimple','ckpt_name',['stable_audio_3_medium_base.safetensors'])]:
                info[kind] = {'input':{'required':{key:[values]}}}
            response = SimpleNamespace(status_code=200, json=lambda:info, raise_for_status=lambda:None)
            with patch('httpx.get', return_value=response), patch('subprocess.run', return_value=SimpleNamespace(returncode=0,stdout='True')), patch('shutil.which', return_value='fixture'), TestClient(create_app(store,pipeline,False)) as client:
                ex = Exchanges(store)
                root = ex.scope()
                _, _ = store.create({'idea':'Fixture', 'voice_id':'test', 'duration_seconds':8}, 'child', connector_bridge=root)
                child = ex.bridge_sessions(root)['items'][0]['scope']
                def heartbeat(age):
                    result = client.post('/api/connector/status/'+root, json={'build':'videostudio-extension-0.3.0','stage':'active','connected':True,'enabled':True,'error':{'code':'chat_mode','message':'Chat mode not confirmed'}})
                    self.assertEqual(result.status_code, 200)
                    with store.db() as c:
                        c.execute('UPDATE connector_status SET updated=? WHERE scope=?', (time.time()-age, root))
                def checks(scope):
                    result = client.get('/api/preflight', params={'scope':scope})
                    self.assertEqual(result.status_code, 200)
                    return result.json(), {c['name']:c for c in result.json()['checks']}
                first = client.post('/api/connector/smoke/'+root).json()['exchange_id']
                prefix = f'/api/v1/projects/{root}/runs/{root}/chatgpt-exchanges/'
                client.post(prefix+first+'/response', json={'expected_version':1,'response_text':'{"connection_test":"videostudio","ok":true}'})
                heartbeat(120)
                for scope in (root,child):
                    _, gates = checks(scope)
                    self.assertFalse(gates['extension_transport']['ok'])
                    self.assertFalse(gates['production_acceptance']['ok'])
                heartbeat(45)
                pending = client.post('/api/connector/smoke/'+root).json()['exchange_id']
                for scope in (root,child):
                    pf, gates = checks(scope)
                    self.assertTrue(gates['extension_transport']['ok'])
                    self.assertFalse(gates['extension_smoke']['ok'])
                    self.assertIn('Chat mode not confirmed', gates['extension_smoke']['message'])
                    self.assertIn('extension_smoke', gates['production_acceptance']['message'])
                    self.assertFalse(pf['ready'])
                status = client.get('/api/connector/bridges/'+root+'/status')
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json()['smoke']['exchange_id'], pending)
                self.assertEqual(client.get('/api/connector/bridges/unknown/status').status_code, 404)
                imported = client.post(prefix+pending+'/response', json={'expected_version':1,'response_text':'{"connection_test":"videostudio","ok":true}'})
                self.assertEqual(imported.status_code, 200)
                for scope in (root,child):
                    pf, gates = checks(scope)
                    self.assertTrue(gates['extension_transport']['ok'])
                    self.assertTrue(gates['extension_smoke']['ok'])
                    self.assertTrue(gates['production_acceptance']['ok'])
                    self.assertTrue(pf['ready'])


if __name__ == '__main__':
    unittest.main()
