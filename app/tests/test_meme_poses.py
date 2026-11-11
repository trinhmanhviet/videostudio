"""Meme rig phase 1: real-size props, floor placement and body poses (fixtures only, no TTS or render)."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MS = ROOT / 'memestudio'
sys.path.insert(0, str(MS / 'engine'))
import prop_layer  # noqa: E402

LIBRARY = ROOT / 'assets/Meme_Animation_Asset_Pack/catalog/library'
STAGE = {'ground_y': 897, 'unit': 2.6, 'body_half': 104, 'center': 800, 'world_w': 1600}


def boxes(html):
    return [tuple(float(v) for v in m) for m in
            re.findall(r'left:([-\d.]+)px;top:([-\d.]+)px;width:([\d.]+)px;height:([\d.]+)px', html)]


class PropSizeTests(unittest.TestCase):
    sizes = prop_layer.load_sizes(MS / 'assets/prop_sizes.json')

    def test_size_table_covers_the_library_and_rejects_bad_rows(self):
        self.assertEqual(self.sizes['crutches'], (0.62, 'underarm'))
        self.assertGreater(len(self.sizes), 100)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sizes.json'
            path.write_text(json.dumps({'_doc': 'x', 'a': [0.5, 'hand'], 'b': [9, 'hand'], 'c': [0.2, 'fly']}), encoding='utf-8')
            self.assertEqual(prop_layer.load_sizes(path), {'a': (0.5, 'hand')})
        self.assertEqual(prop_layer.load_sizes(Path('missing.json')), {})

    def test_crutch_is_held_at_real_length_with_its_top_near_the_armpit(self):
        path = LIBRARY / 'crutches.png'
        layout = prop_layer.sized_layout(path, self.sizes['crutches'])
        self.assertAlmostEqual(layout['grip_y'], 0.3, delta=0.1)
        props = {'nang': {'asset': 'crutches', 'label': 'Nạng'}}
        beat = {'i': 0, 'start': 0, 'end': 1, 'props': {'nang': {'placement': 'held', 'owner': 'bo'}}}
        scene = {'id': 's', 'start': 0, 'end': 1, 'x': {'bo': 800}, 'beats': [beat]}
        html = prop_layer.layer(props, scene, {'crutches': path}, lambda a, b: b, owner='bo', sizes=self.sizes)
        left, top, width, height = boxes(html)[0]
        _, (l, t, r, b) = prop_layer._image_geometry(path)
        shown = max(r - l, b - t) * width / prop_layer._image_geometry(path)[0][0]
        self.assertAlmostEqual(shown, 0.62 * 192, delta=2)          # rig units, about the size of a person's leg+torso
        self.assertLess(top, -20)                                   # starts above the hand
        self.assertGreater(top + height, 60)                        # and reaches the floor (soles at ~52)

    def test_floor_objects_stand_on_the_ground_next_to_their_character_without_overlaps(self):
        props = {'noi': {'asset': 'cooking_pot', 'label': 'Nồi'}, 'xo': {'asset': 'bucket', 'label': 'Xô'},
                 'ghe': {'asset': 'plastic_stool', 'label': 'Ghế'}}
        library = {k: LIBRARY / f'{k}.png' for k in ('cooking_pot', 'bucket', 'plastic_stool')}
        beat = {'i': 0, 'start': 0, 'end': 1, 'props': {
            'noi': {'placement': 'table', 'near': 'con'}, 'xo': {'placement': 'table', 'near': 'con'},
            'ghe': {'placement': 'held', 'owner': 'bo'}}}                 # too big to hold: stands on the floor
        scene = {'id': 's', 'start': 0, 'end': 1, 'x': {'bo': 560, 'con': 1040}, 'beats': [beat]}
        html = prop_layer.layer(props, scene, library, lambda a, b: b, sizes=self.sizes, stage=STAGE)
        placed = boxes(html)
        self.assertEqual(len(placed), 3)
        spans = []
        for (pid, asset), (left, top, width, height) in zip((('noi', 'cooking_pot'), ('xo', 'bucket'), ('ghe', 'plastic_stool')), placed):
            _, (l, t, r, b) = prop_layer._image_geometry(library[asset])
            k = width / prop_layer._image_geometry(library[asset])[0][0]
            self.assertAlmostEqual(top + b * k, STAGE['ground_y'], delta=0.5)   # visible bottom on the floor
            spans.append((left + l * k, left + r * k))
        bodies = [(x - 104, x + 104) for x in scene['x'].values()]
        for i, (a, b) in enumerate(spans):
            for c, d in spans[i + 1:] + bodies:
                self.assertTrue(b <= c or a >= d, (spans, bodies))
        self.assertLess(abs((spans[0][0] + spans[0][1]) / 2 - 1040), 260)     # the pot is next to "con"
        self.assertEqual(prop_layer.layer(props, scene, library, lambda a, b: b, owner='bo', sizes=self.sizes, stage=STAGE), '')


class PoseSpriteCatalogTests(unittest.TestCase):
    def test_every_drawn_pose_exists_and_its_neck_sits_on_the_drawing(self):
        catalog = json.loads((MS / 'assets/rig/poses/poses.json').read_text(encoding='utf-8'))
        from PIL import Image
        seen = set()
        for item in catalog['items']:
            path = MS / 'assets/rig/poses' / item['file']
            with Image.open(path) as image:
                self.assertEqual(list(image.size), item['size'], item['file'])
                self.assertEqual(image.mode, 'RGBA')
                alpha = image.getchannel('A')
                x, y = (min(max(int(v), 0), s - 1) for v, s in zip(item['neck'], image.size))
                near = alpha.crop((max(0, x - 12), max(0, y - 12), x + 13, y + 13))
                self.assertGreater(max(near.getdata()), 0, f"{item['file']}: neck point off the drawing")
                self.assertGreaterEqual(item['ground'], image.height - 8)
            seen.add((item['costume'], item['pose']))
        for costume in ('ao_ba_lo_trang', 'ao_phong_xanh', 'so_mi_hoc_sinh', 'ao_ba_ba_nau'):
            self.assertEqual({p for c, p in seen if c == costume}, set(catalog['poses']), costume)


class PoseValidationTests(unittest.TestCase):
    def check(self, beats_extra, props=None, costume=None):
        script = json.loads((MS / 'episodes/ep1/script.json').read_text(encoding='utf-8'))
        if costume:
            script['cast']['bo']['costume'] = costume
        script['props'] = props or {'ghe': {'asset': 'plastic_stool', 'label': 'Ghế'}}
        script['beats'] = [dict(script['beats'][0], **beats_extra)]
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'script.json').write_text(json.dumps(script, ensure_ascii=False), encoding='utf-8')
            run = subprocess.run([sys.executable, '-I', str(MS / 'engine/make_episode.py'), folder, '--check'],
                                 capture_output=True, cwd=MS, timeout=120)
            return run.returncode, run.stdout.decode('utf-8', 'replace')

    def test_valid_poses_pass(self):
        code, out = self.check({'pose': {'bo': ['sit', 'ghe'], 'con': ['kneel', 'bo']}})
        self.assertEqual(code, 0, out)
        code, out = self.check({'pose': {'bo': 'lie_front', 'con': ['bend', 'left']}})
        self.assertEqual(code, 0, out)

    def test_drawn_only_poses_need_a_drawing_for_the_costume(self):
        # a costume with no drawn poses (vest): a rig cannot fake a butt pose
        code, out = self.check({'pose': {'bo': ['butt', 'con']}}, costume='vest_den')
        self.assertEqual(code, 1)
        self.assertIn('chưa có hình dáng "butt"', out)
        script_costume = 'ao_ba_lo_trang'
        sprites = json.loads((MS / 'assets/rig/poses/poses.json').read_text(encoding='utf-8'))['items']
        self.assertTrue(any(i['costume'] == script_costume and i['pose'] == 'butt' for i in sprites))

    def test_bad_poses_are_reported(self):
        for pose, words in (({'bo': 'fly'}, 'pose sai'), ({'yta': 'sit'}, 'pose sai'), ({'bo': ['sit', 'nope']}, 'ghế'),
                            ({'bo': ['bend', 'up']}, 'hướng'), ({'bo': ['sit_ground', 'left']}, 'không nhận')):
            code, out = self.check({'pose': pose})
            self.assertEqual(code, 1, pose)
            self.assertIn(words, out, pose)


if __name__ == '__main__':
    unittest.main()
