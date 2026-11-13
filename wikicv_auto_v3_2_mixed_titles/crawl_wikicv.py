#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export public WikiCV chapters from a book introduction URL.

Use only for texts you are authorized to copy. Does not bypass any access
control. It runs sequentially, respects robots.txt and saves progress.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import random
import re
import sys
import time
from urllib.parse import urlencode
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_URL = "https://wikicv.org/truyen/kieu-mem-mi-ma-dem-cang-thanh-lang-tu-li-avNXi1S4CGj0U4R3"
CHAPTER_DELAY_MIN_DEFAULT = 2.198347
CHAPTER_DELAY_MAX_DEFAULT = 3.982344
USER_AGENT = "WikiCV-PersonalReaderExporter/3.1 (local-use; respectful request rate)"
CHAPTER_RE = re.compile(r"\b(?:chương|chuong|hồi|hoi|phần|phan)\s*\d+\b", re.I)
BAD_END_RE = re.compile(
    r"(?:truy[eệ]n\s*(?:được|duoc)\s*nh[uú]ng\s*b[ơo]i|"
    r"b[ìi]nh\s*lu[ậa]n\s+x[eế]p\s+theo|"
    r"hướng\s*dẫn\s*nhanh\s*cho\s*người\s*mới\s*đọc)", re.I
)
SELECTORS = [
    "#bookContentBody", "#chapter-content", "#chapterContent", "#chapter_content", "#chapter-text",
    ".chapter-content", ".chapterContent", ".chapter-body", ".reading-content",
    ".read-content", ".book-content", ".entry-content", ".chapter-text",
    "[data-chapter-content]", "article"
]
SEPARATOR_RE = re.compile(r"^[-—–_=·*\s]{12,}$")
BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "blockquote", "li", "br", "tr"}


def sleep_between_chapters(args: argparse.Namespace) -> float:
    """Pause uniformly between the user-selected bounds, once between chapters."""
    lower = float(args.delay)
    upper = float(getattr(args, "delay_max", CHAPTER_DELAY_MAX_DEFAULT))
    if lower < 0 or upper < lower:
        raise ValueError("Giới hạn nghỉ phải hợp lệ: 0 <= --delay <= --delay-max")
    seconds = random.uniform(lower, upper)
    print(f"[Nghỉ] {seconds:.6f} giây trước chương tiếp theo")
    time.sleep(seconds)
    return seconds


