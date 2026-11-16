"""Edit a crawled convert novel (truyen_gop.txt) chapter by chapter through ChatGPT, for TTS.

Input:  <story>/truyen_gop.txt written by the wikicv crawler (wikicv_auto_v3_2_mixed_titles).
Output: <story>/bien_tap/ho_so.json          profile: genre, names, pronouns, glossary (made once)
        <story>/bien_tap/chuong_NNN.txt      one edited chapter per file
        <story>/bien_tap/tien_do.json        progress, checks and notes per chapter (resume point)
        <story>/truyen_gop_bien_tap.txt      the merged file to read aloud

Rules: docs/quy_tac_bien_tap_truyen_convert.md (full text). Each prompt carries a condensed version,
so a 45-chapter novel does not resend 25 KB of rules every time. Requests go through the CDP daemon's
ChatGPT tab; the daemon journals every prompt, so a rerun after a crash or timeout reads the answer
already given instead of sending the chapter again.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

HEADING = re.compile(r'^\s*Chương\s+(\d+)\s*[.:：]?\s*(.*?)\s*$', re.I)
SCENE_BREAK = re.compile(r'^\s*([★☆◆◇■□●○*#=\-_~·•])(?:\s*\1){1,}\s*$')
PAGE_MARK = re.compile(r'^\s*\d{1,3}\s*$')
FORBIDDEN = re.compile(r'[~【】「」『』〈〉《》()（）★☆◆◇■□●○#]|\.\.\.|……|[!?！？]{2,}')
SENTENCE = re.compile(r'(?<=[.!?…])["”]?\s+')
MAX_SENTENCE = 240  # rule says about 200; a little slack before asking ChatGPT to rewrite
DAEMON = 'http://127.0.0.1:8879'
TIMEOUT = 1200  # High reasoning on a full chapter can take several minutes
POLL = 3        # seconds between looks at the daemon's progress (and at Tạm dừng) while a request runs

RULES = """VAI TRÒ: Biên tập viên văn học chuyên nghiệp. Biến bản convert Trung–Việt thành văn tiếng Việt tự nhiên, trôi chảy,
tương đương bản dịch người thật biên tập. Bản này sẽ được ĐỌC THÀNH TIẾNG bằng giọng đọc máy (TTS), người nghe không nhìn thấy chữ.

NGUYÊN TẮC NỘI DUNG
1. Biên tập TOÀN VĂN: giữ mọi tình tiết, hành động, lời thoại, suy nghĩ, miêu tả, trình tự. Không tóm tắt, không cắt, không thêm chi tiết.
   KHÔNG thêm cụm miêu tả, cảm xúc, hành động hay nhận xét mà bản convert không có (sai: "cô đứng chết lặng", "cố giữ bình tĩnh",
   "một linh cảm chẳng lành" khi nguồn không nói). Độ dài bản biên tập nên xấp xỉ bản convert; chỉ dài hơn vì lời dẫn thoại ngắn.
2. Bỏ văn phong convert: đảo lại trật tự câu kiểu tiếng Trung, bỏ "cái kia", "một cái", "đem… làm", "thực" (=rất), "cư nhiên"…
   Không lạm dụng Hán Việt khi có từ thuần Việt tự nhiên (trừ bối cảnh cổ trang, tiên hiệp cần giữ).
3. Hiểu dụng ý (mỉa mai, trêu, đe dọa, làm nũng) rồi diễn đạt cho đúng sắc thái. Giữ nhịp: nhanh khi cao trào, chậm khi nội tâm.
4. Tên riêng, xưng hô, đại từ, thuật ngữ theo đúng HỒ SƠ TRUYỆN. Xưng hô thay đổi hợp lý theo quan hệ, tuổi, bối cảnh.
5. Giữ đúng tính cách, giọng nói từng nhân vật; câu đùa, chơi chữ, cú chốt vẫn phải buồn cười bằng tiếng Việt.
6. Giữ nguyên số liệu, thời gian, địa điểm. Không tự kiểm duyệt, không làm nhẹ hay làm nặng.
7. Chỗ bản convert mơ hồ hoặc bị che (□□): chọn cách hiểu giữ nhiều thông tin nhất, ghi vào "ghi_chu".
8. Tránh lặp dồn dập "cô", "anh", "sau đó", "lúc này", "không khỏi", "trong lòng".

