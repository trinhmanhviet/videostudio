"""Mechanical checks of an edited chapter against the "viết để nghe" rules (docs/quy_tac_bien_tap_truyen_convert.md,
PHẦN IV.1 and IV.2): marks the TTS reads badly or aloud, overlong sentences, decimals with a dot, leftover crawl junk.
Only what a machine can see; tone, names and who-is-speaking stay with the human review."""
from __future__ import annotations

import re

LONG_SENTENCE = 200
LONG_PARAGRAPH = 150
LIMIT = 300

_PATTERNS = [
    ('tilde', 'Dấu ~ (bị đọc thành "khoảng")', re.compile(r'~')),
    ('marks', 'Dấu ? ! dồn, chỉ nên một dấu', re.compile(r'[?!？！]{2,}')),
    ('brackets', 'Ngoặc 【】「」『』[ ] hoặc ( ) chú thích', re.compile(r'[【】「」『』〖〗\[\]()（）]')),
    ('censored', 'Ký tự □ (chữ bị kiểm duyệt)', re.compile(r'[□■]')),
    ('emoji', 'Emoji', re.compile('[\U0001F300-\U0001FAFF☀-☄☇-➿]')),
    ('scene', 'Dòng ký hiệu chuyển cảnh: đổi thành ***', re.compile(r'(?m)^(?!\s*\*\*\*\s*$)[ \t]*[*★☆◇◆□■#=_\-—~·•]{3,}[ \t]*$')),
    ('decimal', 'Số thập phân viết dấu chấm (đọc thành "chấm"), dùng dấu phẩy', re.compile(r'(?<![\d.])\d+\.\d{1,2}(?![\d.])')),
    ('url', 'Đường link hoặc dòng nguồn', re.compile(r'(?im)https?://\S+|www\.\S+|^[ \t]*nguồn[ \t]*:.*$')),
    ('stretch', 'Chữ kéo dài hoặc —— kéo tiếng', re.compile(r'([^\W\d_])\1{3,}|——', re.IGNORECASE)),
    ('ellipsis_only', 'Dòng chỉ có dấu chấm lửng (bị đọc thành im lặng)', re.compile(r'(?m)^[ \t"“”\'‘’—\-]*(?:…|\.{2,})+[ \t"“”\'‘’—\-]*$')),
]
# A single "…" for hesitation is allowed by the rules; the doubled "……" inside a phrase is what reads as a full stop.
_ELLIPSIS = re.compile(r'(?:…{2,}|\.{4,}|…\.+|\.+…)(?=[ \t]*([^\W\d_]))')
_WORD = re.compile(r'[^\W\d_]+')
# Not part of the story: the author's or translator's words, vote begging, "to be continued". The listener should not hear them.
_NOTE_HEAD = re.compile(r'^[\s(\[【「“"\'*-]*(?:lời\s+(?:nói\s+)?(?:của\s+)?(?:tác\s*giả|người\s+dịch|dịch\s+giả|editor|converter|cvt|người\s+biên\s+tập|biên\s+tập\s+viên)'
                        r'|tác\s*giả\s+(?:có\s+(?:lời|điều|đôi\s+lời)\s+muốn\s+nói|nhắn|tâm\s+sự|lảm\s+nhảm|nói\s+thêm|nói\s+nhỏ)|lời\s+ngoài\s+lề|ngoài\s+lề\s*:'
                        r'|tiểu\s+kịch\s+trường|kịch\s+trường\s+nhỏ)\b', re.I)
_NOTE_PREFIX = re.compile(r'^[\s(\[【「*-]*(?:tác\s*giả|converter|cvt|editor|edit|dịch\s+giả|người\s+dịch|beta|ps|p\.\s*s\.?|p/s)\s*[:：]', re.I)
_NOTE_PHRASE = re.compile(r'(?:cầu|xin)\s+(?:nguyệt\s+phiếu|phiếu|vé\s+tháng|đề\s+cử|cất\s+giữ|thu\s+tàng|vote|bình\s+luận|like|follow|theo\s+dõi)\b'
                          r'|nguyệt\s+phiếu|vé\s+tháng|phiếu\s+đề\s+cử|chương\s+mới\s+nhất\s+tại|đọc\s+(?:truyện\s+)?tại\s+(?:website|trang)', re.I)
