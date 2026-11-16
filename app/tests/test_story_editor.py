import json
import tempfile
import unittest
from pathlib import Path

from videostudio.story_editor import StoryEditor, check_chapter, clean_for_speech, split_chapters

RAW = """Truyện thử

1

Chương 1. Mở đầu

Nàng đi ra cửa. Hắn ở phía sau gọi nàng.

★★★★★

Ngày hôm sau trời mưa.

Chương 2 gặp lại

Chương 2. Gặp lại

1

Nàng gặp lại hắn ở bến xe. Hai người nhìn nhau thật lâu.

Chương 3 end

Chương 3.end

Hết thảy kết thúc ở đây, nàng cười.
"""


class StoryEditorTests(unittest.TestCase):
    def test_split_folds_double_headings_page_numbers_and_end_titles(self):
        title, chapters = split_chapters(RAW)
        self.assertEqual(title, 'Truyện thử')
        self.assertEqual([(c['number'], c['title']) for c in chapters], [(1, 'Mở đầu'), (2, 'Gặp lại'), (3, '')])
        self.assertNotIn('\n1\n', '\n' + chapters[1]['text'] + '\n')
        self.assertIn('★★★★★', chapters[0]['text'])

    def test_clean_for_speech_fixes_symbols_the_reader_would_say(self):
        text = clean_for_speech('Hả~ ừm…… được!!! Thật sao?!\n\n★★★★★\n\nGọi lại ——\n3')
        self.assertEqual(text, 'Hả ừm… được! Thật sao?\n\n***\n\nGọi lại…')

    def test_check_flags_cut_text_long_sentences_and_symbols(self):
        source = 'Một câu đủ dài để làm nguồn. ' * 40
        self.assertEqual(check_chapter(source, source), [])
        self.assertTrue(any('cắt' in p for p in check_chapter(source, source[:200])))
        long = 'Một câu rất dài không có dấu chấm ' * 12 + '.'
        self.assertTrue(any('Câu quá dài' in p for p in check_chapter(long, long)))
        self.assertTrue(any('ký hiệu cấm' in p for p in check_chapter(source, source + ' 【hệ thống】')))

    def test_run_builds_profile_edits_learns_terms_merges_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            story = Path(tmp)
            (story / 'truyen_gop.txt').write_text(RAW, encoding='utf-8')
            calls = []

            def ask(job, prompt):
                calls.append(job)
                if '-profile-' in job:
                    return {'ten_truyen': 'Truyện Thử', 'nhan_vat': [{'ten': 'Lan'}], 'thuat_ngu': [], 'luu_y': []}
                number = int(job.split('-')[-2])
                source = split_chapters(RAW)[1][number - 1]['text']
                body = source.replace('Nàng', 'Cô').replace('hắn', 'anh').replace('★★★★★', '***')
                return {'tieu_de': f'Phần {number}', 'noi_dung': body + ' Thêm một câu cho đủ dài để không bị coi là nội dung rỗng.',
                        'thuat_ngu_moi': [{'goc': 'bến xe', 'dich': 'bến xe'}], 'nhan_vat_moi': [], 'ghi_chu': []}

            summary = StoryEditor(story, ask=ask, log=lambda *_: None).run()
            merged = (story / 'truyen_gop_bien_tap.txt').read_text(encoding='utf-8')
            self.assertTrue(merged.startswith('Truyện Thử\n\nChương 1: Phần 1\n\n'))
            self.assertIn('\n***\n', merged)
            self.assertEqual(summary['chapters_done'], 3)
            profile = json.loads((story / 'bien_tap' / 'ho_so.json').read_text(encoding='utf-8'))
            self.assertEqual(profile['thuat_ngu'], [{'goc': 'bến xe', 'dich': 'bến xe'}])
            count = len(calls)
            StoryEditor(story, ask=ask, log=lambda *_: None).run()
            self.assertEqual(len(calls), count)  # finished chapters and the profile are never sent again

    def test_each_chapter_gets_only_the_profile_it_needs(self):
        from videostudio.story_editor import profile_for
        profile = {'ten_truyen': 'T', 'van_phong': 'nhẹ', 'luu_y': ['x'],
                   'nhan_vat': [{'ten': 'Khương Ỷ', 'ten_goi_khac': ['Khương tiểu thư'], 'than_phan': 'nữ chính', 'xung_ho': 'cô'},
                                {'ten': 'Lâm Mạn', 'gioi_tinh': 'Nữ', 'xung_ho': 'chị'},
                                {'ten': 'Chu Lễ', 'gioi_tinh': 'Nam', 'xung_ho': 'anh'}],
                   'thuat_ngu': [{'goc': 'Cảng Thành', 'dich': 'Hồng Kông'}, {'goc': 'hội sở', 'dich': 'câu lạc bộ'},
                                 {'goc': 'tân cửa hàng', 'dich': 'cửa hàng mới'}]}
        part = profile_for(profile, 'Ở cảng thành, lâm mạn bước vào.', 'Đoạn cuối: Chu Lễ gật đầu.')
        self.assertEqual([p['ten'] for p in part['nhan_vat']], ['Khương Ỷ', 'Lâm Mạn', 'Chu Lễ'])  # main always, others named
        self.assertEqual(part['thuat_ngu'], [{'goc': 'Cảng Thành', 'dich': 'Hồng Kông'}])            # any case
        self.assertEqual((part['van_phong'], part['luu_y']), ('nhẹ', ['x']))
        self.assertEqual([p['ten'] for p in profile_for(profile, 'Không ai khác.')['nhan_vat']], ['Khương Ỷ'])
        self.assertEqual(len(profile['thuat_ngu']), 3)  # the saved profile itself is untouched

    def test_wrapped_answers_are_unwrapped(self):
        # 2026-11-16, chapter 99: {"your_response": "<the JSON as a string, with raw line breaks>"} stopped the edit.
        from videostudio.story_editor import unwrap_answer
        inner = '{"tieu_de":"Ngoại Truyện","noi_dung":"Dòng một.\nDòng hai."}'
        self.assertEqual(unwrap_answer({'your_response': inner}, 'noi_dung')['noi_dung'], 'Dòng một.\nDòng hai.')
        self.assertEqual(unwrap_answer({'answer': {'noi_dung': 'x'}}, 'noi_dung'), {'noi_dung': 'x'})
        self.assertEqual(unwrap_answer(inner, 'noi_dung')['tieu_de'], 'Ngoại Truyện')
        self.assertEqual(unwrap_answer({'nhan_vat': []}, 'nhan_vat'), {'nhan_vat': []})
        self.assertEqual(unwrap_answer({'a': 1, 'b': 2}, 'noi_dung'), {'a': 1, 'b': 2})
        self.assertEqual(unwrap_answer('không phải JSON', 'noi_dung'), 'không phải JSON')

    def test_a_reply_without_the_chapter_is_asked_again_in_a_new_chat_not_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            story = Path(tmp)
            (story / 'truyen_gop.txt').write_text(RAW, encoding='utf-8')
            calls = []

            def ask(job, prompt):
                calls.append(job)
                if '-profile-' in job:
                    return {'ten_truyen': 'T', 'nhan_vat': [], 'thuat_ngu': [], 'luu_y': []}
                number = int(job.split('-')[-2])
                if number == 2 and '-chapter-' in job and job.endswith('-0'):
                    return {'loi': 'không có chương'}  # the daemon keeps this answer: asking job -0 again reads it back
                return {'your_response': json.dumps({'tieu_de': 'A', 'noi_dung': split_chapters(RAW)[1][number - 1]['text'] + ' Thêm một câu cho đủ dài để không rỗng.'})}
            StoryEditor(story, ask=ask, log=lambda *_: None).run()
            self.assertTrue((story / 'bien_tap' / 'chuong_003.txt').is_file())
            self.assertEqual([j.rsplit('-', 2)[-2:] for j in calls if '-chapter-' in j][:4], [['001', '0'], ['002', '0'], ['002', '1'], ['003', '0']])

    def test_pause_stops_before_the_next_chapter_and_keeps_progress(self):
        import threading
        from videostudio.story_editor import Paused
        with tempfile.TemporaryDirectory() as tmp:
            story = Path(tmp)
            (story / 'truyen_gop.txt').write_text(RAW, encoding='utf-8')
            stop = threading.Event()

            def ask(job, prompt):
                if '-profile-' in job:
                    return {'ten_truyen': 'T', 'nhan_vat': [], 'thuat_ngu': [], 'luu_y': []}
                number = int(job.split('-')[-2])
                stop.set()  # Tạm dừng pressed while chapter 1 is being edited
                return {'tieu_de': 'A', 'noi_dung': split_chapters(RAW)[1][number - 1]['text'] + ' Thêm một câu cho đủ dài để không rỗng.'}
            with self.assertRaises(Paused):
                StoryEditor(story, ask=ask, log=lambda *_: None, stop=stop).run()
            self.assertTrue((story / 'bien_tap' / 'chuong_001.txt').is_file())    # the chapter in flight is kept
            self.assertFalse((story / 'bien_tap' / 'chuong_002.txt').exists())

    def test_ask_reports_progress_and_withdraws_on_pause(self):
        import threading
        from unittest import mock
        from videostudio import story_editor
        stop, seen, cancelled = threading.Event(), [], []
        release = threading.Event()

        class Response:
            status_code = 200

            def __init__(self, body):
                self.body = body

            def json(self):
                return self.body

        def post(url, json=None, **_):
            if url.endswith('/api/chat/cancel'):
                cancelled.append(json['job_id'])
                release.set()
                return Response({'ok': True})
            release.wait(10)
            return Response({'ok': False, 'code': 'cancelled', 'error': 'withdrawn'})

        def get(url, params=None, **_):
            stop.set()  # the owner presses Tạm dừng while ChatGPT is thinking
            return Response({'phase': 'thinking', 'seconds': 185})
        with mock.patch('httpx.post', post), mock.patch('httpx.get', get), mock.patch.object(story_editor.time, 'sleep'), mock.patch.object(story_editor, 'POLL', 0.05):
            with self.assertRaises(story_editor.Paused):
                story_editor.ask_chatgpt('story-ab-chapter-001-0', 'p', status=seen.append, stop=stop)
        self.assertIn('ChatGPT đang suy nghĩ 3 phút', seen)
        self.assertEqual(cancelled, ['story-ab-chapter-001-0'])


if __name__ == '__main__':
    unittest.main()
