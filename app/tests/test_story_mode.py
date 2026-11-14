import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from videostudio import story_pipeline
from videostudio.core import validate_request
from videostudio.story_library import ConflictError, StoryLibrary, split_chapters, split_heading
from videostudio.story_pipeline import build_units, caption_cues, cut_plan

FFMPEG = shutil.which('ffmpeg')


class StoryLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.library = StoryLibrary(root / 'story', root / 'gameplay')

    def tearDown(self):
        self.tmp.cleanup()

    def test_heading_is_metadata_only_when_clear(self):
        self.assertEqual(split_heading('Chương 3: Lá thư\n\nNội dung.')[:2], (3, 'Lá thư'))
        self.assertEqual(split_heading('Một dòng mở đầu.\nNội dung.')[2], 'Một dòng mở đầu.\nNội dung.')
        title, chapters = split_chapters('Tên truyện\n\nChương 1: A\n\nMột.\n\nChương 2: B\n\nHai.')
        self.assertEqual((title, [c['title'] for c in chapters]), ('Tên truyện', ['A', 'B']))

    def test_import_natural_order_dedupe_revision_and_conflict(self):
        book = self.library.create_book('Truyện thử')
        files = [{'name': '10.txt', 'text': 'Chương 10: Mười\n\nMười.'}, {'name': '2.txt', 'text': 'Hai.'}, {'name': '1.txt', 'text': 'Một.'}]
        self.assertEqual(self.library.import_files(book['id'], files)['added'], 3)
        listing = self.library.chapters(book['id'])
        self.assertEqual([c['title'] for c in listing['items']], ['1', '2', 'Mười'])
        self.assertEqual(self.library.import_files(book['id'], files)['skipped'], 3)
        self.assertEqual(self.library.import_files(book['id'], [{'name': '2.txt', 'text': 'Hai, bản sửa.'}])['updated'], 1)
        chapter = self.library.chapter(listing['items'][0]['id'])
        saved = self.library.save_chapter(chapter['id'], {'text': 'Một, đã sửa.', 'expected_revision': chapter['revision']})
        with self.assertRaises(ConflictError):
            self.library.save_chapter(chapter['id'], {'text': 'Cũ', 'expected_revision': chapter['revision']})
        self.assertEqual(saved['revision'], chapter['revision'] + 1)

    def test_reimport_never_overwrites_a_chapter_the_user_edited(self):
        book = self.library.create_book('Truyện thử')
        self.library.import_files(book['id'], [{'name': 'gop.txt', 'text': 'Chương 1: A\n\nBản máy.\n\nChương 2: B\n\nHai.'}])
        first = self.library.chapters(book['id'])['items'][0]
        self.library.save_chapter(first['id'], {'text': 'Bản người dùng sửa.'})
        result = self.library.import_files(book['id'], [{'name': 'gop.txt', 'text': 'Chương 1: A\n\nBản máy mới.\n\nChương 2: B\n\nHai, mới.'}])
        self.assertEqual((result['kept'], result['updated']), (1, 1))
        self.assertEqual(self.library.chapter(first['id'])['text'], 'Bản người dùng sửa.')
        history = self.library.history(first['id'])
        self.assertEqual(history[0]['reason'], 'trước khi lưu')
        restored = self.library.restore(first['id'], history[0]['revision'])
        self.assertEqual(restored['text'], 'Bản máy.')

    def test_freeze_is_immutable_and_idempotent(self):
        book = self.library.create_book('Truyện thử')
        self.library.import_files(book['id'], [{'name': '1.txt', 'text': 'Một câu.'}])
        chapter = self.library.chapters(book['id'])['items'][0]
        first = self.library.freeze(book['id'], [chapter['id']], 'key-1')
        self.library.save_chapter(chapter['id'], {'text': 'Đã đổi sau khi xếp hàng.'})
        self.assertEqual(self.library.freeze(book['id'], [chapter['id']], 'key-1')['sha256'], first['sha256'])
        self.assertEqual(self.library.snapshot(first['sha256'])['chapters'][0]['text'], 'Một câu.')


