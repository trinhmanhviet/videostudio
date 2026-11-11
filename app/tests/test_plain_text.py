import unittest

from videostudio.core import validate_request
from videostudio.plain_text import strip_markdown

BASE = {'idea': 'x', 'voice_id': 'v', 'duration_seconds': 45}


class StripMarkdownTests(unittest.TestCase):
    def test_bold_keeps_the_words(self):
        self.assertEqual(strip_markdown('**Giây thứ 1**'), 'Giây thứ 1')
        self.assertEqual(strip_markdown('Mặt trời **tắt** ngay *lập tức*.'), 'Mặt trời tắt ngay lập tức.')
        self.assertEqual(strip_markdown('***Rất*** __quan trọng__ và _nghiêng_'), 'Rất quan trọng và nghiêng')

    def test_unbalanced_stars_are_removed(self):
        self.assertEqual(strip_markdown('**Giây thứ 1'), 'Giây thứ 1')
        self.assertEqual(strip_markdown('* * *'), '')

    def test_line_structure(self):
        text = '# Tiêu đề\n\n> Trích dẫn\n- Ý một\n* Ý hai\n---\nCâu cuối'
        self.assertEqual(strip_markdown(text), 'Tiêu đề\n\nTrích dẫn\nÝ một\nÝ hai\nCâu cuối')

    def test_links_code_tables(self):
        self.assertEqual(strip_markdown('Xem [bài này](https://a.b/c) và `mã` ~~bỏ~~'), 'Xem bài này và mã bỏ')
        self.assertEqual(strip_markdown('![ảnh](x.png)'), '')
        self.assertEqual(strip_markdown('```\nCâu trong khối\n```'), 'Câu trong khối')
        self.assertEqual(strip_markdown('| Năm | Việc |\n|---|---|\n| 2009 | Án mạng |'), 'Năm, Việc\n2009, Án mạng')

    def test_normal_text_is_left_alone(self):
        for text in ('Năm 2009, ông A - người lái xe - bỏ đi.', 'Giá tăng 2*3 lần', 'biến snake_case_name giữ nguyên',
                     '1. Thứ nhất', '#1 thế giới', 'Ai đó? Không! (thật sao)'):
            self.assertEqual(strip_markdown(text), text)

    def test_cleaning_twice_changes_nothing(self):
        once = strip_markdown('## **Giây 1**\n- _a_ [b](c)\n| d | e |')
        self.assertEqual(strip_markdown(once), once)


class IntakeTests(unittest.TestCase):
    def test_pasted_narration_is_cleaned(self):
        request = validate_request({**BASE, 'workflow_mode': 'provided_narration', 'idea': '**Giây thứ 1**\n\n- Mặt trời **tắt**.'})
        self.assertEqual(request['idea'], 'Giây thứ 1\n\nMặt trời tắt.')

    def test_meme_script_is_cleaned_but_meme_idea_is_not(self):
        script = validate_request({**BASE, 'workflow_mode': 'meme', 'meme_input_mode': 'script', 'idea': '**Bố** ngã.'})
        self.assertEqual(script['idea'], 'Bố ngã.')
        idea = validate_request({**BASE, 'workflow_mode': 'meme', 'meme_input_mode': 'idea', 'idea': '**Bố** ngã.'})
        self.assertEqual(idea['idea'], '**Bố** ngã.')

    def test_research_idea_is_untouched(self):
        self.assertEqual(validate_request({**BASE, 'idea': '**Chủ đề**'})['idea'], '**Chủ đề**')

    def test_only_markup_is_refused(self):
        with self.assertRaises(ValueError):
            validate_request({**BASE, 'workflow_mode': 'provided_narration', 'idea': '***\n---'})


if __name__ == '__main__':
    unittest.main()