VIẾT ĐỂ NGHE (bắt buộc)
9. Chuyển cảnh (hàng ★, ◇, ***, ---…): một dòng chỉ có *** (có dòng trống trước và sau).
10. Cấm: ~  …… (dùng một dấu …, chỉ khi ngập ngừng, không đặt giữa cụm từ)  !! ?? ?! ????  【】 「」 ( ) chú thích, emoji, chữ in hoa cả câu.
    Mỗi câu chỉ một dấu ! hoặc ?. Lời trong 【】 (hệ thống, giọng trong đầu) viết thành thoại có lời dẫn rõ ai nói.
11. Cảm xúc phải nằm trong chữ: "cô hét lên", "anh ta gầm lên", không dựa vào dấu câu hay chữ in hoa.
12. Ai đang nói phải nghe ra được: mỗi lượt thoại một đoạn; khi không rõ ai nói thì thêm lời dẫn ngắn ("cô nói", "mèo trắng đáp").
    Chỉ thêm lời dẫn, không thêm nội dung. Dòng thoại chỉ có "……" (im lặng) → một câu kể ngắn ("Cô cạn lời.").
13. Mỗi câu tối đa khoảng 200 ký tự (khoảng 40 từ), vế nào cũng có dấu phẩy. Đoạn văn tối đa khoảng 120 từ.
14. Từ nước ngoài: dịch nghĩa sang tiếng Việt. Số thập phân viết dấu phẩy (1,5). Không dùng chữ cái đứng một mình làm tên (ông A).
15. Từ tượng thanh viết bằng chữ có nghĩa ("Két!", "Rầm!"), không kéo dài chữ (kéttt), không dùng ——.
16. Không giữ số trang/phần lẻ của nguồn crawl, URL, dòng "Nguồn", quảng cáo. Không chèn lời bình của AI vào nội dung.
17. BỎ HẲN những gì không phải truyện: lời tác giả ("Lời tác giả", "Tác giả có lời muốn nói", tác giả tâm sự, xin bình luận,
    xin phiếu, báo lịch đăng), lời người dịch/converter/editor, "PS:", tiểu kịch trường, "Hết chương", "Còn tiếp".
    Chép nguyên văn từng phần đã bỏ (từ bản convert) vào "da_bo". Lời nhân vật nói về "tác giả" trong truyện (xuyên thư…) thì giữ."""

PROFILE_PROMPT = """Bạn chuẩn bị biên tập toàn bộ một tiểu thuyết convert Trung–Việt thành bản tiếng Việt để đọc thành tiếng.
Đọc phần mở đầu dưới đây và lập HỒ SƠ TRUYỆN dùng chung cho mọi chương.

{rules}

Tên truyện (convert): {title}
{existing}
PHẦN MỞ ĐẦU (bản convert):
<<<
{sample}
>>>

Trả về your_response là JSON object:
{{"ten_truyen": "tên tiếng Việt", "the_loai": "thể loại chính, cơ chế, mô-típ, phong cách", "van_phong": "giọng kể nên dùng",
 "nhan_vat": [{{"ten": "tên chuẩn", "ten_goi_khac": ["biệt danh", "cách gọi trong convert"], "gioi_tinh": "", "than_phan": "",
   "dai_tu_loi_ke": "đại từ trong lời kể", "xung_ho": "xưng hô với từng người, ghi rõ khi thay đổi"}}],
 "thuat_ngu": [{{"goc": "cách viết trong convert", "dich": "cách viết thống nhất"}}],
 "luu_y": ["điều cần nhớ khi biên tập truyện này"]}}"""

CHAPTER_PROMPT = """{rules}

