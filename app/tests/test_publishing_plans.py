import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from videostudio import social_copy
from videostudio.core import Store
from videostudio.publishing import Publishing
from videostudio.publishing_plans import CASE_NOTE, VN, PostingPlans, captions


class FakeFactory:
    def __init__(self):
        self.approved = []

    def get_video_version(self, job_id):
        return {'version_id': 'v-' + job_id, 'sha256': 's-' + job_id}

    def approve(self, job_id, version_id, sha256):
        self.approved.append(job_id)


class PostingPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / 'jobs.sqlite3', root / 'out')
        # Sunday 15/11/2026 08:00 Vietnam time
        self.now = datetime(2026, 11, 15, 8, 0, tzinfo=VN).timestamp()
        self.publishing = Publishing(self.store, None, clock=lambda: self.now)
        self.publishing.save_channel('youtube:yt', 'youtube', 'Tôi Đọc Truyện', {'refresh_token': 'x'})
        self.publishing.save_channel('facebook:9', 'facebook', 'Trang', {'access_token': 'x', 'page_id': '9'})
        self.made = []
        self.publishing.create_schedule = lambda body, key: (self.made.append((body, key)), {'id': 'sch-%d' % len(self.made)})[1]
        self.factory = FakeFactory()
        self.plans = PostingPlans(self.store, self.publishing, self.factory, clock=lambda: self.now)
        with self.store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS factory_batches(id TEXT, idem TEXT, fingerprint TEXT, scope TEXT, project TEXT, style TEXT,
                                    input_mode TEXT, defaults TEXT, created REAL, updated REAL);
                                CREATE TABLE IF NOT EXISTS factory_items(id TEXT, batch_id TEXT, position INTEGER, title TEXT, content TEXT,
                                    request TEXT, idem TEXT, job_id TEXT, state TEXT)''')
        for order, name in [(3, 'c3'), (1, 'c1'), (2, 'c2')]:
            self.job(name, 'story', 'Trọng Sinh', order)
        self.job('mp3', 'story', 'Trọng Sinh', 0, audio_only=True)
        self.job('case1', 'case', 'Vụ án', None)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, job_id, style, project, order, audio_only=False):
        output = Path(self.tmp.name, 'out', job_id)
        output.mkdir(parents=True)
        if order is not None:
            (output / 'story-snapshot.json').write_text(json.dumps({'chapters': [{'order': order}]}), encoding='utf-8')
        request = {'idea': 'x', 'project': project, 'content_style': style}
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,idem,request,state,output,created,updated) VALUES(?,?,?,?,?,?,?)',
                       (job_id, job_id, json.dumps(request), 'completed', str(output), self.now, self.now))
            db.execute('INSERT INTO factory_batches VALUES(?,?,?,?,?,?,?,?,?,?)', ('b-' + job_id, job_id, 'f', None, project, style, 'idea', '{}', 1, 1))
            db.execute('INSERT INTO factory_items VALUES(?,?,?,?,?,?,?,?,?)', ('i-' + job_id, 'b-' + job_id, 0, 'Tập ' + job_id, '', '{}', job_id, job_id, 'done'))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)', (job_id, 'verify', json.dumps({'verified': True})))
            db.execute('INSERT INTO checkpoints VALUES(?,?,?)', (job_id, 'render', json.dumps({'audio_only': audio_only})))
        social_copy._write(self.store.get(job_id), {'state': 'ready',
                           'youtube': {'title': 'YT ' + job_id, 'description': 'Mô tả.', 'tags': ['truyện audio', 'trọng sinh']},
                           'facebook': {'caption': 'Lời đăng.', 'hashtags': ['#truyenaudio']}})

    def test_story_plan_fills_the_next_slots_in_chapter_order_on_every_channel(self):
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt', 'facebook:9'], 'times': ['19:00']})
        self.assertEqual(plan['waiting'], 3)  # the MP3-only narration is never posted
        self.assertEqual(self.plans.tick(force=True), 2)  # 15/11 and 16/11 19:00 fall inside the next 48 hours
        slots = self.plans.get(plan['id'])['upcoming']
        self.assertEqual([s['job_id'] for s in slots], ['c1', 'c2'])
        youtube, facebook = self.made[0][0], self.made[1][0]
        self.assertEqual((youtube['channel_id'], youtube['title'], youtube['tags']), ('youtube:yt', 'YT c1', ['truyện audio', 'trọng sinh']))
        self.assertEqual(youtube['caption'], 'Mô tả.\n\n#truyệnaudio #trọngsinh')
        self.assertEqual((facebook['channel_id'], facebook['caption'], facebook['tags']), ('facebook:9', 'Lời đăng.\n\n#truyenaudio', []))
        self.assertEqual(datetime.fromisoformat(youtube['publish_at']).astimezone(VN).strftime('%d/%m %H:%M'), '15/11 19:00')
        self.assertTrue(youtube['ai_label'])
        self.assertEqual(self.factory.approved, ['c1', 'c2'])
        self.assertEqual(self.plans.tick(force=True), 0)  # nothing twice
        self.now += 24 * 3600
        self.assertEqual(self.plans.tick(force=True), 1)
        self.assertEqual(self.plans.get(plan['id'])['upcoming'][-1]['job_id'], 'c3')

    def test_case_caption_gets_the_note_and_empty_plans_say_so(self):
        plan = self.plans.save({'style': 'case', 'channels': ['facebook:9'], 'times': ['20:30'], 'days': [6]})  # Sundays only
        self.plans.tick(force=True)
        self.assertIn(CASE_NOTE, self.made[0][0]['caption'])
        self.assertTrue(self.made[0][0]['caption'].endswith('#truyenaudio'))
        self.assertIsNone(self.plans.get(plan['id'])['note'])
        self.now += 7 * 24 * 3600
        self.plans.tick(force=True)
        self.assertIn('Hết video', self.plans.get(plan['id'])['note'])

    def test_validation_and_captions(self):
        for bad in ({'style': 'x', 'channels': ['youtube:yt'], 'times': ['19:00']}, {'style': 'story', 'channels': [], 'times': ['19:00']},
                    {'style': 'story', 'channels': ['youtube:nope'], 'times': ['19:00']}, {'style': 'story', 'channels': ['youtube:yt'], 'times': ['25:00']},
                    {'style': 'story', 'channels': ['youtube:yt'], 'times': ['19:00'], 'days': []}):
            with self.assertRaises(ValueError):
                self.plans.save(bad)
        title, text, tags, fb = captions({'youtube': {'description': 'A #truyenaudio', 'tags': ['truyen audio', 'b']}}, 'story', 'Fallback')
        self.assertEqual((title, text, fb), ('Fallback', 'A #truyenaudio\n\n#b', ''))


if __name__ == '__main__':
    unittest.main()