class StoryUnitsTests(unittest.TestCase):
    def snapshot(self, text, read_title=True):
        return {'chapters': [{'order': 1, 'number': 1, 'title': 'Cánh cổng cũ', 'read_title': read_title, 'text': text}]}

    def test_units_keep_every_word_and_mark_pauses(self):
        text = 'Chiều hôm ấy, Minh trở về. Con đường vẫn thế.\n\n— Có ai ở ngoài cửa đấy?\n\n***\n\nSáng hôm sau trời mưa.'
        units = build_units(self.snapshot(text))
        self.assertEqual(units[0]['text'], 'Chương 1. Cánh cổng cũ.')
        spoken = ' '.join(u['text'] for u in units[1:])
        for word in ('Chiều', 'Minh', 'Có ai ở ngoài cửa đấy?', 'Sáng hôm sau trời mưa.'):
            self.assertIn(word, spoken)
        self.assertNotIn('***', spoken)
        self.assertNotIn('—', spoken)
        question = next(u for u in units if u['text'].startswith('Có ai'))
        self.assertEqual(question['pause'], story_pipeline.PAUSE['scene'])

    def test_long_paragraph_is_grouped_without_cutting_words(self):
        sentence = 'Cô bước chậm qua con ngõ nhỏ, nghe tiếng lá xào xạc dưới chân. '
        units = build_units(self.snapshot(sentence * 12, read_title=False))
        self.assertTrue(all(len(u['text']) <= story_pipeline.UNIT_CHARS + 80 for u in units))
        self.assertEqual(' '.join(u['text'] for u in units).split(), (sentence * 12).split())

    def test_captions_split_display_only(self):
        ledger = [{'kind': 'text', 'text': 'Một hai ba bốn năm sáu bảy tám chín mười mười một mười hai.', 'start': 0, 'speech_end': 4, 'end': 4.6}]
        cues = caption_cues(ledger, 14)
        self.assertGreater(len(cues), 1)
        self.assertEqual(' '.join(' '.join(c['lines']) for c in cues), ledger[0]['text'])
        self.assertTrue(all(len(c['lines']) <= 2 for c in cues))
        self.assertAlmostEqual(cues[0]['start'], 0)


class GameplayPlanTests(unittest.TestCase):
    clips = [{'id': 'a', 'sha256': 'a', 'path': 'a.mp4', 'name': 'a', 'start': 0, 'end': 30},
             {'id': 'b', 'sha256': 'b', 'path': 'b.mp4', 'name': 'b', 'start': 5, 'end': 15}]

    def test_plan_fills_length_loops_and_continues(self):
        segments, cursor, loops = cut_plan(self.clips, {'clip': 0, 'offset': 0}, 45)
        self.assertAlmostEqual(sum(s['length'] for s in segments), 45)
        self.assertEqual([s['id'] for s in segments], ['a', 'b', 'a'])
        self.assertEqual(loops, 1)
        again, _, _ = cut_plan(self.clips, cursor, 3)
        self.assertEqual((again[0]['id'], again[0]['start']), ('a', 5.0))

    def test_plan_is_deterministic(self):
        self.assertEqual(cut_plan(self.clips, {'clip': 1, 'offset': 2}, 20), cut_plan(self.clips, {'clip': 1, 'offset': 2}, 20))


class StoryRequestTests(unittest.TestCase):
    def test_story_request_requires_snapshot_hash(self):
        base = {'idea': 'Kể truyện', 'voice_id': 'v', 'duration_seconds': 60, 'workflow_mode': 'story_narration', 'content_style': 'story'}
        with self.assertRaises(ValueError):
            validate_request(base)
        self.assertEqual(validate_request({**base, 'story_snapshot': 'a' * 64})['story_snapshot'], 'a' * 64)
        with self.assertRaises(ValueError):
            validate_request({'idea': 'x', 'voice_id': 'v', 'duration_seconds': 60, 'story_snapshot': 'a' * 64})


