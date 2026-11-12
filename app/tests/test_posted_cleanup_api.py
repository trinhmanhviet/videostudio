import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from videostudio.api import create_app
from videostudio.core import Store,digest
from videostudio.output_layout import final_video_path
from videostudio.media import asset

class Pipeline:
    def handlers(self):return {}
    def preflight(self):return {'ready':False,'checks':[]}

class PostedCleanupAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'jobs.sqlite3',self.root/'out');self.app=create_app(self.store,Pipeline(),False)
        self.client=TestClient(self.app,base_url='http://localhost:8877')
        job,_=self.store.create(dict(idea='Full private script',project='Project',voice_id='voice',duration_seconds=30),'source')
        self.identifier=job['id'];self.video=final_video_path(job);self.video.parent.mkdir(parents=True,exist_ok=True);self.video.write_bytes(b'fixture')
        self.video.with_suffix('.srt').write_text('Caption')
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='completed' WHERE id=?",(self.identifier,))
            for stage,value in [('render',{'video':str(self.video),'assets':[asset(self.video)]}),('verify',{'verified':True})]:
                db.execute('INSERT INTO checkpoints VALUES(?,?,?)',(self.identifier,stage,json.dumps(value)))
        self.url='/api/jobs/'+self.identifier+'/posted-cleanup'
        self.body=dict(confirm=True,title='Posted',platform='youtube',channel_name='Channel',post_url='https://youtu.be/video',published_at=datetime.now(timezone.utc).isoformat())
        self.headers={'Idempotency-Key':'cleanup'}

    def tearDown(self):self.client.close();self.tmp.cleanup()

    def test_explicit_local_confirmation_persists_history_and_removes_real_fixture_job(self):
        self.assertEqual(self.client.post(self.url,json=self.body).status_code,422)
        self.assertEqual(self.client.post(self.url,json=self.body,headers={**self.headers,'Origin':'https://foreign.invalid'}).status_code,403)
        self.assertEqual(self.client.post(self.url,json={**self.body,'confirm':False},headers=self.headers).status_code,422)
        result=self.client.post(self.url,json=self.body,headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get('/api/jobs/'+self.identifier).status_code,404)
        self.assertFalse(self.video.exists());self.assertFalse(self.video.with_suffix('.srt').exists())
        self.app.state.posted_cleanup.tick()
        self.assertFalse(self.video.parent.exists())
        repeated=self.client.post(self.url,json=self.body,headers=self.headers)
        self.assertEqual(repeated.json()['entry']['id'],result.json()['entry']['id'])
        history=self.client.get('/api/publication-history?q=posted&platform=youtube&page_size=10').json()
        self.assertEqual(history['total'],1);self.assertEqual(history['items'][0]['title'],'Posted')
        self.assertNotIn('Full private script',json.dumps(history))
        self.assertEqual(self.client.get('/api/publication-history?page_size=12').status_code,422)

    def test_an_inflight_manual_render_prevents_cleanup(self):
        from videostudio.meme_editor import _EDITOR_RENDERS
        _EDITOR_RENDERS.add(self.identifier)
        try:self.assertEqual(self.client.post(self.url,json=self.body,headers=self.headers).status_code,409)
        finally:_EDITOR_RENDERS.discard(self.identifier)
        self.assertTrue(self.video.exists())
        self.assertEqual(self.client.get('/api/publication-history').json()['total'],0)

    def test_http_response_does_not_wait_for_physical_file_purge_and_status_is_read_only(self):
        service=self.app.state.posted_cleanup
        status=self.client.get(self.url,headers=self.headers)
        self.assertEqual(status.status_code,200)
        self.assertFalse(status.json()['ok'])
        with patch.object(service,'_purge_path') as purge:
            result=self.client.post(self.url,json={'confirm':True},headers=self.headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertTrue(result.json()['cleanup_pending'])
            purge.assert_not_called()
            receipt=self.client.get(self.url,headers=self.headers).json()
            self.assertTrue(receipt['ok']);self.assertEqual(receipt['entry']['id'],result.json()['entry']['id'])
        service.tick()
        self.assertFalse(self.client.get(self.url,headers=self.headers).json()['cleanup_pending'])

    def test_confirmation_only_automatically_keeps_a_small_history_and_retries_after_job_is_gone(self):
        result=self.client.post(self.url,json={'confirm':True},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        entry=result.json()['entry']
        self.assertEqual(entry['title'],'Project')
        self.assertEqual(entry['platform'],'other')
        self.assertEqual(self.client.get('/api/jobs/'+self.identifier).status_code,404)
        retry=self.client.post(self.url,json={'confirm':True},headers=self.headers)
        self.assertEqual(retry.json()['entry']['id'],entry['id'])
        self.assertEqual(self.client.get('/api/publication-history').json()['total'],1)

    def test_confirmation_only_uses_actual_published_page_metadata(self):
        import time
        self.app.state.publishing.save_channel('facebook:1','facebook','My Page',{'access_token':'fixture'})
        with self.store.db() as db:
            db.execute('''INSERT INTO publishing_schedules
                (id,idem,fingerprint,job_id,version_id,path,sha256,channel_id,platform,title,caption,publish_at,state,remote_url,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',('schedule','schedule-key','fingerprint',self.identifier,'v1',str(self.video),digest(self.video),'facebook:1','facebook','Title','',time.time()-3600,'published','https://www.facebook.com/reel/123',time.time(),time.time()))
        result=self.client.post(self.url,json={'confirm':True},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        entry=result.json()['entry']
        self.assertEqual(entry['platform'],'facebook')
        self.assertEqual(entry['channel_name'],'My Page')
        self.assertEqual(entry['post_url'],'https://www.facebook.com/reel/123')

    def test_background_social_writer_cannot_recreate_a_cleaned_folder(self):
        from videostudio import social_copy
        social_copy._running.add(self.identifier)
        try:self.assertEqual(self.client.post(self.url,json=self.body,headers=self.headers).status_code,409)
        finally:social_copy._running.discard(self.identifier)
        self.assertTrue(self.video.exists())

    def test_schedule_admission_rechecks_job_after_approval_race(self):
        publisher=self.app.state.publishing
        publisher.save_channel('youtube:test','youtube','Channel',{'refresh_token':'fixture'})
        record={'job_id':self.identifier,'version_id':'fixture-version','path':str(self.video),'sha256':digest(self.video),'duration_seconds':30}
        class Versions:
            def approved_version(self,identifier):return record
        publisher.versions=Versions()
        def remove_after_hash(path):
            value=digest(path)
            response=self.client.post(self.url,json=self.body,headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            return value
        import time
        with patch('videostudio.publishing.digest',side_effect=remove_after_hash):
            with self.assertRaises(ValueError):publisher.create_schedule(dict(job_id=self.identifier,version_id='fixture-version',channel_id='youtube:test',title='Title',publish_at=datetime.fromtimestamp(time.time()+3600,timezone.utc).isoformat()),'schedule')
        self.assertEqual(publisher.schedules()['items'],[])

if __name__=='__main__':unittest.main()
