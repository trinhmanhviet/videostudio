import tempfile
import unittest
from pathlib import Path

from videostudio import story_pipeline
from videostudio.story_library import StoryLibrary, validate_settings
from videostudio.story_pronounce import read_number, suggest


class PronunciationSuggestionTests(unittest.TestCase):
    def test_abbreviations_units_times_and_symbols(self):
        text = ('Anh ta là CEO của công ty, chạy 5km lúc 6h30. Lương 20tr, giảm 50%. ANH ĐỨNG LẠI ĐI! '
                'Xe chạy 60km/h. GPS báo sai. Tôi & cô ấy. Gặp ở TP HCM.')
        found = {i['from']: i['to'] for i in suggest([text, 'Lại là CEO.'], existing=['gps'])}
        self.assertEqual(found['CEO'], 'xi i ô')
        self.assertEqual((found['5km'], found['6h30'], found['20tr'], found['50%']), ('5 ki lô mét', '6 giờ 30', '20 triệu', '50 phần trăm'))
        self.assertEqual((found['60km/h'], found['&'], found['TP'], found['HCM']), ('60 ki lô mét trên giờ', 'và', 'thành phố', 'Hồ Chí Minh'))
        self.assertNotIn('GPS', found)        # already in the dictionary
        self.assertNotIn('ANH', found)        # shouting, not an abbreviation
        self.assertNotIn('ĐI', found)
        self.assertEqual(suggest(['CEO và CEO.'])[0]['count'], 2)
        self.assertEqual(suggest(['Mã XYZ.'])[0]['to'], 'ích i dài dét')

    def test_small_numbers(self):
        self.assertEqual([read_number(n) for n in ('5', '15', '21', '45', '70', '123')],
                         ['năm', 'mười lăm', 'hai mươi mốt', 'bốn mươi lăm', 'bảy mươi', '123'])


class RetakeTests(unittest.TestCase):
    def test_retake_counts_and_marks_only_the_unit_holding_the_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = StoryLibrary(Path(tmp, 'lib'), Path(tmp, 'game'))
            book = library.create_book('Truyện thử')
            with self.assertRaises(ValueError):
                library.retake(book['id'], ' ab ')
            self.assertEqual(library.retake(book['id'], 'Cô ấy  quay lại.')['take'], 1)
            result = library.retake(book['id'], 'Cô ấy quay lại.')
            self.assertEqual(result['take'], 2)
            self.assertEqual(result['book']['settings']['retakes'], [{'text': 'Cô ấy quay lại.', 'take': 2}])
        snapshot = {'settings': {'retakes': [{'text': 'Cô ấy quay lại.', 'take': 2}]},
                    'chapters': [{'number': 1, 'order': 1, 'title': 'A', 'read_title': False,
                                  'text': 'Trời mưa to.\n\nCô ấy quay lại. Không ai nói gì.\n\nHết.'}]}
        units = story_pipeline.build_units(snapshot)
        self.assertEqual([u.get('take') for u in units], [None, 2, None])
        self.assertEqual(validate_settings({'retakes': [{'text': ' a  b ', 'take': 3}]})['retakes'], [{'text': 'a b', 'take': 3}])
        with self.assertRaises(ValueError):
            validate_settings({'retakes': [{'text': 'x', 'take': 'nhiều'}]})


class GreetingTests(unittest.TestCase):
    def test_intro_and_outro_wrap_the_episode(self):
        snapshot = {'book': {'title': 'Trọng Sinh'}, 'settings': {'intro_text': 'Chào mừng. Hôm nay là {chuong} của truyện {truyen}.',
                                                               'outro_text': 'Hẹn gặp lại.'},
                    'chapters': [{'number': 3, 'order': 3, 'title': 'Trở về', 'read_title': True, 'text': 'Trời mưa.'},
                                 {'number': 4, 'order': 4, 'title': 'Đi', 'read_title': True, 'text': 'Hết.'}]}
        texts = [u['text'] for u in story_pipeline.build_units(snapshot)]
        self.assertEqual(texts[0], 'Chào mừng. Hôm nay là Chương 3–4 của truyện Trọng Sinh.')
        self.assertEqual(texts[1], 'Chương 3. Trở về.')
        self.assertEqual(texts[-1], 'Hẹn gặp lại.')
        snapshot['settings'] = {}
        self.assertEqual(story_pipeline.build_units(snapshot)[0]['text'], 'Chương 3. Trở về.')
        self.assertEqual(validate_settings({'intro_text': ' a\n b '})['intro_text'], 'a b')


