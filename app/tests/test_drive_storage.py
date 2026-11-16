import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import drive_storage
from videostudio.core import Store
from videostudio.drive_storage import DriveError, DriveStorage, file_id_from_link


class DriveStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'jobs.sqlite3', Path(self.tmp.name) / 'out')
        self.drive = DriveStorage(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_are_parsed_and_other_hosts_refused(self):
        file_id = '1AbCdEfGhIjKlMnOpQrStUvWxYz012345'
        for link in (f'https://drive.google.com/file/d/{file_id}/view?usp=sharing', f'https://drive.google.com/open?id={file_id}', file_id):
            self.assertEqual(file_id_from_link(link), file_id)
        with self.assertRaises(ValueError):
            file_id_from_link(f'https://www.youtube.com/watch?v={file_id}')

    def test_first_account_with_room_is_used_then_the_next(self):
        with self.store.db() as db:
            db.execute("INSERT INTO drive_accounts VALUES('a@x','a@x','t',0,0,0)")
            db.execute("INSERT INTO drive_accounts VALUES('b@x','b@x','t',1,0,0)")
        free = {'a@x': 10 * 2**30, 'b@x': 100 * 2**30}
        with patch.object(DriveStorage, 'quota', lambda self, account: {'free': free[account], 'limit': 1, 'usage': 0}):
            self.assertEqual(self.drive.pick_account(1 * 2**30), 'a@x')
            free['a@x'] = 2 * 2**30  # nearly full: keep the safety margin
            self.assertEqual(self.drive.pick_account(1 * 2**30), 'b@x')
            free['b@x'] = 0
            with self.assertRaises(DriveError):
                self.drive.pick_account(1 * 2**30)

    def test_metadata_asks_each_account_by_its_id_and_skips_disabled_ones(self):
        # 2026-11-16: the whole account row went to _headers, so "fetch the clip again from Drive" failed with
        # "unhashable type: 'dict'" and the rebuild of a chapter stopped.
        with self.store.db() as db:
            db.execute("INSERT INTO drive_accounts VALUES('off@x','off@x','t',0,0,1)")
            db.execute("INSERT INTO drive_accounts VALUES('a@x','a@x','t',1,0,0)")
            db.execute("INSERT INTO drive_accounts VALUES('b@x','b@x','t',2,0,0)")
        asked = []

        class Response:
            def __init__(self, status):
                self.status_code = status

            def json(self):
                return {'id': 'F', 'name': 'clip.mp4'}

        def get(url, headers, **kwargs):
            asked.append(headers['Authorization'])
            return Response(200 if headers['Authorization'] == 'Bearer b@x' else 404)
        with patch.object(DriveStorage, 'token', lambda self, account: account), patch.object(drive_storage.httpx, 'get', get):
            self.assertEqual(self.drive.metadata('F'), ('b@x', {'id': 'F', 'name': 'clip.mp4'}))
        self.assertEqual(asked, ['Bearer a@x', 'Bearer b@x'])

    def test_cache_trim_removes_oldest_beyond_limit_but_keeps_files_in_use(self):
        cache = Path(self.tmp.name) / 'cache'
        cache.mkdir()
        files = []
        for index in range(3):
            path = cache / f'clip{index}.mp4'
            path.write_bytes(b'x' * 100)
            files.append(path)
        with patch.object(drive_storage, 'CACHE', cache), patch.object(drive_storage, 'CACHE_LIMIT', 150):
            drive_storage.cache_trim(keep=[files[0]])
        self.assertTrue(files[0].exists())
        self.assertEqual(sum(p.exists() for p in files), 1)

    def test_upload_reports_progress_while_sending(self):
        source = Path(self.tmp.name) / 'v.mp4'
        source.write_bytes(b'a' * (3 * 1024 * 1024 + 5))
        seen, sent = [], bytearray()

        class Response:
            def __init__(self, status, headers=None, body=None):
                self.status_code, self.headers, self._body, self.text = status, headers or {}, body, ''

            def json(self):
                return self._body

        def put(url, content=None, **kwargs):
            sent.extend(b''.join(content) if not isinstance(content, bytes) else content)
            return Response(200, body={'id': 'f1', 'size': str(len(sent)), 'md5Checksum': drive_storage.local_md5(source)})
        with patch.object(drive_storage.httpx, 'post', lambda *a, **k: Response(200, {'location': 'https://upload/s'})), \
                patch.object(drive_storage.httpx, 'put', put), patch.object(DriveStorage, '_headers', lambda self, account: {}):
            result = self.drive.upload('a@x', source, 'folder', progress=seen.append)
        self.assertEqual(bytes(sent), source.read_bytes())
        self.assertEqual(result['id'], 'f1')
        self.assertEqual(seen[-1], source.stat().st_size)
        self.assertEqual(seen, sorted(seen))
        self.assertGreaterEqual(len(seen), 4)  # moves about every megabyte, not once per 64 MB part

    def test_sync_publishes_live_progress_then_a_summary(self):
        import json as _json
        import time as _time
        from types import SimpleNamespace
        from fastapi import FastAPI
        from videostudio import drive_api
        out = Path(self.tmp.name) / 'videos'
        out.mkdir()
        files = {'j1': [out / 'a_doc.mp4', out / 'a_ngang.mp4'], 'j2': [out / 'b_doc.mp4']}
        for paths in files.values():
            for path in paths:
                path.write_bytes(b'v' * 2048)
        now = _time.time()
        with self.store.db() as db:
            db.execute("INSERT INTO drive_accounts VALUES('a@x','a@x','t',0,0,0)")
            db.execute('CREATE TABLE IF NOT EXISTS factory_batches(id TEXT, style TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS factory_items(job_id TEXT, batch_id TEXT)')
            for job_id in files:
                db.execute('INSERT INTO jobs(id,idem,request,state,output,created,updated) VALUES(?,?,?,?,?,?,?)',
                           (job_id, job_id, _json.dumps({'project': 'Truyện', 'title': 'Chương ' + job_id}), 'completed', str(out), now, now))
        self.drive.set_setting('include_old', True)
        snapshots = []
        app = FastAPI()

        def upload(self, account, path, folder, check=None, progress=None):
            progress(1024)
            snapshots.append(_json.loads(_json.dumps(routes['progress']())))
            progress(path.stat().st_size)
            return {'id': path.name, 'size': str(path.stat().st_size), 'md5Checksum': drive_storage.local_md5(path)}
        real_get = self.store.get
        fake_get = lambda job_id: {**real_get(job_id), 'checkpoints': {'verify': {'verified': True}}}
        with patch.object(DriveStorage, 'pick_account', lambda self, size: 'a@x'), patch.object(DriveStorage, 'folder', lambda self, a, parts: 'F'), \
                patch.object(DriveStorage, 'upload', upload), patch.object(self.store, 'get', fake_get), \
                patch('videostudio.output_layout.job_deliverables', lambda job: files[job['id']]):
            drive_api.register_drive_routes(app, self.store, SimpleNamespace(), lambda request: None, background=False)
            routes = {r.name: r.endpoint for r in app.routes if hasattr(r, 'endpoint')}
            routes['sync_now'](SimpleNamespace())
            for _ in range(200):
                if routes['progress']()['result']:
                    break
                _time.sleep(0.02)
        first = snapshots[0]
        self.assertTrue(first['running'])
        self.assertEqual((first['phase'], first['jobs_total'], first['bytes_total']), ('upload', 2, 3 * 2048))
        self.assertEqual((first['file']['name'], first['file']['index'], first['file']['count'], first['file']['done']), ('a_doc.mp4', 1, 2, 1024))
        self.assertEqual(first['file']['job'], 'Chương j1')
        self.assertEqual(snapshots[2]['bytes_done'], 2 * 2048 + 1024)  # second video starts after both files of the first
        done = routes['progress']()
        self.assertFalse(done['running'])
        self.assertEqual(done['result']['uploaded'], 2)
        self.assertEqual(done['result']['bytes'], 3 * 2048)
        self.assertEqual([r['job'] for r in done['recent']], ['Chương j2', 'Chương j1'])
        self.assertFalse(any(p.exists() for paths in files.values() for p in paths))  # deleted after the match

    def test_posted_videos_go_to_drive_trash_only_when_switched_on_and_all_posts_are_public(self):
        from types import SimpleNamespace
        from fastapi import FastAPI
        from videostudio import drive_api
        from videostudio.publishing import Publishing
        Publishing(self.store, None)  # creates the schedule table
        with self.store.db() as db:
            for job in ('done', 'waiting'):
                db.execute("INSERT INTO drive_files(job_id,kind,name,local_path,account,file_id,size,md5,uploaded,local_deleted) VALUES(?,?,?,?,?,?,?,?,?,1)",
                           (job, 'v.mp4', 'v.mp4', 'x', 'a@x', 'file-' + job, 1, 'm', 1))
            rows = [('s1', 'done', 'published'), ('s2', 'waiting', 'published'), ('s3', 'waiting', 'scheduled_remote')]
            for sid, job, state in rows:
                db.execute("""INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,path,sha256,channel_id,platform,title,caption,
                              publish_at,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (sid, sid, 'f', job, 'v', 'p', 's', 'c', 'youtube', 't', '', 1, state, 1, 1))
        trashed = []
        with patch.object(DriveStorage, 'trash', lambda self, account, file_id: trashed.append(file_id) or True):
            drive = drive_api.register_drive_routes(FastAPI(), self.store, SimpleNamespace(), lambda request: None, background=False)
            self.assertEqual(drive.trash_posted(), 0)  # switch off by default
            drive.set_setting('delete_after_post', True)
            self.assertEqual(drive.trash_posted(), 1)
            self.assertEqual(drive.trash_posted(), 0)  # never twice
        self.assertEqual(trashed, ['file-done'])  # "waiting" still has a post YouTube has not made public


if __name__ == '__main__':
    unittest.main()
