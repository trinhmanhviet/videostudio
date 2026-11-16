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
from videostudio.story_api import group_by_length
from videostudio.story_lint import lint
from videostudio.story_library import ConflictError, StoryLibrary, split_chapters, split_heading, validate_layout, validate_settings
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

    def test_rerender_keeps_text_and_gameplay_but_takes_the_new_look(self):
        book = self.library.create_book('Truyện thử')
        self.library.import_files(book['id'], [{'name': '1.txt', 'text': 'Một câu.'}])
        chapter = self.library.chapters(book['id'])['items'][0]
        old = self.library.freeze(book['id'], [chapter['id']], 'key-1')
        self.library.save_chapter(chapter['id'], {'text': 'Đã đổi sau khi làm video.'})
        self.library.update_book(book['id'], {'layout': {'channel': 'Kênh mới', 'video_codec': 'h264', 'cover_text': False}})
        plan = {'seconds': 12.0, 'segments': [], 'loops': 0}
        again = self.library.freeze_rerender(old, 'rerender-1', plan)
        self.assertNotEqual(again['sha256'], old['sha256'])
        self.assertEqual(again['chapters'][0]['text'], 'Một câu.')
        self.assertEqual((again['layout']['channel'], again['layout']['video_codec'], again['layout']['cover_text']), ('Kênh mới', 'h264', False))
        self.assertEqual(again['gameplay_plan'], plan)
        self.assertEqual(self.library.freeze_rerender(old, 'rerender-1', plan)['sha256'], again['sha256'])

    def test_settings_and_layout_validation_for_dictionary_and_cover(self):
        rules = validate_settings({'pronunciations': [{'from': ' CEO ', 'to': 'xi i ô'}, {'from': 'A', 'to': 'A'}, {'from': '', 'to': 'x'}]})['pronunciations']
        self.assertEqual(rules, [{'from': 'CEO', 'to': 'xi i ô'}])
        with self.assertRaises(ValueError):
            validate_settings({'pronunciations': [{'from': 'x'}]})
        self.assertEqual(validate_layout({'cover_source': 'image', 'cover_at': 0.5})['cover_at'], 0.5)
        for bad in ({'cover_source': 'web'}, {'cover_at': 1.5}, {'cover_text': 'yes'}, {'intro': 1}):
            with self.assertRaises(ValueError):
                validate_layout(bad)
        self.assertFalse(validate_layout({'intro': False})['intro'])
        self.assertTrue(self.library.book(self.library.create_book('Truyện thử')['id'])['layout']['intro'])

    def test_title_intro_animates_each_letter_and_waits_for_it(self):
        snapshot = {'book': {'id': 'b', 'title': 'Trọng sinh: Công lược'}, 'layout': {'channel': 'Kênh'},
                    'chapters': [{'id': 'c1', 'order': 1, 'number': 1, 'title': 'Trọng sinh', 'read_title': True, 'text': 'x'}]}
        # Last letter lands, half a second of hold, the fade-out: then the story starts.
        landed = max(start for _, _, starts, _ in story_pipeline._intro_flights(snapshot) for _, start in starts) + story_pipeline.INTRO_FLIGHT_MS
        intro = story_pipeline.intro_seconds(snapshot)
        self.assertAlmostEqual(intro, (landed + 500 + story_pipeline.INTRO_FADE_OUT_MS) / 1000, delta=.01)
        self.assertEqual(story_pipeline.hold_first_frame(1.5), ',tpad=start_duration=1.500:start_mode=clone')
        self.assertEqual(story_pipeline.hold_first_frame(0), '')
        self.assertEqual(story_pipeline.intro_seconds({**snapshot, 'layout': {'intro': False}}), 0)
        self.assertEqual(story_pipeline.intro_seconds({**snapshot, 'audio_only': True}), 0)
        # Decomposed accents stay with their letter.
        self.assertEqual(story_pipeline._graphemes('Tro\u0323ng'), ['T', 'r', 'ọ', 'n', 'g'])
        cues = [{'start': 0.0, 'end': 2.0, 'lines': ['Một câu.']}]
        with tempfile.TemporaryDirectory() as tmp:
            for orientation in ('ngang', 'doc'):
                plain = story_pipeline.write_ass(Path(tmp) / 'a.ass', orientation, snapshot, cues, True).read_text(encoding='utf-8')
                self.assertNotIn('IntroBook', plain)
                self.assertIn('Dialogue: 1,0:00:00.00', plain)
                shifted = story_pipeline.shift_cues(cues, intro)
                text = story_pipeline.write_ass(Path(tmp) / 'b.ass', orientation, snapshot, shifted, True, intro=intro).read_text(encoding='utf-8')
                letters = len([c for c in 'TRỌNG SINH: CÔNG LƯỢC' if c != ' ']) + len([c for c in 'Chương 1: Trọng sinh' if c != ' '])
                self.assertEqual(text.count('\\move('), 2 * letters)  # outline + fill per letter
                self.assertEqual(text.count('\\p1}'), 1)  # one dark band
                self.assertNotIn('Dialogue: 1,0:00:00.00', text)  # top titles wait for the intro to leave
                at = story_pipeline._ass_time(intro)
                self.assertIn(f'Dialogue: 0,{at},{story_pipeline._ass_time(intro + 2)},Caption', text)
                self.assertIn(f'Dialogue: 1,{at},', text)  # top titles return with the story
                self.assertIn(f'Dialogue: 5,0:00:00.00,{at},', text)  # the intro is gone by then

    def test_listing_counts_writing_issues_and_filters_them(self):
        book = self.library.create_book('Truyện thử')
        self.library.import_files(book['id'], [{'name': 'gop.txt', 'text': 'Chương 1: A\n\nSạch sẽ.\n\nChương 2: B\n\nCô…… đi~'}])
        listing = self.library.chapters(book['id'])
        self.assertEqual([c['issues'] for c in listing['items']], [0, 2])
        self.assertEqual([c['title'] for c in self.library.chapters(book['id'], status='issues')['items']], ['B'])
        detail = self.library.chapter(listing['items'][1]['id'])
        self.assertEqual([i['code'] for i in detail['lint']], ['ellipsis_mid', 'tilde'])

    def test_finished_videos_move_chapters_to_the_done_tab(self):
        book = self.library.create_book('Truyện thử')
        self.library.import_files(book['id'], [{'name': 'gop.txt', 'text': ''.join(f'Chương {n}: C{n}\n\nCâu {n}.\n\n' for n in range(1, 6))}])
        ids = self.library.chapters(book['id'])['all_ids']
        single = self.library.freeze(book['id'], [ids[0]], 'one')
        merged = self.library.freeze(book['id'], ids[2:4], 'merged')
        audio = self.library.freeze(book['id'], [ids[4]], 'audio', audio_only=True)
        self.library.freeze(book['id'], [ids[1]], 'queued-only')
        self.library.mark_done([single['sha256'], merged['sha256'], audio['sha256'], 'f' * 64])
        todo = self.library.chapters(book['id'], view='todo')
        done = self.library.chapters(book['id'], view='done')
        self.assertEqual(todo['counts'], {'todo': 2, 'done': 3})
        self.assertEqual(todo['all_ids'], [ids[1], ids[4]])
        self.assertEqual([c['order'] for c in done['items']], [1, 3, 4])
        self.assertTrue(all(c['done'] for c in done['items']))
        self.assertEqual(done['order_ids'], ids)
        # Moving a chapter in one tab keeps every chapter in the book's order.
        self.library.reorder(book['id'], [ids[1], ids[0], *ids[2:]])
        self.assertEqual([c['order'] for c in self.library.chapters(book['id'], view='done')['items']], [2, 3, 4])

    def test_audio_only_episode_has_no_gameplay(self):
        book = self.library.create_book('Truyện thử')
        self.library.import_files(book['id'], [{'name': '1.txt', 'text': 'Một câu.'}])
        chapter = self.library.chapters(book['id'])['items'][0]
        snapshot = self.library.freeze(book['id'], [chapter['id']], 'audio-1', audio_only=True)
        self.assertEqual((snapshot['audio_only'], snapshot['gameplay']), (True, []))
        self.assertNotIn('audio_only', self.library.freeze(book['id'], [chapter['id']], 'video-1'))

    def test_chapters_group_into_episodes_near_the_target_length(self):
        words = {f'c{i}': 4.2 * 600 for i in range(7)}  # each chapter about 10 minutes
        self.assertEqual([len(g) for g in group_by_length(list(words), words, 30)], [3, 3, 1])
        self.assertEqual([len(g) for g in group_by_length(list(words), words, 5)], [1] * 7)
        self.assertEqual(sum(group_by_length(list(words), words, 30), []), list(words))


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

    def test_pronunciation_changes_speech_only(self):
        snapshot = {**self.snapshot('CEO Lý gặp ceo Lýa ở LýThành.', read_title=False),
                    'settings': {'pronunciations': [{'from': 'CEO', 'to': 'xi i ô'}, {'from': 'Lý', 'to': 'Lí'}]}}
        unit = build_units(snapshot)[0]
        self.assertEqual(unit['text'], 'CEO Lý gặp ceo Lýa ở LýThành.')
        self.assertEqual(unit['spoken'], 'xi i ô Lí gặp xi i ô Lýa ở LýThành.')
        self.assertNotIn('spoken', build_units(self.snapshot('Không có gì để đổi.', read_title=False))[0])

    def test_master_is_built_at_the_largest_game_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {'output': tmp}
            write = lambda layout: Path(tmp, 'story-snapshot.json').write_text(json.dumps({'layout': layout}), encoding='utf-8')
            write({'horizontal': True, 'vertical': True})
            self.assertEqual(story_pipeline.master_size(job), (1152, 648))
            write({'horizontal': False, 'vertical': True})
            self.assertEqual(story_pipeline.master_size(job), (1008, 568))
            Path(tmp, 'story-snapshot.json').unlink()
            self.assertEqual(story_pipeline.master_size(job), (1920, 1080))

    def test_captions_split_display_only(self):
        ledger = [{'kind': 'text', 'text': 'Một hai ba bốn năm sáu bảy tám chín mười mười một mười hai.', 'start': 0, 'speech_end': 4, 'end': 4.6}]
        cues = caption_cues(ledger, 14)
        self.assertGreater(len(cues), 1)
        self.assertEqual(' '.join(' '.join(c['lines']) for c in cues), ledger[0]['text'])
        self.assertTrue(all(len(c['lines']) <= 2 for c in cues))
        self.assertAlmostEqual(cues[0]['start'], 0)