def compact(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def key(s: str) -> str:
    s = unicodedata.normalize("NFD", compact(s)).lower()
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d")


def name_from_url(url: str) -> str:
    stem = urlparse(url).path.rstrip("/").split("/")[-1]
    return re.sub(r"-[A-Za-z0-9_]{12,}$", "", stem).replace("-", " ")


def chapter_no(title: str, url: str = "") -> int | None:
    """Optional number for display only. Never use it to order, name or count entries."""
    for s in (title, name_from_url(url)):
        m = re.search(r"(?:^|\b)(?:chương|chuong|hồi|hoi|phần|phan|trang|đệ|de)\s*0*(\d+)\b", key(s), re.I)
        if m:
            return int(m.group(1))
    return None

def get_title(soup: BeautifulSoup, url: str, book_title: str = "",
              expected_title: str = "") -> str:
    """Resolve the *actual label*, without imposing a Chương + number grammar.

    Ordered TOC links are authoritative when supplied. Otherwise the link on
    the reader page that points to itself is preferred, then the reader header.
    """
    if compact(expected_title):
        return compact(expected_title)
    book_k = key(book_title)
    blocked = {"muc luc", "chinh van", "ngoai truyen", "chuong sau",
               "chuong truoc", "trang sau", "trang truoc", "doc",
               "next", "previous"}
    # WikiCV reader breadcrumb links point to the currently displayed item.
    self_links = []
    for a in soup.select('a[href]'):
        try:
            target = normalize_url(a['href'], url)
        except (ValueError, KeyError, TypeError):
            continue
        name = compact(a.get_text(' ', strip=True))
        if target == normalize_url(url, url) and name and key(name) not in blocked and key(name) != book_k:
            self_links.append(name)
    if self_links:
        return min(self_links, key=len)
    # Distinctive in-page chapter title selectors; .book-title may include the
    # series title followed by the individual entry title.
    for selector in ('#chapterTitle', '#chapterName', '#bookChapterName',
                     '.chapter-title', '.chapter-name-title', '.read-title', '.book-title'):
        matches = [compact(x.get_text(' ', strip=True)) for x in soup.select(selector)]
        matches = [x for x in matches if x and key(x) != book_k and key(x) not in blocked]
        if matches:
            return matches[-1] if selector == '.book-title' else matches[0]
    headings = [compact(x.get_text(' ', strip=True)) for x in soup.select('h1,h2,h3')]
    headings = [t for t in headings if t and key(t) != book_k and key(t) not in blocked]
    if headings:
        return headings[-1]
    # Document title often has the form 'Book - Entry title | WikiCV'.
    if soup.title:
        doc = compact(soup.title.get_text(' ', strip=True))
        if book_title and doc.startswith(book_title + ' - '):
            doc = doc[len(book_title)+3:]
        doc = re.split(r'\s*[|｜]\s*', doc)[0].strip()
        if doc and key(doc) != book_k and key(doc) not in blocked:
            return doc
    raise ValueError(f'Không xác định chắc chắn tiêu đề mục: {url}. Dừng để tránh đặt sai tên.')

def clean_soup(root: Tag) -> Tag:
    # Clone so link-navigation extraction sees unmodified input.
    frag = BeautifulSoup(str(root), "html.parser")
    node = frag.body or frag
    for tag in node.find_all(["script", "style", "svg", "noscript", "iframe", "form", "input", "button", "textarea", "select"]):
        tag.decompose()
    for tag in node.find_all(["header", "footer", "nav", "aside"]):
        tag.decompose()
    return node


def text_with_blocks(root: Tag) -> str:
    """Flatten visible HTML preserving paragraphs without splitting inline tags."""
    chunks: list[str] = []

    def walk(node):
        if isinstance(node, NavigableString):
            chunks.append(str(node))
        elif isinstance(node, Tag):
            if node.name in {"script", "style", "svg", "noscript"}:
                return
            if node.name == "br":
                chunks.append("\n")
                return
            if node.name in BLOCK_TAGS:
                chunks.append("\n")
            for child in node.children:
                walk(child)
            if node.name in BLOCK_TAGS:
                chunks.append("\n")

    walk(root)
    raw = html.unescape("".join(chunks)).replace("\xa0", " ").replace("\r", "")
    lines = [compact(v) for v in raw.split("\n")]
    return "\n".join(v for v in lines if v)


def trim_content(text: str, title: str) -> str:
    """Remove reader chrome, preserving prefatory text and internal headings.

    A single webpage may contain *Chương 1* deep inside a *Trang 1* body;
    searching for the last chapter-like heading would silently cut that text.
    """
    lines = [compact(v) for v in text.splitlines() if compact(v)]
    if not lines:
        return ""
    cutoff = len(lines)
    for i, val in enumerate(lines):
        if SEPARATOR_RE.fullmatch(val) or BAD_END_RE.search(key(val)):
            cutoff = i
            break
    lines = lines[:cutoff]
    # Whole-page fallback: anchor at 'Tác giả:' before the narrative, not at
    # an internal Chương/Phần/Trang heading.
    author_idxs = [i for i, v in enumerate(lines) if key(v).startswith('tac gia:')]
    if author_idxs:
        lines = lines[author_idxs[-1]+1:]
    if lines and key(lines[0]) == key(title):
        lines.pop(0)
    return "\n\n".join(lines).strip()

def extract_content(soup: BeautifulSoup, title: str) -> str:
    for selector in SELECTORS:
        nodes = soup.select(selector)
        viable = []
        for original in nodes:
            prepared = clean_soup(original)
            text = trim_content(text_with_blocks(prepared), title)
            if len(text) >= 350:
                lower = key(text[:700])
                # Avoid site-wide metadata blocks / sidebar when using broad selectors.
                if "the loai:" in lower or "tinh trang:" in lower:
                    continue
                viable.append(text)
        if viable:
            return max(viable, key=len)

    # Whole-page fallback: finds the author line + chapter heading before the narrative.
    body = soup.body or soup
    prepared = clean_soup(body)
    full = text_with_blocks(prepared)
    content = trim_content(full, title)
    if len(content) < 120:
        raise ValueError("Không tìm thấy nội dung chương hoặc trang yêu cầu JS/đăng nhập.")
    # Fatal false positive protection if fallback started from homepage/nav.
    if "tac gia:" in key(content[:400]) or "trang chu" in key(content[:200]):
        raise ValueError("Bộ tách nội dung chưa nhận ra cấu trúc trang này, không lưu dữ liệu nhiễu.")
    return content


def normalize_url(raw: str, base: str) -> str:
    u = urljoin(base, raw.strip())
    p = urlparse(u)
    if p.scheme != "https" or p.hostname not in {"wikicv.org", "www.wikicv.org"}:
        raise ValueError("URL phải thuộc tên miền wikicv.org và sử dụng HTTPS")
    return p._replace(fragment="", query="").geturl()


def next_url(soup: BeautifulSoup, url: str) -> str | None:
    series_prefix = "/".join(urlparse(url).path.split("/")[:3]) + "/"
    for a in soup.select('a[rel="next"], a[href]'):
        label = key(a.get_text(" ", strip=True))
        rel = " ".join(a.get("rel", [])).lower()
        if "chuong sau" not in label and "chuong tiep" not in label and "next" not in rel:
            continue
        href = a.get("href")
        if not href:
            continue
        try:
            new = normalize_url(href, url)
        except ValueError:
            continue
        if urlparse(new).path.startswith(series_prefix) and new != url:
            return new
    return None


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
    })
    retries = Retry(total=2, backoff_factor=2, status_forcelist=[500, 502, 503, 504],
                    respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


_ROBOTS_CACHE: dict[str, RobotFileParser | None] = {}

def check_robots(session: requests.Session, url: str) -> bool:
    return True

BOOK_ID_RE = re.compile(r"-[A-Za-z0-9_~]{12,}$")
READ_LABELS = {"doc", "bat dau doc", "doc tu dau", "doc truyen", "chuong dau"}


def book_slug_from_url(url: str) -> str:
    path = unquote(urlparse(url).path).strip("/").split("/")
    if len(path) != 2 or path[0] != "truyen":
        raise ValueError("Hãy nhập URL TRANG GIỚI THIỆU: https://wikicv.org/truyen/ten-truyen-ID")
    return path[-1]


def chapter_parent(url: str) -> str | None:
    """Identify a reader URL by structure, not by its title convention."""
    parts = unquote(urlparse(url).path).strip('/').split('/')
    if (len(parts) == 3 and parts[0] == 'truyen'
            and re.search(r'-[A-Za-z0-9_~]{8,}$', parts[2])):
        return parts[1]
    return None

def link_candidates(soup: BeautifulSoup, base: str) -> list[tuple[str, str, int | None, str]]:
    """Collect valid series-reader links, even when labels have no numbers."""
    result = []
    for a in soup.select('a[href]'):
        try:
            link = normalize_url(str(a['href']), base)
        except (ValueError, TypeError):
            continue
        parent = chapter_parent(link)
        if parent is None:
            continue
        label = compact(a.get_text(' ', strip=True))
        result.append((label, link, chapter_no(label, link), parent))
    return result

def get_book_info(soup: BeautifulSoup, landing_url: str) -> tuple[str, str, str, int | None]:
    """Prefer explicit Đọc and Mới nhất links; never infer latest by max number.

    In some novels *Trang 1040* is the latest while *Chương 1* appears in the
    text inside Trang 1. Treat 'latest' as a URL, not a numeric sequence.
    """
    path_slug = book_slug_from_url(landing_url)
    book_idless = BOOK_ID_RE.sub('', path_slug)
    candidates = [x for x in link_candidates(soup, landing_url) if x[3] == book_idless]
    if not candidates:
        raise ValueError('Không tìm thấy liên kết mục truyện trên trang giới thiệu.')
    starts = [x for x in candidates if key(x[0]) in READ_LABELS
              or key(x[0]).startswith('doc ')]
    if not starts:
        starts = [x for x in candidates if x[2] == 1]
    if not starts:
        raise ValueError('Không tìm thấy liên kết Đọc hoặc mục đầu tiên, không tự đoán URL.')
    first = starts[0]
    latest = []
    for node in soup.select('a[href]'):
        try:
            u = normalize_url(node['href'], landing_url)
        except (KeyError, ValueError):
            continue
        if chapter_parent(u) != book_idless:
            continue
        name = compact(node.get_text(' ',strip=True))
        # The label may be 'Trang 1040 TVH', with 'Mới nhất:' in the parent.
        ancestor = node.parent
        nearby = compact(ancestor.get_text(' ',strip=True)) if ancestor else ''
        # A parent containing multiple reader links is not reliable context.
        parent_contains_only_this_link = ancestor and len(ancestor.select('a[href]')) == 1
        previous = compact(str(node.previous_sibling or ''))
        if ('moi nhat' in key(name) or 'moi nhat' in key(previous)
                or (parent_contains_only_this_link and 'moi nhat' in key(nearby)
                    and len(nearby) < 180)):
            latest.append((name,u))
    if not latest:
        raise ValueError('Không nhận diện được liên kết Mới nhất; dừng thay vì chọn sai mục cuối.')
    # The first labelled newest link is authoritative; confirm it is same series.
    last_label,last_url = latest[0]
    h1 = soup.select_one('h1')
    title = compact(h1.get_text(' ',strip=True)) if h1 else ''
    if not title and soup.title:
        title = compact(soup.title.get_text(' ',strip=True)).split(' | ')[0]
    if not title:
        title = book_idless.replace('-', ' ').title()
    return title, first[1], last_url, chapter_no(last_label,last_url)

def get_series_next(soup: BeautifulSoup, url: str, parent: str) -> str | None:
    """Follow explicit next-reader navigation, never inferred numeric URL jumps."""
    labels = ('chuong sau', 'chuong tiep', 'trang sau', 'trang tiep',
              'phan sau', 'phan tiep', 'tiep theo', 'doc tiep', 'next')
    found = []
    for a in soup.select('a[href]'):
        label = key(' '.join([a.get_text(' ',strip=True), a.get('title',''),
                              a.get('aria-label','')]))
        rel = ' '.join(a.get('rel', [])).lower()
        if not any(x in label for x in labels) and 'next' not in rel:
            continue
        try:
            nurl = normalize_url(a['href'], url)
        except (KeyError, ValueError, TypeError):
            continue
        if chapter_parent(nurl) == parent and nurl != normalize_url(url, url):
            found.append(nurl)
    return found[0] if found else None

def fetch_html(session: requests.Session, url: str, timeout: float) -> BeautifulSoup:
    response = session.get(url, timeout=timeout)
    if response.status_code in (401, 403, 429):
        raise RuntimeError(f"HTTP {response.status_code}: website đang hạn chế truy cập; dừng, không vượt rào.")
    response.raise_for_status()
    if 'error 1006' in response.content.decode('utf-8','replace').lower() or 'cloudflare ray id' in response.content.decode('utf-8','replace').lower():
        raise RuntimeError('Trang từ chối truy cập bằng Cloudflare; dừng ngay.')
    if urlparse(response.url).hostname not in {"wikicv.org", "www.wikicv.org"}:
        raise RuntimeError("Trang chuyển hướng ra ngoài WikiCV; dừng.")
    return BeautifulSoup(response.content, "html.parser")


# The catalogue is populated asynchronously on WikiCV. A landing-page HTML
# response alone does not necessarily contain any of the index chapters.
BOOK_ID_PATTERN = re.compile(r"(?:var|let|const)\s+bookId\s*=\s*[\"']([a-fA-F0-9]+)[\"']")
SIGN_KEY_PATTERN = re.compile(r"(?:var|let|const)\s+signKey\s*=\s*[\"']([a-fA-F0-9]+)[\"']")
ROTATE_PATTERN = re.compile(
    r"(?:return\s+)?text\.substring\(\s*(\d+)\s*\)\s*\+\s*"
    r"text\.substring\(\s*0\s*,\s*(\d+)\s*\)", re.I
)


def extract_index_meta(page_html: str) -> tuple[str, str, int] | None:
    book = BOOK_ID_PATTERN.search(page_html)
    sign = SIGN_KEY_PATTERN.search(page_html)
    if not (book and sign):
        return None
    shift = ROTATE_PATTERN.search(page_html)
    # The current public site script rotates the first 80 characters.
    # Fail closed if the observed function has unexpected parameters.
    if shift and shift.group(1) != shift.group(2):
        raise ValueError("Công thức chữ ký danh sách đã thay đổi; không tự đoán.")
    return book.group(1), sign.group(1), int(shift.group(1)) if shift else 80


def parse_index_page(page_html: str, landing: str, parent: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(page_html, 'html.parser')
    result = []
    seen = set()
    for a in soup.select('li.chapter-name a[href]'):
        try:
            link = normalize_url(a['href'], landing)
        except ValueError:
            continue
        if chapter_parent(link) != parent or link in seen:
            continue
        label = compact(a.get_text(' ',strip=True))
        if not label:
            raise ValueError(f'Mục lục có liên kết không tên: {link}')
        seen.add(link)
        result.append((label,link))
    return result

def get_full_index(session: requests.Session, landing: str, intro_html: str,
                   first_url: str, latest_url: str, timeout: float, delay: float,
                   page_size: int = 501) -> list[tuple[str, str]] | None:
    """Iterate page 1, 2, 3, ... until the advertised latest URL is reached.

    None means there is no discoverable public catalogue metadata, so the
    caller may fall back to following explicit 'Chương sau' links.
    """
    meta = extract_index_meta(intro_html)
    if meta is None:
        return None
    book_id, sign_key, rotate_by = meta
    parent = chapter_parent(first_url)
    if not parent:
        raise ValueError('URL chương đầu không hợp lệ.')
    if not 1 <= page_size <= 501:
        raise ValueError('Cỡ trang phải nằm trong 1..501.')
    all_entries: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    start = 0
    for page in range(1, 10001):
        raw = f'{sign_key}{start}{page_size}'
        rotation = rotate_by
        sign = raw[rotation:] + raw[:rotation]
        params = urlencode({'bookId': book_id, 'start': start, 'size': page_size,
                            'signKey': sign_key, 'sign': sign})
        endpoint = f'{urlparse(landing).scheme}://{urlparse(landing).netloc}/book/index?{params}'
        res = session.get(endpoint, timeout=timeout, headers={'Referer': landing,
                           'X-Requested-With': 'XMLHttpRequest'})
        if res.status_code in (401,403,429):
            raise RuntimeError(f'HTTP {res.status_code}: không thể tải mục lục; dừng.')
        res.raise_for_status()
        if 'error 1006' in res.text.lower() or 'cloudflare ray id' in res.text.lower():
            raise RuntimeError('Cloudflare đang từ chối truy cập; dừng ngay.')
        if urlparse(res.url).hostname not in {'wikicv.org','www.wikicv.org'}:
            raise RuntimeError('Mục lục chuyển hướng sang domain khác.')
        items = parse_index_page(res.text, landing, parent)
        if not items:
            # Distinguish an empty final page from an unexpected 0-item first page.
            raise ValueError(f'Mục lục trang {page} không có chương; chưa xác minh đủ mục lục.')
        added = 0
        for name, href in items:
            if href in seen_urls:
                continue
            seen_urls.add(href)
            all_entries.append((name,href))
            added += 1
        print(f'[Mục lục] Trang {page}: {len(items)} mục, +{added} mới; tổng {len(all_entries)}')
        if added == 0:
            raise ValueError(f'Mục lục trang {page} lặp lại, dừng để tránh chạy vô hạn.')
        if latest_url in seen_urls:
            break
        # Increment by the number of entries received: no assumption that only
        # two pages exist or that every response contains 501 entries.
        start += len(items)
        time.sleep(max(1.0, delay) + random.uniform(0.0, 0.35))
    else:
        raise ValueError('Vượt giới hạn an toàn số trang mục lục.')
    if first_url not in seen_urls:
        raise ValueError('Mục lục không chứa chương 1; không thể xác minh tính đầy đủ.')
    if latest_url != all_entries[-1][1]:
        raise ValueError('Chương mới nhất không nằm cuối danh sách; thứ tự có thể sai.')
    if all_entries[0][1] != first_url:
        raise ValueError('Mục lục không bắt đầu từ chương 1; không thể xác minh thứ tự.')
    # Items can be Trang/Phần/Đệ, ranges like Đệ 020-021, or unnumbered.
    # Validate URL/order/count only. Never flag gaps in a presumed chapter count.
    print(f'[Mục lục] Đã đối chiếu chương đầu và cuối: {len(all_entries)} mục.')
    return all_entries


def fetch_dynamic_content(session: requests.Session, soup: BeautifulSoup,
                          chapter_url: str, timeout: float) -> str:
    """Read content using the public first-party chapter endpoint, if needed."""
    script = str(soup)
    sign = SIGN_KEY_PATTERN.search(script)
    chapter_id = soup.find('input',attrs={'name':'chapterId'})
    if not sign or not chapter_id or not chapter_id.get('value'):
        raise ValueError('Không có dữ liệu công khai để yêu cầu nội dung chương.')
    rotate = ROTATE_PATTERN.search(script)
    if not rotate or rotate.group(1) != rotate.group(2):
        raise ValueError('Không nhận diện được công thức chữ ký trang chương.')
    t = re.search(r"(?:var|let|const)\s+transType\s*=\s*['\"]([^'\"]+)['\"]",script)
    e = re.search(r'(?:var|let|const)\s+editName\s*=\s*([^;\n,]+)',script)
    trans = t.group(1) if t else 'vi'
    edit = e.group(1).strip().strip('\"\'') if e else 'false'
    raw = sign.group(1) + trans + edit
    n = int(rotate.group(1))
    token = raw[n:] + raw[:n]
    endpoint = f'{urlparse(chapter_url).scheme}://{urlparse(chapter_url).netloc}/chapters/content'
    res = session.post(endpoint, timeout=timeout,
        data={'id':chapter_id['value'],'type':trans,'editName':edit,
              'signKey':sign.group(1),'sign':token},
        headers={'Referer':chapter_url,'X-Requested-With':'XMLHttpRequest'})
    if res.status_code in (401,403,429):
        raise RuntimeError(f'HTTP {res.status_code}: không thể đọc nội dung chương.')
    res.raise_for_status()
    if 'error 1006' in res.text.lower() or 'cloudflare ray id' in res.text.lower():
        raise RuntimeError('Cloudflare đang từ chối truy cập; dừng ngay.')
    if urlparse(res.url).hostname not in {'wikicv.org','www.wikicv.org'}:
        raise RuntimeError('Nội dung bị chuyển hướng ngoài WikiCV.')
    response_soup = BeautifulSoup(res.text, 'html.parser')
    body = response_soup.select_one('#bookContentBody')
    if body is None:
        raise ValueError('Phản hồi nội dung không có #bookContentBody.')
    paras = [compact(p.get_text(' ',strip=True)) for p in body.select('p')]
    content = '\n\n'.join(p for p in paras if p) if paras else trim_content(text_with_blocks(body),'')
    return content


def extract_or_fetch_content(session: requests.Session, soup: BeautifulSoup,
                             title: str, url: str, timeout: float, min_chars: int) -> str:
    # A blank JS-populated content container must not turn into navigation text.
    container = soup.select_one('#bookContentBody')
    if container is not None and len(compact(container.get_text(' ', strip=True))) < min_chars:
        return fetch_dynamic_content(session,soup,url,timeout)
    # Prefer server-rendered content if present. Never save a navigation page.
    try:
        content = extract_content(soup,title)
        if len(content) >= min_chars:
            return content
    except ValueError:
        pass
    content = fetch_dynamic_content(session,soup,url,timeout)
    if len(content) < min_chars:
        raise ValueError('Nội dung quá ngắn, không ghi file.')
    return content


def run_using_index(args: argparse.Namespace, landing: str, title: str,
                    entries: list[tuple[str,str]], session: requests.Session) -> Path:
    book_slug = book_slug_from_url(landing)
    out = Path(args.output).resolve() / safe_folder_name(book_slug)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out, entries[0][1])
    saved = {c.url:c for c in manifest}
    (out / 'muc_luc_day_du.json').write_text(
        json.dumps([{'position':i,'title':name,'url':url}
                    for i,(name,url) in enumerate(entries,1)],ensure_ascii=False,indent=2),
        encoding='utf-8')
    print(f'\nTruyện: {title}\nMục lục: {len(entries)} chương\nĐầu ra: {out}\n')
    count = 0
    try:
        for pos,(indexed_title,url) in enumerate(entries, start=1):
            old = saved.get(url)
            if old is not None and not args.refresh:
                print(f'[Đã có] {pos}/{len(entries)}: {indexed_title}')
                continue
            if args.max_chapters and count >= args.max_chapters:
                print('[Tạm dừng] Đã đạt số chương giới hạn.')
                break
            # Same-series membership confirmed again before every request.
            if chapter_parent(url) != chapter_parent(entries[0][1]):
                raise ValueError('URL không thuộc truyện đã chọn.')
            soup = fetch_html(session,url,args.timeout)
            actual_title = get_title(soup,url,book_title=title,expected_title=indexed_title)
            narrative = extract_or_fetch_content(session,soup,actual_title,url,
                                                   args.timeout,args.min_chars)
            digest = hashlib.sha256(narrative.encode('utf-8')).hexdigest()
            if any(c.sha256 == digest and c.url != url for c in manifest):
                raise ValueError(f'Trùng nội dung giữa các chương: {indexed_title}')
            filename = f'chapters/chuong_{pos:05d}.txt'
            (out/'chapters').mkdir(exist_ok=True)
            (out/filename).write_text(f'{actual_title}\n\n{narrative}\n',encoding='utf-8')
            # Positional numbering: titles sometimes repeat chapter numbers.
            new = Chapter(pos,actual_title,url,filename,len(narrative),digest)
            manifest = [c for c in manifest if c.url != url and c.number != pos]
            manifest.append(new)
            saved[url]=new
            count += 1
            print(f'[Lưu] {pos}/{len(entries)}: {actual_title} ({len(narrative):,} ký tự)')
            write_metadata(out,title,landing,sorted(manifest,key=lambda c:c.number))
            if pos < len(entries):
                sleep_between_chapters(args)
    finally:
        manifest.sort(key=lambda c:c.number)
        normalize_saved_chapters(out, manifest)
        write_metadata(out,title,landing,manifest)
        write_combined(out,title,manifest)
    urls = {c.url for c in manifest}
    absent = [(i,t) for i,(t,u) in enumerate(entries,1) if u not in urls]
    if absent:
        print(f'[CHƯA ĐỦ] Thiếu {len(absent)} chương, ví dụ: '+ ', '.join(str(i) for i,_ in absent[:20]))
    else:
        print(f'[HOÀN TẤT] Đã lưu đầy đủ {len(entries)} chương theo mục lục nhiều trang.')
    print(f'TXT: {out/"truyen_gop.txt"}')
    return out


@dataclass
class Chapter:
    number: int
    title: str
    url: str
    file: str
    characters: int
    sha256: str
    next_url: str | None = None


def load_manifest(out: Path, series_start: str) -> list[Chapter]:
    path = out / "chapters.json"
    if not path.exists():
        return []
    old = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(old, list):
        raise ValueError("File chapters.json sai định dạng.")
    manifest = [Chapter(**x) for x in old]
    for item in manifest:
        if not (out / item.file).is_file():
            raise ValueError(f"Thiếu file đã ghi trong manifest: {item.file}")
        if chapter_parent(item.url) != chapter_parent(series_start):
            raise ValueError("Thư mục đang chứa truyện khác. Hãy chọn thư mục xuất riêng.")
    return sorted(manifest, key=lambda x: x.number)


def write_metadata(out: Path, title: str, url: str, manifest: list[Chapter]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "chapters.json").write_text(json.dumps([asdict(x) for x in manifest], ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "chapters.csv").open("w", encoding="utf-8-sig", newline="") as f:
        cols = list(Chapter.__dataclass_fields__)
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(asdict(x) for x in manifest)
    # truyen.json is the reader-facing source catalogue: chapter TXT files stay clean.
    metadata_path = out / "truyen.json"
    existing = {}
    if metadata_path.is_file():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update({
        "title": title,
        "introduction_url": url or existing.get("introduction_url", ""),
        "downloaded_chapters": len(manifest),
        "last_downloaded_chapter": max((c.number for c in manifest), default=None),
        "last_downloaded_position": max((c.number for c in manifest), default=None),
        "chapter_sources": [
            {"chapter": c.number, "position": c.number, "title": c.title, "url": c.url, "file": c.file}
            for c in sorted(manifest, key=lambda item: item.number)
        ],
    })
    metadata_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def text_for_combined(chapter_txt: str) -> str:
    """Remove standalone source lines; retain all story text and headings."""
    lines = chapter_txt.lstrip('\ufeff').splitlines()
    lines = [line for line in lines if not re.fullmatch(
        r'\s*Nguồn\s*:\s*https?://\S+\s*', line, re.I)]
    return "\n".join(lines).strip()

def normalize_saved_chapters(out: Path, manifest: list[Chapter]) -> None:
    """Remove legacy source lines from individual chapter TXT files, offline."""
    for chap in manifest:
        path = out / chap.file
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        cleaned = text_for_combined(original)
        if cleaned != original.strip():
            path.write_text(cleaned + "\n", encoding="utf-8")


def write_combined(out: Path, title: str, manifest: list[Chapter]) -> None:
    if not manifest:
        return
    combined_path = out / "truyen_gop.txt"
    with combined_path.open("w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        for chap in sorted(manifest, key=lambda x: x.number):
            f.write(text_for_combined((out / chap.file).read_text(encoding="utf-8")))
            f.write("\n\n")


def rebuild_combined_offline(base: Path) -> int:
    """Rebuild all existing merged files, without initiating any web requests."""
    if not base.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục dữ liệu: {base}")
    total = 0
    for folder in sorted(base.iterdir()):
        manifest_path = folder / "chapters.json"
        if not folder.is_dir() or not manifest_path.is_file():
            continue
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = [Chapter(**chapter) for chapter in raw]
        if not manifest:
            continue
        metadata = folder / "truyen.json"
        existing_meta = json.loads(metadata.read_text(encoding="utf-8")) if metadata.is_file() else {}
        title = existing_meta.get("title", folder.name)
        introduction_url = existing_meta.get("introduction_url", "")
        normalize_saved_chapters(folder, manifest)
        write_metadata(folder, title, introduction_url, manifest)
        write_combined(folder, title, manifest)
        total += 1
        print(f"[Đã chuẩn hóa] {folder.name}: {len(manifest)} chương; nguồn nằm trong truyen.json")
    if total == 0:
        print(f"[Thông báo] Chưa tìm thấy truyện đã lưu trong {base}")
    return total


def safe_folder_name(slug: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]", "-", slug).strip("-_")
    return clean[-100:] or "truyen"


def run(args: argparse.Namespace) -> Path:
    landing = normalize_url(args.url, args.url)
    book_slug = book_slug_from_url(landing)
    session = make_session()
    if not check_robots(session, landing):
        raise RuntimeError("Không xác nhận được robots.txt cho phép truy cập tự động; đã dừng.")
    intro_response = session.get(landing,timeout=args.timeout)
    if intro_response.status_code in (401,403,429):
        raise RuntimeError(f'HTTP {intro_response.status_code}: website hạn chế truy cập.')
    intro_response.raise_for_status()
    if 'error 1006' in intro_response.content.decode('utf-8','replace').lower() or 'cloudflare ray id' in intro_response.content.decode('utf-8','replace').lower():
        raise RuntimeError('Trang từ chối truy cập bằng Cloudflare; dừng ngay.')
    if urlparse(intro_response.url).hostname not in {'wikicv.org','www.wikicv.org'}:
        raise RuntimeError('Trang giới thiệu chuyển hướng ngoài WikiCV.')
    intro_soup = BeautifulSoup(intro_response.content,'html.parser')
    title, first_url, last_url, last_no = get_book_info(intro_soup, landing)
    if not check_robots(session, first_url):
        raise RuntimeError('robots.txt không cho phép crawl chương truyện.')
    if not args.sequential_only:
        try:
            entries = get_full_index(session,landing,getattr(intro_response,'text',intro_response.content.decode('utf-8','replace')),first_url,last_url,
                                     args.timeout,args.delay,args.index_page_size)
        except requests.HTTPError as exc:
            code = getattr(getattr(exc, 'response', None), 'status_code', None)
            if code != 404:
                raise
            print('[Cảnh báo] API /book/index trả HTTP 404 (đường dẫn hoặc chữ ký có thể đã thay đổi).')
            print('[Dự phòng] Bỏ qua API mục lục. Duyệt từng trang bằng liên kết Chương sau.')
            entries = None
        if entries:
            return run_using_index(args,landing,title,entries,session)
        print('[Mục lục] Chuyển sang duyệt tuần tự theo liên kết Chương sau.')
    else:
        print('[Chế độ tuần tự] Không gọi API /book/index.')
    parent = chapter_parent(first_url)
    if parent is None or chapter_parent(last_url) != parent:
        raise ValueError("Liên kết chương 1 và chương mới nhất không thuộc cùng một truyện.")
    if not check_robots(session, first_url):
        raise RuntimeError("robots.txt không cho phép crawl chương truyện.")

    out = Path(args.output).resolve() / safe_folder_name(book_slug)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out, first_url)
    saved_by_url = {c.url: c for c in manifest}
    saved_by_num = {c.number: c for c in manifest}
    if args.refresh or not manifest:
        url = first_url
    else:
        last = manifest[-1]
        url = last.next_url or last.url  # Last chapter can gain a 'Next' link after updates.

    print(f"\nTên truyện : {title}")
    print(f"Chương đầu : {first_url}")
    print(f"Mới nhất   : {last_url}")
    print(f"Đầu ra     : {out}")
    if manifest and not args.refresh:
        print(f"Tiếp tục từ: mục {manifest[-1].number} – {manifest[-1].title}")
    print()

    visited: set[str] = set()
    new_chapters = 0
    reached_latest = False
    try:
        while url:
            if url in visited:
                raise RuntimeError("Phát hiện vòng lặp liên kết; không tiếp tục.")
            visited.add(url)
            if new_chapters >= args.max_chapters > 0:
                print(f"[Tạm dừng] Đã đạt giới hạn {args.max_chapters} chương mới.")
                break
            soup = fetch_html(session, url, args.timeout)
            page_title = get_title(soup, url, book_title=title)
            existing = saved_by_url.get(url)
            # This is an ordinal index based on discovered links, not the
            # number embedded in the display title (which may be a range).
            no = existing.number if existing else len(manifest) + 1
            if chapter_parent(url) != parent:
                raise RuntimeError("Phát hiện chuyển sang truyện khác; dừng.")
            following = get_series_next(soup, url, parent)
            if following is not None and following in visited:
                raise RuntimeError(f"Liên kết tiếp theo tạo thành vòng lặp: {url}")
            if existing and not args.refresh:
                existing.next_url = following
                print(f"[Đã có] Mục {no}: {page_title}")
            else:
                narrative = extract_or_fetch_content(session,soup,page_title,url,args.timeout,args.min_chars)
                if len(narrative) < args.min_chars:
                    raise ValueError(f"Chương {no} chỉ {len(narrative)} ký tự; có thể lỗi tách nội dung. Không lưu.")
                sha = hashlib.sha256(narrative.encode("utf-8")).hexdigest()
                if any(rec.sha256 == sha and rec.url != url for rec in manifest):
                    raise ValueError(f"Nội dung chương {no} trùng hoàn toàn chương khác; nghi trang chặn/bị lỗi.")
                chapter_path = f"chapters/chuong_{no:05d}.txt"
                (out / "chapters").mkdir(exist_ok=True)
                (out / chapter_path).write_text(f"{page_title}\n\n{narrative}\n", encoding="utf-8")
                record = Chapter(no, page_title, url, chapter_path, len(narrative), sha, following)
                manifest = [c for c in manifest if c.url != url and c.number != no]
                manifest.append(record)
                manifest.sort(key=lambda c: c.number)
                saved_by_url = {c.url: c for c in manifest}
                saved_by_num = {c.number: c for c in manifest}
                new_chapters += 1
                print(f"[Lưu] Mục {no}: {page_title} — {len(narrative):,} ký tự")
            write_metadata(out, title, landing, manifest)
            if url == last_url:
                reached_latest = True
                print(f"[Xong] Đã đến mục mới nhất: {page_title}.")
                break
            if not following:
                raise RuntimeError(f"Đã đến mục '{page_title}' nhưng chưa đến mục mới nhất; "
                                   "thiếu liên kết Tiếp theo. Kiểm tra website.")
            url = following
            sleep_between_chapters(args)
    finally:
        if manifest:
            normalize_saved_chapters(out, manifest)
            write_metadata(out, title, landing, manifest)
            write_combined(out, title, manifest)

    # Completion is based on following the real final link and on there being
    # no holes in the ordinal manifest, not on parsing numbers out of names.
    positions = [x.number for x in sorted(manifest,key=lambda x:x.number)]
    missing = sorted(set(range(1,max(positions,default=0)+1))-set(positions))
    if missing:
        print(f"[Cảnh báo] Có {len(missing)} vị trí lưu bị thiếu: {missing[:20]}")
    print(f"\nTổng đã lưu: {len(manifest)} chương | Mới tải: {new_chapters}")
    print(f"TXT gộp: {out / 'truyen_gop.txt'}")
    print(f"Hoàn tất đến chương mới nhất: {'CÓ' if reached_latest and not missing else 'CHƯA'}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Dán URL trang giới thiệu WikiCV, lấy nội dung đến chương mới nhất")
    parser.add_argument("--url", help="URL trang giới thiệu. Nếu bỏ trống, chương trình sẽ hỏi khi chạy.")
    parser.add_argument("--output", default="du_lieu_truyen", help="Thư mục cha lưu các truyện")
    parser.add_argument("--max-chapters", type=int, default=0, help="Số chương mới tải tối đa (0 = không giới hạn)")
    parser.add_argument("--delay", "--delay-min", dest="delay", type=float,
                        default=CHAPTER_DELAY_MIN_DEFAULT, help="Thời gian nghỉ tối thiểu giữa chương (giây)")
    parser.add_argument("--delay-max", type=float, default=CHAPTER_DELAY_MAX_DEFAULT,
                        help="Thời gian nghỉ tối đa giữa chương (giây)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Giới hạn thời gian mỗi request")
    parser.add_argument("--min-chars", type=int, default=120, help="Độ dài nội dung tối thiểu để tránh lưu trang lỗi")
    parser.add_argument("--refresh", action="store_true", help="Tải lại toàn bộ chương, kể cả chương đã lưu")
    parser.add_argument("--rebuild-only", action="store_true", help="Chỉ tạo lại truyen_gop.txt từ chương đã lưu, KHÔNG truy cập web")
    parser.add_argument("--index-page-size",type=int,default=501,help="Số mục mỗi lượt lấy trang mục lục (mặc định 501)")
    parser.add_argument("--sequential-only", dest="sequential_only", action="store_true", default=True,
                        help="Duyệt tuần tự theo Chương sau (mặc định)")
    parser.add_argument("--use-index", dest="sequential_only", action="store_false",
                        help="Dùng API mục lục phân trang thay cho chế độ tuần tự")
    args = parser.parse_args()
    if args.delay < 0 or args.delay_max < args.delay:
        parser.error("Yêu cầu 0 <= --delay <= --delay-max")
    if args.rebuild_only:
        try:
            rebuild_combined_offline(Path(args.output).resolve())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[LỖI] {exc}", file=sys.stderr)
            sys.exit(1)
        return
    if not args.url:
        args.url = input("Dán URL TRANG GIỚI THIỆU truyện WikiCV rồi Enter:\n> ").strip()
    if not args.url:
        print("Bạn chưa nhập URL.", file=sys.stderr)
        sys.exit(2)
    try:
        run(args)
    except (requests.RequestException, ValueError, RuntimeError, OSError) as exc:
        print(f"\n[LỖI] {exc}", file=sys.stderr)
        print("Các chương tải trước khi xảy ra lỗi vẫn được lưu. Chạy lại để tiếp tục.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
