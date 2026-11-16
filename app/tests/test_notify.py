"""Telegram notices: the queue, merging, speed limits, retries, and that Telegram trouble never touches the work."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from videostudio import notify
from videostudio.core import Store
from videostudio.notify import Notifier, TelegramError, Watch

TOKEN = '123456789:AAHsecretsecretsecretsecretsecret12'


class FakeTime:
    """A clock and a stop event whose wait() moves the clock instead of sleeping."""

    def __init__(self):
        self.now = 1000.0
        self.waits = []

    def clock(self):
        return self.now

    def is_set(self):
        return False

    def wait(self, seconds=None):
        self.waits.append(seconds)
        self.now += seconds or 0


def settings(**changes):
    return {'token': TOKEN, 'chat': '42', 'enabled': True, 'groups': {}, **changes}


class NotifierTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()
        self.sent = []
        self.failures = []

        def send(token, chat, text):
            if self.failures:
                raise self.failures.pop(0)
            self.sent.append((self.time.now, text))
        self.settings = settings()
        self.notifier = Notifier(lambda: self.settings, send, clock=self.time.clock, stop=self.time)

    def test_lines_arriving_together_go_out_as_one_message(self):
        for text in ('🎬 Vào hàng đợi: A', '▶️ Bắt đầu làm video: A', '✅ Video xong: B'):
            self.notifier.emit('video', text)
        self.assertEqual(self.notifier.pump(block=False), 0)  # still inside the gathering window
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 1)
        self.assertEqual(self.sent[0][1], '🎬 Vào hàng đợi: A\n\n▶️ Bắt đầu làm video: A\n\n✅ Video xong: B')

    def test_finished_chapters_merge_into_one_line_and_repeats_are_counted(self):
        for number in (3, 4, 5):
            self.notifier.emit('story', '', merge=('chapters:x', '📖 Truyện X: xong chương ', number))
            self.time.now += 20
        for _ in range(3):
            self.notifier.emit('story', '⚠️ Lỗi tạm')
        self.time.now += 5
        self.notifier.pump(block=False)
        self.assertEqual([t for _, t in self.sent], ['⚠️ Lỗi tạm (×3)'])  # the chapters are held so more can join
        self.time.now += 60
        self.notifier.pump(block=False)
        self.assertEqual([t for _, t in self.sent][1:], ['📖 Truyện X: xong chương 3, 4, 5'])

    def test_groups_switched_off_and_notices_switched_off_send_nothing(self):
        self.settings = settings(groups={'drive': False})
        self.notifier.emit('drive', 'Drive')
        self.notifier.emit('video', 'Video')
        self.time.now += 5
        self.notifier.pump(block=False)
        self.assertEqual([t for _, t in self.sent], ['Video'])
        self.settings = settings(enabled=False)
        self.notifier.emit('video', 'Video 2')
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 0)
        self.settings = settings(token=None)
        self.notifier.emit('video', 'Video 3')
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 0)
        self.assertEqual(len(self.sent), 1)

    def test_long_batches_split_under_the_size_limit_and_keep_the_speed_limits(self):
        for index in range(40):
            self.notifier.emit('video', f'{index:02d} ' + 'x' * 400)
        self.time.now += 5
        self.notifier.pump(block=False)
        self.assertGreater(len(self.sent), 3)
        self.assertTrue(all(len(text) <= notify.LIMIT for _, text in self.sent))
        times = [at for at, _ in self.sent]
        self.assertTrue(all(b - a >= self.notifier.interval for a, b in zip(times, times[1:])))
        self.assertIn('39 ', self.sent[-1][1])

    def test_no_more_than_the_per_minute_limit(self):
        self.notifier.interval = 0
        for index in range(25):
            self.notifier.emit('video', f'line {index}')
            self.time.now += 5
            self.notifier.pump(block=False)
        times = [at for at, _ in self.sent]
        for index, at in enumerate(times):
            self.assertLessEqual(sum(1 for t in times[index:] if t - at < 60), self.notifier.per_minute)

    def test_network_errors_are_retried_with_growing_pauses(self):
        self.failures = [TelegramError('mất mạng'), TelegramError('mất mạng')]
        self.notifier.emit('video', 'A')
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 1)
        self.assertEqual(self.time.waits[:2], [2, 4])
        self.assertIsNone(self.notifier.last_error)

    def test_telegram_asking_to_slow_down_is_obeyed(self):
        self.failures = [TelegramError('chậm lại', retry_after=17)]
        self.notifier.emit('video', 'A')
        self.time.now += 5
        self.notifier.pump(block=False)
        self.assertIn(17, self.time.waits)
        self.assertEqual(len(self.sent), 1)

    def test_a_wrong_token_is_not_retried_and_is_reported(self):
        self.failures = [TelegramError('Token bot sai', permanent=True)]
        self.notifier.emit('video', 'A')
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 0)
        self.assertEqual(self.notifier.last_error, 'Token bot sai')
        self.assertEqual(self.time.waits, [])

    def test_offline_messages_are_kept_and_sent_first_when_back(self):
        self.failures = [TelegramError('mất mạng')] * (self.notifier.retries + 1)
        self.notifier.emit('video', 'A')
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 0)
        self.assertEqual(self.notifier.waiting(), 1)
        self.notifier.emit('video', 'B')
        self.time.now += 5
        self.assertEqual(self.notifier.pump(block=False), 2)
        self.assertEqual([t for _, t in self.sent], ['A', 'B'])

    def test_unexpected_sender_errors_never_escape(self):
        self.failures = [RuntimeError('boom ' + TOKEN)] * (self.notifier.retries + 1)
        self.notifier.emit('video', 'A')
        self.time.now += 5
        self.notifier.pump(block=False)
        self.assertNotIn(TOKEN, self.notifier.last_error)


class WorkIsNeverHurtTests(unittest.TestCase):
    def test_emit_returns_at_once_while_telegram_hangs_and_the_queue_stays_bounded(self):
        hang = threading.Event()
        stop = threading.Event()
        notifier = Notifier(lambda: settings(), lambda *a: hang.wait(10), window=0, stop=stop, limit=50)
        notifier.start()
        try:
            started = time.monotonic()
            for index in range(2000):
                notifier.emit('video', f'line {index}')
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertLessEqual(len(notifier.items), 50)
        finally:
            stop.set()
            hang.set()
        dropped = notifier.take(block=False)
        self.assertIn('Bỏ bớt', dropped[0]['text'])

    def test_emit_without_a_notifier_or_with_a_broken_one_does_nothing(self):
        with patch.object(notify, '_notifier', None):
            self.assertIsNone(notify.emit('video', 'A'))
        broken = Notifier(lambda: settings(), lambda *a: None)
        broken.cond = None  # anything inside going wrong
        with patch.object(notify, '_notifier', broken):
            self.assertIsNone(notify.emit('video', 'A'))

    def test_a_broken_settings_store_sends_nothing_and_does_not_raise(self):
        def settings_fail():
            raise OSError('database locked')
        notifier = Notifier(settings_fail, lambda *a: None, window=0)
        notifier.emit('video', 'A')
        self.assertEqual(notifier.pump(block=False), 0)

    def test_the_token_never_appears_in_errors(self):
        def refused(*args, **kwargs):
            raise httpx.ConnectError(f'cannot reach https://api.telegram.org/bot{TOKEN}/sendMessage')
        with patch.object(notify.httpx, 'post', refused):
            with self.assertRaises(TelegramError) as caught:
                notify.telegram_send(TOKEN, '42', 'hi')
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertFalse(caught.exception.permanent)
        answer = SimpleNamespace(status_code=401, text='Unauthorized', json=lambda: {'ok': False, 'description': 'Unauthorized'})
        with patch.object(notify.httpx, 'post', lambda *a, **k: answer):
            with self.assertRaises(TelegramError) as caught:
                notify.telegram_send(TOKEN, '42', 'hi')
        self.assertTrue(caught.exception.permanent)
        answer = SimpleNamespace(status_code=429, text='', json=lambda: {'ok': False, 'parameters': {'retry_after': 9}})
        with patch.object(notify.httpx, 'post', lambda *a, **k: answer):
            with self.assertRaises(TelegramError) as caught:
                notify.telegram_send(TOKEN, '42', 'hi')
        self.assertEqual(caught.exception.retry_after, 9)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'jobs.sqlite3', Path(self.tmp.name) / 'out')
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS notify_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS factory_items(job_id TEXT, title TEXT)')
            db.execute("INSERT INTO factory_items VALUES('j1','Truyện ma đêm khuya')")
        self.notices = []
        self.watch = Watch(self.store, emit=lambda group, text, merge=None: self.notices.append((group, text)))

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, kind, stage=None, detail=''):
        with self.store.db() as db:
            self.store.event(db, 'j1', stage, kind, detail)

    def test_old_events_are_not_reported_and_new_ones_are_once(self):
        self.event('created')
        self.event('failed', 'render', 'cũ')
        self.watch.videos()
        self.assertEqual(self.notices, [])
        self.event('retried', 'render')
        self.event('started', 'render')
        self.event('progress', 'images', 'Flow bị chặn; tạo cảnh 3 bằng Comfy. Còn 5 ảnh trước khi thử lại Flow.')
        self.event('progress', 'images', 'Flow bị chặn; tạo cảnh 4 bằng Comfy. Còn 4 ảnh trước khi thử lại Flow.')
        self.event('progress', 'images', 'Đang tạo hình ảnh: cảnh 4/9')
        self.event('completed', 'render')
        self.event('started', 'verify')
        self.event('retry', 'verify', 'ffprobe timeout')
        self.event('started', 'verify')
        self.event('failed', 'verify', 'Verification did not pass')
        self.event('cancel_requested')
        self.watch.videos()
        texts = [t for _, t in self.notices]
        self.assertEqual(len(texts), 6, texts)
        self.assertTrue(texts[0].startswith('🔁 Làm lại bước dựng video'))
        self.assertEqual(texts[1], '▶️ Bắt đầu làm video: Truyện ma đêm khuya')
        self.assertTrue(texts[2].startswith('🛟 Tự dùng phương án dự phòng (hình ảnh)'))
        self.assertTrue(texts[3].startswith('🔁 Lỗi tạm ở bước kiểm tra'))
        self.assertTrue(texts[4].startswith('❌ Video lỗi ở bước kiểm tra'))
        self.assertEqual(texts[5], '🛑 Đã huỷ video: Truyện ma đêm khuya')
        # the cursor is saved: a restarted server does not report them again
        again = Watch(self.store, emit=lambda *a, **k: self.notices.append(a))
        again.videos()
        self.assertEqual(len(self.notices), 6)

    def test_finished_video_names_its_file(self):
        self.watch.videos()
        job = {'checkpoints': {'verify': {'duration_seconds': 125}, 'render': {'video': 'D:/out/video.mp4'}}}
        with patch.object(self.store, 'get', lambda job_id: job):
            self.event('completed', 'verify')
            self.watch.videos()
        self.assertEqual(self.notices[-1], ('video', '✅ Video xong: Truyện ma đêm khuya (2 phút 5 giây)\n📁 D:/out/video.mp4'))

    def test_posts_report_link_or_error_on_change_only(self):
        with self.store.db() as db:
            db.execute('CREATE TABLE publishing_schedules(id TEXT, platform TEXT, title TEXT, state TEXT, remote_url TEXT, error TEXT, publish_at REAL)')
            db.execute("INSERT INTO publishing_schedules VALUES('p1','youtube','Tập 1','scheduled',NULL,NULL,0)")
            db.execute("INSERT INTO publishing_schedules VALUES('p2','facebook','Tập 2','uploading',NULL,NULL,0)")
        self.watch.publishing()
        self.assertEqual(self.notices, [])
        with self.store.db() as db:
            db.execute("UPDATE publishing_schedules SET state='published',remote_url='https://www.youtube.com/watch?v=abc' WHERE id='p1'")
            db.execute("UPDATE publishing_schedules SET state='blocked',error='Quyền đăng đã hết hạn' WHERE id='p2'")
        self.watch.publishing()
        self.watch.publishing()
        self.assertEqual(self.notices, [('publish', '📢 Đã đăng YouTube: Tập 1\nhttps://www.youtube.com/watch?v=abc'),
                                        ('publish', '⚠️ Đăng Facebook lỗi: Tập 2\nQuyền đăng đã hết hạn')])

    def test_chatgpt_service_restart_down_and_sign_in(self):
        answers = [{'started_at': 1}, {'started_at': 2}, {'started_at': 2, 'last_error': 'authentication_required'},
                   OSError(), OSError(), OSError(), {'started_at': 3}]

        def http(url):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        self.watch.http = http
        for _ in range(7):
            self.watch.chatgpt()
        self.assertEqual([t.split()[0] for _, t in self.notices], ['🔄', '🔐', '🔴', '🔄'])

    def test_low_disk_is_reported_once_until_it_recovers(self):
        free = [5 * 2**30, 4 * 2**30, 20 * 2**30, 3 * 2**30]
        self.watch.disks = lambda: ['D:/data']
        with patch.object(notify.shutil, 'disk_usage', lambda path: SimpleNamespace(free=free.pop(0))):
            for _ in range(4):
                self.watch.disk()
        self.assertEqual(len(self.notices), 2)
        self.assertIn('sắp đầy: còn 5,0 GB', self.notices[0][1])


class SettingsRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'jobs.sqlite3', Path(self.tmp.name) / 'out')
        self.sent = []
        self.fail = None

        def send(token, chat, text):
            if self.fail:
                raise self.fail
            self.sent.append((token, chat, text))
        app = FastAPI()
        notify.register_notify_routes(app, self.store, lambda request: None, background=False, send_function=send)
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_token_and_chat_then_send_a_test(self):
        self.assertEqual(self.client.post('/api/notify/test').status_code, 422)
        self.assertEqual(self.client.put('/api/notify', json={'token': 'abc'}).status_code, 422)
        info = self.client.put('/api/notify', json={'token': TOKEN, 'chat': '123456789'}).json()
        self.assertTrue(info['configured'])
        self.assertNotIn(TOKEN, str(info))  # the token never goes back to the page
        self.assertEqual(self.client.post('/api/notify/test').json(), {'sent': True})
        self.assertEqual(self.sent[0][:2], (TOKEN, '123456789'))
        self.fail = TelegramError('Chat ID sai, hoặc bạn chưa nhắn cho bot lần nào.', permanent=True)
        response = self.client.post('/api/notify/test')
        self.assertEqual(response.status_code, 422)
        self.assertIn('Chat ID sai', response.json()['detail'])

    def test_groups_switch_on_and_off(self):
        info = self.client.put('/api/notify', json={'groups': {'drive': False, 'nope': False}}).json()
        groups = {g['key']: g['on'] for g in info['groups']}
        self.assertEqual(groups, {'video': True, 'story': True, 'publish': True, 'drive': False, 'system': True})
        self.assertEqual(notify.settings_of(self.store)['groups'], {'drive': False})


if __name__ == '__main__':
    unittest.main()
