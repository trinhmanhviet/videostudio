"""Làm dần cả truyện: one episode at a time, a stop when new gameplay is short, going on by itself, restarts, reuse."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from videostudio import gameplay_drive
from videostudio.gameplay_drive import GameplayFolder
from videostudio.story_autorun import AutoRun, fresh_seconds
from videostudio.story_pipeline import cut_plan

from test_gameplay_drive import FOLDER, FakeDrive, add_clip, make_library

# 420 words read at 4.2 a second: 100 s of narration, 105 s with the margin. Each clip is 60 s.
def chapter(n):
    return ' '.join(['chữ'] * 419 + [f'hết{n}'])


class Queue:
    """Stands in for the shared video queue: freezes the episode like the real one and remembers its state."""

    def __init__(self, library):
        self.library, self.states, self.calls = library, {}, []

    def __call__(self, book_id, chapter_ids, key):
        snapshot = self.library.freeze(book_id, chapter_ids, key)
        self.calls.append((chapter_ids, key))
        self.states[snapshot['sha256']] = ('active', '')
        return snapshot['sha256']

    def episode_states(self, digests):
        return {d: self.states[d] for d in digests if d in self.states}

    def finish(self, digest, ok=True):
        """The video was made: its gameplay plan consumed footage from the book's cursor, as the pipeline does."""
        snapshot = self.library.snapshot(digest)
        seconds = sum(len(c['text'].split()) for c in snapshot['chapters']) / 4.2
        book_id = snapshot['book']['id']
        _, cursor, _ = cut_plan(snapshot['gameplay'], self.library.cursor(book_id), seconds)
        self.library.advance_cursor(book_id, cursor['clip'], cursor['offset'], 'job')
        self.states[digest] = ('done', '') if ok else ('failed', 'Lỗi giọng đọc')


class AutoRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.library = make_library(self.tmp)
        self.book = self.library.create_book('Truyện Thử')['id']
        self.library.import_files(self.book, [{'name': f'{n}.txt', 'text': chapter(n)} for n in (1, 2, 3)], split=False)
        self.chapters = [c['id'] for c in self.library.chapters(self.book)['items']]
        self.queue = Queue(self.library)
        self.notices = []

    def runner(self):
        return AutoRun(self.library, self.queue, self.queue.episode_states, notify=self.notices.append)

    def clips(self, *names):
        for name in names:
            add_clip(self.library, self.tmp, name)

    def test_stops_when_new_gameplay_is_short_and_says_where(self):
        self.clips('a.mp4')  # 60 s of new footage, the episode needs 105 s
        status = self.runner().start(self.book)
        self.assertEqual(status['state'], 'waiting_gameplay')
        self.assertEqual(self.queue.calls, [])  # no episode that would repeat old footage
        self.assertIn('Truyện Truyện Thử dừng ở chương 1: gameplay mới còn 1 phút, tập cần 1.8 phút. Thêm clip vào thư mục Drive', status['message'])
        self.assertIn('dừng ở chương 1', self.notices[-1])
        count = len(self.notices)
        self.runner().tick()
        self.assertEqual(len(self.notices), count)  # told once, not on every check

    def test_goes_on_by_itself_when_new_clips_are_enough(self):
        self.clips('a.mp4')
        run = self.runner()
        run.start(self.book)
        self.clips('b.mp4', 'c.mp4')  # now 180 s: enough for chapter 1
        run.tick()
        status = run.status(self.book)
        self.assertEqual(status['state'], 'running')
        self.assertEqual([ids for ids, _ in self.queue.calls], [[self.chapters[0]]])
        self.assertIn('đủ gameplay', self.notices[-1])
        # Chapter 1 used 100 s: 80 s of new footage left, chapter 2 needs 105 s, so the book stops at chapter 2.
        self.queue.finish(status['current']['snapshot'])
        status = run.tick_book(self.book)
        self.assertEqual(status['state'], 'waiting_gameplay')
        self.assertIn('dừng ở chương 2', status['message'])
        self.assertEqual(len(self.queue.calls), 1)

    def test_a_sync_that_brings_clips_runs_the_check(self):
        patches = [mock.patch.object(gameplay_drive, 'CACHE', Path(self.tmp, 'cache')), mock.patch.object(gameplay_drive, 'cache_trim', lambda keep=(): None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        run = self.runner()
        self.assertEqual(run.start(self.book)['state'], 'waiting_gameplay')  # no clip at all yet
        folder = GameplayFolder(store=None, library=self.library, drive=FakeDrive(self.tmp))
        folder.on_new_clips = run.tick
        folder.drive.files[FOLDER].append({'id': 'v3', 'name': 'three.mp4', 'size': 3})
        folder.configure({'link': FOLDER})
        folder.sync()  # three 60 s clips arrive
        self.assertEqual(run.status(self.book)['state'], 'running')
        self.assertEqual(len(self.queue.calls), 1)

    def test_one_episode_at_a_time_and_a_restart_goes_on(self):
        self.clips('a.mp4', 'b.mp4', 'c.mp4', 'd.mp4', 'e.mp4', 'f.mp4')  # 360 s: enough for all three chapters
        status = self.runner().start(self.book)
        self.assertEqual(len(self.queue.calls), 1)
        self.runner().tick()
        self.assertEqual(len(self.queue.calls), 1)  # the first episode is still in the queue
        first = status['current']['snapshot']
        self.queue.finish(first)
        again = self.runner()  # the server restarted: the run is read back from its file
        self.assertTrue(Path(self.library.root, 'lam-dan', self.book + '.json').is_file())
        again.tick()
        self.assertEqual([ids for ids, _ in self.queue.calls], [[self.chapters[0]], [self.chapters[1]]])
        self.assertIn(self.chapters[0], self.library.done_chapter_ids(self.book))
        # Paused by the owner: a restart keeps it paused, new clips do not start it.
        again.pause(self.book)
        self.queue.finish(again.status(self.book)['current']['snapshot'])
        self.runner().tick()
        self.assertEqual(len(self.queue.calls), 2)
        self.assertEqual(self.runner().resume(self.book)['state'], 'running')
        self.assertEqual(len(self.queue.calls), 3)
        self.assertEqual(self.runner().stop(self.book), {'state': 'off'})
        self.assertFalse(Path(self.library.root, 'lam-dan', self.book + '.json').exists())

    def test_reuse_of_used_clips_never_stops_for_new_gameplay(self):
        self.clips('a.mp4')
        self.library.set_reuse(True)
        status = self.runner().start(self.book)
        self.assertEqual(status['state'], 'running')
        self.assertEqual(len(self.queue.calls), 1)
        self.assertTrue(status['reuse'])

    def test_every_new_clip_used_counts_as_no_new_gameplay(self):
        self.clips('a.mp4', 'b.mp4')
        ids = [c['id'] for c in self.library.gameplay(self.book)['items']]
        self.library.mark_used(ids)  # the playlist falls back to used clips: nothing new
        self.assertEqual(fresh_seconds(self.library, self.book, {}), 0.0)
        self.assertEqual(self.runner().start(self.book)['state'], 'waiting_gameplay')

    def test_a_failed_episode_stops_the_run_and_continue_makes_it_again(self):
        self.clips('a.mp4', 'b.mp4', 'c.mp4', 'd.mp4')
        run = self.runner()
        status = run.start(self.book)
        self.queue.finish(status['current']['snapshot'], ok=False)
        status = run.tick_book(self.book)
        self.assertEqual(status['state'], 'error')
        self.assertIn('Lỗi giọng đọc', status['message'])
        self.assertEqual(len(self.queue.calls), 1)
        run.resume(self.book)
        self.assertEqual([ids for ids, _ in self.queue.calls], [[self.chapters[0]], [self.chapters[0]]])
        self.assertNotEqual(self.queue.calls[0][1], self.queue.calls[1][1])  # a new queue key

    def test_group_mode_queues_one_episode_of_several_chapters(self):
        self.clips(*[f'{n}.mp4' for n in range(8)])
        status = self.runner().start(self.book, 'group', 5)  # 5 min target: three 100 s chapters fit one episode
        self.assertEqual(self.queue.calls[0][0], self.chapters)
        self.assertEqual(status['current']['label'], 'chương 1–3')

    def test_everything_made_waits_for_new_chapters(self):
        self.clips(*[f'{n}.mp4' for n in range(8)])
        run = self.runner()
        for _ in range(3):
            status = run.tick_book(self.book) if self.queue.calls else run.start(self.book)
            self.queue.finish(status['current']['snapshot'])
        status = run.tick_book(self.book)
        self.assertEqual((status['state'], status['todo']), ('running', 0))
        self.library.import_files(self.book, [{'name': '4.txt', 'text': chapter(4)}], split=False)
        run.tick()
        self.assertEqual(len(self.queue.calls), 4)


if __name__ == '__main__':
    unittest.main()