HỒ SƠ TRUYỆN (bắt buộc theo):
{profile}

{previous}CHƯƠNG CẦN BIÊN TẬP: Chương {number} — tiêu đề convert: "{title}"
Bản convert:
<<<
{text}
>>>

Biên tập toàn văn chương này theo mọi quy tắc trên. Trả về your_response là JSON object:
{{"tieu_de": "tên chương tiếng Việt, không kèm chữ Chương và số", "noi_dung": "toàn bộ nội dung đã biên tập, các đoạn cách nhau bằng một dòng trống, không có dòng tiêu đề",
 "thuat_ngu_moi": [{{"goc": "", "dich": ""}}], "nhan_vat_moi": [{{"ten": "", "gioi_tinh": "", "xung_ho": ""}}],
 "ghi_chu": ["chỗ convert mơ hồ và cách đã hiểu; chỗ đã thêm lời dẫn để người nghe biết ai nói"],
 "da_bo": ["nguyên văn phần lời tác giả/người dịch đã bỏ, chép từ bản convert"]}}"""

FIX_PROMPT = """{rules}

HỒ SƠ TRUYỆN:
{profile}

Bản biên tập Chương {number} dưới đây chưa đạt các điểm sau:
{problems}

Sửa đúng các điểm đó, giữ nguyên mọi phần khác (không cắt, không tóm tắt).
Bản convert gốc để đối chiếu:
<<<
{source}
>>>
Bản biên tập cần sửa:
<<<
{edited}
>>>
Trả về your_response là JSON object cùng dạng: {{"tieu_de": "", "noi_dung": "", "thuat_ngu_moi": [], "nhan_vat_moi": [], "ghi_chu": [], "da_bo": []}}"""


def split_chapters(raw: str):
    """Chapters from the crawler's merged file. The crawler writes a page title and the chapter's own heading
    ("Chương 2 kỳ ngộ" then "Chương 2. Kỳ ngộ") plus bare page numbers; both are folded away here."""
    lines = raw.replace('\r\n', '\n').replace('﻿', '').split('\n')
    title = next((l.strip() for l in lines if l.strip()), '')
    chapters, current = [], None
    for line in lines:
        match = HEADING.match(line)
        if match:
            number, name = int(match.group(1)), match.group(2).strip()
            name = '' if re.fullmatch(r'(?:end|hết|kết thúc|\.)', name, re.I) else name
            if current and current['number'] == number and not any(t.strip() for t in current['lines']):
                if len(name) >= len(current['title']) or not current['title']:
                    current['title'] = name or current['title']
                continue
            current = {'number': number, 'title': name, 'lines': []}
            chapters.append(current)
            continue
        if current is None or PAGE_MARK.match(line):
            continue
        current['lines'].append(line)
    result = []
    for chapter in chapters:
        text = '\n'.join(chapter['lines']).strip()
        text = re.sub(r'\n{3,}', '\n\n', text)
        result.append({'number': chapter['number'], 'title': chapter['title'], 'text': text})
    numbers = [c['number'] for c in result]
    if numbers != sorted(set(numbers)):
        raise ValueError('Số chương trong truyen_gop.txt bị trùng hoặc lệch thứ tự: ' + str(numbers[:60]))
    return title, result


def clean_for_speech(text: str) -> str:
    """Deterministic fixes the reader must never hear; ChatGPT is not asked to redo these."""
    out = []
    for line in text.replace('\r\n', '\n').split('\n'):
        stripped = line.strip()
        if SCENE_BREAK.match(stripped) or stripped == '***':
            out.extend(['', '***', ''])
            continue
        if PAGE_MARK.match(stripped):
            continue
        line = re.sub(r'\.{3,}|…{2,}|…\.+', '…', line)
        line = re.sub(r'([!?])[!?！？]+', r'\1', line)
        line = re.sub(r'\s*~+\s*', ' ', line)
        line = re.sub(r'\s*[—–]{2,}\s*$', '…', line)
        line = re.sub(r'\s*[—–]{2,}\s*', ', ', line)
        line = re.sub(r'[ \t]{2,}', ' ', line).rstrip()
        out.append(line)
    text = '\n'.join(out)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return re.sub(r'^(\*\*\*\n\n)+|(\n\n\*\*\*)+$', '', text).strip()


def removed_chars(answer):
    """Length of the author's/translator's notes ChatGPT left out on purpose (rule 17), so they do not count as cut text."""
    parts = answer.get('da_bo') if isinstance(answer, dict) else None
    return sum(len(p) for p in parts if isinstance(p, str)) if isinstance(parts, list) else 0


def check_chapter(source: str, edited: str, removed: int = 0):
    """Problems a listener would hear, or signs that text was dropped. Empty list means the chapter passes.
    `removed`: characters of author/translator notes left out on purpose."""
    from .story_lint import notes
    problems = []
    body = edited.replace('\n***\n', '\n')
    found = sorted(set(FORBIDDEN.findall(body)))
    if found:
        problems.append('Còn ký hiệu cấm: ' + ' '.join(found))
    ratio = len(edited) / max(1, len(source) - min(removed, len(source) // 2))
    if ratio < 0.72:
        problems.append(f'Bản biên tập chỉ dài {ratio:.0%} bản convert: có thể đã bị cắt hoặc tóm tắt. Phải biên tập toàn văn.')
    if ratio > 1.3:
        problems.append(f'Bản biên tập dài {ratio:.0%} bản convert: đã thêm cụm miêu tả/cảm xúc không có trong nguồn. Bỏ các phần thêm đó, chỉ giữ lời dẫn thoại ngắn.')
    long = [s for paragraph in body.split('\n') for s in SENTENCE.split(paragraph) if len(s) > MAX_SENTENCE]
    if long:
        problems.append('Câu quá dài (trên 200 ký tự), cần tách: ' + ' | '.join(s[:80] + '…' for s in long[:6]))
    if body.count('“') != body.count('”'):
        problems.append('Ngoặc kép mở và đóng không khớp.')
    if re.search(r'^\s*Chương\s+\d+', edited, re.M):
        problems.append('Không được có dòng tiêu đề "Chương" trong nội dung.')
    if re.search(r'https?://|www\.|Nguồn\s*:', edited, re.I):
        problems.append('Còn URL hoặc dòng nguồn.')
    left = notes(edited)
    if left:
        problems.append('Còn lời tác giả/người dịch, phải bỏ hẳn (quy tắc 17): ' + ' | '.join(edited[s:e][:80] for s, e, _ in left[:3]))
    return problems


def profile_for(profile, *texts):
    """Story profile trimmed to one chapter: everything except the character and term lists as is; the main characters
    (full entries from the profile prompt) always; a later-learned character or a term only when one of its names or
    spellings occurs (any case) in the given texts (the chapter's convert text, the previous chapter's ending)."""
    haystack = '\n'.join(t for t in texts if t).lower()

    def occurs(*names):
        return any(isinstance(n, str) and len(n.strip()) >= 2 and n.strip().lower() in haystack for n in names)

    people = []
    for person in profile.get('nhan_vat') or []:
        if not isinstance(person, dict):
            continue
        main = bool(person.get('than_phan') or person.get('dai_tu_loi_ke'))
        if main or occurs(person.get('ten'), *(person.get('ten_goi_khac') or [])):
            people.append(person)
    terms = [t for t in profile.get('thuat_ngu') or [] if isinstance(t, dict) and occurs(t.get('goc'), t.get('dich'))]
    return {**profile, 'nhan_vat': people, 'thuat_ngu': terms}


def unwrap_answer(value, key):
    """ChatGPT sometimes wraps the requested object: {"your_response": "<the object as a JSON string>"} (2026-11-16,
    chapter 99 of a story), a one-key object around it, or the object as a string with raw line breaks inside.
    Peel such layers until the object that has `key` shows; anything else comes back as it was."""
    for _ in range(4):
        if isinstance(value, str):
            try:
                value = json.loads(value.strip(), strict=False)
            except ValueError:
                return value
            continue
        if isinstance(value, dict) and key not in value and len(value) == 1:
            value = next(iter(value.values()))
            continue
        return value
    return value


class Paused(Exception):
    """The owner paused this story's edit; progress is kept and nothing is half-typed in a ChatGPT tab."""


