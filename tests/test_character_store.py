# Test character store, roster matching, and API endpoints
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from videostudio.api import create_app
from videostudio.core import Store
from videostudio.character_store import (
    load_roster,
    save_roster,
    find_matching_character,
    apply_roster_to_cast,
    describe_roster_for_prompt
)


class CharacterStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_file = Path(self.tmp.name) / 'characters.json'
        self.roster_patch=patch('videostudio.character_store.DEFAULT_STORE_PATH',self.store_file)
        self.roster_patch.start();self.addCleanup(self.roster_patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_roster_initializes_with_four_core_characters(self):
        roster = load_roster(self.store_file)
        self.assertGreaterEqual(len(roster), 4)
        ids = [c['id'] for c in roster]
        self.assertIn('bo', ids)
        self.assertIn('toi', ids)
        self.assertIn('me', ids)
        self.assertIn('hang_xom', ids)

    def test_matching_by_id_name_and_aliases(self):
        roster = load_roster(self.store_file)
        self.assertEqual(find_matching_character('bo', roster)['id'], 'bo')
        self.assertEqual(find_matching_character('Bố', roster)['id'], 'bo')
        self.assertEqual(find_matching_character('ông bố', roster)['id'], 'bo')
        self.assertEqual(find_matching_character('cha', roster)['id'], 'bo')
        self.assertEqual(find_matching_character('con trai', roster)['id'], 'toi')
        self.assertEqual(find_matching_character('mẹ', roster)['id'], 'me')
        self.assertEqual(find_matching_character('bác hàng xóm', roster)['id'], 'hang_xom')
        self.assertIsNone(find_matching_character('bác sĩ lạ', roster))

    def test_apply_roster_preserves_custom_characters_and_locks_roster_characters(self):
        roster = [
            {
                'id': 'bo',
                'name': 'Bố',
                'costume': 'ao_ba_lo_trang',
                'costume_offset': {'dx': 5, 'dy': -2, 'scale': 1.05},
                'acc': [
                    {'id': 'toc_dung_nguoc', 'dx': 0, 'dy': -10, 'scale': 1.0, 'rotation': 0},
                    {'id': 'rau_mep', 'dx': 0, 'dy': 2, 'scale': 1.0, 'rotation': 0}
                ]
            }
        ]
        cast = {
            'bo': {'name': 'Bố', 'costume': 'blouse_bac_si', 'acc': [], 'face': 'gian'},
            'bac_si': {'name': 'Bác sĩ', 'costume': 'blouse_bac_si', 'acc': ['kinh_can'], 'face': 'noi'}
        }
        updated = apply_roster_to_cast(cast, roster)
        # 'bo' must be locked to roster
        self.assertEqual(updated['bo']['costume'], 'ao_ba_lo_trang')
        self.assertEqual(len(updated['bo']['acc']), 2)
        self.assertEqual(updated['bo']['acc'][0]['id'], 'toc_dung_nguoc')
        self.assertEqual(updated['bo']['acc'][0]['dy'], -10)
        self.assertEqual(updated['bo']['costume_offset']['dx'], 5)
        # 'bac_si' (not in roster) must be preserved as generated
        self.assertEqual(updated['bac_si']['costume'], 'blouse_bac_si')
        self.assertEqual(updated['bac_si']['acc'], ['kinh_can'])

    def test_head_box_with_offsets(self):
        HEAD_CHIN = [86.5, 143]
        def calc_head_box(p, size, offset=None):
            offset = offset or {}
            dx = float(offset.get('dx', 0))
            dy = float(offset.get('dy', 0))
            scale_mul = float(offset.get('scale', 1.0))
            rot_add = float(offset.get('rotation', 0))
            k = p['scale'] * scale_mul
            w, h = size
            ax, ay = p['anchor'][0] * k, p['anchor'][1] * k
            left, top = p['at'][0] + dx - HEAD_CHIN[0] - ax, p['at'][1] + dy - HEAD_CHIN[1] - ay
            rot = p.get('rotation', 0) + rot_add
            turn = f'; transform:rotate({rot}deg); transform-origin:{ax:.2f}px {ay:.2f}px' if rot else ''
            return f'left:{left:.2f}px; top:{top:.2f}px; width:{w * k:.2f}px; height:{h * k:.2f}px{turn}'

        item = {
            'anchor': [172.0, 0.0],
            'at': [86.5, -50],
            'scale': 0.4593,
            'rotation': 0
        }
        size = [344, 293]
        css_default = calc_head_box(item, size)
        self.assertIn('left:', css_default)
        self.assertIn('top:', css_default)
        css_custom = calc_head_box(item, size, {'dx': 10, 'dy': -15, 'scale': 1.2, 'rotation': 5})
        self.assertIn('rotate(5.0deg)', css_custom)
        expected_w = 344 * 0.4593 * 1.2
        self.assertIn(f'width:{expected_w:.2f}px', css_custom)

    def test_api_character_endpoints(self):
        app = create_app(store=Store(Path(self.tmp.name)/'jobs.db',Path(self.tmp.name)/'videos'),worker_enabled=False)
        client = TestClient(app)

        # GET /characters (HTML dressing room)
        resp = client.get('/characters')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/html', resp.headers['content-type'])
        self.assertIn('Kho Nhân Vật', resp.text)

        # GET /api/characters
        resp = client.get('/api/characters')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('characters', data)
        self.assertIn('catalog', data)
        self.assertGreaterEqual(len(data['catalog']['costumes']), 10)
        self.assertGreaterEqual(len(data['catalog']['accessories']), 10)

        # POST /api/characters
        new_char = {
            'id': 'co_giao',
            'name': 'Cô giáo',
            'aliases': ['cô', 'cô giáo'],
            'costume': 'ao_dai_trang',
            'costume_offset': {'dx': 0, 'dy': 0, 'scale': 1.0},
            'acc': [
                {'id': 'toc_dai_thang', 'dx': 0, 'dy': -5, 'scale': 1.0, 'rotation': 0},
                {'id': 'kinh_can', 'dx': 0, 'dy': 0, 'scale': 1.0, 'rotation': 0}
            ],
            'default_face': 'cuoi',
            'voice': '',
            'description': 'Cô giáo chủ nhiệm'
        }
        resp = client.post('/api/characters', json=new_char)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

        # Verify added
        resp = client.get('/api/characters')
        char_ids = [c['id'] for c in resp.json()['characters']]
        self.assertIn('co_giao', char_ids)

        # DELETE /api/characters/co_giao
        resp = client.delete('/api/characters/co_giao')
        self.assertEqual(resp.status_code, 200)
        resp = client.get('/api/characters')
        char_ids = [c['id'] for c in resp.json()['characters']]
        self.assertNotIn('co_giao', char_ids)

    def test_broken_existing_roster_is_preserved_instead_of_reset_to_defaults(self):
        original='{"characters": [broken'
        self.store_file.write_text(original,encoding='utf8')
        with self.assertRaises(ValueError):load_roster(self.store_file)
        self.assertEqual(self.store_file.read_text(encoding='utf8'),original)

    def test_appearance_preset_does_not_rename_a_supplied_story_character(self):
        result=apply_roster_to_cast({'bo':{'name':'Phúc','costume':'so_mi_caro','acc':[]}},load_roster(self.store_file))
        self.assertEqual(result['bo']['name'],'Phúc')

    def test_invalid_offsets_are_rejected_before_replacing_the_saved_roster(self):
        roster=load_roster(self.store_file);original=self.store_file.read_bytes()
        roster[0]['costume_offset']['scale']=float('nan')
        with self.assertRaises(ValueError):save_roster(roster,self.store_file)
        self.assertEqual(self.store_file.read_bytes(),original)

    def test_roster_edits_are_one_locked_read_modify_write_operation(self):
        from concurrent.futures import ThreadPoolExecutor
        from videostudio.character_store import edit_roster
        load_roster(self.store_file)
        def add(i):
            def change(rows):
                rows.append({'id':f'custom_{i}','name':str(i),'costume':'ao_phong_xanh','acc':[]})
                return rows
            return edit_roster(change,self.store_file)
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(add,range(12)))
        self.assertEqual(len(load_roster(self.store_file)),16)


if __name__ == '__main__':
    unittest.main()
