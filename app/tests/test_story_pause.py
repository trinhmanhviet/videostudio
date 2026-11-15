"""Tạm dừng / Tiếp tục for the ChatGPT edit of a crawled story (Kể truyện → Truyện nguồn)."""
import functools
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from videostudio import story_api, story_editor
from videostudio.story_library import StoryLibrary
from test_story_editor import RAW


def wait_for(condition, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class PauseResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.sources = root / 'sources'
        (self.sources / 'abc').mkdir(parents=True)
        (self.sources / 'abc' / 'truyen_gop.txt').write_text(RAW, encoding='utf-8')
        self.library = functools.partial(StoryLibrary, root=root / 'lib', gameplay_root=root / 'gameplay')
        self.release = threading.Event()   # chapters wait for this, like a real ChatGPT answer
        self.asked = []

        def ask(job, prompt, *, status=None, stop=None):
            self.asked.append(job)
            if '-profile-' in job:
                return {'ten_truyen': 'Truyện Thử', 'nhan_vat': [], 'thuat_ngu': [], 'luu_y': []}
            status('ChatGPT đang suy nghĩ 1 phút')
            while not self.release.wait(0.02):
                if stop is not None and stop.is_set():
                    raise story_editor.Paused()
            number = int(job.split('-')[-2])
            return {'tieu_de': 'A', 'noi_dung': story_editor.split_chapters(RAW)[1][number - 1]['text'] + ' Thêm một câu cho đủ dài để không rỗng.'}
        for patch in (mock.patch.object(story_api, 'SOURCES_ROOT', self.sources), mock.patch.object(story_api, 'StoryLibrary', self.library),
                      mock.patch.object(story_editor, 'ask_chatgpt', ask)):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.release.set()
        time.sleep(0.1)
        self.tmp.cleanup()

    def server(self):
        """A fresh server process (as after a restart): the startup loop resumes unpaused edits."""
        app = FastAPI()
        story_api.register_story_routes(app, MagicMock(), MagicMock(), MagicMock(), None, lambda request: None, resume_editing=True)
        app.state.resume_story_edits()   # what the real server's startup does
        return TestClient(app)

    def test_pause_keeps_progress_survives_a_restart_and_resumes(self):
        client = self.server()
        info = client.post('/api/story/sources/abc/edit', json={}).json()
        self.assertTrue(info['running'])
        self.assertTrue(wait_for(lambda: client.get('/api/story/sources/abc').json()['status'] == 'ChatGPT đang suy nghĩ 1 phút'))

        info = client.post('/api/story/sources/abc/pause', json={}).json()
        self.assertTrue(info['pausing'] or info['paused'])
        self.assertTrue(wait_for(lambda: client.get('/api/story/sources/abc').json()['paused']))
        info = client.get('/api/story/sources/abc').json()
        self.assertFalse(info['running'])
        self.assertEqual(info['status'], '')
        self.assertIn('Đã tạm dừng', '\n'.join(info['log']))
        marker = self.sources / 'abc' / 'bien_tap' / '.dang-bien-tap'
        self.assertTrue(json.loads(marker.read_text(encoding='utf-8'))['paused'])

        restarted = self.server()            # a restart never resumes a paused story
        time.sleep(0.2)
        self.assertFalse(restarted.get('/api/story/sources/abc').json()['running'])
        self.assertTrue(restarted.get('/api/story/sources/abc').json()['paused'])

        self.release.set()                   # Tiếp tục: the edit goes on and finishes
        info = restarted.post('/api/story/sources/abc/edit', json={}).json()
        self.assertTrue(info['running'])
        self.assertFalse(info['paused'])
        self.assertTrue(wait_for(lambda: not restarted.get('/api/story/sources/abc').json()['running']))
        info = restarted.get('/api/story/sources/abc').json()
        self.assertEqual((info['edited'], info['chapters'], info['paused']), (3, 3, False))
        self.assertFalse(marker.exists())
        self.assertEqual(self.asked.count('story-' + self.asked[0].split('-')[1] + '-profile-000-0'), 1)  # profile made once

    def test_an_unpaused_edit_resumes_after_a_restart(self):
        marker = self.sources / 'abc' / 'bien_tap' / '.dang-bien-tap'
        marker.parent.mkdir()
        marker.write_text(json.dumps({'from': None, 'to': None}), encoding='utf-8')
        client = self.server()
        self.assertTrue(client.get('/api/story/sources/abc').json()['running'])
        client.post('/api/story/sources/abc/pause', json={})
        self.assertTrue(wait_for(lambda: client.get('/api/story/sources/abc').json()['paused']))

    def test_registering_the_routes_alone_never_starts_an_edit(self):
        marker = self.sources / 'abc' / 'bien_tap' / '.dang-bien-tap'
        marker.parent.mkdir()
        marker.write_text(json.dumps({'from': None, 'to': None}), encoding='utf-8')
        app = FastAPI()
        story_api.register_story_routes(app, MagicMock(), MagicMock(), MagicMock(), None, lambda request: None, resume_editing=True)
        time.sleep(0.1)
        self.assertEqual(self.asked, [])
        self.assertFalse(TestClient(app).get('/api/story/sources/abc').json()['running'])

    def test_pausing_a_story_that_is_not_being_edited_is_refused(self):
        self.assertEqual(self.server().post('/api/story/sources/abc/pause', json={}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