class StoryLintTests(unittest.TestCase):
    def codes(self, text):
        return [(i['code'], text[i['start']:i['end']]) for i in lint(text)]

    def test_marks_the_tts_reads_badly(self):
        text = ('Cô…… đã xuyên không~ Thật sao?!\n\n★★★★★\n\n……\n\nAnh ta hét: ĐỪNG CÓ CHẠY! Giá 1.5 triệu cho 1.000 người. Kétttt.\n'
                'Nguồn: truyenfull\n\n***\n\nCô ấy đi... Rồi về. Xem (chú thích) 【hệ thống】 😀')
        found = self.codes(text)
        for expected in [('ellipsis_mid', '……'), ('tilde', '~'), ('marks', '?!'), ('scene', '★★★★★'), ('ellipsis_only', '……'),
                         ('caps', 'ĐỪNG CÓ CHẠY'), ('decimal', '1.5'), ('stretch', 'tttt'), ('url', 'Nguồn: truyenfull'), ('emoji', '😀')]:
            self.assertIn(expected, found)
        self.assertNotIn(('decimal', '1.000'), found)
        self.assertFalse([f for f in found if f[0] == 'scene' and f[1] == '***'])
        self.assertFalse([f for f in found if f[0] == 'ellipsis_mid' and f[1] == '...'])  # "đi... Rồi" ends a sentence

    def test_long_sentence_and_clean_text(self):
        long = 'Cô bước chậm qua con ngõ nhỏ nghe tiếng lá xào xạc dưới chân ' * 5 + 'rồi dừng lại.'
        self.assertEqual([c for c, _ in self.codes(long)], ['long_sentence'])
        self.assertEqual(lint('Chiều hôm ấy, Minh trở về. Con đường vẫn thế.\n\n— Có ai ở ngoài cửa đấy?'), [])


