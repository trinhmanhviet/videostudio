import tempfile
import time
import unittest
from pathlib import Path

from videostudio.story_crawl import Crawler, valid_url

FAKE = r'''
import sys, time
args = sys.argv
assert args[args.index("--url") + 1].startswith("https://wikicv.org/truyen/")
print("Tên truyện : Trọng Sinh Chi Khẩn Cấp Công Lược")
print("Đầu ra     : " + args[args.index("--output") + 1] + "/trong-sinh-YNdD")
print("Tiếp tục từ: mục 45 – Chương 45")
print("[Đã có] Mục 45: Chương 45")
print("[Lưu] Mục 46: Chương 46 trở về — 7,932 ký tự")
print("[Lưu] Mục 47: Chương 47 — 8,001 ký tự")
print("[Xong] Đã đến mục mới nhất: Chương 47.")
print("Tổng đã lưu: 47 chương | Mới tải: 2")
print("Hoàn tất đến chương mới nhất: CÓ")
'''

FAILING = r'''
import sys
print("Tên truyện : Truyện X")
print("[Lưu] Mục 1: Chương 1 — 500 ký tự")
print("[LỖI] HTTP 429: website hạn chế truy cập.", file=sys.stderr)
sys.exit(1)
'''


class StoryCrawlTests(unittest.TestCase):
    def run_fake(self, body, **start):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp, 'crawl_wikicv.py')
            script.write_text(body, encoding='utf-8')
            finished = []
            crawler = Crawler(script, Path(tmp, 'du_lieu_truyen'), on_finish=finished.append)
            crawler.start('https://wikicv.org/truyen/trong-sinh-YNdD', **start)
            with self.assertRaises(ValueError):
                crawler.start('https://wikicv.org/truyen/other')  # one download at a time
            for _ in range(200):
                if finished:
                    break
                time.sleep(0.05)
            return crawler.status(), finished

    def test_progress_is_read_from_the_downloader_output(self):
        status, finished = self.run_fake(FAKE)
        self.assertFalse(status['running'])
        self.assertEqual((status['title'], status['folder']), ('Trọng Sinh Chi Khẩn Cấp Công Lược', 'trong-sinh-YNdD'))
        self.assertEqual((status['saved'], status['known'], status['position'], status['last']), (2, 1, 47, 'Chương 47'))
        self.assertEqual((status['total'], status['complete'], status['error']), (47, True, None))
        self.assertEqual(len(finished), 1)

    def test_stop_signal_from_the_site_is_reported(self):
        status, _ = self.run_fake(FAILING)
        self.assertEqual(status['saved'], 1)
        self.assertEqual(status['error'], 'HTTP 429: website hạn chế truy cập.')
        self.assertEqual(status['code'], 1)

    def test_only_wikicv_book_links(self):
        for bad in ('http://wikicv.org/truyen/a', 'https://evil.example/truyen/a', 'https://wikicv.org/user/a', ''):
            with self.assertRaises(ValueError):
                valid_url(bad)
        self.assertEqual(valid_url(' https://wikicv.org/truyen/a-b '), 'https://wikicv.org/truyen/a-b')


if __name__ == '__main__':
    unittest.main()
