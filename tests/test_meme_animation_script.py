import copy
import importlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST = {'idea': 'Bạn tôi viết sách nhưng vợ mới là tác giả.', 'duration_seconds': 60,
           'voice_id': 'clone:selected'}


class AnimationScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.api = importlib.import_module('videostudio.meme_animation_script')
        except ModuleNotFoundError:
            cls.api = None
        cls.catalog = cls.api.AnimationCatalog() if cls.api else None
        cls.example = json.loads((ROOT / 'tests/fixtures/meme-animation-script.json').read_text(encoding='utf-8'))

    def valid(self):
        data = copy.deepcopy(self.example)
        data['beats'] = (data['beats'] * 3)[:24]
        return data

    def test_contract_module_exists(self):
        self.assertIsNotNone(self.api)

    def test_real_episode_is_engine_compatible_and_voices_are_selected(self):
        script = self.api.validate(self.valid(), self.catalog, REQUEST)
        self.assertEqual(script['speed'], 1.15)
        self.assertEqual(script['narrator_voice'], REQUEST['voice_id'])
        self.assertEqual(len(script['title']), 2)
        self.assertEqual(len(script['payoff']), 2)
        self.assertTrue(all(c['voice'] == REQUEST['voice_id'] for c in script['cast'].values()))
        for beat in script['beats']:
            self.assertEqual(set(beat['emo']), set(script['scenes'][beat['scene']]['cast']))

    def test_catalog_reads_real_assets_and_fingerprints_content(self):
        self.assertIn('ao_phong_xanh', self.catalog.costumes)
        self.assertIn('kinh_can', self.catalog.accessories)
        self.assertIn('noi', self.catalog.faces)
        self.assertIn('bg_office', self.catalog.backgrounds)
        self.assertTrue(all(p.is_absolute() and len(h) == 64 for p, h in self.catalog.assets.items()))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'memestudio'
            shutil.copytree(ROOT / 'memestudio/assets', target / 'assets')
            cat = self.api.AnimationCatalog(target)
            before = cat.fingerprint()
            asset = next((target / 'assets/backgrounds').glob('*.png'))
            original = asset.read_bytes()
            asset.write_bytes(original + b'changed')
            self.assertNotEqual(before, cat.fingerprint())

    def test_prompt_uses_catalog_and_preserves_provided_story(self):
        request = dict(REQUEST, idea='Chuyện A có câu chốt CHỐT_A. Chuyện B có câu chốt CHỐT_B.')
        prompt = self.api.build_prompt(request, self.catalog, feedback=['fix face'])
        for value in ('ao_phong_xanh', 'bg_office', 'noi', 'walk_in', 'look_up', 'ding', '1.15', '24',
                      'adaptation_note', 'CHỐT_A', 'CHỐT_B', 'fix face'):
            self.assertIn(value, prompt)
        shorter = self.api.build_prompt(dict(request, duration_seconds=20), self.catalog)
        self.assertNotEqual(prompt, shorter)

    def test_bad_json_types_are_validation_errors_and_repair_locally(self):
        for field, value in [('cast', []), ('scenes', []), ('title', {}), ('payoff', 4)]:
            data = self.valid(); data[field] = value
            with self.subTest(field=field):
                with self.assertRaises(self.api.MemeScriptError):
                    self.api.validate(data, self.catalog, REQUEST)
                self.assertTrue(self.api.validate(data, self.catalog, REQUEST, lenient=True)['beats'])
        for field, value in [('who', []), ('scene', {}), ('focus', []), ('emo', []),
                             ('act', {}), ('punch', []), ('text', {}), ('act', [[[], {}]])]:
            data = self.valid(); data['beats'][0][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(self.api.MemeScriptError):
                    self.api.validate(data, self.catalog, REQUEST)
                result = self.api.validate(data, self.catalog, REQUEST, lenient=True)
                self.assertGreaterEqual(len(result['beats']), 2)

    def test_unknown_ids_actions_and_bad_arity_are_rejected(self):
        for action in [['run', 'toi'], ['gesture'], ['point', 'toi'], ['lean', 'toi', 'missing'],
                       ['ding', True], ['ding', 9], ['walk_in', ['toi']]]:
            data = self.valid(); data['beats'][0]['act'] = [action]
            with self.subTest(action=action):
                with self.assertRaises(self.api.MemeScriptError):
                    self.api.validate(data, self.catalog, REQUEST)
                self.assertEqual(self.api.validate(data, self.catalog, REQUEST, lenient=True)['beats'][0]['act'], [])
        data = self.valid(); data['scenes']['quan_cafe']['bg'] = '../bad'
        with self.assertRaises(self.api.MemeScriptError):
            self.api.validate(data, self.catalog, REQUEST)
        data = self.valid(); data['beats'][0]['punch'] = {'who': 'missing', 'face': 'soc'}
        with self.assertRaises(self.api.MemeScriptError):
            self.api.validate(data, self.catalog, REQUEST)

    def test_unsafe_actor_and_scene_ids_cannot_reach_engine(self):
        for field in ('cast', 'scenes'):
            data = self.valid(); data[field]['x\" onclick=\"bad'] = next(iter(data[field].values()))
            with self.subTest(field=field):
                with self.assertRaises(self.api.MemeScriptError):
                    self.api.validate(data, self.catalog, REQUEST)
                fixed = self.api.validate(data, self.catalog, REQUEST, lenient=True)
                self.assertNotIn('x\" onclick=\"bad', fixed[field])

    def test_visual_identity_defaults_are_stable_and_distinct(self):
        data = self.valid()
        for role in data['cast'].values():
            role.update(costume='missing', acc=[{}], face=['noi'])
        fixed = self.api.validate(data, self.catalog, REQUEST, lenient=True)
        self.assertEqual(fixed, self.api.validate(data, self.catalog, REQUEST, lenient=True))
        identities = {(r['costume'], tuple(r['acc'])) for r in fixed['cast'].values()}
        self.assertEqual(len(identities), len(fixed['cast']))
        for role in fixed['cast'].values():
            self.assertIn(role['costume'], self.catalog.costumes)
            self.assertIn(role['face'], self.catalog.faces)

    def test_checkpoint_has_one_scene_per_beat_and_full_script(self):
        script = self.api.validate(self.valid(), self.catalog, REQUEST)
        checkpoint = self.api.to_checkpoint(script, 'catalog-sha')
        self.assertEqual(checkpoint['animation_script'], script)
        self.assertEqual(checkpoint['meme_engine'], 'hyperframes')
        self.assertEqual(len(checkpoint['scenes']), len(script['beats']))
        self.assertEqual(len({s['scene_id'] for s in checkpoint['scenes']}), len(script['beats']))
        for scene, beat in zip(checkpoint['scenes'], script['beats']):
            self.assertEqual(scene['narration'], beat['text'])
            self.assertEqual(scene['narration_lines'], [beat['text']])
        self.assertEqual(checkpoint, self.api.to_checkpoint(script, 'catalog-sha'))

    def test_fixed_pacing_is_preserved_and_matches_real_engine_validator(self):
        import ast
        data = self.valid()
        data.update(start=9, gap=9, react=9, tail=9)
        script = self.api.validate(data, self.catalog, REQUEST)
        for field, expected in {'start': .15, 'gap': .12, 'react': .45, 'tail': .6}.items():
            self.assertEqual(script.get(field), expected)
        module = ast.parse((ROOT / 'memestudio/engine/make_episode.py').read_text(encoding='utf-8'))
        validator = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'validate')
        scope = {'FACES': {'faces': self.catalog.faces},
                 'CATALOG': dict(self.catalog.costumes, **self.catalog.accessories),
                 'BACKGROUNDS': self.catalog.root / 'assets/backgrounds', 'ACTIONS': self.api.ACTIONS}
        exec(compile(ast.Module(body=[validator], type_ignores=[]), '<engine-validator>', 'exec'), scope)
        self.assertEqual(scope['validate'](script), [])

    def test_unknown_fields_dropped_and_adaptation_note_retained(self):
        data = self.valid(); data.update(adaptation_note='Chỉ chuyển thể chuyện A, giữ câu chốt.', unexpected='bad')
        data['cast']['toi']['injected'] = 'bad'; data['beats'][0]['html'] = '<script>'
        script = self.api.validate(data, self.catalog, REQUEST)
        self.assertNotIn('unexpected', script)
        self.assertNotIn('injected', script['cast']['toi'])
        self.assertNotIn('html', script['beats'][0])
        self.assertEqual(script['adaptation_note'], data['adaptation_note'])


if __name__ == '__main__':
    unittest.main()




