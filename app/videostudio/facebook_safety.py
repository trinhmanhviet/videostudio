"""Checks a Facebook caption against the word list in facebook_words.json.

The list is an editing aid built from two research notes (Gemini, ChatGPT), not Meta's own list: Meta judges context,
so a word here is never forbidden by itself. The result has three levels, as both notes recommend:
  safe   - nothing found
  review - words or habits that can lower reach or monetisation; worth a second look
  fix    - words that can bring a strike (gậy) or masked spellings (gi*t, g.i.ế.t) that read as dodging the rules
The tool only warns and suggests a softer phrase; the person decides, nothing is replaced on its own."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

HOOK = 150          # characters shown before "Xem thêm"
REEL_WORDS = 180    # both notes put a Reels caption at roughly 80–180 words
MAX_HASHTAGS = 5
EFFECTS = {'gay': 'có thể bị gỡ bài hoặc cảnh cáo', 'tien': 'có thể mất kiếm tiền', 'reach': 'có thể bị giảm đề xuất'}
_LETTER = r'[^\W\d_]'
_MASKED = re.compile(rf'(?<!\w)(?:{_LETTER}+\*+{_LETTER}*|(?:{_LETTER}[.\-_]){{2,}}{_LETTER})(?!\w)', re.IGNORECASE)
_HASHTAG = re.compile(r'#(\w+)')


def _fold(text):
    text = unicodedata.normalize('NFD', str(text).replace('đ', 'd').replace('Đ', 'D'))
    return ''.join(c for c in text if not unicodedata.combining(c)).lower()


@lru_cache(maxsize=1)
def rules():
    data = json.loads(Path(__file__).with_name('facebook_words.json').read_text(encoding='utf-8'))
    words = sorted(data['words'], key=lambda w: -len(w['word']))  # "đâm chết" before "chết"
    for entry in words:
        # \s* also catches words run together to dodge the filter ("thithể" for "thi thể")
        entry['pattern'] = re.compile(r'(?<!\w)' + r'\s*'.join(map(re.escape, entry['word'].split())) + r'(?!\w)', re.IGNORECASE)
        entry['folded'] = _fold(entry['word']).replace(' ', '')
    phrases = [dict(p, regex=re.compile(p['pattern'], re.IGNORECASE)) for p in data['phrases']]
    return words, phrases, data['emoji']


def _level(entry):
    if entry['effect'] == 'gay' and entry['risk'] == 'high':
        return 'fix'
    return 'review' if entry['risk'] in ('high', 'medium') else 'note'


def check(text):
    """{'verdict': 'safe'|'review'|'fix', 'issues': [{kind, level, start, end, text, label, replace}]}"""
    text = text or ''
    words, phrases, emoji = rules()
    issues, taken = [], []
    for entry in words:
        for match in entry['pattern'].finditer(text):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            early = match.start() < HOOK  # even a low-risk word is better kept out of the first lines
            label = EFFECTS[entry['effect']] + (' · nằm trong 150 ký tự đầu, trước nút Xem thêm' if early else '')
            level = _level(entry)
            if early and level == 'note':
                level = 'review'
            if ' ' in entry['word'] and not re.search(r'\s', match.group()):
                issues.append({'kind': 'masked', 'level': 'fix', 'start': match.start(), 'end': match.end(), 'text': match.group(),
                               'label': f'Viết dính "{entry["word"]}" để né: Facebook vẫn đọc được và có thể coi là cố tình lách luật',
                               'replace': entry['replace']})
                continue
            issues.append({'kind': 'word', 'level': level, 'start': match.start(), 'end': match.end(), 'text': match.group(),
                           'label': label, 'replace': entry['replace']})
    # Written without diacritics to dodge ("THITHE", "giet nguoi"): fold letter by letter so positions stay the same.
    plain = ''.join((_fold(c) or c)[:1] for c in text)
    for entry in words:
        if entry['folded'] == _fold(entry['word']).replace(' ', '') and _fold(entry['word']) == entry['word'].lower():
            continue  # the word has no diacritics, nothing to unaccent
        if entry['risk'] == 'low' or len(entry['folded']) < 5:
            continue  # short plain spellings ("chet", "mau") collide with ordinary words
        folded = re.compile(r'(?<!\w)' + r'\s*'.join(map(re.escape, _fold(entry['word']).split())) + r'(?!\w)', re.IGNORECASE)
        for match in folded.finditer(plain):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            original = text[match.start():match.end()]
            if _fold(original) != original.lower():
                continue  # it carries diacritics, so it is a different word
            taken.append((match.start(), match.end()))
            issues.append({'kind': 'masked', 'level': 'review', 'start': match.start(), 'end': match.end(), 'text': original,
                           'label': f'Viết không dấu "{entry["word"]}" để né: Facebook vẫn đọc được', 'replace': entry['replace']})
    for match in _MASKED.finditer(text):
        issues.append({'kind': 'masked', 'level': 'fix', 'start': match.start(), 'end': match.end(), 'text': match.group(),
                       'label': 'Chữ viết che: Facebook vẫn đọc được và có thể coi là cố tình lách luật; đổi sang cách nói tránh',
                       'replace': []})
    for phrase in phrases:
        for match in phrase['regex'].finditer(text):
            issues.append({'kind': 'phrase', 'level': 'review', 'start': match.start(), 'end': match.end(), 'text': match.group(),
                           'label': phrase['label'], 'replace': []})
    for symbol in emoji:
        for match in re.finditer(re.escape(symbol), text):
            issues.append({'kind': 'emoji', 'level': 'review', 'start': match.start(), 'end': match.end(), 'text': match.group(),
                           'label': 'Emoji vũ khí, máu, chết chóc', 'replace': []})
    hashtags = list(_HASHTAG.finditer(text))
    for match in hashtags:  # "#GietNguoi" carries the word even without spaces or accents
        folded = _fold(match.group(1))
        hit = next((w for w in words if w['risk'] != 'low' and len(w['folded']) >= 4 and w['folded'] in folded), None)
        if hit:
            issues.append({'kind': 'hashtag', 'level': 'review', 'start': match.start(), 'end': match.end(), 'text': match.group(),
                           'label': f'Hashtag chứa "{hit["word"]}": dùng hashtag trung tính như #hosovuan, #truyenaudio', 'replace': []})
    if len(hashtags) > MAX_HASHTAGS:
        issues.append({'kind': 'count', 'level': 'note', 'start': hashtags[MAX_HASHTAGS].start(), 'end': hashtags[-1].end(),
                       'text': f'{len(hashtags)} hashtag', 'label': f'Nên dùng 3–{MAX_HASHTAGS} hashtag', 'replace': []})
    count = len(re.findall(r'\S+', text))
    if count > REEL_WORDS:
        issues.append({'kind': 'length', 'level': 'note', 'start': 0, 'end': 0, 'text': f'{count} chữ',
                       'label': f'Lời đăng Reels nên khoảng 80–{REEL_WORDS} chữ', 'replace': []})
    issues.sort(key=lambda i: (i['start'], i['kind']))
    levels = {i['level'] for i in issues}
    verdict = 'fix' if 'fix' in levels else 'review' if 'review' in levels else 'safe'
    return {'verdict': verdict, 'issues': issues}