class StorySpaceTests(unittest.TestCase):
    def test_space_estimate(self):
        self.assertEqual(story_pipeline.space_needed(600, 0), int((100 + 30) * 2**20))
        self.assertGreater(story_pipeline.space_needed(600, 2), story_pipeline.space_needed(600, 2, master=False))

    def test_short_disk_pauses_the_queue_and_stops(self):
        from videostudio.core import PermanentError
        from unittest import mock
        executed = []

        class FakeDB:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def execute(self, sql, *a):
                executed.append(sql)

        pipeline = SimpleNamespace(store=SimpleNamespace(db=FakeDB, log=lambda *a: None))
        with tempfile.TemporaryDirectory() as tmp, mock.patch('videostudio.drive_storage.DriveStorage', side_effect=RuntimeError('no drive')):
            job = {'id': 'j', 'output': tmp}
            story_pipeline.ensure_space(pipeline, job, 1, lambda: None, 'render')  # enough room: nothing happens
            self.assertEqual(executed, [])
            with self.assertRaises(PermanentError) as caught:
                story_pipeline.ensure_space(pipeline, job, 2**62, lambda: None, 'render')
        self.assertIn('tạm dừng hàng đợi', str(caught.exception))
        self.assertTrue(any('paused=1' in sql for sql in executed))

    def test_tts_cache_trim_keeps_recent_and_own(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            for index, name in enumerate(['old', 'mine', 'new']):
                path = Path(tmp, name + '.wav')
                path.write_bytes(b'x' * 100)
                os.utime(path, (1000 + index, 1000 + index))
            os.utime(Path(tmp, 'mine.wav'), (1, 1))
            freed = story_pipeline.trim_tts_cache(tmp, keep={'mine'}, limit=200)
            self.assertEqual(freed, 100)
            self.assertEqual(sorted(p.stem for p in Path(tmp).glob('*.wav')), ['mine', 'new'])


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
            own_cover = root / 'cover.png'
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=800x800', '-frames:v', '1', str(own_cover)], check=True)
            snapshot = {'book': {'id': 'book', 'title': 'Chuyến trở về'}, 'layout': {'channel': 'Truyện đêm', 'horizontal': True, 'vertical': True,
                        'burn_subtitles': True, 'export_srt': True, 'export_mp3': True, 'game_audio': False, 'continue_gameplay': False,
                        'cover_source': 'image', 'cover_text': False},
                        'cover_path': str(own_cover),
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
                probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                                        job['checkpoints']['images']['master']], capture_output=True, text=True, check=True)
                self.assertEqual(probe.stdout.strip(), '1152,648')
                job['checkpoints']['subtitles'] = story_pipeline.subtitles(pipeline, job, lambda: None)
                job['checkpoints']['render'] = story_pipeline.render(pipeline, job, lambda: None)
                result = story_pipeline.verify(pipeline, job, lambda: None)
            finally:
                story_pipeline.StoryLibrary = original
            self.assertTrue(result['verified'])
            names = sorted(p.name for p in (root / 'Book').iterdir() if p.is_file())
            self.assertEqual(names, ['chuong-001-canh-cong-cu-v1.mp3', 'chuong-001-canh-cong-cu-v1.srt', 'chuong-001-canh-cong-cu-v1_anh-bia.jpg',
                                     'chuong-001-canh-cong-cu-v1_dang-bai.txt', 'chuong-001-canh-cong-cu-v1_doc.mp4',
                                     'chuong-001-canh-cong-cu-v1_ngang.mp4'])  # one subtitle file shared by both videos
            # The title intro is on by default: narration and subtitles wait for it, the video is that much longer.
            intro = story_pipeline.intro_seconds(snapshot)
            self.assertGreater(intro, 1)
            self.assertEqual(job['checkpoints']['render']['intro_seconds'], intro)
            srt = (root / 'Book' / 'chuong-001-canh-cong-cu-v1.srt').read_text(encoding='utf-8')
            self.assertIn(story_pipeline._srt_time(intro) + ' --> ', srt)
            self.assertAlmostEqual(result['duration_seconds'], 4.0 + intro, places=3)
            # The intro plays on the first gameplay frame held still: no extra footage is planned for it.
            self.assertAlmostEqual(json.loads((output / 'story-gameplay' / 'plan.json').read_text(encoding='utf-8'))['seconds'], 4.5)
            kit = (root / 'Book' / 'chuong-001-canh-cong-cu-v1_dang-bai.txt').read_text(encoding='utf-8')
            self.assertIn('Chuyến trở về · Chương 1: Cánh cổng cũ', kit)
            self.assertIn('#truyenaudio', kit)
            cover = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(root / 'Book' / 'chuong-001-canh-cong-cu-v1_anh-bia.jpg'),
                                    '-vf', 'scale=1:1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
            self.assertGreater(cover[0], 200)  # the user's red image, not a darkened gameplay frame with text
            plan = json.loads((output / 'story-gameplay' / 'plan.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(len(plan['segments']), 2)  # 3-second clip looped to cover 4.5 seconds

    def test_audio_only_episode_publishes_mp3_and_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'Book' / 'data' / 'job2'
            output.mkdir(parents=True)
            narration = output / 'story-narration.wav'
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=f=220:d=3', '-ar', '24000', '-ac', '1', str(narration)], check=True)
            snapshot = {'book': {'id': 'book', 'title': 'Chuyến trở về'}, 'audio_only': True, 'gameplay': [],
                        'layout': {'horizontal': True, 'vertical': True, 'export_srt': True, 'export_mp3': True},
                        'chapters': [{'id': 'c1', 'order': 1, 'number': 1, 'title': 'Cánh cổng cũ', 'read_title': True, 'text': 'x'}]}
            (output / 'story-snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
            ledger = [{'id': 'u0', 'text': 'Chiều hôm ấy, Minh trở về.', 'kind': 'text', 'chapter': 0, 'start': 0, 'speech_end': 2.5, 'end': 3.0}]
            (output / 'story-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
            pipeline = SimpleNamespace(ffmpeg=FFMPEG, ffprobe=shutil.which('ffprobe'), store=None)
            job = {'id': 'job2', 'output': str(output), 'request': {}, 'checkpoints': {'speech': {'path': str(narration), 'duration_seconds': 3.0}}}
            job['checkpoints']['images'] = story_pipeline.images(pipeline, job, lambda: None)
            job['checkpoints']['subtitles'] = story_pipeline.subtitles(pipeline, job, lambda: None)
            job['checkpoints']['render'] = story_pipeline.render(pipeline, job, lambda: None)
            self.assertTrue(story_pipeline.verify(pipeline, job, lambda: None)['verified'])
            self.assertFalse((output / 'story-gameplay' / 'plan.json').exists())
            names = sorted(p.name for p in (root / 'Book').iterdir() if p.is_file())
            self.assertEqual(names, ['chuong-001-canh-cong-cu-v1_loi-doc.mp3', 'chuong-001-canh-cong-cu-v1_loi-doc.srt'])


if __name__ == '__main__':
    unittest.main()
