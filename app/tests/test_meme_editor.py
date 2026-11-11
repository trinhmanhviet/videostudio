# Unit tests for Meme Episode Dynamic Editor, Asset Ingestion & Prompt Generator
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient

from videostudio.api import create_app
from videostudio.meme_editor import (
    build_prop_prompt,
    detect_missing_props,
    save_prop_asset,
    update_episode_script
)


class MemeEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_prop_prompt_contains_exact_style_and_negative_constraints(self):
        res = build_prop_prompt('Cần câu mới mua', 'can_cau')
        self.assertEqual(res['prop_id'], 'can_cau')
        self.assertIn('512x512', res['prompt_vi'])
        self.assertIn('transparent PNG', res['prompt_vi'])
        self.assertIn('#3d2b1f', res['prompt_vi'])
        self.assertIn('KHÔNG đổ bóng', res['prompt_vi'])
        self.assertIn('TUYỆT ĐỐI KHÔNG có chữ', res['prompt_vi'])
        self.assertIn('512x512', res['prompt_en'])
        self.assertIn('pure transparent background', res['prompt_en'])
        self.assertIn('NO drop shadows', res['prompt_en'])
        self.assertIn('NO 3D rendering', res['prompt_en'])

    def test_detect_missing_props(self):
        script = {
            'props': {
                'app': {'asset': 'smartphone', 'label': 'Ứng dụng ghi chi tiêu'},
                'can_cau': {'asset': None, 'label': 'Cần câu mới mua'},
                'cuoc': {'asset': 'non_existent_asset_xyz', 'label': 'Cuốc làm vườn'}
            }
        }
        res = detect_missing_props(script)
        # 'app' has 'smartphone' in library -> available
        # 'can_cau' and 'cuoc' -> missing
        missing_ids = [p['id'] for p in res['missing']]
        self.assertIn('can_cau', missing_ids)
        self.assertIn('cuoc', missing_ids)

        # Check prompts attached
        can_cau_info = next(p for p in res['missing'] if p['id'] == 'can_cau')
        self.assertIn('prompts', can_cau_info)
        self.assertIn('prompt_vi', can_cau_info['prompts'])
        self.assertIn('prompt_en', can_cau_info['prompts'])

    def test_save_prop_asset_ingestion(self):
        # Create a mock 100x100 PNG
        img = Image.new('RGBA', (100, 100), (255, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        png_bytes = buf.getvalue()

        with patch.multiple('videostudio.meme_editor',
                            LIBRARY_DIR=self.tmp_path / 'library',
                            MS_PROPS_DIR=self.tmp_path / 'props',
                            LIBRARY_JSON=self.tmp_path / 'library.json'):
            # Ingest asset
            res = save_prop_asset('test_tool_axe', png_bytes, 'Chiếc rìu')
            self.assertTrue(res['ok'])
            self.assertEqual(res['prop_id'], 'test_tool_axe')
            self.assertTrue(Path(res['path']).is_file())

            # Verify it now appears in load_prop_library
            from videostudio.meme_editor import load_prop_library
            lib = load_prop_library()
            self.assertIn('test_tool_axe', lib)

    def test_update_episode_script(self):
        ep_dir = self.tmp_path / 'episode'
        ep_dir.mkdir(parents=True)
        initial_script = {
            'title': ['A', 'B'],
            'payoff': ['C', 'D'],
            'props': {
                'can_cau': {'asset': None, 'label': 'Cần câu'}
            },
            'scenes': {
                'sc1': {'bg': 'bg_living_room', 'cast': ['bo']}
            },
            'beats': [
                {'i': 0, 'who': 'bo', 'text': 'Alo', 'emo': {'bo': 'noi'}}
            ]
        }
        (ep_dir / 'script.json').write_text(json.dumps(initial_script, ensure_ascii=False), encoding='utf-8')

        updates = {
            'scenes': {'sc1': {'bg': 'bg_garden'}},
            'props': {'can_cau': {'asset': 'smartphone', 'label': 'Cần câu siêu xịn'}},
            'beats': [{'i': 0, 'emo': {'bo': 'soc'}}]
        }
        updated = update_episode_script(self.tmp_path, updates)
        self.assertEqual(updated['scenes']['sc1']['bg'], 'bg_garden')
        self.assertEqual(updated['props']['can_cau']['asset'], 'smartphone')
        self.assertEqual(updated['beats'][0]['emo']['bo'], 'soc')

    def test_api_meme_editor_endpoints(self):
        app = create_app(worker_enabled=False)
        client = TestClient(app)

        # 1. GET /meme-editor
        res = client.get('/meme-editor')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/html', res.headers['content-type'])
        self.assertIn('Chỉnh Sửa Tập Phim Meme', res.text)

        # 2. GET /api/meme/catalog
        res = client.get('/api/meme/catalog')
        self.assertEqual(res.status_code, 200)
        cat = res.json()
        self.assertGreaterEqual(len(cat['props']), 10)
        self.assertGreaterEqual(len(cat['backgrounds']), 10)
        self.assertGreaterEqual(len(cat['face_names']), 5)

        # 3. POST /api/meme/props/prompt
        res = client.post('/api/meme/props/prompt', json={'label': 'Chiếc nỏ thần', 'prop_id': 'no_than'})
        self.assertEqual(res.status_code, 200)
        pdata = res.json()
        self.assertIn('prompt_vi', pdata)
        self.assertIn('prompt_en', pdata)
        self.assertIn('512x512', pdata['prompt_vi'])


if __name__ == '__main__':
    unittest.main()