class AuthorNoteTests(unittest.TestCase):
    def test_author_and_translator_notes_are_flagged(self):
        from videostudio.story_lint import lint, notes
        story = 'Lễ hội văn nghệ sắp bắt đầu.\n\nCô nói: "Tác giả của cuốn sách này là ai?"'
        self.assertEqual(notes(story), [])  # a character talking about an author stays
        text = story + '\n\nLời tác giả.\n\nỪm, tự nhiên mình lại muốn mở một truyện mới quá.\n\nCầu bình luận nha.'
        found = notes(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(text[found[0][0]:found[0][1]], 'Lời tác giả.\n\nỪm, tự nhiên mình lại muốn mở một truyện mới quá.\n\nCầu bình luận nha.')
        self.assertIn('hết chương', found[0][2])
        lines = 'Trời mưa.\n\nPS: mai mình nghỉ một hôm.\n\nAnh đi ra.\n\nConverter: chương này khó quá.\n\nCòn tiếp.'
        self.assertEqual([lines[s:e] for s, e, _ in notes(lines)], ['PS: mai mình nghỉ một hôm.', 'Converter: chương này khó quá.', 'Còn tiếp.'])
        self.assertEqual([i['code'] for i in lint(lines)].count('note'), 3)

    def test_editor_must_drop_notes_and_does_not_count_them_as_cut(self):
        from videostudio.story_editor import check_chapter, removed_chars
        body = 'Cô bước vào phòng, nhìn quanh một lượt rồi ngồi xuống. ' * 6
        note = 'Tác giả có lời muốn nói: hôm nay mình bận quá, mọi người thông cảm nhé, mai mình bù chương. ' * 3
        self.assertTrue(any('lời tác giả' in p for p in check_chapter(body, body + '\n\nLời tác giả.\n\nMai mình nghỉ.')))
        self.assertTrue(any('cắt' in p for p in check_chapter(body + note, body)))
        self.assertEqual(check_chapter(body + note, body, removed_chars({'da_bo': [note]})), [])


class BookIssuesTests(unittest.TestCase):
    def test_whole_book_list_in_reading_order_with_counts_and_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = StoryLibrary(Path(tmp, 'lib'), Path(tmp, 'game'))
            book = library.create_book('Truyện thử')
            bodies = ['Sạch sẽ.', 'Trời mưa~ to.\n\nLời tác giả.\n\nCảm ơn.', 'Hết.\n\nPS: mai nghỉ.']
            library.import_files(book['id'], [{'name': f'{n}.txt', 'text': body} for n, body in enumerate(bodies, 1)], split=False)
            result = library.issues(book['id'])
            self.assertEqual((result['total'], result['chapters']), (3, 2))
            self.assertEqual([(i['order'], i['code']) for i in result['items']], [(2, 'tilde'), (2, 'note'), (3, 'note')])
            self.assertEqual(result['counts']['note']['count'], 2)
            only = library.issues(book['id'], 'note', limit=1)
            self.assertEqual((len(only['items']), only['more']), (1, 1))

    def test_strip_notes_removes_every_note_and_keeps_the_old_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = StoryLibrary(Path(tmp, 'lib'), Path(tmp, 'game'))
            book = library.create_book('Truyện thử')
            bodies = ['Sạch sẽ.', 'Trời mưa to.\n\n***\n\nLời tác giả.\n\nCảm ơn.', 'Anh đi.\n\nPS: mai nghỉ.\n\nCô về.', 'Lời tác giả.\n\nChỉ có lời bình.']
            library.import_files(book['id'], [{'name': f'{n}.txt', 'text': body} for n, body in enumerate(bodies, 1)], split=False)
            result = library.strip_notes(book['id'])
            self.assertEqual(result, {'chapters': 2, 'parts': 2, 'skipped': [4]})
            items = library.chapters(book['id'])['items']
            texts = [library.chapter(i['id'])['text'] for i in items]
            self.assertEqual(texts[:3], ['Sạch sẽ.', 'Trời mưa to.', 'Anh đi.\n\nCô về.'])
            self.assertEqual(library.history(items[1]['id'])[0]['reason'], 'trước khi xoá lời bình')
            self.assertEqual(library.strip_notes(book['id'])['chapters'], 0)


if __name__ == '__main__':
    unittest.main()
