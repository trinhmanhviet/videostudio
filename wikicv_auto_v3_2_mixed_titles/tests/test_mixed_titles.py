import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from bs4 import BeautifulSoup
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crawl_wikicv as crawler

INTRO='https://wikicv.org/truyen/hon-hop-nhieu-kieu-abcdefghijklmno1'
BASE='https://wikicv.org/truyen/hon-hop-nhieu-kieu/'
LABELS=[
    'Trang 1 - bị bắt trở thành đỉnh lưu sau ( 1 )',
    'Chương 2',
    'Đệ 020-021 chương',
    'Phần 28',
    '13. Chương 13 có người theo dõi',
    'Trang 1040 TVH',
]
LINKS=[BASE+f'foo-{i}-abcdefghijklm{i:03}' for i in range(1,len(LABELS)+1)]


def intro():
    return ('<html><h1>Truyện hỗn hợp</h1>'
            f'<div><a href="{LINKS[0]}">Đọc</a></div>'
            f'<div><span>Mới nhất: </span><a href="{LINKS[-1]}">{LABELS[-1]}</a></div>'
            '</html>')


def chap(i):
    label=LABELS[i]
    next_link= (f'<a href="{LINKS[i+1]}">'
                + ('Trang sau' if i==0 else 'Phần sau' if i==1 else 'Tiếp theo')
                + '</a>') if i<len(LINKS)-1 else ''
    # A chapter heading *inside* the page is not an outer navigation boundary.
    preface = f'<p>Lời tựa đầu trang nên được giữ nguyên ở mục {i}. '+ ('Văn mở đầu. '*15) +'</p>'
    story = '<p>Chương 1 chỉ là tiêu đề nằm bên trong nội dung. '+('Câu chuyện tiếp diễn. '*15)+'</p>'
    return (f'<html><head><title>Truyện hỗn hợp - {label}</title></head><body>'
            f'<h1>Truyện hỗn hợp</h1><a href="{LINKS[i]}">{label}</a>'
            f'<p>Tác giả: Tên tác giả</p><div id="bookContentBody">{preface}{story}</div>'
            f'{next_link}<footer>Bình luận</footer></body></html>')

class FakeSession:
    def __init__(self):
        self.urls=[]
    def get(self,url,**kwargs):
        self.urls.append(url)
        if url==INTRO:
            body=intro()
        elif url in LINKS:
            body=chap(LINKS.index(url))
        else:
            raise AssertionError('Unexpected request: '+url)
        return SimpleNamespace(url=url,status_code=200,content=body.encode('utf-8'),
                               text=body,raise_for_status=lambda:None)

