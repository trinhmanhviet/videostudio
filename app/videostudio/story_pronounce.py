"""Suggestions for the pronunciation dictionary: spots in a book the voice tends to read wrong.

Abbreviations in capitals (CEO, VIP), numbers glued to a unit or sign (5km, 50%, 8h30, 2tr) and stray symbols.
Each suggestion carries a proposed reading, how often it occurs and one example; nothing is added on its own:
the person ticks what to keep. Tokens already in the dictionary are left out."""
from __future__ import annotations

import re
from collections import Counter

LETTERS = {'A': 'a', 'B': 'bê', 'C': 'xê', 'D': 'đê', 'E': 'e', 'F': 'ép', 'G': 'giê', 'H': 'hát', 'I': 'i', 'J': 'giây', 'K': 'ca',
           'L': 'e lờ', 'M': 'em mờ', 'N': 'en nờ', 'O': 'o', 'P': 'pê', 'Q': 'quy', 'R': 'e rờ', 'S': 'ét', 'T': 'tê', 'U': 'u',
           'V': 'vê', 'W': 'vê kép', 'X': 'ích', 'Y': 'i dài', 'Z': 'dét'}
# Common abbreviations Vietnamese listeners hear the English way.
KNOWN = {'CEO': 'xi i ô', 'VIP': 'vi ai pi', 'OK': 'ô kê', 'ID': 'ai đi', 'GPS': 'gi pi ét', 'TV': 'ti vi', 'PR': 'pi a', 'KPI': 'kây pi ai',
         'MC': 'em xi', 'DJ': 'đi giây', 'USB': 'u ét bê', 'IT': 'ai ti', 'AI': 'ây ai', 'CV': 'xi vi', 'HR': 'ếch a', 'IQ': 'ai kiu',
         'EQ': 'i kiu', 'PK': 'pi ca', 'NPC': 'en pi xi', 'BOSS': 'bốt', 'GDP': 'giê đê pê', 'ATM': 'a tê em mờ', 'SOS': 'ét ô ét',
         'FBI': 'ép bi ai', 'CIA': 'xi ai ây', 'MV': 'em vi', 'BTS': 'bi ti ét', 'KTV': 'ca tê vê', 'VN': 'Việt Nam', 'TP': 'thành phố',
         'HCM': 'Hồ Chí Minh', 'THPT': 'trung học phổ thông', 'THCS': 'trung học cơ sở', 'ĐH': 'đại học', 'CA': 'công an', 'UBND': 'ủy ban nhân dân'}
UNITS = {'km': 'ki lô mét', 'kg': 'ki lô gam', 'cm': 'xen ti mét', 'mm': 'mi li mét', 'm2': 'mét vuông', 'm²': 'mét vuông', 'm3': 'mét khối',
         'm': 'mét', 'g': 'gam', 'ml': 'mi li lít', 'l': 'lít', 'ha': 'héc ta', '%': 'phần trăm', 'tr': 'triệu', 'k': 'nghìn',
         'đ': 'đồng', 'vnđ': 'đồng', 'usd': 'đô la', '$': 'đô la', 'tỷ': 'tỷ', 'h': 'giờ', 'p': 'phút', 's': 'giây', 'km/h': 'ki lô mét trên giờ'}
DIGITS = ['không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín']
SYMBOLS = {'&': 'và', '@': 'a còng', '+': 'cộng', '#': 'thăng'}

_ABBREVIATION = re.compile(r'(?<![\w.])([A-ZĐ]{2,6})(?!\w)')
_GLUED = re.compile(r'(?<![\w.,])(\d+(?:[.,]\d+)?)(km/h|km|kg|cm|mm|m2|m²|m3|ml|ha|tr|vnđ|usd|tỷ|m|g|l|k|đ|%|\$)(?![\w])', re.IGNORECASE)
_CLOCK = re.compile(r'(?<![\w.,])(\d{1,2})h(\d{2})?(?![\w])')
_SYMBOL = re.compile(r'(?<=\s)([&@+#])(?=\s)')
_WORD = re.compile(r'[^\W\d_]+')


def read_number(text):
    """Small numbers in words; longer ones are left to the voice ("2 triệu" reads fine)."""
    if not text.isdigit() or len(text) > 2:
        return text
    n = int(text)
    if n < 10:
        return DIGITS[n]
    tens, ones = divmod(n, 10)
    head = 'mười' if tens == 1 else DIGITS[tens] + ' mươi'
    if ones == 0:
        return head
    tail = {1: 'mốt' if tens > 1 else 'một', 4: 'tư' if tens > 1 else 'bốn', 5: 'lăm'}.get(ones, DIGITS[ones])
    return head + ' ' + tail


def _example(text, start, end):
    return text[max(0, start - 40):end + 40].replace('\n', ' ').strip()


def _shouting(text, start, end):
    """An all-caps word next to an all-caps Vietnamese word ("ANH ĐỨNG LẠI") is shouting, not an abbreviation."""
    before = _WORD.findall(text[max(0, start - 40):start])[-1:]
    after = _WORD.findall(text[end:end + 40])[:1]
    return any(len(w) > 1 and w.isupper() and not w.isascii() for w in before + after)


def suggest(texts, existing=(), limit=80):
    known = {str(e).casefold() for e in existing}
    found = {}

    def add(token, reading, kind, text, start, end):
        if token.casefold() in known or not reading or reading == token:
            return
        item = found.setdefault(token, {'from': token, 'to': reading, 'kind': kind, 'count': 0, 'example': _example(text, start, end)})
        item['count'] += 1

    for text in texts:
        text = text or ''
        for match in _ABBREVIATION.finditer(text):
            token = match.group(1)
            if _shouting(text, match.start(), match.end()) or (not token.isascii() and token not in KNOWN):
                continue
            reading = KNOWN.get(token) or ' '.join(LETTERS.get(c, c.lower()) for c in token)
            add(token, reading, 'Chữ viết tắt', text, match.start(), match.end())
        for match in _CLOCK.finditer(text):
            hour, minute = match.group(1), match.group(2)
            add(match.group(0), f'{hour} giờ' + (f' {minute}' if minute and minute != '00' else ''), 'Giờ', text, match.start(), match.end())
        for match in _GLUED.finditer(text):
            number, unit = match.group(1), match.group(2)
            if unit.lower() == 'h':
                continue
            reading = UNITS.get(unit.lower()) or UNITS.get(unit)
            add(match.group(0), f'{number} {reading}', 'Số kèm đơn vị', text, match.start(), match.end())
        for match in _SYMBOL.finditer(text):
            add(match.group(1), SYMBOLS[match.group(1)], 'Ký hiệu', text, match.start(), match.end())
    items = sorted(found.values(), key=lambda i: (-i['count'], i['from']))
    return items[:limit]
