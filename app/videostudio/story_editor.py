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

RULES = """VAI TRÒ: Biên tập viên văn học chuyên nghiệp. Biến bản convert Trung–Việt thành văn tiếng Việt tự nhiên, trôi chảy,
tương đương bản dịch người thật biên tập. Bản này sẽ được ĐỌC THÀNH TIẾNG bằng giọng đọc máy (TTS), người nghe không nhìn thấy chữ.

NGUYÊN TẮC NỘI DUNG
1. Biên tập TOÀN VĂN: giữ mọi tình tiết, hành động, lời thoại, suy nghĩ, miêu tả, trình tự. Không tóm tắt, không cắt, không thêm chi tiết.
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
16. Không giữ số trang/phần lẻ của nguồn crawl, URL, dòng "Nguồn", quảng cáo. Không chèn lời bình của AI vào nội dung."""

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
 "ghi_chu": ["chỗ convert mơ hồ và cách đã hiểu; chỗ đã thêm lời dẫn để người nghe biết ai nói"]}}"""

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
Trả về your_response là JSON object cùng dạng: {{"tieu_de": "", "noi_dung": "", "thuat_ngu_moi": [], "nhan_vat_moi": [], "ghi_chu": []}}"""


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


def check_chapter(source: str, edited: str):
    """Problems a listener would hear, or signs that text was dropped. Empty list means the chapter passes."""
    problems = []
    body = edited.replace('\n***\n', '\n')
    found = sorted(set(FORBIDDEN.findall(body)))
    if found:
        problems.append('Còn ký hiệu cấm: ' + ' '.join(found))
    ratio = len(edited) / max(1, len(source))
    if ratio < 0.72:
        problems.append(f'Bản biên tập chỉ dài {ratio:.0%} bản convert: có thể đã bị cắt hoặc tóm tắt. Phải biên tập toàn văn.')
    if ratio > 1.45:
        problems.append(f'Bản biên tập dài {ratio:.0%} bản convert: có thể đã thêm nội dung. Chỉ được thêm lời dẫn ngắn.')
    long = [s for paragraph in body.split('\n') for s in SENTENCE.split(paragraph) if len(s) > MAX_SENTENCE]
    if long:
        problems.append('Câu quá dài (trên 200 ký tự), cần tách: ' + ' | '.join(s[:80] + '…' for s in long[:6]))
    if body.count('“') != body.count('”'):
        problems.append('Ngoặc kép mở và đóng không khớp.')
    if re.search(r'^\s*Chương\s+\d+', edited, re.M):
        problems.append('Không được có dòng tiêu đề "Chương" trong nội dung.')
    if re.search(r'https?://|www\.|Nguồn\s*:', edited, re.I):
        problems.append('Còn URL hoặc dòng nguồn.')
    return problems


class StoryEditor:
    def __init__(self, story_dir, ask=None, log=print):
        self.story = Path(story_dir).resolve()
        self.source = self.story / 'truyen_gop.txt'
        if not self.source.is_file():
            raise FileNotFoundError(f'Không thấy {self.source}')
        self.out = self.story / 'bien_tap'
        self.ask = ask or ask_chatgpt
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
        value = self.ask(self._job('profile'), prompt)
        if not isinstance(value, dict) or not isinstance(value.get('nhan_vat'), list):
            raise ValueError('ChatGPT không trả về hồ sơ truyện hợp lệ')
        value.setdefault('thuat_ngu', [])
        value.setdefault('luu_y', [])
        self._write(path, value)
        return value

    @staticmethod
    def _profile_text(profile):
        return json.dumps(profile, ensure_ascii=False, indent=1)

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
        prompt = CHAPTER_PROMPT.format(rules=RULES, profile=self._profile_text(profile), previous=previous,
                                       number=number, title=chapter['title'], text=chapter['text'])
        answer = self._answer(self.ask(self._job('chapter', number), prompt))
        edited = clean_for_speech(answer['noi_dung'])
        problems = check_chapter(chapter['text'], edited)
        attempts = [{'problems': problems}]
        if problems:
            self.log(f'  Chương {number}: nhờ ChatGPT sửa: ' + '; '.join(p[:90] for p in problems))
            fix = FIX_PROMPT.format(rules=RULES, profile=self._profile_text(profile), number=number,
                                    problems='\n'.join('- ' + p for p in problems), source=chapter['text'], edited=edited)
            fixed = self._answer(self.ask(self._job('fix', number), fix))
            fixed_text = clean_for_speech(fixed['noi_dung'])
            fixed_problems = check_chapter(chapter['text'], fixed_text)
            attempts.append({'problems': fixed_problems})
            if len(fixed_problems) <= len(problems):
                answer, edited, problems = {**answer, **fixed, 'ghi_chu': (answer.get('ghi_chu') or []) + (fixed.get('ghi_chu') or [])}, fixed_text, fixed_problems
        return answer, edited, problems, attempts

    @staticmethod
    def _answer(value):
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
                                         'notes': answer.get('ghi_chu') or [], 'seconds': round(time.time() - started), 'at': time.time()}
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


def ask_chatgpt(job, prompt, *, daemon=DAEMON, attempts=4):
    """One prompt through the dedicated ChatGPT tab. A timeout is not a failure: the daemon has journaled the
    request, so asking again with the same job and prompt only waits for and reads the same answer."""
    import httpx
    last = None
    for attempt in range(attempts):
        try:
            response = httpx.post(daemon + '/api/chat', json={'prompt': prompt, 'job_id': job, 'timeout_seconds': TIMEOUT},
                                  headers={'X-VS-Client': 'videostudio'}, timeout=TIMEOUT + 120, trust_env=False)
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
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
        time.sleep(15)
    raise RuntimeError(str(last))
