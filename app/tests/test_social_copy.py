import json
import tempfile
import unittest
from pathlib import Path

from videostudio import social_copy


def job(folder, **checkpoints):
    return {'id': 'job-1', 'output': str(folder), 'request': {'idea': 'Lời đọc gốc', 'project': 'Dự án'},
            'checkpoints': checkpoints}


GOOD = {'youtube': {'title': 'Tiêu đề', 'description': 'Mô tả', 'tags': ['vụ án', '#bí ẩn', 'vụ án']},
        'facebook': {'caption': 'Caption FB', 'hashtags': ['vuan', '#bian hay']},
        'tiktok': {'caption': 'Caption TikTok', 'hashtags': ['#a', 'b', 'c', 'd', 'e', 'f', 'g']}}


class SocialCopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / 'out'

    def tearDown(self):
        self.tmp.cleanup()

    def test_prompt_uses_final_narration_and_title(self):
        value = job(self.folder, script={'narration': 'Lời đọc đã viết', 'title': 'Tên video'})
        text = social_copy.prompt(value)
        self.assertIn('Lời đọc đã viết', text)
        self.assertIn('Tên video', text)
        self.assertNotIn('Lời đọc gốc', text)
        self.assertIn('Lời đọc gốc', social_copy.prompt(job(self.folder)))

    def test_validate_normalises_tags_and_limits(self):
        result = social_copy.validate(GOOD)
        self.assertEqual(result['youtube']['tags'], ['vụán', 'bíẩn'])
        self.assertEqual(result['facebook']['hashtags'], ['#vuan', '#bianhay'])
        self.assertEqual(len(result['tiktok']['hashtags']), 6)
        with self.assertRaises(ValueError):
            social_copy.validate({'youtube': {'title': ''}, 'facebook': {}, 'tiktok': {}})

    def test_generate_writes_ready_copy(self):
        value = job(self.folder, script={'narration': 'Lời đọc'})
        social_copy.generate(lambda prompt: GOOD, value)
        saved = json.loads((self.folder / 'social.json').read_text(encoding='utf8'))
        self.assertEqual(saved['state'], 'ready')
        self.assertEqual(saved['youtube']['title'], 'Tiêu đề')

    def test_provider_failure_is_stored_not_raised(self):
        def broken(prompt):
            raise RuntimeError('ChatGPT không phản hồi')
        result = social_copy.generate(broken, job(self.folder, script={'narration': 'Lời đọc'}))
        self.assertEqual(result['state'], 'error')
        self.assertIn('ChatGPT', social_copy.read(job(self.folder))['error'])



    def test_ai_name_is_trimmed_and_required(self):
        self.assertEqual(social_copy.ask_name(lambda prompt: {'title': '  Tên hay  '}, 'Nội dung'), 'Tên hay')
        self.assertIn('Nội dung', social_copy.name_prompt('Nội dung'))
        with self.assertRaises(ValueError):
            social_copy.ask_name(lambda prompt: {'name': 'x'}, 'Nội dung')


class SocialCopyApiTests(unittest.TestCase):
    def test_endpoints_only_write_for_finished_videos_and_report_progress(self):
        import threading
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from videostudio.api import create_app
        from videostudio.core import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db', Path(tmp) / 'out')
            asked, release = [], threading.Event()
            def llm_json(prompt, check):
                asked.append(pipeline.context.job)
                release.wait(5)
                return GOOD
            pipeline = SimpleNamespace(handlers=lambda: {}, context=threading.local(), llm_json=llm_json)
            with TestClient(create_app(store, pipeline, False)) as client:
                j, _ = store.create({'idea': 'Lời đọc', 'voice_id': 'v', 'duration_seconds': 8}, 'one')
                url = f"/api/jobs/{j['id']}/social"
                self.assertEqual(client.get(url).json()['state'], 'none')
                self.assertEqual(client.post(url).status_code, 409)
                with store.db() as db:
                    db.execute("UPDATE jobs SET state='completed' WHERE id=?", (j['id'],))
                self.assertEqual(client.post(url, headers={'Origin': 'https://untrusted.invalid'}).status_code, 403)
                self.assertEqual(client.post(url).json()['state'], 'running')
                self.assertEqual(client.get(url).json()['state'], 'running')
                release.set()
                for _ in range(50):
                    if client.get(url).json()['state'] == 'ready':
                        break
                    threading.Event().wait(.05)
                self.assertEqual(client.get(url).json()['youtube']['title'], 'Tiêu đề')
                self.assertEqual(asked, [j['id']])

if __name__ == '__main__':
    unittest.main()
