import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from videostudio.bilingual_captions import ENGLISH_MAX, TITLE_MAX, balanced_lines, translate, write_two_formats
from videostudio.captions import caption_cues, split_caption_text
from videostudio.media import probe, render_pair, scenes_are_wide
from videostudio.output_layout import final_video_path, job_deliverables, publish_pair
from videostudio.providers import PORTRAIT_SIZE, SCENE_SIZE, image_graph, single_frame_prompt, wide_image_prompt, without_vertical_wording


def noop():
    pass


class ImageShapeTests(unittest.TestCase):
    def test_scene_pictures_are_landscape(self):
        latent = image_graph('a cat', 1, 'x')['5']['inputs']
        self.assertEqual((latent['width'], latent['height']), SCENE_SIZE)
        self.assertGreater(SCENE_SIZE[0], SCENE_SIZE[1])

    def test_portrait_stays_available_for_references(self):
        graph = image_graph('a cat', 1, 'x', size=PORTRAIT_SIZE)
        self.assertEqual(graph['5']['inputs']['height'], 1376)
        self.assertNotIn('landscape', graph['4']['inputs']['prompt'])

    def test_landscape_prompt_keeps_the_subject_centred(self):
        self.assertIn('centre', single_frame_prompt('a cat', wide=True))
        self.assertIn('landscape', wide_image_prompt('a cat'))

    def test_vertical_wording_from_the_writer_is_removed(self):
        for text in ('Dark sky. Vertical 9:16 composition. Earth below.', 'Dark sky. 9:16 vertical format. Earth below.', 'Dark sky. Vertical composition. Earth below.'):
            self.assertEqual(without_vertical_wording(text), 'Dark sky. Earth below.')
        self.assertEqual(without_vertical_wording('A portrait of a vertical cliff'), 'A portrait of a vertical cliff')
        self.assertNotIn('9:16', single_frame_prompt('Style. Vertical 9:16 composition. | Scene', wide=True))

    def test_shape_of_a_set_of_scenes(self):
        with tempfile.TemporaryDirectory() as folder:
            wide, tall = Path(folder) / 'w.png', Path(folder) / 't.png'
            Image.new('RGB', (1376, 768)).save(wide)
            Image.new('RGB', (768, 1376)).save(tall)
            self.assertTrue(scenes_are_wide([{'path': wide}, {'path': wide}]))
            self.assertFalse(scenes_are_wide([{'path': tall}, {'path': tall}]))
            self.assertFalse(scenes_are_wide([{'path': Path(folder) / 'missing.png'}]))
            self.assertFalse(scenes_are_wide([]))


class TranslationTests(unittest.TestCase):
    def test_lines_are_kept_in_order_and_saved_for_a_retry(self):
        calls = []

        def llm(prompt, check):
            calls.append(prompt)
            count = int(prompt.split('exactly ')[1].split(' ')[0])
            return {'short_title': 'Tiêu đề ngắn.', 'english': [f'Line {len(calls)}-{k}' for k in range(count)]}

        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / 'b.json'
            texts = [f'Câu {k}' for k in range(45)]
            english, title = translate(llm, 'Tiêu đề', texts, cache, noop)
            self.assertEqual((len(english), title), (45, 'Tiêu đề ngắn'))
            self.assertEqual(len(calls), 2)
            again, _ = translate(llm, 'Tiêu đề', texts, cache, noop)
            self.assertEqual((again, len(calls)), (english, 2))

    def test_wrong_line_count_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                translate(lambda p, c: {'short_title': 'T', 'english': ['one']}, 'T', ['a', 'b'], Path(folder) / 'b.json', noop)

    def test_long_lines_are_asked_again_and_markup_is_removed(self):
        long_line = 'word ' * 40

        def llm(prompt, check):
            if prompt.startswith('Shorten'):
                return {'lines': ['Short {x} now']}
            return {'short_title': 'T', 'english': [long_line]}

        with tempfile.TemporaryDirectory() as folder:
            english, _ = translate(llm, 'T', ['a'], Path(folder) / 'b.json', noop)
        self.assertEqual(english, ['Short x now'])
        self.assertLessEqual(len(english[0]), ENGLISH_MAX)

    def test_long_title_is_cut_on_a_word(self):
        long_title = 'Một tiêu đề rất dài ' * 5

        def llm(prompt, check):
            if prompt.startswith('Shorten'):
                return {'lines': [long_title]}
            return {'short_title': long_title, 'english': ['x']}

        with tempfile.TemporaryDirectory() as folder:
            _, title = translate(llm, 'T', ['a'], Path(folder) / 'b.json', noop)
        self.assertLessEqual(len(title), TITLE_MAX)
        self.assertIn(title.split(' ')[-1], long_title.split(' '))

    def test_translation_never_changes_where_the_voice_pauses(self):
        text = 'Mặt trời tắt ngay lập tức, bóng tối bao trùm khắp nơi và mọi người đều hoảng sợ vì không ai biết chuyện gì đã xảy ra trên bầu trời.'
        before = split_caption_text(text)
        cues = caption_cues([{'start': 0, 'end': 8, 'narration': text}])
        self.assertEqual([cue[2] for cue in cues], before)


