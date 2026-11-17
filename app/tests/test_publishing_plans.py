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

    def test_two_renders_of_one_chapter_are_one_episode_and_a_removed_post_frees_it(self):
        """Chapter 1 was rendered twice and the plan posted both on two days (2026-11-17)."""
        for job_id in ('c1', 'c2', 'c3'):
            (Path(self.tmp.name, 'out', job_id) / 'story-snapshot.json').write_text(
                json.dumps({'chapters': [{'id': 'ch-' + job_id, 'order': int(job_id[1])}]}), encoding='utf-8')
        self.job('c1new', 'story', 'Trọng Sinh', 1)
        (Path(self.tmp.name, 'out', 'c1new') / 'story-snapshot.json').write_text(
            json.dumps({'chapters': [{'id': 'ch-c1', 'order': 1}]}), encoding='utf-8')
        with self.store.db() as db:
            db.execute('UPDATE jobs SET created=? WHERE id=?', (self.now + 60, 'c1new'))
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        self.assertEqual([j['id'] for j in self.plans.candidates(self.plans.get(plan['id']))], ['c1new', 'c2', 'c3'])
        # chapter 1 already posted in its old render: no other render of it is posted again
        with self.store.db() as db:
            db.execute("INSERT INTO publishing_plan_slots VALUES(?,?,?,?,?)", ('old-plan', 1.0, 'c1', '["sch-old"]', self.now))
            db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,created,updated)"
                       " VALUES('sch-old','k','f','c1','v','youtube:yt','youtube','t','c',1,'p','s','scheduled_remote',1,1)")
        self.assertEqual([j['id'] for j in self.plans.candidates(self.plans.get(plan['id']))], ['c2', 'c3'])
        # the owner deleted that post on YouTube: the slot is freed and the newest render of chapter 1 comes back
        with self.store.db() as db:
            db.execute("UPDATE publishing_schedules SET state='cancelled' WHERE id='sch-old'")
        self.assertEqual([j['id'] for j in self.plans.candidates(self.plans.get(plan['id']))], ['c1new', 'c2', 'c3'])
        with self.store.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM publishing_plan_slots WHERE plan_id='old-plan'").fetchone())

    def test_a_slot_whose_post_was_removed_is_filled_again_under_a_new_key(self):
        """Chapter 2 was deleted on YouTube; its slot came back with the old cancelled schedule, never a new upload (2026-11-17)."""
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        self.plans.tick(force=True)
        first_key = self.made[0][1]
        with self.store.db() as db:
            db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,created,updated)"
                       " VALUES('sch-1',?,'f','c1','v','youtube:yt','youtube','t','c',1,'p','s','cancelled',1,1)", (first_key,))
            db.execute('UPDATE publishing_plan_slots SET schedule_ids=? WHERE job_id=?', ('["sch-1"]', 'c1'))
        self.made.clear()
        self.assertEqual(self.plans.tick(force=True), 1)
        self.assertEqual((self.made[0][0]['job_id'], self.made[0][1]), ('c1', first_key + ':1'))

    def test_a_chapter_dropped_twice_by_the_channel_stops_the_story_plan(self):
        """YouTube dropped chapter 2 after each upload and the plan uploaded it 7 times overnight (2026-11-17)."""
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        def dropped(n):
            with self.store.db() as db:
                db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,phase,created,updated)"
                           " VALUES(?,?,'f','c1','v','youtube:yt','youtube','t','c',1,'p','s','cancelled','removed',1,1)", (f'gone-{n}', f'k{n}'))
        dropped(1)
        self.assertEqual(self.plans.tick(force=True), 2)  # once: chapter 1 is posted again, then chapter 2
        self.assertEqual([b['job_id'] for b, _ in self.made], ['c1', 'c2'])
        with self.store.db() as db:
            db.execute('DELETE FROM publishing_plan_slots')
        self.made.clear()
        dropped(2)
        self.assertEqual(self.plans.tick(force=True), 0)  # twice: nothing more, not even chapter 2 ahead of it
        self.assertEqual(self.made, [])
        self.assertIn('2 lần', self.plans.get(plan['id'])['note'])

    def test_a_chapter_posted_early_gives_its_slot_to_the_next_chapter(self):
        """Chapters 2 and 3 were posted with Đăng ngay; chapter 4 must take tomorrow's slot, not wait three days (2026-11-17)."""
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        self.assertEqual(self.plans.tick(force=True), 2)  # 15/11 c1, 16/11 c2
        with self.store.db() as db:
            for n, (job_id, at) in enumerate(db.execute('SELECT job_id, slot_at FROM publishing_plan_slots ORDER BY slot_at').fetchall()):
                state, when = ('published', self.now) if job_id == 'c2' else ('scheduled_remote', at)
                db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,created,updated)"
                           " VALUES(?,?,'f',?,'v','youtube:yt','youtube','t','c',?,'p','s',?,1,1)", (f'sch-{n + 1}', f'k{n}', job_id, when, state))
        self.made.clear()
        self.assertEqual(self.plans.tick(force=True), 1)
        self.assertEqual([b['job_id'] for b, _ in self.made], ['c3'])
        upcoming = {s['job_id']: s['slot_at'] for s in self.plans.get(plan['id'])['upcoming']}
        self.assertEqual(datetime.fromtimestamp(upcoming['c3'], VN).strftime('%d/%m %H:%M'), '16/11 19:00')

    def test_a_freed_slot_never_reuses_the_key_of_the_post_that_left_it(self):
        """Chapter 2 posted early left its 18/11 key; chapter 4 got "Idempotency-Key already used" and the plan marked
        all 42 remaining chapters as skipped (2026-11-17)."""
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        self.plans.tick(force=True)
        keys = {b['job_id']: k for b, k in self.made}
        with self.store.db() as db:
            for n, job_id in enumerate(('c1', 'c2')):
                state, when = ('published', self.now) if job_id == 'c2' else ('scheduled_remote', self.now + 3600)
                db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,created,updated)"
                           " VALUES(?,?,'f',?,'v','youtube:yt','youtube','t','c',?,'p','s',?,1,1)", (f'sch-{n + 1}', keys[job_id], job_id, when, state))
                db.execute('UPDATE publishing_plan_slots SET schedule_ids=? WHERE job_id=?', (f'["sch-{n + 1}"]', job_id))
            db.execute("INSERT INTO publishing_plan_skips VALUES(?,?,?,?)", (plan['id'], 'c3', 'Kênh: Idempotency-Key already used cho lịch khác', 1))
        PostingPlans(self.store, self.publishing, self.factory, clock=lambda: self.now)   # a restart clears those wrong skips
        self.made.clear()
        self.assertEqual(self.plans.tick(force=True), 1)
        self.assertEqual((self.made[0][0]['job_id'], self.made[0][1]), ('c3', keys['c2'] + ':1'))
        self.assertEqual(self.plans._key(plan, 0, 'youtube:yt', 'x'), 'plan:%s:0:youtube:yt' % plan['id'])

    def test_posting_the_next_chapter_early_moves_the_later_ones_up_in_order(self):
        """Đăng ngay on chapter 1 while chapter 2 waits for the next day: chapter 2 moves up, chapter 3 takes the last day."""
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        self.now = datetime(2026, 11, 15, 20, 0, tzinfo=VN).timestamp()  # slots: 16/11 and 17/11 19:00
        self.assertEqual(self.plans.tick(force=True), 2)
        with self.store.db() as db:
            slots = db.execute('SELECT job_id, slot_at FROM publishing_plan_slots ORDER BY slot_at').fetchall()
            for n, (job_id, at) in enumerate(slots):
                state, when = ('published', self.now) if job_id == 'c1' else ('scheduled_remote', at)
                db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,created,updated)"
                           " VALUES(?,?,'f',?,'v','youtube:yt','youtube','t','c',?,'p','s',?,1,1)", (f'sch-{n + 1}', f'k{n}', job_id, when, state))
                db.execute('UPDATE publishing_plan_slots SET schedule_ids=? WHERE job_id=?', (f'["sch-{n + 1}"]', job_id))
        moved = []
        self.publishing.reschedule = lambda identifier, at: moved.append((identifier, datetime.fromtimestamp(at, VN).strftime('%d/%m')))
        self.made.clear()
        self.assertEqual(self.plans.tick(force=True), 1)
        self.assertEqual(moved, [('sch-2', '16/11')])                      # chapter 2 moved up a day
        self.assertEqual([b['job_id'] for b, _ in self.made], ['c3'])      # chapter 3 takes the day it left
        days = {s['job_id']: datetime.fromtimestamp(s['slot_at'], VN).strftime('%d/%m') for s in self.plans.get(plan['id'])['upcoming']}
        self.assertEqual((days['c2'], days['c3']), ('16/11', '17/11'))

    def test_a_story_slot_that_cannot_be_filled_in_order_stays_empty(self):
        plan = self.plans.save({'style': 'story', 'project': 'Trọng Sinh', 'channels': ['youtube:yt'], 'times': ['19:00']})
        self.now = datetime(2026, 11, 15, 20, 0, tzinfo=VN).timestamp()
        self.plans.tick(force=True)
        with self.store.db() as db:  # chapter 1 posted early: its day is free again
            for n, (job_id, at) in enumerate(db.execute('SELECT job_id, slot_at FROM publishing_plan_slots ORDER BY slot_at').fetchall()):
                state, when = ('published', self.now) if job_id == 'c1' else ('scheduled_remote', at)
                db.execute("INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,channel_id,platform,title,caption,publish_at,path,sha256,state,created,updated)"
                           " VALUES(?,?,'f',?,'v','youtube:yt','youtube','t','c',?,'p','s',?,1,1)", (f'sch-{n + 1}', f'k{n}', job_id, when, state))
                db.execute('UPDATE publishing_plan_slots SET schedule_ids=? WHERE job_id=?', (f'["sch-{n + 1}"]', job_id))
        def refuse(identifier, at):
            raise ValueError('Kênh chưa cấp quyền sửa video')
        self.publishing.reschedule = refuse
        self.made.clear()
        self.assertEqual(self.plans.tick(force=True), 0)
        self.assertEqual(self.made, [])                                    # chapter 3 is never put before chapter 2
        self.assertIn('để trống', self.plans.get(plan['id'])['note'])

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
