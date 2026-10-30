"""Video job/API/worker/exchange integration, without model or media generation."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store, Worker
from videostudio.providers import Pipeline


class ExtensionVideoConnectionTests(unittest.TestCase):
    def test_health_exposes_the_selected_text_transport(self):
        class Fixture:
            def handlers(self):return {}
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'VS_LLM_TRANSPORT':'extension'}):
            store=Store(Path(tmp)/'jobs.db',Path(tmp)/'out')
            with TestClient(create_app(store,Fixture(),False)) as client:
                self.assertEqual(client.get('/api/health').json().get('text_transport'),'extension')

    def test_video_text_stages_wait_for_their_scoped_bridge_responses(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'VS_LLM_TRANSPORT':'extension'}):
            store=Store(Path(tmp)/'jobs.db',Path(tmp)/'out')
            voices=SimpleNamespace(root=Path(tmp),selected=lambda voice:{'id':voice})
            pipeline=Pipeline(voices)
            # Infrastructure is a fixture; actual plan/research/script and exchange paths run.
            pipeline.preflight=lambda scope=None:{'ready':True,'checks':[]}
            with TestClient(create_app(store,pipeline,False)) as client, patch('videostudio.providers.httpx.post',side_effect=AssertionError('No CDP or paid API allowed')):
                scope=client.post('/api/connector/sessions').json()['project_id']
                client.post('/api/connector/status/'+scope,json={'build':'videostudio-extension-0.3.0','stage':'active','connected':True,'enabled':True})
                request={'idea':'One short narration line.','voice_id':'preset:test','duration_seconds':8,'workflow_mode':'provided_narration','image_provider':'comfy','text_provider':'chatgpt'}
                response=client.post('/api/jobs',headers={'Idempotency-Key':'bridge-video','X-Connector-Scope':scope},json=request)
                self.assertEqual(response.status_code,201,response.text)
                first=response.json()
                second_response=client.post('/api/jobs',headers={'Idempotency-Key':'bridge-video-two','X-Connector-Scope':scope},json=request)
                self.assertEqual(second_response.status_code,201,second_response.text)
                second=second_response.json()
                sessions=client.get(f'/api/connector/bridges/{scope}/sessions').json()['items']
                self.assertEqual({s['job_id'] for s in sessions},{first['id'],second['id']})
                self.assertNotEqual(first['connector_scope'],second['connector_scope'])
                worker=Worker(store,pipeline.handlers())
                ids=[]

                def run_stage(expected,response_body):
                    thread=threading.Thread(target=worker.step)
                    thread.start()
                    try:
                        deadline=time.monotonic()+5
                        pending=[]
                        while time.monotonic()<deadline:
                            pending=client.get(base).json()['items']
                            if pending:break
                            time.sleep(.01)
                        self.assertEqual(len(pending),1)
                        item=pending[0];ids.append(item['id'])
                        self.assertTrue(item['prompt'].startswith('YÊU CẦU STUDIO '+item['id']+'\n'))
                        receipt=client.post(base+'/'+item['id']+'/response',json={'expected_version':item['version'],'response_text':json.dumps(response_body)})
                        self.assertEqual(receipt.status_code,200,receipt.text)
                    finally:
                        # Release a waiter even if an assertion fails; never leave an orphan test thread.
                        if thread.is_alive():
                            pending=client.get(base).json()['items']
                            for item in pending:
                                client.post(base+'/'+item['id']+'/response',json={'expected_version':item['version'],'response_text':json.dumps(response_body)})
                        thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
                    saved=store.get(job['id'])
                    self.assertIn(expected,saved['checkpoints'],saved.get('error'))

                for job in (first,second):
                    child=job['connector_scope']
                    self.assertNotEqual(child,scope)
                    self.assertEqual(pipeline.exchanges.for_job(job['id']),child)
                    base=f'/api/v1/projects/{child}/runs/{child}/chatgpt-exchanges'
                    run_stage('plan',{'title':'Fixture video','visual_style':'documentary','music_prompt':'quiet instrumental','characters':[]})
                    worker.step()  # real no-research path for supplied narration
                    run_stage('script',{'scenes':[{'line_id':'line-0001','visual_prompt':'A quiet landscape','character_ids':[]}],'characters':[]})
                    saved=store.get(job['id'])
                    self.assertEqual(saved['checkpoints']['script']['narration'],request['idea'])
                    self.assertEqual(client.get(base).json()['items'],[])
                    self.assertNotIn('speech',saved['checkpoints'])
                    # End fixture work before speech; the serial worker may now take the next video.
                    cancelled=client.post(f"/api/connector/bridges/{scope}/jobs/{job['id']}/cancel")
                    self.assertEqual(cancelled.status_code,200,cancelled.text)
                self.assertEqual(len(set(ids)),4)


if __name__=='__main__':unittest.main()
