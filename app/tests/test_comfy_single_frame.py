import unittest

from videostudio.providers import ANTI_COLLAGE, SINGLE_FRAME, image_graph, single_frame_prompt


STYLE = ('Phim tài liệu điều tra tội phạm, phong cách cinematic documentary realism. Bối cảnh Trung Quốc năm 2009. '
         'Ưu tiên hình ảnh tư liệu hóa, bản đồ địa lý, camera giao thông, hồ sơ ngân hàng, nhật ký cuộc gọi.')
PROMPT = STYLE + ' | Tổ điều tra: cảnh sát | Interior of the villa at night, investigators examining blood traces.'


class ComfySingleFrameTests(unittest.TestCase):
    def test_scene_comes_first_and_style_lists_are_dropped(self):
        out = single_frame_prompt(PROMPT)
        self.assertTrue(out.startswith('Interior of the villa at night'))
        self.assertIn('Tổ điều tra: cảnh sát', out)
        self.assertIn('Visual style: Phim tài liệu', out)
        self.assertNotIn('camera giao thông', out)
        self.assertNotIn('Giai đoạn', single_frame_prompt('A. Tỷ lệ 9:16 dọc. Giai đoạn 2: phố, tuyết. | scene'))
        self.assertTrue(out.endswith(SINGLE_FRAME))

    def test_quality_notes_stay_after_scene(self):
        out = single_frame_prompt(STYLE + ' | Scene: a man at a desk | Scene intent: worry | Must show: phone')
        parts = out.split(' | ')
        self.assertEqual(parts[0], 'Scene: a man at a desk')
        self.assertLess(parts.index('Scene intent: worry'), parts.index(SINGLE_FRAME))

    def test_rewrite_is_idempotent_and_keeps_plain_prompts(self):
        once = single_frame_prompt(PROMPT)
        self.assertEqual(single_frame_prompt(once), once)
        self.assertEqual(single_frame_prompt('a cat on a sofa'), 'a cat on a sofa | No blood, open wounds or exposed human remains. | ' + SINGLE_FRAME)

    def test_graph_always_carries_anti_collage_negative(self):
        graph = image_graph(PROMPT, 1, 'x', negative_prompt='blur, watermark')
        texts = [n['inputs'] for n in graph.values() if isinstance(n, dict) and 'inputs' in n]
        negative = ' '.join(str(i.get('negative_prompt', '')) for i in texts)
        for term in ANTI_COLLAGE:
            self.assertIn(term, negative)
        self.assertIn('blur, watermark', negative)
        self.assertIn(SINGLE_FRAME, str(graph))


if __name__ == '__main__':
    unittest.main()
