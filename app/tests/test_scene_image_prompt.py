import unittest

from videostudio.providers import (NATURAL_ACTING, SHOT_VARIETY, SINGLE_FRAME, WIDE_FRAME, scene_image_prompt,
                                   wide_image_prompt)

MAI = 'A 30-year-old slim woman with a short red bob, a green raincoat and black rubber boots.'
TUAN = 'A heavy-set 50-year-old man with a shaved head, a grey suit and round glasses.'
STYLE = ('Realistic documentary photography, vertical 9:16, rural Guangxi in 2007. '
         'VISUAL GROUPING: group lines by location, time, subject, action. Keep all images vertical 9:16.')
SCENE = (f'Close-up, low angle. Mai grips the stick and glares at Tuấn. Mai: {MAI} Tuấn: {TUAN} '
         'A single bare bulb lights the room, vertical 9:16.')
PROMPT = ' | '.join([STYLE, f'Mai: {MAI}; Tuấn: {TUAN}', SCENE])


class SceneImagePromptTests(unittest.TestCase):
    def test_action_first_each_look_once_and_no_editing_rules(self):
        out = scene_image_prompt(PROMPT)
        self.assertTrue(out.startswith('Close-up, low angle. Mai grips the stick'))
        self.assertEqual(out.count(MAI), 1)
        self.assertEqual(out.count(TUAN), 1)
        self.assertIn(NATURAL_ACTING, out)
        self.assertNotIn('VISUAL GROUPING', out)
        self.assertNotIn('9:16', out)
        self.assertTrue(out.endswith(WIDE_FRAME + ' | ' + SINGLE_FRAME))

    def test_every_provider_gets_the_same_content(self):
        compact = scene_image_prompt(PROMPT)
        self.assertEqual(scene_image_prompt(compact), compact)
        self.assertTrue(wide_image_prompt(PROMPT).endswith(compact))
        portrait = scene_image_prompt(PROMPT, wide=False)
        self.assertTrue(portrait.startswith('Close-up, low angle. Mai grips the stick'))
        self.assertNotIn(WIDE_FRAME, portrait)

    def test_scene_without_people_has_no_acting_note(self):
        out = scene_image_prompt(STYLE + ' | Extreme close-up of a muddy sack beside the pigsty.')
        self.assertNotIn(NATURAL_ACTING, out)

    def test_planning_asks_for_varied_dramatic_shots(self):
        self.assertIn('close-ups', SHOT_VARIETY)
        self.assertIn('Never two similar shots in a row', SHOT_VARIETY)


if __name__ == '__main__':
    unittest.main()
