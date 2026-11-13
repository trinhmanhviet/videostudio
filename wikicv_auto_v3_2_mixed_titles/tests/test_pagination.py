import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs,urlparse
from unittest.mock import patch
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crawl_wikicv as crawler

INTRO='https://wikicv.org/truyen/test-long-story-1234567890abcdef'
BASE='https://wikicv.org/truyen/test-long-story/'
URLS=[BASE+f'chuong-{i}-abcdefghijklmnop' for i in range(1,9)]
BOOKID='aaabbbcc'
KEY='ffeeddccbbaa'


def intro_html(latest=8):
    return f'''<html><body><h1>Test Long Story</h1>
    <a href="{URLS[0]}">Đọc</a><a href="{URLS[latest-1]}">Chương {latest} mới nhất</a>
    <script>var bookId = "{BOOKID}"; var signKey = "{KEY}";
    function fuzzySign(text){{return text.substring(80)+text.substring(0,80);}}</script>
    </body></html>'''


def page_html(nums):
    return '<ul>'+''.join(f'<li class="chapter-name"><a href="{URLS[i-1]}">Chương {i}</a></li>' for i in nums)+'</ul>'


def chap_html(i,with_dynamic=False):
    if with_dynamic:
        return f'''<html><head><script>var signKey = "{KEY}";
        function fuzzySign(text){{return text.substring(80)+text.substring(0,80);}}
        var transType = "vi"; var editName = false;</script></head><body>
        <input name="chapterId" value="abcdef{i:03x}"><p class="book-title">Truyện</p>
        <p class="book-title">Chương {i}</p><div id="bookContentBody"></div></body></html>'''
    return f'<h2>Chương {i}</h2><p>Tác giả: Test</p><h2>Chương {i}</h2><div id="bookContentBody"><p>{"Nội dung " + str(i) + ". ":>s}' + 'Đoạn kể ở chương này. '*15 +'</p></div>'


def resp(url,text,status=200):
    return SimpleNamespace(url=url,status_code=status,content=text.encode('utf-8'),text=text,raise_for_status=lambda:None)


class FakeSession:
    def __init__(self,n=8,page_size=2,duplicate=False, dynamic=False):
        self.n=n
        self.page_size=page_size
        self.duplicate=duplicate
        self.dynamic=dynamic
        self.visited=[]
        self.posts=[]

    def get(self,url,**kwargs):
        self.visited.append(url)
        parsed=urlparse(url)
        if url == INTRO:
            return resp(url,intro_html(self.n))
        if parsed.path == '/book/index':
            args=parse_qs(parsed.query)
            start=int(args['start'][0]); size=int(args['size'][0])
            if size!=self.page_size: raise AssertionError('Unexpected page size')
            if args['sign'][0] != (KEY+str(start)+str(size)):
                raise AssertionError('Invalid short-key signature')
            if self.duplicate and start>=4:
                start=2
            return resp(url,page_html(range(start+1,min(start+size,self.n)+1)))
        if url in URLS:
            i=URLS.index(url)+1
            return resp(url,chap_html(i,self.dynamic))
        raise AssertionError('Unknown URL '+url)

    def post(self,url,**kwargs):
        self.posts.append((url,kwargs))
        if urlparse(url).path!='/chapters/content': raise AssertionError(url)
        i=int(kwargs['data']['id'][-3:],16)
        return resp(url,f'<div id="bookContentBody"><p>Chương {i} đã tải bằng API. '+('Bài viết '+str(i)+'. ')*22+'</p></div>')


def args(out,n=8):
    return SimpleNamespace(url=INTRO,output=str(out),timeout=5,delay=1,max_chapters=0,
        min_chars=100,refresh=False,sequential_only=False,index_page_size=2)


class IndexTests(unittest.TestCase):
    def test_four_pages_and_content_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            fake=FakeSession(dynamic=True)
            with patch.object(crawler,'make_session',return_value=fake),patch.object(crawler,'check_robots',return_value=True),patch.object(crawler.time,'sleep',return_value=None):
                dest=crawler.run(args(temp))
            index_requests=[url for url in fake.visited if '/book/index' in url]
            self.assertEqual([int(parse_qs(urlparse(u).query)['start'][0]) for u in index_requests],[0,2,4,6])
            self.assertEqual(len(fake.posts),8)
            rows=json.loads((dest/'chapters.json').read_text('utf-8'))
            self.assertEqual(len(rows),8)
            combined=(dest/'truyen_gop.txt').read_text('utf-8')
            self.assertIn('Chương 8 đã tải bằng API', combined)
            self.assertLess(combined.index('Chương 1 đã tải'),combined.index('Chương 8 đã tải'))
            second=FakeSession(dynamic=True)
            with patch.object(crawler,'make_session',return_value=second),patch.object(crawler,'check_robots',return_value=True),patch.object(crawler.time,'sleep',return_value=None):
                crawler.run(args(temp))
            self.assertEqual(len(second.posts),0)
            self.assertEqual(len([u for u in second.visited if u in URLS]),0)

    def test_duplicate_page_is_error_not_success(self):
        fake=FakeSession(duplicate=True)
        with patch.object(crawler.time,'sleep',return_value=None):
            with self.assertRaisesRegex(ValueError,'lặp lại'):
                crawler.get_full_index(fake,INTRO,intro_html(),URLS[0],URLS[-1],5,1,2)

    def test_no_index_metadata_falls_back(self):
        self.assertIsNone(crawler.extract_index_meta('<html>No metadata</html>'))

    def test_partial_index_never_passes(self):
        fake=FakeSession(n=8)
        with patch.object(crawler.time,'sleep',return_value=None):
            index=crawler.get_full_index(fake,INTRO,intro_html(),URLS[0],URLS[7],5,1,2)
        self.assertEqual(len(index),8)

if __name__=='__main__': unittest.main(verbosity=2)
