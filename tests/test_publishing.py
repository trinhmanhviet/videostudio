import json
import tempfile
import unittest
import threading
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path

from videostudio.core import Store, digest
from videostudio.publishing import Publishing, PublishBlocked, PublishUncertain


class Versions:
    def __init__(self, root):
        self.path = root / 'verified.mp4'
        self.path.write_bytes(b'fixture-video')
        self.record = dict(job_id='job', version_id='v1', path=str(self.path),
                           sha256=digest(self.path), duration_seconds=30, approved_at=1)

    def approved_version(self, job):
        return self.record if job == 'job' else None


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'jobs.sqlite3', self.root / 'out')
        self.versions = Versions(self.root)
        self.now = 1800000000.
        self.sent = []
        self.service = Publishing(self.store, self.versions, clock=lambda: self.now)
        self.service.save_channel('youtube:one', 'youtube', 'Test channel', {'refresh_token': 'secret'})
        def adapter(row, channel, save):
            self.sent.append(row['id'])
            save(remote_id='remote-one')
            return dict(state='scheduled_remote', remote_id='remote-one', remote_url='https://youtu.be/remote-one')
        self.service.adapters['youtube'] = adapter

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, **changes):
        body = dict(job_id='job', version_id='v1', channel_id='youtube:one', title='A title', caption='Description',
                    publish_at=datetime.fromtimestamp(self.now+3600, timezone.utc).isoformat())
        body.update(changes)
        return self.service.create_schedule(body, 'schedule-key')

    def test_schedule_is_durable_and_idempotent_and_secrets_are_redacted(self):
        row = self.schedule()
        self.assertEqual(row['id'], self.schedule()['id'])
        self.assertNotIn('secret', json.dumps(self.service.channels()))
        restored = Publishing(self.store, self.versions, clock=lambda: self.now)
        self.assertEqual(restored.schedules()['items'][0]['id'], row['id'])
        with self.assertRaises(ValueError):
            self.schedule(title='Different')

    def test_requires_exact_approved_version_timezone_and_future(self):
        for changes in ({'version_id':'old'}, {'publish_at':'2027-01-01T10:00'},
                        {'publish_at':datetime.fromtimestamp(self.now-10, timezone.utc).isoformat()}):
            with self.assertRaises(ValueError):
                self.schedule(**changes)

    def test_file_change_blocks_upload_even_after_approval(self):
        row = self.schedule()
        self.versions.path.write_bytes(b'changed-same-path')
        self.service.tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.service.get_schedule(row['id'])['state'], 'blocked')

    def test_upload_receipt_survives_restart_and_is_not_recreated(self):
        row = self.schedule()
        self.assertTrue(self.service.tick())
        self.assertEqual(self.service.get_schedule(row['id'])['state'], 'scheduled_remote')
        restored = Publishing(self.store, self.versions, clock=lambda: self.now)
        restored.adapters['youtube'] = lambda *args: self.fail('must reconcile remote receipt')
        # The remote status poll has its own method and may not start an upload.
        restored.poll_remote = lambda *args: dict(state='scheduled_remote')
        restored.tick()
        self.assertEqual(self.sent, [row['id']])

    def test_uncertain_reply_never_reuploads_automatically(self):
        row = self.schedule()
        def uncertain(row, channel, save):
            save(remote_id='possibly-created')
            raise PublishUncertain('Connection lost after finish')
        self.service.adapters['youtube'] = uncertain
        self.service.tick()
        current = self.service.get_schedule(row['id'])
        self.assertEqual(current['state'], 'needs_attention')
        with self.assertRaises(ValueError):
            self.service.retry(row['id'])
        self.assertEqual(current['remote_id'], 'possibly-created')

    def test_cancel_only_before_remote_upload(self):
        row = self.schedule()
        self.service.cancel(row['id'])
        self.assertFalse(self.service.tick())
        self.assertEqual(self.sent, [])

    def test_facebook_waits_until_due(self):
        self.service.save_channel('facebook:1', 'facebook', 'Page', {'access_token':'page-secret', 'page_id':'1'})
        row = self.schedule(channel_id='facebook:1')
        self.service.adapters['facebook'] = lambda row, channel, save: dict(state='processing', remote_id='fb1')
        self.assertFalse(self.service.tick())
        self.now += 3601
        self.assertTrue(self.service.tick())
        self.assertEqual(self.service.get_schedule(row['id'])['remote_id'], 'fb1')

    def test_expired_inflight_claim_becomes_attention_after_restart(self):
        row = self.schedule()
        with self.store.db() as db:
            db.execute("UPDATE publishing_schedules SET state='uploading',lease_until=?,remote_id='durable' WHERE id=?", (self.now-1,row['id']))
        self.service.tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.service.get_schedule(row['id'])['state'], 'needs_attention')

    def test_reconcile_excludes_simultaneous_reconcile_and_tick(self):
        row = self.schedule()
        self.service._save(row['id'],state='needs_attention',remote_id='known')
        entered, release = threading.Event(), threading.Event()
        def poll(*args):
            entered.set(); release.wait(3)
            return {'state':'processing'}
        self.service.poll_remote=poll
        thread=threading.Thread(target=lambda:self.service.reconcile(row['id']))
        thread.start(); self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(ValueError):self.service.reconcile(row['id'])
            self.assertFalse(self.service.tick())
        finally:
            release.set();thread.join(3)

    def test_youtube_missing_range_resumes_at_zero_and_sends_approved_snapshot(self):
        row=self.schedule()
        raw=self.service._raw_schedule(row['id'])
        raw['upload_url']='https://www.googleapis.com/upload/session'
        def headers(channel):
            self.versions.path.write_bytes(b'changed-file!')
            return {'Authorization':'Bearer fixture'}
        self.service._yt_headers=headers
        calls=[]
        def http(method,url,**kwargs):
            calls.append(kwargs)
            if kwargs['headers']['Content-Range'].startswith('bytes */'):return httpx.Response(308)
            return httpx.Response(201,json={'id':'known'})
        self.service._request=http
        self.service.upload_youtube(raw,self.service.channel('youtube:one'),lambda **kw:None)
        self.assertEqual(calls[1]['content'],b'fixture-video')
        self.assertTrue(calls[1]['headers']['Content-Range'].startswith('bytes 0-'))

    def test_pre_upload_network_failure_can_retry_without_new_remote_receipt(self):
        row=self.schedule()
        self.service._yt_headers=lambda channel:(_ for _ in ()).throw(httpx.ConnectError('offline'))
        self.service.adapters['youtube']=self.service.upload_youtube
        self.service.tick()
        self.assertEqual(self.service.get_schedule(row['id'])['state'],'blocked')
        self.service.retry(row['id'])
        self.assertEqual(self.service.get_schedule(row['id'])['state'],'scheduled')

    def test_facebook_lost_binary_reply_is_reconciled_on_same_remote_id(self):
        self.service.save_channel('facebook:1','facebook','Page',{'access_token':'secret','page_id':'1'})
        row=self.schedule(channel_id='facebook:1')
        self.now+=3601
        self.service._save(row['id'],state='needs_attention',phase='created',remote_id='123')
        calls=[]
        def http(method,url,**kwargs):
            calls.append((method,kwargs))
            return httpx.Response(200,json={'status':{'video_status':'ready','processing_phase':{'status':'complete'}}} if method=='GET' else {'success':True})
        self.service._request=http
        self.service.reconcile(row['id'])
        self.assertEqual([call[0] for call in calls],['GET','POST'])
        self.assertEqual(calls[1][1]['data']['video_id'],'123')


if __name__ == '__main__':
    unittest.main()
