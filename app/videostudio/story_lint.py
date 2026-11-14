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
    issues = issues[:LIMIT]
    if key:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = issues
    return issues