@unittest.skipUnless(FFMPEG, 'FFmpeg required')
class StoryRenderTests(unittest.TestCase):
    """Short real FFmpeg run (about 4 seconds of output) through the gameplay, subtitle, render and verify stages."""

    def test_short_episode_renders_both_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / 'game.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=25:d=3', '-pix_fmt', 'yuv420p', str(clip)], check=True)
            output = root / 'Book' / 'data' / 'job1'
            output.mkdir(parents=True)
            narration = output / 'story-narration.wav'
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=f=220:d=4', '-ar', '24000', '-ac', '1', str(narration)], check=True)
            snapshot = {'book': {'id': 'book', 'title': 'Chuyến trở về'}, 'layout': {'channel': 'Truyện đêm', 'horizontal': True, 'vertical': True,
                        'burn_subtitles': True, 'export_srt': True, 'export_mp3': True, 'game_audio': False, 'continue_gameplay': False},
                        'chapters': [{'id': 'c1', 'order': 1, 'number': 1, 'title': 'Cánh cổng cũ', 'read_title': True, 'text': 'x'}],
                        'gameplay': [{'id': 'g', 'sha256': 'g', 'name': 'game.mp4', 'path': str(clip), 'start': 0, 'end': 3, 'has_audio': False}],
                        'background': None, 'background_preset': {'top': '0x0b1a33', 'bottom': '0x1d3b63'}}
            (output / 'story-snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
            ledger = [{'id': 'u0', 'text': 'Chiều hôm ấy, Minh trở về làng sau năm năm xa nhà.', 'kind': 'text', 'chapter': 0,
                       'start': 0, 'speech_end': 3.5, 'end': 4.0}]
            (output / 'story-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
            pipeline = SimpleNamespace(ffmpeg=FFMPEG, ffprobe=shutil.which('ffprobe'), store=None)
            job = {'id': 'job1', 'output': str(output), 'request': {}, 'checkpoints': {'speech': {'path': str(narration), 'duration_seconds': 4.0}}}
            original = story_pipeline.StoryLibrary
            story_pipeline.StoryLibrary = lambda: SimpleNamespace(cursor=lambda b: {'clip': 0, 'offset': 0}, advance_cursor=lambda *a: None)
            try:
                job['checkpoints']['images'] = story_pipeline.images(pipeline, job, lambda: None)
                job['checkpoints']['subtitles'] = story_pipeline.subtitles(pipeline, job, lambda: None)
                job['checkpoints']['render'] = story_pipeline.render(pipeline, job, lambda: None)
                result = story_pipeline.verify(pipeline, job, lambda: None)
            finally:
                story_pipeline.StoryLibrary = original
            self.assertTrue(result['verified'])
            names = sorted(p.name for p in (root / 'Book').iterdir() if p.is_file())
            self.assertEqual(names, ['chuong-001-canh-cong-cu-v1.mp3', 'chuong-001-canh-cong-cu-v1_anh-bia.jpg', 'chuong-001-canh-cong-cu-v1_dang-bai.txt',
                                     'chuong-001-canh-cong-cu-v1_doc.mp4', 'chuong-001-canh-cong-cu-v1_doc.srt',
                                     'chuong-001-canh-cong-cu-v1_ngang.mp4', 'chuong-001-canh-cong-cu-v1_ngang.srt'])
            kit = (root / 'Book' / 'chuong-001-canh-cong-cu-v1_dang-bai.txt').read_text(encoding='utf-8')
            self.assertIn('Chuyến trở về · Chương 1: Cánh cổng cũ', kit)
            self.assertIn('#truyenaudio', kit)
            plan = json.loads((output / 'story-gameplay' / 'plan.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(len(plan['segments']), 2)  # 3-second clip looped to cover 4.5 seconds


if __name__ == '__main__':
    unittest.main()