class StoryEditor:
    def __init__(self, story_dir, ask=None, log=print, status=None, stop=None):
        """status(text): the live state of the request in flight ('' when none); stop: a threading.Event set by Pause."""
        self.story = Path(story_dir).resolve()
        self.source = self.story / 'truyen_gop.txt'
        if not self.source.is_file():
            raise FileNotFoundError(f'Không thấy {self.source}')
        self.out = self.story / 'bien_tap'
        self.status = status or (lambda text: None)
        self.stop = stop
        self.ask = ask or (lambda job, prompt: ask_chatgpt(job, prompt, status=self.status, stop=self.stop))
        self.log = log
        self.progress_path = self.out / 'tien_do.json'

    # --- state -------------------------------------------------------------------------------------------
    def _read(self, path, fallback):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return fallback

    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(path.suffix + '.part')
        part.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
        part.replace(path)

    def _job(self, kind, number=0, attempt=0):
        # Stable per story/chapter/attempt: rerunning reaches the daemon's journal, never a second send.
        digest = hashlib.sha256(str(self.story).encode()).hexdigest()[:10]
        return f'story-{digest}-{kind}-{number:03d}-{attempt}'

    # --- profile -----------------------------------------------------------------------------------------
    def profile(self, title, chapters):
        path = self.out / 'ho_so.json'
        saved = self._read(path, None)
        if isinstance(saved, dict) and saved.get('nhan_vat') is not None:
            return saved
        sample, size = [], 0
        for chapter in chapters:
            if size > 24000:
                break
            sample.append(f'Chương {chapter["number"]}: {chapter["title"]}\n{chapter["text"]}')
            size += len(chapter['text'])
        existing = ''
        old = self.story / 'ho_so_bien_tap.md'
        if old.is_file():
            existing = 'Hồ sơ biên tập đã có từ trước (kiểm tra lại, dùng phần đúng):\n<<<\n' + old.read_text(encoding='utf-8')[:8000] + '\n>>>\n'
        prompt = PROFILE_PROMPT.format(rules=RULES, title=title, existing=existing, sample='\n\n'.join(sample)[:30000])
        self.log('Lập hồ sơ truyện (tên, xưng hô, thuật ngữ)…')
        value = unwrap_answer(self.ask(self._job('profile'), prompt), 'nhan_vat')
        if not isinstance(value, dict) or not isinstance(value.get('nhan_vat'), list):
            raise ValueError('ChatGPT không trả về hồ sơ truyện hợp lệ')
        value.setdefault('thuat_ngu', [])
        value.setdefault('luu_y', [])
        self._write(path, value)
        return value

    @staticmethod
    def _profile_text(profile, *texts):
        """The profile part a chapter needs. The profile grows with every chapter (180 chapters: ~150 people, ~1,300
        terms, 190,000 characters); sending all of it made each prompt ~200,000 characters, so typing took a minute
        and ChatGPT slowed down chapter after chapter. A term whose convert spelling is not in this chapter (or the end
        of the previous one) cannot be used in it, so only matching terms go; the main characters (made with the
        profile) always go, a character learned later goes when the chapter names them."""
        return json.dumps(profile_for(profile, *texts), ensure_ascii=False)

    def _learn(self, profile, answer):
        """New names and terms from a chapter join the profile, so later chapters write them the same way."""
        changed = False
        known_terms = {t.get('goc') for t in profile.get('thuat_ngu', []) if isinstance(t, dict)}
        for term in answer.get('thuat_ngu_moi') or []:
            if isinstance(term, dict) and term.get('goc') and term.get('dich') and term['goc'] not in known_terms:
                profile['thuat_ngu'].append({'goc': term['goc'], 'dich': term['dich']}); known_terms.add(term['goc']); changed = True
        known_people = {p.get('ten') for p in profile.get('nhan_vat', []) if isinstance(p, dict)}
        for person in answer.get('nhan_vat_moi') or []:
            if isinstance(person, dict) and person.get('ten') and person['ten'] not in known_people:
                profile['nhan_vat'].append(person); known_people.add(person['ten']); changed = True
        if changed:
            self._write(self.out / 'ho_so.json', profile)

    # --- chapters ----------------------------------------------------------------------------------------
    def edit_chapter(self, chapter, profile, previous_tail):
        number = chapter['number']
        previous = ''
        if previous_tail:
            previous = 'Đoạn cuối chương trước (đã biên tập, để nối mạch và giữ xưng hô):\n<<<\n' + previous_tail + '\n>>>\n\n'
        prompt = CHAPTER_PROMPT.format(rules=RULES, profile=self._profile_text(profile, chapter['text'], previous_tail), previous=previous,
                                       number=number, title=chapter['title'], text=chapter['text'])
        try:
            answer = self._answer(self.ask(self._job('chapter', number), prompt))
        except ValueError:
            # The answer is kept by the daemon, so asking the same request again only reads it back: a reply without
            # the chapter (an odd wrapper, a cut-off answer) is asked once more in a new chat instead of stopping.
            self.log(f'  Chương {number}: câu trả lời không có nội dung chương, hỏi lại trong cuộc trò chuyện mới…')
            answer = self._answer(self.ask(self._job('chapter', number, 1), prompt))
        edited = clean_for_speech(answer['noi_dung'])
        problems = check_chapter(chapter['text'], edited, removed_chars(answer))
        attempts = [{'problems': problems}]
        if problems:
            self.log(f'  Chương {number}: nhờ ChatGPT sửa: ' + '; '.join(p[:90] for p in problems))
            fix = FIX_PROMPT.format(rules=RULES, profile=self._profile_text(profile, chapter['text'], edited), number=number,
                                    problems='\n'.join('- ' + p for p in problems), source=chapter['text'], edited=edited)
            fixed = self._answer(self.ask(self._job('fix', number), fix))
            fixed_text = clean_for_speech(fixed['noi_dung'])
            fixed_problems = check_chapter(chapter['text'], fixed_text, removed_chars(fixed) or removed_chars(answer))
            attempts.append({'problems': fixed_problems})
            if len(fixed_problems) <= len(problems):
                answer, edited, problems = {**answer, **fixed, 'ghi_chu': (answer.get('ghi_chu') or []) + (fixed.get('ghi_chu') or []),
                                            'da_bo': fixed.get('da_bo') or answer.get('da_bo') or []}, fixed_text, fixed_problems
        return answer, edited, problems, attempts

    @staticmethod
    def _answer(value):
        value = unwrap_answer(value, 'noi_dung')
        if not isinstance(value, dict) or not isinstance(value.get('noi_dung'), str) or len(value['noi_dung'].strip()) < 50:
            raise ValueError('ChatGPT không trả về nội dung chương')
        value['tieu_de'] = str(value.get('tieu_de') or '').strip()
        return value

    def run(self, first=None, last=None, on_chapter=None):
        raw = self.source.read_text(encoding='utf-8')
        title, chapters = split_chapters(raw)
        progress = self._read(self.progress_path, {'chapters': {}})
        progress['source_sha256'] = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        profile = self.profile(title, chapters)
        selected = [c for c in chapters if (first is None or c['number'] >= first) and (last is None or c['number'] <= last)]
        self.log(f'{profile.get("ten_truyen") or title}: {len(chapters)} chương, biên tập {len(selected)} chương.')
        for chapter in selected:
            if self.stop is not None and self.stop.is_set():
                raise Paused()
            key = str(chapter['number'])
            path = self.out / f'chuong_{chapter["number"]:03d}.txt'
            source_hash = hashlib.sha256(chapter['text'].encode('utf-8')).hexdigest()
            done = progress['chapters'].get(key) or {}
            if path.is_file() and done.get('source_sha256') == source_hash:
                continue
            started = time.time()
            self.log(f'Chương {chapter["number"]}: gửi ChatGPT ({len(chapter["text"])} ký tự)…')
            before = self.out / f'chuong_{chapter["number"] - 1:03d}.txt'
            tail = ''
            if before.is_file():
                paragraphs = [p for p in before.read_text(encoding='utf-8').split('\n\n') if p.strip() and p.strip() != '***']
                tail = '\n\n'.join(paragraphs[-3:])
            answer, edited, problems, attempts = self.edit_chapter(chapter, profile, tail)
            heading = f'Chương {chapter["number"]}: {answer["tieu_de"] or chapter["title"]}'.rstrip(': ')
            self._write(path, heading + '\n\n' + edited + '\n')
            self._learn(profile, answer)
            progress['chapters'][key] = {'source_sha256': source_hash, 'title': heading, 'chars_source': len(chapter['text']),
                                         'chars_edited': len(edited), 'problems': problems, 'attempts': attempts,
                                         'notes': answer.get('ghi_chu') or [], 'removed': answer.get('da_bo') or [], 'seconds': round(time.time() - started), 'at': time.time()}
            self._write(self.progress_path, progress)
            self.log(f'  xong sau {round(time.time() - started)} giây' + (' · CẦN XEM LẠI: ' + '; '.join(problems) if problems else ''))
            # Each finished chapter is merged (and handed to the caller) at once, so it can be reviewed and queued
            # while the rest of the book is still being edited.
            self.merge(profile.get('ten_truyen') or title, chapters, progress, quiet=True)
            if on_chapter:
                on_chapter(chapter['number'])
        return self.merge(profile.get('ten_truyen') or title, chapters, progress)

    def merge(self, title, chapters, progress, quiet=False):
        parts, missing = [title.strip()], []
        for chapter in chapters:
            path = self.out / f'chuong_{chapter["number"]:03d}.txt'
            if path.is_file():
                parts.append(path.read_text(encoding='utf-8').strip())
            else:
                missing.append(chapter['number'])
        target = self.story / 'truyen_gop_bien_tap.txt'
        self._write(target, '\n\n'.join(parts) + '\n')
        review = [int(k) for k, v in progress['chapters'].items() if v.get('problems')]
        summary = {'file': str(target), 'chapters_done': len(chapters) - len(missing), 'chapters_total': len(chapters),
                   'missing': missing, 'needs_review': sorted(review)}
        if not quiet:
            self.log(f'Đã gộp {summary["chapters_done"]}/{len(chapters)} chương vào {target.name}'
                 + (f'; chưa làm: {missing[:10]}{"…" if len(missing) > 10 else ""}' if missing else '')
                 + (f'; cần xem lại: {summary["needs_review"]}' if review else ''))
        return summary