class MixedTests(unittest.TestCase):
    def test_intro_does_not_require_chuong(self):
        book,start,latest,last_no = crawler.get_book_info(BeautifulSoup(intro(),'html.parser'),INTRO)
        self.assertEqual(book,'Truyện hỗn hợp')
        self.assertEqual(start,LINKS[0])
        self.assertEqual(latest,LINKS[-1])
        self.assertEqual(last_no,1040)

    def test_percent_encoded_tilde_in_introduction_id(self):
        example = 'https://wikicv.org/truyen/xuyen-nhanh-vai-ac-nu-chu-man-cap-luc-sa-Ym0Y1VS4CCm%7EQm_T'
        raw = 'https://wikicv.org/truyen/xuyen-nhanh-vai-ac-nu-chu-man-cap-luc-sa/'
        first = raw + 'trang-1-bi-bat-tro-thanh-dinh-luu-sau-1-Ym2PG8QsRGEDAt93'
        last = raw + 'trang-1040-tvh-ZRBQZ8QsRE9UuKA1'
        html = ('<h1>Ví dụ</h1>'
                f'<a href="{first}">Đọc</a>'
                f'<span>Mới nhất: <a href="{last}">Trang 1040 TVH</a></span>')
        _,a,b,_ = crawler.get_book_info(BeautifulSoup(html,'html.parser'),example)
        self.assertEqual((a,b),(first,last))

    def test_urls_do_not_require_number(self):
        for url in LINKS:
            self.assertEqual(crawler.chapter_parent(url),'hon-hop-nhieu-kieu')

    def test_keep_exact_labels_and_embedded_chapter_marker(self):
        for i,url in enumerate(LINKS):
            soup=BeautifulSoup(chap(i),'html.parser')
            self.assertEqual(crawler.get_title(soup,url,'Truyện hỗn hợp'),LABELS[i])
            content=crawler.extract_content(soup,LABELS[i])
            self.assertIn('Lời tựa đầu trang',content)
            self.assertIn('Chương 1 chỉ là tiêu đề nằm bên trong nội dung.',content)

    def test_sequential_uses_order_not_title_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(url=INTRO,output=tmp,timeout=5,delay=0,max_chapters=0,
                min_chars=100,refresh=False,sequential_only=True,index_page_size=501,delay_max=0)
            fake=FakeSession()
            with patch.object(crawler,'make_session',return_value=fake), \
                    patch.object(crawler,'check_robots',return_value=True), \
                    patch.object(crawler.time,'sleep',return_value=None):
                dest=crawler.run(args)
            m=json.loads((dest/'chapters.json').read_text(encoding='utf-8'))
            self.assertEqual([x['title'] for x in m],LABELS)
            self.assertEqual([x['number'] for x in m],[1,2,3,4,5,6])
            self.assertEqual([x['url'] for x in m],LINKS)
            for i in range(1,7):
                p=dest/f'chapters/chuong_{i:05d}.txt'
                body=p.read_text(encoding='utf-8')
                self.assertTrue(body.startswith(LABELS[i-1]+'\n'))
                self.assertNotIn('Nguồn:',body)
            combo=(dest/'truyen_gop.txt').read_text(encoding='utf-8')
            self.assertLess(combo.index(LABELS[1]),combo.index(LABELS[2]))
            self.assertLess(combo.index(LABELS[3]),combo.index(LABELS[4]))
            src=json.loads((dest/'truyen.json').read_text(encoding='utf-8'))
            self.assertEqual(src['chapter_sources'][-1]['title'],'Trang 1040 TVH')
            self.assertEqual(src['chapter_sources'][-1]['position'],6)
            self.assertFalse(any('/book/index' in x for x in fake.urls))

    def test_toc_mixed_entries_no_numbering_assumptions(self):
        raw='<ul>'+''.join(f'<li class="chapter-name"><a href="{url}">{label}</a></li>'
                for label,url in zip(LABELS,LINKS))+'</ul>'
        self.assertEqual(crawler.parse_index_page(raw,INTRO,'hon-hop-nhieu-kieu'),list(zip(LABELS,LINKS)))

    def test_page_without_expected_chapter_number_is_not_cut(self):
        text=('Trang 1\nTác giả: Test\nĐoạn giới thiệu quan trọng.\n'
              'Chương 1\nTác phẩm bắt đầu.\nTruyện được nhúng bởi AI')
        parsed=crawler.trim_content(text,'Trang 1')
        self.assertIn('Đoạn giới thiệu quan trọng.',parsed)
        self.assertIn('Chương 1',parsed)
        self.assertIn('Tác phẩm bắt đầu.',parsed)
        self.assertNotIn('Truyện được nhúng',parsed)

    def test_fail_if_latest_missing_not_guess_number(self):
        html=f'<html><h1>Truyện hỗn hợp</h1><a href="{LINKS[0]}">Đọc</a></html>'
        with self.assertRaisesRegex(ValueError, 'Mới nhất'):
            crawler.get_book_info(BeautifulSoup(html,'html.parser'),INTRO)

    def test_block_page_not_saved(self):
        fake=FakeSession()
        fake.get=lambda url,**kwargs: SimpleNamespace(url=url,status_code=200,
            content=b'<html>Error 1006 - Cloudflare Ray ID: xxx</html>',
            raise_for_status=lambda:None)
        with self.assertRaisesRegex(RuntimeError,'Cloudflare'):
            crawler.fetch_html(fake,LINKS[0],5)

if __name__=='__main__': unittest.main(verbosity=2)
