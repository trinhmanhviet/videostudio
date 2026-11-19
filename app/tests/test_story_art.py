import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from videostudio import story_art, story_pipeline
from videostudio.story_library import validate_layout

SHEET = {'genre': 'trọng sinh', 'style': 'Manhua. Keep faces.', 'characters': [
    {'name': 'Bạch Thù Văn', 'role': 'nữ chính', 'look': 'girl'}, {'name': 'Giang Thự', 'role': 'nam chính', 'look': 'boy'}]}


def ledger(count=40, step=20.0):
    return [{'text': f'Câu {i}.', 'start': i * step, 'end': i * step + step - 1} for i in range(count)]


class StoryArtTests(unittest.TestCase):
    def test_stretches_start_at_zero_are_long_enough_and_have_one_key_moment(self):
        answer = {'doan': [
            {'tu': 3, 'canh': 'Rain on the street.', 'nhan_vat_trong_anh': ['Bạch Thù Văn'], 'chinh': False},
            {'tu': 4, 'canh': 'Too soon after the first.', 'chinh': True},            # 20 s later: joined, its key mark kept
            {'tu': 15, 'canh': 'At school.', 'nhan_vat_trong_anh': ['Giang Thự', 'Bạch Thù Văn'], 'chinh': True},
            {'tu': 99, 'canh': 'Out of range.'},
            {'tu': 25, 'canh': 'Night, a letter.', 'nhan_vat_trong_anh': ['Người lạ'],
             'nhan_vat_moi': [{'ten': 'Người lạ', 'vai': 'bạn thân', 'ngoai_hinh': 'tall man'}]},
            {'tu': 39, 'canh': 'The very last sentence.'},                           # 20 s before the end: joined
        ]}
        stretches = story_art.check_segments(answer, ledger(), SHEET, 800.0)
        self.assertEqual([s['index'] for s in stretches], [0, 15, 25])
        self.assertEqual([s['start'] for s in stretches], [0.0, 300.0, 500.0])
        self.assertEqual(sum(s['key'] for s in stretches), 1)
        self.assertEqual(stretches[1]['people'], ['Giang Thự', 'Bạch Thù Văn'])
        self.assertEqual([p['name'] for p in stretches[2]['new']], ['Người lạ'])
        with self.assertRaises(ValueError):
            story_art.check_segments({'doan': []}, ledger(), SHEET, 800.0)

    def test_a_chapter_gets_about_one_picture_per_two_and_a_half_minutes(self):
        self.assertEqual(story_art.stretch_count(720), (4, 6))
        self.assertEqual(story_art.stretch_count(120), (3, 4))
        self.assertEqual(story_art.stretch_count(3600), (5, 6))

    def test_background_crossfades_at_the_stretches_on_the_video_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            segments = []
            for number, color in enumerate(('red', 'green', 'blue')):
                path = folder / f'seg-{number}.png'
                Image.new('RGB', (1376, 768), color).save(path)
                segments.append({'start': [0.0, 100.0, 250.0][number], 'path': str(path), 'sha256': f'{number:064d}', 'key': number == 1})
            # the stills go into the job's folder, which does not exist yet (chapter 1 failed on this, 2026-11-19)
            inputs, graph, count = story_art.background(segments, 'ngang', folder / 'job' / 'story-art', 400.0, 2.5, 30)
            self.assertEqual(count, 3)
            self.assertEqual(inputs.count('-i'), 3)
            self.assertEqual([inputs[i + 1] for i, v in enumerate(inputs) if v == '-t'], ['103.500', '151.000', '147.500'])
            self.assertIn('xfade=transition=fade:duration=1.0:offset=102.500', graph)
            self.assertIn('offset=252.500', graph)
            self.assertTrue(graph.endswith('null[bg]'))
            with Image.open(story_art.frames(segments, 'doc', folder)[0]) as frame:
                self.assertEqual(frame.size, (1080, 1920))
                self.assertEqual(frame.getpixel((540, 300))[0], 255)    # the sharp picture at the top
                self.assertLess(frame.getpixel((540, 1700))[0], 140)    # blurred and darkened below

    def test_landscape_over_pictures_has_no_burned_subtitles_and_titles_at_the_top_left(self):
        snapshot = {'book': {'title': 'Trọng Sinh'}, 'layout': {'channel': ''},
                    'chapters': [{'number': 1, 'order': 1, 'title': 'Trọng sinh'}]}
        cues = [{'start': 1.0, 'end': 2.0, 'lines': ['Xin chào']}]
        with tempfile.TemporaryDirectory() as folder:
            wide = story_pipeline.write_ass(Path(folder) / 'a.ass', 'ngang', snapshot, cues, False, layout=story_pipeline.art_layout('ngang')).read_text(encoding='utf-8')
            tall = story_pipeline.write_ass(Path(folder) / 'b.ass', 'doc', snapshot, cues, True, layout=story_pipeline.art_layout('doc')).read_text(encoding='utf-8')
        self.assertIn('\\an7\\pos(60,62)', wide)
        self.assertNotIn('Xin chào', wide)
        self.assertIn('Xin chào', tall)
        self.assertIn('\\pos(540,1250)', tall)
        self.assertIn('\\pos(540,1410)', tall)     # the chapter under a two-line book name
        self.assertEqual(story_pipeline.art_layout('ngang')['game'], (40, 534, 900, 506))   # the lower-left quarter

    def test_books_turn_story_pictures_on_in_their_layout(self):
        self.assertEqual(validate_layout({'story_art': True}), {'story_art': True})
        with self.assertRaises(ValueError):
            validate_layout({'story_art': 'yes'})


if __name__ == '__main__':
    unittest.main()
