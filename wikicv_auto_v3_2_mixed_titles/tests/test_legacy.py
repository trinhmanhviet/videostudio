import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crawl_wikicv as c

INTRO = 'https://wikicv.org/truyen/truyen-thu-nghiem-abCDEF0123456789'
BASE = 'https://wikicv.org/truyen/truyen-thu-nghiem/'
L1 = BASE+'chuong-1-abCDEF0123456789'
L2 = BASE+'chuong-2-abCDEF0123456788'
L3 = BASE+'chuong-3-abCDEF0123456787'
OTHER = 'https://wikicv.org/truyen/truyen-khac-FEDCBA9876543210'
OTHERL1 = 'https://wikicv.org/truyen/truyen-khac/chuong-1-FEDCBA9876543210'


def intro(latest_no=3):
    u = {1:L1,2:L2,3:L3}[latest_no]
    return (f'<html><head><title>Demo</title></head><body><h1>Truyện thử nghiệm</h1>'
            f'<a href="{L1}">Đọc</a>'
            f'<a href="{u}">Chương {latest_no} mới nhất</a>'
            '<a href="https://evil.org/chapter-1">Chương 1</a>'
            '</body></html>')


def chapter(no, next_url=None):
    narrative = (f'Văn bản riêng của chương số {no}. ' * 18)
    a = f'<a href="{next_url}">Chương sau</a>' if next_url else ''
    return ('<html><body><nav>Trang chủ</nav><h2>Chương '+str(no)+' thử nghiệm</h2>'
           '<p>Tác giả: Demo</p><h2>Chương '+str(no)+' thử nghiệm</h2>'
           f'<div><p>{narrative}</p><p>Lời thoại thứ {no}.</p></div>'
           '<p>----------------------------------------</p>'
           '<p>Truyện được nhúng bởi Demo</p>'
           f'{a}<footer>Bình luận</footer></body></html>')


class FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping
        self.visited = []
    def get(self, url, **kwargs):
        self.visited.append(url)
        if url not in self.mapping: raise AssertionError(f'Unknown URL: {url}')
        return SimpleNamespace(url=url, status_code=200, content=self.mapping[url].encode('utf-8'),
                               raise_for_status=lambda: None)


def args(output, max_chapters=0):
    return SimpleNamespace(url=INTRO, output=str(output), timeout=10, delay=1, max_chapters=max_chapters,
                           min_chars=120, refresh=False, sequential_only=False, index_page_size=501)


class CrawlerTests(unittest.TestCase):
    def test_landing_detection(self):
        title, start, latest, no = c.get_book_info(BeautifulSoup(intro(), 'html.parser'), INTRO)
        self.assertEqual(title, 'Truyện thử nghiệm')
        self.assertEqual(start, L1)
        self.assertEqual(latest, L3)
        self.assertEqual(no, 3)

    def test_all_chapters_and_resume_and_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = {INTRO:intro(), L1:chapter(1,L2), L2:chapter(2,L3), L3:chapter(3)}
            session = FakeSession(m)
            with patch.object(c, 'make_session', return_value=session), patch.object(c, 'check_robots', return_value=True), patch.object(c.time, 'sleep', return_value=None):
                folder = c.run(args(tmp))
            manifest = json.loads((folder/'chapters.json').read_text('utf-8'))
            self.assertEqual([x['number'] for x in manifest], [1,2,3])
            combined = (folder/'truyen_gop.txt').read_text('utf-8')
            self.assertIn('Lời thoại thứ 1', combined)
            self.assertIn('Lời thoại thứ 3', combined)
            self.assertNotIn('Truyện được nhúng', combined)
            chapter_one=(folder/'chapters/chuong_00001.txt').read_text(encoding='utf-8')
            self.assertNotIn('Nguồn:', chapter_one)
            book_meta=json.loads((folder/'truyen.json').read_text(encoding='utf-8'))
            self.assertEqual(len(book_meta['chapter_sources']), 3)
            self.assertEqual(book_meta['chapter_sources'][0]['url'], L1)
            self.assertLess(combined.index('Lời thoại thứ 1'), combined.index('Lời thoại thứ 3'))
            self.assertFalse(any('evil.org' in u for u in session.visited))
            session2 = FakeSession(m)
            with patch.object(c, 'make_session', return_value=session2), patch.object(c, 'check_robots', return_value=True), patch.object(c.time, 'sleep', return_value=None):
                c.run(args(tmp))
            self.assertEqual(session2.visited, [INTRO,L3])  # Resume without redownloading 1/2
            m[INTRO] = intro(3)
            # Additional chapter scenario: 1->2->3 updated elsewhere in a new session.
            # In a live site, latest changes with a new chapter 4 link; emulate 4 below.
            L4 = BASE+'chuong-4-abcdef0123456789'
            m[INTRO] = intro(3).replace('Chương 3 mới nhất','Chương 4 mới nhất').replace(L3+'">Chương 4', L4+'">Chương 4')
            m[L3] = chapter(3,L4)
            m[L4] = chapter(4)
            session3 = FakeSession(m)
            with patch.object(c, 'make_session', return_value=session3), patch.object(c, 'check_robots', return_value=True), patch.object(c.time, 'sleep', return_value=None):
                c.run(args(tmp))
            self.assertEqual(session3.visited, [INTRO,L3,L4])
            self.assertEqual(len(json.loads((folder/'chapters.json').read_text('utf-8'))), 4)

    def test_limit_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = {INTRO:intro(), L1:chapter(1,L2), L2:chapter(2,L3), L3:chapter(3)}
            with patch.object(c, 'make_session', return_value=FakeSession(m)), patch.object(c, 'check_robots', return_value=True), patch.object(c.time, 'sleep', return_value=None):
                out = c.run(args(tmp,max_chapters=1))
            self.assertEqual(len(json.loads((out/'chapters.json').read_text('utf-8'))),1)
            with patch.object(c, 'make_session', return_value=FakeSession(m)), patch.object(c, 'check_robots', return_value=True), patch.object(c.time, 'sleep', return_value=None):
                out = c.run(args(tmp))
            self.assertEqual(len(json.loads((out/'chapters.json').read_text('utf-8'))),3)

    def test_reject_wrong_urls(self):
        with self.assertRaises(ValueError): c.book_slug_from_url(L1)
        with self.assertRaises(ValueError): c.normalize_url('https://evil.org/foo', INTRO)


if __name__ == '__main__':
    unittest.main(verbosity=2)
