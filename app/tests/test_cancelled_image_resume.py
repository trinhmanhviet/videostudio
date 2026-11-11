import json,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from videostudio.core import Store
from videostudio.api import create_app


class CancelledImageResumeTests(unittest.TestCase):
    def test_explicit_animation_script_resume_keeps_job_and_replaces_blocked_scope(self):
        from videostudio.exchanges import Exchanges
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'videos')
            req={'idea':'test','voice_id':'test','duration_seconds':420,'workflow_mode':'meme','meme_engine':'hyperframes'}
            job,_=store.create(req,'job');exchanges=Exchanges(store)
            root=exchanges.scope();scope=exchanges.scope();exchanges.bind(scope,job['id'])
            pending=exchanges.enqueue(scope,'Old oversized script request')
            saved={'plan':{'meme_engine':'hyperframes'},'research':{'sources':[]}}
            with store.db() as db:
                db.execute('INSERT INTO connector_bridge_memberships VALUES(?,?)',(scope,root))
                for stage,value in saved.items():db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],stage,json.dumps(value)))
                db.execute("UPDATE jobs SET state='cancelled',cancel=1,stage='script' WHERE id=?",(job['id'],))
            with TestClient(create_app(store=store,worker_enabled=False)) as client:
                url='/api/jobs/'+job['id']+'/retry'
                self.assertEqual(client.post(url,json={}).status_code,400)
                self.assertEqual(client.post(url,json={'resume_cancelled':True}).status_code,200)
            result=store.get(job['id']);self.assertEqual(result['state'],'queued');self.assertEqual(result['checkpoints'],saved)
            self.assertNotEqual(exchanges.for_job(job['id']),scope)
            self.assertNotIn(pending,[r['id'] for r in exchanges.bridge_pending(root)['items']])
            self.assertIsNone(exchanges.get(scope,pending)['response'])  # preserve real reply/receipt history
    def test_resume_requires_explicit_click_and_retains_completed_checkpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'videos')
            job,_=store.create({'idea':'test','voice_id':'test','duration_seconds':8},'job')
            saved={'script':{'narration':'keep'},'speech':{'path':'unchanged.wav'},'music':{'path':'unchanged.mp3'}}
            with store.db() as db:
                for stage,value in saved.items():db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(job['id'],stage,json.dumps(value)))
                db.execute("UPDATE jobs SET state='cancelled',cancel=1,stage='images' WHERE id=?",(job['id'],))
            with TestClient(create_app(store=store,worker_enabled=False)) as client:
                url='/api/jobs/'+job['id']+'/retry'
                self.assertEqual(client.post(url,json={}).status_code,400)
                response=client.post(url,json={'resume_cancelled':True})
                self.assertEqual(response.status_code,200)
            result=store.get(job['id']);self.assertEqual(result['state'],'queued');self.assertEqual(result['cancel'],0)
            self.assertEqual(result['checkpoints'],saved)

    def test_cancelled_text_generation_is_not_silently_restarted(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db',Path(folder)/'videos');job,_=store.create({'idea':'test','voice_id':'test','duration_seconds':8},'job')
            with store.db() as db:db.execute("UPDATE jobs SET state='cancelled',cancel=1,stage='script' WHERE id=?",(job['id'],))
            with TestClient(create_app(store=store,worker_enabled=False)) as client:
                self.assertEqual(client.post('/api/jobs/'+job['id']+'/retry',json={'resume_cancelled':True}).status_code,400)
            self.assertEqual(store.get(job['id'])['cancel'],1)
