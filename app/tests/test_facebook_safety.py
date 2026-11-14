import unittest

from videostudio.facebook_safety import check


class FacebookSafetyTests(unittest.TestCase):
    def found(self, text):
        return [(i['kind'], i['level'], i['text']) for i in check(text)['issues']]

    def test_words_masks_bait_emoji_and_hashtags(self):
        text = ('Người vợ bị giết, thi thể được tìm thấy. Hắn gi*t rồi g.i.ế.t tiếp. Xem ngay kẻo bị xóa 🔪 '
                '#GietNguoi #hosovuan #a #b #c #d')
        found = self.found(text)
        self.assertIn(('word', 'review', 'bị giết'), found)  # the longer phrase wins over "giết"
        self.assertNotIn(('word', 'review', 'giết'), found)
        self.assertIn(('masked', 'fix', 'gi*t'), found)
        self.assertIn(('masked', 'fix', 'g.i.ế.t'), found)
        self.assertIn(('phrase', 'review', 'Xem ngay kẻo'), found)
        self.assertIn(('emoji', 'review', '🔪'), found)
        self.assertIn(('hashtag', 'review', '#GietNguoi'), found)
        self.assertIn(('count', 'note', '6 hashtag'), found)
        self.assertEqual(check(text)['verdict'], 'fix')

    def test_strike_words_and_the_first_150_characters(self):
        self.assertEqual(self.found('Cô ấy chọn tự tử.')[0][:2], ('word', 'fix'))
        late = 'Một căn phòng khóa kín và một chiếc điện thoại biến mất. ' * 3 + 'Người chồng ngoại tình.'
        self.assertEqual(self.found(late), [('word', 'note', 'ngoại tình')])  # low risk, past the "Xem thêm" fold
        self.assertEqual(self.found('Ngoại tình và bí mật.'), [('word', 'review', 'Ngoại tình')])

    def test_clean_story_caption_is_safe_and_replacements_are_offered(self):
        self.assertEqual(check('Một căn phòng khóa kín. Theo bạn, manh mối nào đáng nghi nhất? #hosovuan #truyenaudio')['verdict'], 'safe')
        issue = check('Nạn nhân được phát hiện, thi thể lạnh ngắt.')['issues'][0]
        self.assertIn('nạn nhân', issue['replace'])
        self.assertEqual(issue['text'], 'thi thể')


if __name__ == '__main__':
    unittest.main()
