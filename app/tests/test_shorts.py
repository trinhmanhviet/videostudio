import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from videostudio import shorts
from videostudio.core import Store, digest
from videostudio.publishing import Publishing

JOB = '11111111-2222-3333-4444-555555555555'
SRT = '\n\n'.join(f'{i + 1}\n00:{(i * 6) // 60:02d}:{(i * 6) % 60:02d},000 --> 00:{(i * 6 + 5) // 60:02d}:{(i * 6 + 5) % 60:02d},500\nCâu số {i}.'
                  for i in range(40))


class Versions:
    def approved_version(self, job_id):
        return {'version_id': 'v1', 'path': 'x', 'sha256': 's'} if job_id == JOB else None


class ShortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root / 'shorts'
        self.store = Store(root / 'jobs.sqlite3', root / 'out')
        out = root / 'out' / JOB
        out.mkdir(parents=True)
        (out / 'story-doc.srt').write_text(SRT, encoding='utf-8')
        (out / 'video_doc.mp4').write_bytes(b'full video')
        self.now = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc).timestamp()
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,idem,request,state,output,created,updated) VALUES(?,?,?,?,?,?,?)',
                       (JOB, JOB, json.dumps({'idea': 'Vụ án quán bar'}), 'completed', str(out), 1, 1))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)', (JOB, 'render', json.dumps({'video': str(out / 'video_doc.mp4')})))
        self.cuts = []

        def cutter(source, start, end, target):
            self.cuts.append((Path(source).name, start, end))
            Path(target).write_bytes(b'short video')
            return round(end - start, 2)
        self.cutter = cutter

    def tearDown(self):
        self.tmp.cleanup()

    def test_subtitles_are_read_with_their_times(self):
        cues = shorts.parse_srt(SRT)
        self.assertEqual(len(cues), 40)
        self.assertEqual(cues[1], (6.0, 11.5, 'Câu số 1.'))

    def test_chatgpt_picks_the_stretch_and_a_bad_answer_takes_the_opening(self):
        cues = shorts.parse_srt(SRT)
        start, end, title, how = shorts.choose(cues, 'Vụ án', lambda prompt: {'tu': 10, 'den': 21, 'tieu_de': '18 giây định mệnh'})
        self.assertEqual((round(start, 2), how, title), (59.85, 'chatgpt', '18 giây định mệnh'))
        self.assertTrue(shorts.SHORT_MIN - 5 <= end - start <= shorts.SHORT_MAX)
        for bad in ({'tu': 0, 'den': 2}, {'tu': 30, 'den': 99}, {}, None):   # too short, out of range, nothing
            start, end, title, how = shorts.choose(cues, 'Vụ án', lambda prompt, bad=bad: bad)
            self.assertEqual((start, how, title), (0.0, 'opening', 'Vụ án'))
            self.assertTrue(shorts.SHORT_MIN <= end <= shorts.FALLBACK + 1)

    def test_the_short_is_made_once_and_kept(self):
        made = shorts.make(self.store, JOB, ask=lambda p: {'tu': 5, 'den': 16, 'tieu_de': 'Cú đấm 18 giây'}, root=self.root, cutter=self.cutter)
        again = shorts.make(self.store, JOB, ask=lambda p: self.fail('asked twice'), root=self.root, cutter=self.cutter)
        self.assertEqual(len(self.cuts), 1)
        self.assertEqual(self.cuts[0][0], 'video_doc.mp4')
        self.assertEqual((made['title'], again['sha256']), ('Cú đấm 18 giây', made['sha256']))
        with self.assertRaises(ValueError):
            shorts.load('../x', root=self.root)

    def test_the_short_is_scheduled_as_its_own_post_and_the_full_video_stays_unposted(self):
        publishing = Publishing(self.store, Versions(), clock=lambda: self.now)
        publishing.save_channel('youtube:yt', 'youtube', 'Kênh', {'refresh_token': 'x'})
        publishing.save_channel('facebook:9', 'facebook', 'Trang', {'access_token': 'x', 'page_id': '9'})
        original = shorts.ROOT
        shorts.ROOT = self.root
        try:
            record = shorts.make(self.store, JOB, ask=lambda p: {'tu': 5, 'den': 16, 'tieu_de': 'Cú đấm'}, cutter=self.cutter)
            ids, problems = shorts.schedule(self.store, publishing, Versions(), JOB, ['youtube:yt', 'facebook:9'], self.now + 3600, record=record)
            self.assertEqual(problems, [])
            youtube, facebook = (publishing._raw_schedule(i) for i in ids)
            self.assertEqual((youtube['cut'], youtube['title'], youtube['path']), ('short', 'Cú đấm #shorts', str(self.root / JOB / 'short.mp4')))
            self.assertEqual((facebook['title'], facebook['sha256']), ('Cú đấm', digest(self.root / JOB / 'short.mp4')))
            self.assertIn('Bản đầy đủ có trên kênh', facebook['caption'])
            self.assertEqual(publishing._video_seconds(facebook), record['seconds'])   # its own length: posted as a Reel
        finally:
            shorts.ROOT = original
        # the plan still sees the full video as not posted
        with self.store.db() as db:
            posted = [r[0] for r in db.execute("SELECT job_id FROM publishing_schedules WHERE state!='cancelled' AND cut=''")]
        self.assertEqual(posted, [])

    def test_maker_waits_for_the_gpu_and_flags_a_short_that_does_well(self):
        publishing = Publishing(self.store, Versions(), clock=lambda: self.now)
        sent = []
        maker = shorts.ShortMaker(self.store, publishing, Versions(), notify=sent.append, clock=lambda: self.now, root=self.root)
        made = []
        original = shorts.schedule
        shorts.schedule = lambda *a, **k: (made.append(a[3]), (['sch-1'], []))[1]
        try:
            maker.request(JOB, ['facebook:9'], self.now + 7200)
            maker.request(JOB, ['facebook:9'], self.now + 7200)      # asked twice: one request
            with self.store.db() as db:
                db.execute("UPDATE jobs SET state='running' WHERE id=?", (JOB,))
            maker.tick()
            self.assertEqual(made, [])                               # a video is being made: wait
            with self.store.db() as db:
                db.execute("UPDATE jobs SET state='completed' WHERE id=?", (JOB,))
            self.assertTrue(maker.tick())
            self.assertEqual(made, [JOB])
            self.assertEqual(maker.requests()[0]['state'], 'done')
        finally:
            shorts.schedule = original
        # a day later the short has 3x the channel's usual views: flagged once
        publishing.save_channel('facebook:9', 'facebook', 'Trang', {'access_token': 'x', 'page_id': '9'})
        with self.store.db() as db:
            db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,remote_id,created,updated,cut)"
                       " VALUES('sch-1','k','f',?,'v1','facebook:9','facebook','Cú đấm','c',1,'p','s','published','fb77',1,?,'short')", (JOB, self.now))
        publishing.facebook_reels = lambda channel, *a: {'median_views': 200, 'items': [{'id': 'fb77', 'views': 640}]}
        maker.last_check = 0
        self.now += shorts.FLAG_AGE + 60
        self.assertEqual(len(maker.check()), 1)
        self.assertEqual(maker.check(), [])
        self.assertIn('Nên tự đăng Reel bản đầy đủ', sent[0])
        self.assertEqual(maker.flags()['fb77']['views'], 640)


if __name__ == '__main__':
    unittest.main()
