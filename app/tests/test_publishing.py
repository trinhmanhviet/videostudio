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

    def test_a_video_over_15_minutes_is_not_sent_to_a_channel_not_verified_for_long_videos(self):
        """Chương 2 (17 min) was uploaded 7 times: YouTube stopped processing it and hid it from the API (2026-11-17)."""
        row = {'path': 'p', 'job_id': 'job', 'channel_id': 'youtube:UCx'}
        asked = []
        reply = {'items': [{'status': {'longUploadsStatus': 'eligible'}}]}
        self.service._request = lambda method, url, **kw: (asked.append(kw.get('params')), type('R', (), {'json': lambda s: reply})())[1]
        self.service._video_seconds = lambda row: 1032.5
        with self.assertRaisesRegex(PublishBlocked, 'Video dài 17 phút 12 giây.*youtube.com/verify'):
            self.service._check_youtube_length(row, {}, {})
        self.assertEqual(asked, [{'part': 'status', 'id': 'UCx'}])
        reply = {'items': [{'status': {'longUploadsStatus': 'allowed'}}]}
        self.service._check_youtube_length(row, {}, {})       # verified channel: sent
        self.service._video_seconds = lambda row: 642.5
        asked.clear()
        self.service._check_youtube_length(row, {}, {})       # short video: no question asked
        self.assertEqual(asked, [])

    def test_a_second_schedule_of_the_same_video_says_when_it_is_already_planned(self):
        """Posting chapter 3 by hand while the plan had it for 08:00 on 19/11 only said "không tạo trùng" (2026-11-17)."""
        first = self.schedule()
        body = dict(job_id='job', version_id='v1', channel_id='youtube:one', title='A title', caption='Description',
                    publish_at=datetime.fromtimestamp(self.now+7200, timezone.utc).isoformat())
        when = datetime.fromtimestamp(self.now+3600, timezone(timedelta(hours=7))).strftime('%H:%M ngày %d/%m')
        with self.assertRaisesRegex(ValueError, f'đã có lịch đăng lên kênh lúc {when}.*Đăng ngay'):
            self.service.create_schedule(body, 'other-key')

    def test_publish_now_makes_the_scheduled_youtube_video_public(self):
        row = self.schedule()
        self.service._save(row['id'], state='scheduled_remote', remote_id='abc123')
        sent = []
        granted = {'https://www.googleapis.com/auth/youtube.upload'}
        self.service._yt_token = lambda channel: ({'Authorization': 'Bearer t'}, granted)
        # on YouTube: scheduled, embedding allowed, a licence chosen by the owner; only the visibility may change
        on_youtube = {'items': [{'status': {'privacyStatus': 'private', 'publishAt': '2026-11-19T01:00:00Z', 'embeddable': True,
                                            'license': 'creativeCommon', 'publicStatsViewable': True, 'uploadStatus': 'processed'}}]}
        self.service._request = lambda method, url, **kw: (sent.append((method, kw.get('params'), kw.get('json'))),
                                                           type('R', (), {'json': lambda s: on_youtube if method == 'GET' else {'status': {'privacyStatus': 'public'}}})())[1]
        with self.assertRaisesRegex(PublishBlocked, 'kết nối lại kênh YouTube'):
            self.service.publish_now(row['id'])       # the channel was connected before the new permission
        self.assertEqual(sent, [])
        granted.add('https://www.googleapis.com/auth/youtube')
        done = self.service.publish_now(row['id'])
        self.assertEqual(sent[-1], ('PUT', {'part': 'status'}, {'id': 'abc123', 'status': {
            'privacyStatus': 'public', 'embeddable': True, 'license': 'creativeCommon', 'publicStatsViewable': True,
            'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': True}}))   # chapters 2 and 3 lost "embeddable" (2026-11-18)
        self.assertEqual(done['state'], 'published')
        with self.assertRaises(ValueError):
            self.service.publish_now(row['id'])

    def test_reschedule_moves_the_youtube_time_then_the_calendar(self):
        row = self.schedule()
        self.service._save(row['id'], state='scheduled_remote', remote_id='abc123')
        sent = []
        self.service._yt_token = lambda channel: ({}, {'https://www.googleapis.com/auth/youtube'})
        on_youtube = {'items': [{'status': {'privacyStatus': 'private', 'publishAt': 'old', 'embeddable': False}}]}
        self.service._request = lambda method, url, **kw: (sent.append(kw.get('json')), type('R', (), {'json': lambda s: on_youtube if method == 'GET' else {'status': {'publishAt': 'x'}}})())[1]
        at = self.now + 7200
        self.assertEqual(self.service.reschedule(row['id'], at)['publish_at'], datetime.fromtimestamp(at, timezone.utc).isoformat().replace('+00:00', 'Z'))
        status = sent[-1]['status']
        self.assertEqual((status['privacyStatus'], status['embeddable']), ('private', False))   # the owner's choice is kept
        self.assertEqual(status['publishAt'], datetime.fromtimestamp(at, timezone.utc).isoformat().replace('+00:00', 'Z'))
        with self.assertRaises(ValueError):
            self.service.reschedule(row['id'], self.now + 60)   # too close

    def test_a_facebook_video_longer_than_a_reel_is_posted_as_a_page_video(self):
        """Reels of 3–16 minutes sent through the Reels API got 0 views; by hand they were normal videos (2026-11-18)."""
        import io
        from contextlib import contextmanager
        data = b'x' * 2500
        @contextmanager
        def source(row, save=None):
            yield io.BytesIO(data), len(data)
        self.service.upload_source = source
        calls, saved = [], []
        def answer(method, url, **kw):
            calls.append((url, dict(kw.get('data') or {})))
            phase = (kw.get('data') or {}).get('upload_phase')
            body = {'start': {'video_id': '555', 'upload_session_id': 'up1', 'start_offset': '0', 'end_offset': '1000'},
                    'transfer': {'start_offset': str(min(int(kw['data']['start_offset']) + 1000, 2500)),
                                 'end_offset': str(min(int(kw['data']['start_offset']) + 2000, 2500))} if phase == 'transfer' else {},
                    'finish': {'success': True}}.get(phase, {})
            return type('R', (), {'json': lambda s: body})()
        self.service._request = answer
        row = {'path': 'p', 'job_id': 'job', 'title': 'Tiêu đề', 'caption': 'Lời đăng'}
        channel = {'credentials': {'page_id': '9', 'access_token': 't'}}
        self.service._video_seconds = lambda row: 403.0
        result = self.service.upload_facebook(row, channel, lambda **c: saved.append(c))
        self.assertEqual([c[1]['upload_phase'] for c in calls], ['start', 'transfer', 'transfer', 'transfer', 'finish'])
        self.assertTrue(all(c[0] == 'https://graph-video.facebook.com/v24.0/9/videos' for c in calls))
        self.assertEqual((calls[-1][1]['published'], calls[-1][1]['title'], calls[-1][1]['description']), ('true', 'Tiêu đề', 'Lời đăng'))
        self.assertEqual((result['phase'], result['remote_id'], result['remote_url']), ('video-finished', '555', 'https://www.facebook.com/9/videos/555'))
        self.assertIn({'remote_id': '555', 'phase': 'video-created'}, saved)
        # its status: published once Facebook has processed it
        reply = {'status': {'video_status': 'processing'}, 'published': True}
        self.service._request = lambda method, url, **kw: type('R', (), {'json': lambda s: reply})()
        polled = {'remote_id': '555', 'platform': 'facebook', 'phase': 'video-finished'}
        self.assertEqual(self.service.poll_remote(polled, channel), {'state': 'processing'})
        reply = {'status': {'video_status': 'ready'}, 'published': True}
        self.assertEqual(self.service.poll_remote(polled, channel)['state'], 'published')
        # a short one stays a Reel
        self.service._video_seconds = lambda row: 75.0
        self.service._upload_facebook = lambda *a: {'phase': 'reel'}
        self.assertEqual(self.service.upload_facebook(row, channel, lambda **c: None), {'phase': 'reel'})

    def test_a_server_hiccup_while_checking_a_sent_post_is_asked_again_later(self):
        """Chapter 4 was marked blocked for good after one HTTP 500 from Google while checking it (2026-11-17)."""
        row = self.schedule()
        self.assertTrue(self.service.tick())                    # sent: scheduled_remote
        self.service.client = type('C', (), {'request': lambda s, *a, **k: httpx.Response(500, json={})})()
        self.service._yt_headers = lambda channel: {}
        self.now += 120
        self.service.tick()
        current = self.service.get_schedule(row['id'])
        self.assertEqual(current['state'], 'scheduled_remote')
        self.assertIn('lỗi tạm thời', current['error'])
        self.assertFalse(self.service.tick())                   # not asked again at once
        self.now += 301
        self.assertTrue(self.service.tick())                    # asked again five minutes later

    def test_publish_now_sends_a_waiting_facebook_post_at_once(self):
        self.service.save_channel('facebook:1', 'facebook', 'Page', {'access_token': 'page-secret', 'page_id': '1'})
        row = self.schedule(channel_id='facebook:1')
        self.service.adapters['facebook'] = lambda row, channel, save: dict(state='processing', remote_id='fb1')
        self.assertFalse(self.service.tick())          # its time has not come
        self.service.publish_now(row['id'])
        self.assertTrue(self.service.tick())
        self.assertEqual(self.service.get_schedule(row['id'])['remote_id'], 'fb1')

    def test_platform_refusals_say_what_the_platform_said(self):
        def answer(status, reason):
            body = {'error': {'errors': [{'reason': reason}], 'message': 'The user has exceeded the number of videos they may upload.'}}
            self.service.client = type('C', (), {'request': lambda s, *a, **k: httpx.Response(status, json=body)})()
        answer(400, 'uploadLimitExceeded')
        with self.assertRaisesRegex(PublishBlocked, 'hết lượt tải video'):
            self.service._request('POST', 'https://x')
        answer(403, 'quotaExceeded')
        with self.assertRaisesRegex(PublishBlocked, 'hạn mức gọi YouTube API'):
            self.service._request('POST', 'https://x')
        answer(400, 'invalidTitle')
        with self.assertRaisesRegex(PublishBlocked, 'HTTP 400, invalidTitle'):
            self.service._request('POST', 'https://x')

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

    def test_scheduled_video_deleted_in_youtube_studio_ends_the_schedule(self):
        """The tool may only upload; the owner deletes a scheduled video in Studio and the schedule is then gone (2026-11-17)."""
        row = self.schedule()
        self.assertTrue(self.service.tick())
        self.service._yt_headers = lambda channel: {}
        found = {'items': [{'status': {'privacyStatus': 'private', 'publishAt': 'x', 'uploadStatus': 'processed'}}]}
        self.service._request = lambda *args, **kwargs: type('R', (), {'json': lambda s: found})()
        self.assertEqual(self.service.reconcile(row['id'])['state'], 'scheduled_remote')
        # One empty answer is not enough: chapter 2 was dropped two minutes after its upload, then uploaded again (2026-11-17).
        found = {'items': []}
        first = self.service.reconcile(row['id'])
        self.assertEqual((first['state'], first['phase']), ('scheduled_remote', 'missing'))
        self.assertIn('10 phút', first['error'])
        self.assertEqual(self.service.reconcile(row['id'])['state'], 'scheduled_remote')  # asked again at once: still kept
        self.assertFalse(self.service.tick())  # the worker waits the ten minutes too
        found = {'items': [{'status': {'privacyStatus': 'private', 'publishAt': 'x', 'uploadStatus': 'processed'}}]}
        back = self.service.reconcile(row['id'])
        self.assertEqual((back['state'], back['phase'], back['error']), ('scheduled_remote', 'uploaded', None))
        found = {'items': []}
        self.service.reconcile(row['id'])
        self.now += 601
        self.assertTrue(self.service.tick())
        after = self.service.get_schedule(row['id'])
        self.assertEqual((after['state'], after['error']), ('cancelled', 'Video đã bị xóa trên YouTube; lịch này đã gỡ'))
        # a video that was never seen scheduled is not taken for deleted
        with self.assertRaises(PublishUncertain):
            self.service.poll_remote({'remote_id': 'x', 'platform': 'youtube', 'state': 'processing'}, {'credentials': {}})

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

    def youtube_http(self, calls, upload_status=201):
        def http(method, url, **kwargs):
            calls.append((method, kwargs))
            if method == 'POST':
                return httpx.Response(200, headers={'Location': 'https://www.googleapis.com/upload/session'})
            return httpx.Response(upload_status, json={'id': 'vid'})
        return http

    def test_youtube_upload_sends_title_and_tags(self):
        row = self.schedule(title='Chương 1: Cánh cổng', tags=['truyện audio', '#ngôn tình', 'truyện audio'])
        raw = self.service._raw_schedule(row['id'])
        self.service._yt_headers = lambda channel: {'Authorization': 'Bearer fixture'}
        calls = []
        self.service._request = self.youtube_http(calls)
        self.service.upload_youtube(raw, self.service.channel('youtube:one'), lambda **kw: None)
        snippet = calls[0][1]['json']['snippet']
        self.assertEqual((snippet['title'], snippet['tags']), ('Chương 1: Cánh cổng', ['truyện audio', 'ngôn tình']))
        self.assertTrue(calls[0][1]['json']['status']['containsSyntheticMedia'])  # AI label is on unless switched off
        self.service.cancel(row['id'])
        untagged = self.service.create_schedule(dict(job_id='job', version_id='v1', channel_id='youtube:one', title='B', caption='',
                                                     publish_at=datetime.fromtimestamp(self.now+7200, timezone.utc).isoformat()), 'other-key')
        self.assertEqual(json.loads(self.service._raw_schedule(untagged['id'])['tags']), [])
        self.service.cancel(untagged['id'])
        plain = self.service.create_schedule(dict(job_id='job', version_id='v1', channel_id='youtube:one', title='C', caption='', ai_label=False,
                                                  publish_at=datetime.fromtimestamp(self.now+9000, timezone.utc).isoformat()), 'third-key')
        calls.clear()
        self.service.upload_youtube(self.service._raw_schedule(plain['id']), self.service.channel('youtube:one'), lambda **kw: None)
        self.assertFalse(calls[0][1]['json']['status']['containsSyntheticMedia'])

    def test_video_on_drive_is_downloaded_checked_posted_and_removed(self):
        import hashlib
        from unittest import mock
        from videostudio.drive_storage import DriveStorage
        DriveStorage(self.store)  # creates the drive tables
        wide = b'wide-video-on-drive'
        with self.store.db() as db:
            for name, data in (('ep_doc.mp4', b'tall'), ('ep_ngang.mp4', wide)):
                db.execute('INSERT INTO drive_files(job_id,kind,name,local_path,account,file_id,size,md5,uploaded,local_deleted) VALUES(?,?,?,?,?,?,?,?,?,1)',
                           ('job', name, name, str(self.root / name), 'a@x', 'id-' + name, len(data), hashlib.md5(data).hexdigest(), 1))
        self.versions.record = dict(self.versions.record, version_id='drive-abc', path=str(self.root / 'ep_doc.mp4'))
        row = self.schedule(version_id='drive-abc')
        raw = self.service._raw_schedule(row['id'])
        self.assertEqual(raw['path'], 'drive:job/ep_ngang.mp4')  # YouTube gets the landscape copy
        fetched = []

        def download(self_, file_id, target, check=None, account=None, progress=None):
            fetched.append((file_id, account, Path(target)))
            Path(target).write_bytes(wide)
        self.service._yt_headers = lambda channel: {'Authorization': 'Bearer fixture'}
        calls = []
        self.service._request = self.youtube_http(calls)
        with mock.patch.object(DriveStorage, 'download', download):
            result = self.service.upload_youtube(raw, self.service.channel('youtube:one'), lambda **kw: None)
        self.assertEqual(result['remote_id'], 'vid')
        self.assertEqual(calls[1][1]['content'], wide)
        self.assertEqual(fetched[0][:2], ('id-ep_ngang.mp4', 'a@x'))
        self.assertFalse(fetched[0][2].exists())  # the temporary copy is gone
        with mock.patch.object(DriveStorage, 'download', lambda *a, **k: Path(a[2]).write_bytes(b'other')):
            with self.assertRaises(PublishBlocked):
                self.service.upload_youtube(dict(raw, upload_url=None), self.service.channel('youtube:one'), lambda **kw: None)

    def test_default_channel_per_kind_and_removing_a_channel(self):
        self.service.save_channel('youtube:two', 'youtube', 'Story channel', {'refresh_token': 'x'})
        self.service.save_channel('facebook:9', 'facebook', 'Page', {'access_token': 'x', 'page_id': '9'})
        self.service.set_default_channels({'case': {'youtube': 'youtube:one', 'facebook': 'facebook:9'},
                                           'story': {'youtube': 'youtube:two', 'facebook': ''}, 'news': {}})
        self.assertEqual(self.service.channels()['defaults'],
                         {'case': {'youtube': 'youtube:one', 'facebook': 'facebook:9'}, 'story': {'youtube': 'youtube:two'}})
        for wrong in ({'story': {'youtube': 'youtube:missing'}}, {'story': {'facebook': 'youtube:two'}}, {'story': 'youtube:two'}):
            with self.assertRaises(ValueError):
                self.service.set_default_channels(wrong)
        with self.service.store.db() as db:  # the older one-channel-per-kind setting still reads
            db.execute("INSERT OR REPLACE INTO publishing_settings VALUES('default_channels',?)", (json.dumps({'case': 'youtube:one'}),))
        self.assertEqual(self.service.default_channels(), {'case': {'youtube': 'youtube:one'}})
        self.service.set_default_channels({'case': {'youtube': 'youtube:one'}, 'story': {'youtube': 'youtube:two'}})
        row = self.schedule()  # on youtube:one, not posted yet
        with self.assertRaises(ValueError):
            self.service.remove_channel('youtube:one')
        self.service.cancel(row['id'])
        self.service.remove_channel('youtube:one')
        self.assertEqual(self.service.channels()['defaults'], {'story': {'youtube': 'youtube:two'}})
        self.assertNotIn('youtube:one', [c['id'] for c in self.service.channels()['items']])
        with self.assertRaises(KeyError):
            self.service.remove_channel('youtube:one')

    def test_facebook_reels_report_views_checks_and_low_ones(self):
        def handler(request):
            path = request.url.path
            if path.endswith('/video_insights'):
                return httpx.Response(403, json={'error': {'message': 'read_insights permission missing'}})
            if path.endswith('/video_reels'):
                old = '2020-01-0{}T00:00:00+0000'
                data = [{'id': str(n), 'description': caption, 'created_time': old.format(n), 'permalink_url': f'/reel/{n}/', 'views': views,
                         'post_views': 1, 'length': 60.0, 'status': {'publishing_phase': {'publish_status': 'published'},
                                                                     'copyright_check_status': {'status': 'complete', 'matches_found': n == 2}},
                         'comments': {'summary': {'total_count': 3}}, 'likes': {'summary': {'total_count': 4}}}
                        for n, views, caption in [(1, 500, 'Một căn phòng khóa kín.'), (2, 400, 'Cô ấy tự tử.'), (3, 450, 'Bí ẩn'),
                                                  (4, 30, 'THITHỂ trong chuồng'), (5, 480, 'Lá thư')]]
                return httpx.Response(200, json={'data': data})
            return httpx.Response(200, json={'name': 'Trang', 'followers_count': 7})
        service = Publishing(self.store, self.versions, clock=lambda: self.now, client=httpx.Client(transport=httpx.MockTransport(handler)))
        service.save_channel('facebook:9', 'facebook', 'Trang', {'access_token': 'x', 'page_id': '9'})
        result = service.facebook_reels('facebook:9')
        self.assertEqual((result['page'], result['insights']), ({'name': 'Trang', 'followers': 7}, False))
        by_id = {item['id']: item for item in result['items']}
        self.assertEqual(by_id['1']['url'], 'https://www.facebook.com/reel/1/')
        self.assertEqual((by_id['1']['comments'], by_id['1']['likes'], by_id['1']['check']['verdict']), (3, 4, 'safe'))
        self.assertEqual((by_id['2']['copyright'], by_id['2']['check']['verdict']), ('match', 'fix'))
        self.assertEqual(by_id['4']['check']['issues'][0]['kind'], 'masked')
        self.assertEqual([i for i in by_id if by_id[i]['low']], ['4'])
        with self.assertRaises(ValueError):
            service.facebook_reels('youtube:one')

    def test_facebook_reel_is_finished_once_the_upload_is_complete(self):
        self.service.save_channel('facebook:1','facebook','Page',{'access_token':'secret','page_id':'1'})
        row=self.schedule(channel_id='facebook:1')
        self.now+=3601
        self.service._save(row['id'],state='processing',phase='uploaded',remote_id='123')
        calls=[]
        def http(method,url,**kwargs):
            calls.append(method)
            if method=='GET':  # what Facebook really answers before "finish": processing has not started
                return httpx.Response(200,json={'status':{'video_status':'upload_complete','uploading_phase':{'status':'complete'},
                                                          'processing_phase':{'status':'not_started'},'publishing_phase':{'status':'not_started'}}})
            return httpx.Response(200,json={'success':True})
        self.service._request=http
        changes=self.service.poll_remote(self.service._raw_schedule(row['id']),self.service.channel('facebook:1'))
        self.assertEqual(calls,['GET','POST'])
        self.assertEqual(changes,{'state':'processing','phase':'finished'})


if __name__ == '__main__':
    unittest.main()