def _wait_text(progress):
    """The daemon's progress for one request, in the owner's words (shown live under the Truyện nguồn log)."""
    phase, seconds = progress.get('phase'), int(progress.get('seconds') or 0)
    minutes = f'{seconds // 60} phút' if seconds >= 60 else f'{seconds} giây'
    chars = progress.get('chars') or 0
    return {'queued': f'chờ lượt (yêu cầu trước của truyện này chưa xong) {minutes}',
            'composing': f'chờ lượt gõ (tab ChatGPT khác đang gõ) {minutes}',
            'typing': f'đang gõ chương vào ChatGPT {minutes}',
            'sent': f'đã gửi, chờ ChatGPT bắt đầu {minutes}',
            'thinking': f'ChatGPT đang suy nghĩ {minutes}',
            'writing': f'ChatGPT đang viết ({chars:,} ký tự) {minutes}'.replace(',', '.'),
            'reading': f'ChatGPT đã viết xong, đang đọc câu trả lời {minutes}',
            'reloading': progress.get('detail') or 'tải lại trang ChatGPT',
            'retry': progress.get('detail') or 'hỏi lại trong cuộc trò chuyện mới'}.get(phase, '')


def ask_chatgpt(job, prompt, *, daemon=DAEMON, attempts=6, status=None, stop=None):
    """One prompt through the dedicated ChatGPT tab. A timeout is not a failure: the daemon has journaled the
    request, so asking again with the same job and prompt only waits for and reads the same answer.
    status(text) gets the live state every few seconds; stop (threading.Event) pauses: a request not yet typed is
    withdrawn, one already sent keeps being read by the daemon, so resuming reads its answer without sending again."""
    import httpx
    import threading
    status = status or (lambda text: None)
    last = None
    for attempt in range(attempts):
        box = {}

        def post():
            try:
                box['response'] = httpx.post(daemon + '/api/chat', json={'prompt': prompt, 'job_id': job, 'timeout_seconds': TIMEOUT},
                                             headers={'X-VS-Client': 'videostudio'}, timeout=TIMEOUT + 900, trust_env=False)
            except Exception as error:  # noqa: BLE001 - reported below like any failed try
                box['error'] = error
        worker = threading.Thread(target=post, name='chatgpt-' + job, daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(POLL)
            if stop is not None and stop.is_set():
                try:
                    httpx.post(daemon + '/api/chat/cancel', json={'job_id': job}, headers={'X-VS-Client': 'videostudio'}, timeout=10, trust_env=False)
                except httpx.HTTPError:
                    pass
                status('')
                raise Paused()
            if worker.is_alive():
                try:
                    progress = httpx.get(daemon + '/api/chat/progress', params={'job_id': job}, timeout=5, trust_env=False).json()
                    status(_wait_text(progress) if isinstance(progress, dict) else '')
                except (httpx.HTTPError, ValueError):
                    pass
        status('')
        if 'error' in box:
            last = box['error']
            if not isinstance(last, (httpx.HTTPError, ValueError)):
                raise last
            status('Không liên lạc được dịch vụ ChatGPT, thử lại sau 10 giây…')
            time.sleep(10)
            continue
        response = box['response']
        try:
            data = response.json()
        except ValueError as error:
            last = error
            time.sleep(10)
            continue
        if response.status_code == 200 and data.get('ok') and isinstance(data.get('data'), dict):
            value = data['data']
            inner = value.get('your_response') if len(value) == 1 else None
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    inner = None
            return inner if isinstance(inner, dict) else value
        last = RuntimeError(f'ChatGPT lỗi HTTP {response.status_code}: {data.get("code") or ""} {str(data.get("error") or "")[:300]}')
        if data.get('code') in ('authentication_required',):
            break
        if data.get('code') == 'cancelled' and stop is not None and stop.is_set():
            raise Paused()
        if data.get('code') == 'ask_again':  # the daemon found the chat stuck and put the chapter back: ask at once
            status('ChatGPT đứng yên, hỏi lại trong cuộc trò chuyện mới…')
            time.sleep(2)
            continue
        status('Lỗi: ' + str(data.get('error') or data.get('code') or '')[:160] + ' · thử lại sau 15 giây…')
        time.sleep(15)
    raise RuntimeError(str(last))