class CaptionFileTests(unittest.TestCase):
    def test_lines_are_balanced(self):
        lines = balanced_lines('một hai ba bốn năm sáu bảy tám', 22)
        self.assertEqual(len(lines), 2)
        self.assertLessEqual(abs(len(lines[0]) - len(lines[1])), 6)

    def test_vertical_captions_carry_both_languages_and_the_title(self):
        with tempfile.TemporaryDirectory() as folder:
            result = write_two_formats([(0, 2, 'Xin chào các bạn')], ['Hello everyone'], 'Tiêu đề', 2, folder)
            doc = Path(result['doc']).read_text(encoding='utf8')
            self.assertFalse((Path(folder) / 'subtitles-ngang.ass').exists())
        for words in ('Xin chào các bạn', 'Hello everyone', 'Tiêu đề'):
            self.assertIn(words, doc)

    def test_count_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            write_two_formats([(0, 2, 'a')], [], 'T', 2, folder)


class PublishTests(unittest.TestCase):
    def _job(self, root, job_id, project='Khi mặt trời tắt'):
        output = Path(root) / 'data' / job_id
        output.mkdir(parents=True)
        return {'id': job_id, 'output': str(output), 'request': {'project': project}, 'checkpoints': {}}

    def _rendered(self, job):
        doc, wide = Path(job['output']) / 'video.mp4', Path(job['output']) / 'video-ngang.mp4'
        doc.write_bytes(b'doc')
        wide.write_bytes(b'wide')
        return {'video': str(doc), 'video_ngang': str(wide), 'assets': []}

    def test_names_have_no_accents_and_a_second_job_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            first = publish_pair(self._job(root, 'one'), self._rendered(self._job(root, 'a')))
            self.assertEqual(Path(first['video']).name, 'khi-mat-troi-tat_doc.mp4')
            self.assertEqual(Path(first['video_ngang']).name, 'khi-mat-troi-tat_ngang.mp4')
            second = publish_pair(self._job(root, 'two'), self._rendered(self._job(root, 'b')))
            self.assertEqual(Path(second['video']).name, 'khi-mat-troi-tat-2_doc.mp4')
            self.assertEqual(Path(first['video']).read_bytes(), b'doc')

    def test_a_new_render_of_the_same_job_replaces_its_pair(self):
        with tempfile.TemporaryDirectory() as root:
            job = self._job(root, 'one')
            first = publish_pair(job, self._rendered(job))
            second = publish_pair(job, self._rendered(job))
            self.assertEqual(first['video'], second['video'])

    def test_both_files_belong_to_the_job(self):
        with tempfile.TemporaryDirectory() as root:
            job = self._job(root, 'one')
            job['checkpoints']['render'] = publish_pair(job, self._rendered(job))
            self.assertEqual(final_video_path(job), Path(job['checkpoints']['render']['video']))
            names = {path.name for path in job_deliverables(job)}
            self.assertEqual(names, {'khi-mat-troi-tat_doc.mp4', 'khi-mat-troi-tat_ngang.mp4'})


class RenderPairTests(unittest.TestCase):
    def test_two_real_videos_from_one_picture_track(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            image = p / 'scene.png'
            Image.effect_noise((1376, 768), 90).convert('RGB').save(image)
            for name, source in (('speech.wav', 'sine=f=300:d=2'), ('music.wav', 'sine=f=200:d=2')):
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', source, str(p / name)], check=True)
            captions = write_two_formats([(0, 2, 'Xin chào các bạn')], ['Hello everyone'], 'Tiêu đề', 2, p)
            result = render_pair([{'path': str(image), 'duration': 2}], p / 'speech.wav', p / 'music.wav', captions, p, 2, noop)
            sizes = []
            for path in (result['video'], result['video_ngang']):
                video = next(s for s in probe(path)['streams'] if s['codec_type'] == 'video')
                sizes.append((video['width'], video['height']))
            self.assertEqual(sizes, [(1080, 1920), (1920, 1080)])
            self.assertEqual(json.loads(json.dumps(result))['video'], result['video'])


if __name__ == '__main__':
    unittest.main()
