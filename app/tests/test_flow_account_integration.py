import json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient
from videostudio.core import Store,Worker,STAGES
from videostudio.api import create_app
from videostudio.providers import Pipeline

class Fixture:
    def handlers(self):return {}
    def preflight(self):return {'ready':False,'checks':[]}

class FlowAccountIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/'db',self.root/'outputs')
        self.job,_=self.store.create({'idea':'test','voice_id':'selected','duration_seconds':8,'image_provider':'flow'},'one')
        with self.store.db() as c:
            for stage in STAGES[:4]:c.execute('INSERT INTO checkpoints VALUES(?,?,?)',(self.job['id'],stage,json.dumps({'assets':[]})))
            c.execute("UPDATE jobs SET stage='images' WHERE id=?",(self.job['id'],))
    def tearDown(self):self.tmp.cleanup()
    def pause(self):
        with self.store.db() as c:c.execute('INSERT OR REPLACE INTO flow_account_changes VALUES(?,?,?,0)',(self.job['id'],'pausing','{}'))
    def test_pause_during_image_stage_keeps_job_and_does_not_spend_attempt(self):
        def images(job,check):self.pause();check();raise AssertionError('Paused work must not continue')
        self.assertTrue(Worker(self.store,{'images':images}).step())
        job=self.store.get(self.job['id']);self.assertEqual(job['state'],'awaiting_flow_account');self.assertEqual(job['cancel'],0);self.assertNotIn('images',job['checkpoints']);self.assertEqual(job['attempts']['images'],0)
    def test_failed_transport_with_pause_requested_parks_instead_of_retrying(self):
        def images(job,check):self.pause();raise ConnectionError('transport was waiting')
        Worker(self.store,{'images':images}).step();self.assertEqual(self.store.get(self.job['id'])['state'],'awaiting_flow_account')
    def test_cancelled_paused_job_does_not_keep_global_handoff_block(self):
        self.pause()
        with self.store.db() as c:c.execute("UPDATE jobs SET state='awaiting_flow_account' WHERE id=?",(self.job['id'],))
        self.store.cancel(self.job['id']);self.assertEqual(self.store.get(self.job['id'])['state'],'cancelled')
        from videostudio.flow_account import FlowAccountService
        self.assertFalse(FlowAccountService(self.store).blocks_workers())
    def test_browser_changes_blocked_while_reconciling_but_allowed_when_ready(self):
        app=create_app(self.store,Fixture(),False);browser=app.state.browser_manager
        browser.launcher.host_state=Mock(return_value={'processes':[]})
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='awaiting_flow_account' WHERE id=?",(self.job['id'],))
            c.execute('INSERT OR REPLACE INTO flow_account_changes VALUES(?,?,?,0)',(self.job['id'],'reconciling','{}'))
        with TestClient(app,base_url='http://localhost:8877') as client:
            self.assertFalse(client.get('/api/browser/profile').json()['can_change'])
            with self.store.db() as c:c.execute("UPDATE flow_account_changes SET phase='ready' WHERE job=?",(self.job['id'],))
            self.assertTrue(client.get('/api/browser/profile').json()['can_change'])
    def test_flow_handoff_routes_enforce_local_origin(self):
        app=create_app(self.store,Fixture(),False);service=app.state.flow_accounts;service.prepare=Mock(return_value={'phase':'pausing'});service.continue_job=Mock(return_value={'phase':'running'})
        with TestClient(app,base_url='http://localhost:8877') as client:
            base='/api/jobs/'+self.job['id']+'/flow-account'
            self.assertEqual(client.post(base+'/prepare',headers={'Origin':'https://evil.test'}).status_code,403);service.prepare.assert_not_called()
            self.assertEqual(client.post(base+'/prepare').json()['phase'],'pausing')
            self.assertEqual(client.post(base+'/continue').json()['phase'],'running')
    def test_active_flow_run_changes_only_new_flow_task_namespace(self):
        from videostudio import providers
        run=str(uuid.uuid4());p=Pipeline.__new__(Pipeline);p.flow_accounts=Mock();p.flow_accounts.active_run.return_value=run
        self.assertEqual(p._active_flow_run(self.job),run)
        tasks=[{'task_id':str(uuid.uuid5(uuid.UUID(run),'bulk-scene-image:0')),'prompt':'frame','character_mentions':[],'ordinal':0,'output_path':self.root/'scene.png'}]
        captured=[]
        def post(url,**kwargs):captured.append(kwargs['json']);raise providers.httpx.ConnectError('offline fixture')
        with patch('videostudio.providers.httpx.post',side_effect=post):
            with self.assertRaises(Exception):p._browser_scene_images_batch(self.job,tasks,lambda:None,timeout=60)
        self.assertEqual(captured[0]['job_id'],run);self.assertEqual(self.job['id'],self.store.get(self.job['id'])['id'])

if __name__=='__main__':unittest.main()
