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


if __name__ == '__main__':
    unittest.main()
