import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from videostudio.providers import DISTINCT_CHARACTERS, Pipeline, SCENE_SIZE


def job(folder, **request):
    return {'id': '11111111-2222-3333-4444-555555555555', 'output': str(folder), 'events': [],
            'request': {'image_provider': 'comfy', **request},
            'checkpoints': {'plan': {'visual_style': 'Cinematic documentary', 'characters': [
                {'character_id': 'mai', 'name': 'Mai', 'description': 'Slim woman, 30, short red bob, green raincoat.'},
                {'character_id': 'tuan', 'name': 'Tuấn', 'description': 'Heavy-set man, 50, shaved head, grey suit.'},
                {'character_id': 'extra', 'name': 'Khách', 'description': 'Tall teenager, curly hair, yellow hoodie.'},
            ]}}}


SCENES = [{'visual_prompt': 'Mai at the door', 'character_ids': ['mai']},
          {'visual_prompt': 'Mai and Tuấn argue', 'character_ids': ['mai', 'tuan', 'extra']},
          {'visual_prompt': 'Empty street', 'character_ids': []}]


class ComfyCharacterReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.pipeline = Pipeline.__new__(Pipeline)
        self.pipeline.comfy = 'http://127.0.0.1:8188'
        self.made = []

        def comfy_asset(j, kind, graph, path, check):
            self.made.append((kind, graph))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (64, 96), (len(self.made) * 40 % 255, 90, 120)).save(path)
            return {'prompt_id': kind}
        self.pipeline.comfy_asset = comfy_asset

    def tearDown(self):
        self.tmp.cleanup()

    def prompt_of(self, graph):
        return graph['4']['inputs']['prompt']

    def test_each_on_screen_character_gets_one_reusable_portrait(self):
        refs = self.pipeline._comfy_character_references(job(self.folder), SCENES, lambda: None)
        self.assertEqual(set(refs), {'mai', 'tuan', 'extra'})
        self.assertEqual(len(self.made), 3)
        self.assertIn('short red bob, green raincoat', self.prompt_of(self.made[0][1]))
        self.assertIn('Knee-up portrait, three-quarter view', self.prompt_of(self.made[0][1]))
        again = self.pipeline._comfy_character_references(job(self.folder), SCENES, lambda: None)
        self.assertEqual(len(self.made), 3)
        self.assertEqual(again, refs)

    def test_portrait_keeps_only_the_leading_look_of_a_storyboard_style(self):
        value = job(self.folder)
        value['checkpoints']['plan']['visual_style'] = 'Realistic documentary photography, vertical 9:16. Begin with a 35mm wide shot, then a close-up.'
        self.pipeline._comfy_character_references(value, SCENES[:1], lambda: None)
        prompt = self.prompt_of(self.made[0][1])
        self.assertIn('Realistic documentary photography.', prompt)
        self.assertNotIn('35mm', prompt)
        self.assertNotIn('9:16', prompt)

    def test_changed_description_redraws_only_that_portrait(self):
        self.pipeline._comfy_character_references(job(self.folder), SCENES, lambda: None)
        changed = job(self.folder)
        changed['checkpoints']['plan']['characters'][1]['description'] = 'Thin man, 50, long white ponytail, black coat.'
        self.pipeline._comfy_character_references(changed, SCENES, lambda: None)
        self.assertEqual([kind for kind, _ in self.made[3:]], ['images-character-01'])

    def test_references_can_be_turned_off_and_unused_characters_are_skipped(self):
        self.assertEqual(self.pipeline._comfy_character_references(job(self.folder, references_enabled=False), SCENES, lambda: None), {})
        refs = self.pipeline._comfy_character_references(job(self.folder), SCENES[:1], lambda: None)
        self.assertEqual(set(refs), {'mai'})

    def test_scene_uses_at_most_two_references_on_a_landscape_canvas(self):
        refs = self.pipeline._comfy_character_references(job(self.folder), SCENES, lambda: None)
        uploads = []

        def upload(base, job_id, selected, folder, check, canvas=None):
            uploads.append(([r['character_id'] for r in selected], canvas))
            return [f'ref-{r["character_id"]}.png' for r in selected], []
        with patch('videostudio.comfy_references.upload_references', upload):
            graph, used = self.pipeline._comfy_scene_graph(job(self.folder), SCENES[1], 1, 'prefix', refs, lambda: None)
            plain, none = self.pipeline._comfy_scene_graph(job(self.folder), SCENES[2], 2, 'prefix', refs, lambda: None)
        self.assertEqual(uploads, [(['mai', 'tuan'], SCENE_SIZE)])
        self.assertEqual(used, [refs['mai']['portrait_sha256'], refs['tuan']['portrait_sha256']])
        self.assertTrue(self.prompt_of(graph).startswith('Use the supplied images only for each person'))
        self.assertIn('Reference image 1: Mai. Reference image 2: Tuấn.', self.prompt_of(graph))
        self.assertIn('never copy their pose, expression', self.prompt_of(graph))
        self.assertEqual(graph['4']['inputs']['images.image_2'][0], '11')
        self.assertEqual(none, [])
        self.assertNotIn('images.image_1', plain['4']['inputs'])

    def test_planning_rule_demands_distinct_concrete_looks(self):
        self.assertIn('clearly different', DISTINCT_CHARACTERS)
        self.assertIn('never write that they are unspecified', DISTINCT_CHARACTERS)


if __name__ == '__main__':
    unittest.main()