_NOTE_END = re.compile(r'^[\s(\[]*(?:hết\s+chương(?:\s+\d+)?|còn\s+tiếp|chưa\s+xong\s+còn\s+tiếp|to\s+be\s+continued)[\s.!…)\]]*$', re.I)
NOTE_LABEL = 'Lời tác giả / người dịch, không phải truyện: xoá đoạn này'
NOTE_TAIL_LABEL = 'Lời tác giả / người dịch, không phải truyện: xoá từ đây đến hết chương'


def notes(text):
    """(start, end, label) of the parts that are not the story. A heading such as "Lời tác giả" takes the rest of the chapter."""
    found, offset = [], 0
    text = text or ''
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped:
            if len(stripped) <= 80 and _NOTE_HEAD.search(stripped):
                found.append((offset + line.index(stripped[0]), len(text.rstrip()), NOTE_TAIL_LABEL))
                break
            if _NOTE_PREFIX.search(stripped) or _NOTE_END.search(stripped) or _NOTE_PHRASE.search(stripped):
                found.append((offset + line.index(stripped[0]), offset + len(line.rstrip()), NOTE_LABEL))
        offset += len(line) + 1
    return found
_SENTENCE = re.compile(r'[^.!?…\n]+(?:[.!?…]+|$)', re.M)
_cache: dict = {}


def _issue(code, label, start, end, text):
    return {'code': code, 'label': label, 'start': start, 'end': end, 'excerpt': text[max(0, start - 30):end + 30].replace('\n', ' ').strip()}


def lint(text, key=None):
    """Issues sorted by position: {code, label, start, end, excerpt}; offsets are code points in `text`."""
    if key and key in _cache:
        return _cache[key]
    text = text or ''
    issues = []
    for code, label, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            issues.append(_issue(code, label, match.start(), match.end(), text))
    for match in _ELLIPSIS.finditer(text):  # "cô…… đã xuyên không": an ellipsis inside a phrase, before a lowercase word
        if match.group(1).islower():
            issues.append(_issue('ellipsis_mid', 'Dấu chấm lửng giữa câu (bị đọc thành dấu chấm)', match.start(), match.end(), text))
    for start, end, label in notes(text):
        issues.append(_issue('note', label, start, end, text))
    words = list(_WORD.finditer(text))
    run = []
    for word in words + [None]:  # three or more whole-caps words in a row: shouting the TTS cannot voice
        if word is not None and len(word.group()) >= 2 and word.group().isupper():
            run.append(word)
            continue
        if len(run) >= 3:
            issues.append(_issue('caps', 'Cả cụm viết hoa: cảm xúc nên nằm trong lời dẫn', run[0].start(), run[-1].end(), text))
        run = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group().strip()
        if len(sentence) > LONG_SENTENCE:
            issues.append(_issue('long_sentence', f'Câu dài {len(sentence)} ký tự (nên dưới {LONG_SENTENCE})', match.start(), match.end(), text))
    offset = 0
    for paragraph in text.split('\n'):
        count = len(paragraph.split())
        if count > LONG_PARAGRAPH:
            issues.append(_issue('long_paragraph', f'Đoạn dài {count} từ (nên tách, dưới khoảng {LONG_PARAGRAPH})', offset, offset + len(paragraph), text))
        offset += len(paragraph) + 1
    issues.sort(key=lambda i: (i['start'], i['code']))
    issues = issues[:LIMIT] + [i for i in issues[LIMIT:] if i['code'] == 'note']  # never hide the author's notes
    if key:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = issues
    return issues
