import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crawl_wikicv as crawler
from test_pagination import INTRO, URLS, FakeSession, args

class Fallback404Tests(unittest.TestCase):
    def test_404_index_falls_back_and_saves_content(self):
        with tempfile.TemporaryDirectory() as t:
            fake=FakeSession(n=8)
            def go_next(soup,url,parent):
                i=URLS.index(url)
                return URLS[i+1] if i+1 < len(URLS) else None
            err=requests.HTTPError('404 Client Error: Not Found', response=SimpleNamespace(status_code=404))
            with patch.object(crawler,'make_session',return_value=fake), patch.object(crawler,'check_robots',return_value=True), \
                 patch.object(crawler,'get_full_index',side_effect=err), patch.object(crawler,'get_series_next',side_effect=go_next), \
                 patch.object(crawler.time,'sleep',return_value=None):
                out=crawler.run(args(t))
            self.assertEqual(len(list((out/'chapters').glob('*.txt'))),8)
            self.assertTrue((out/'truyen_gop.txt').exists())

    def test_403_index_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as t:
            err=requests.HTTPError('403', response=SimpleNamespace(status_code=403))
            with patch.object(crawler,'make_session',return_value=FakeSession(n=8)), \
                 patch.object(crawler,'check_robots',return_value=True),patch.object(crawler,'get_full_index',side_effect=err):
                with self.assertRaises(requests.HTTPError):
                    crawler.run(args(t))

if __name__ == '__main__':
    unittest.main()
