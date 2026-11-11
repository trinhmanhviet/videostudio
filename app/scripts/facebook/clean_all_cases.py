"""Batch clean all crawled Facebook crime scripts into pure, production-ready plain text files.
- Removes all Markdown formatting (# headers, > quotes, --- dividers, bold/italic syntax, links)
- Strips disclaimers, metadata, image tags like (ảnh 1), and trailing outro/hashtags
- Replaces Facebook censor evasion patterns (slashes in words, asterisks, unaccented words) with proper Vietnamese
- Normalizes unicode (NFC), spaces, punctuation, and paragraph breaks
- Produces individual .txt files, an aggregated all_cases_clean.txt, and an INDEX.txt
"""
import re
import sys
import time
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT.parent / "data" / "facebook_cases" / "dem-nay-lai-co-chuyen"
OUT_DIR = ROOT.parent / "data" / "facebook_cases" / "clean" / "dem-nay-lai-co-chuyen"

EVASIONS = {
    'sathai': 'sát hại',
    'sat-hai': 'sát hại',
    'sathat': 'sát hại',
    'anmang': 'án mạng',
    'gietnguoi': 'giết người',
    'gietchet': 'giết chết',
    'giethai': 'giết hại',
    'giethet': 'giết hết',
    'gietcha': 'giết cha',
    'gietnuoi': 'giết người',
    'thithe': 'thi thể',
    'thiithe': 'thi thể',
    'thithr': 'thi thể',
    'thith': 'thi thể',
    'tuthi': 'tử thi',
    'tuvong': 'tử vong',
    'nannhan': 'nạn nhân',
    'nannhann': 'nạn nhân',
    'nanhan': 'nạn nhân',
    'mattich': 'mất tích',
    'phitang': 'phi tang',
    'satnhan': 'sát nhân',
    'satthu': 'sát thủ',
    'thamsat': 'thảm sát',
    'tansat': 'tàn sát',
    'truysat': 'truy sát',
    'cuongsat': 'cuồng sát',
    'muusat': 'mưu sát',
    'muosat': 'mưu sát',
    'tuhinh': 'tử hình',
    'chungthan': 'chung thân',
    'tutu': 'tự tử',
    'tusat': 'tự sát',
    'batcoc': 'bắt cóc',
    'cuopcua': 'cướp của',
    'cuoptaisan': 'cướp tài sản',
    'cuopgiat': 'cướp giật',
    'cuopsung': 'cướp súng',
    'cuopcon': 'cướp con',
    'cuopdoat': 'cướp đoạt',
    'tromcap': 'trộm cắp',
    'danhdap': 'đánh đập',
    'danhchet': 'đánh chết',
    'banchet': 'bắn chết',
    'chemchet': 'chém chết',
    'damchem': 'đâm chém',
    'sietco': 'siết cổ',
    'bopco': 'bóp cổ',
    'bopchat': 'bóp chặt',
    'sietchat': 'siết chặt',
    'tattho': 'tắt thở',
    'cuonghiep': 'cưỡng hiếp',
    'cuongbuc': 'cưỡng bức',
    'cuongdam': 'cuồng dâm',
    'hiepdam': 'hiếp dâm',
    'hipdam': 'hiếp dâm',
    'xamhai': 'xâm hại',
    'xampham': 'xâm phạm',
    'xhtd': 'xâm hại tình dục',
    'khoathan': 'khỏa thân',
    'trantruong': 'trần truồng',
    'trantrui': 'trần trụi',
    'khongmacdo': 'không mặc đồ',
    'quanlot': 'quần lót',
    'baocaosu': 'bao cao su',
    'maithuy': 'ma túy',
    'maidam': 'mại dâm',
    'gaimaidam': 'gái mại dâm',
    'tandoc': 'tàn độc',
    'tanbao': 'tàn bạo',
    'tannhan': 'tàn nhẫn',
    'tankhoc': 'tàn khốc',
    'thamkhoc': 'thảm khốc',
    'thamkich': 'thảm kịch',
    'daman': 'dã man',
    'doibai': 'đồi bại',
    'doitruy': 'đồi trụy',
    'baohanh': 'bạo hành',
    'baoluc': 'bạo lực',
    'toipham': 'tội phạm',
    'toiac': 'tội ác',
    'nghipham': 'nghi phạm',
    'hungthu': 'hung thủ',
    'xacchet': 'xác chết',
    'nhaxac': 'nhà xác',
    'chonxac': 'chôn xác',
    'giauxac': 'giấu xác',
    'vutxac': 'vứt xác',
    'phanxac': 'phân xác',
    'phanhuy': 'phân hủy',
    'doatmang': 'đoạt mạng',
    'matmang': 'mất mạng',
    'sinhmang': 'sinh mạng',
    'mangsong': 'mạng sống',
    'mangnguoi': 'mạng người',
    'denmang': 'đền mạng',
    'chetnguoi': 'chết người',
    'chetchoc': 'chết chóc',
    'caichet': 'cái chết',
    'chetduoi': 'chết đuối',
    'chetoan': 'chết oan',
    'chettham': 'chết thảm',
    'chetlang': 'chết lặng',
    'thuocdoc': 'thuốc độc',
    'thuocno': 'thuốc nổ',
    'hadoc': 'hạ độc',
    'ngodoc': 'ngộ độc',
    'vetmau': 'vết máu',
    'vungmau': 'vũng máu',
    'dammau': 'đẫm máu',
    'maulanh': 'máu lạnh',
    'vetdan': 'vết đạn',
    'sungdan': 'súng đạn',
    'sungsan': 'súng săn',
    'trungdan': 'trúng đạn',
    'vetthuong': 'vết thương',
    'thuongtich': 'thương tích',
    'chanthuong': 'chấn thương',
    'luadao': 'lừa đảo',
    'tongtien': 'tống tiền',
    'uyhiep': 'uy hiếp',
    'dedoa': 'đe dọa',
    'tratan': 'tra tấn',
    'troichat': 'trói chặt',
    'batgiu': 'bắt giữ',
    'khongche': 'khống chế',
    'tuocdoat': 'tước đoạt',
    'tancong': 'tấn công',
    'kinhhoang': 'kinh hoàng',
    'tuyetvong': 'tuyệt vọng',
    'tramcam': 'trầm cảm',
    'tamthan': 'tâm thần',
    'benhhoan': 'bệnh hoạn',
    'loanluan': 'loạn luân',
    'truyna': 'truy nã',
    'phongtoa': 'phong tỏa',
    'hientruong': 'hiện trường',
    'uchiep': 'ức hiếp',
    'trathu': 'trả thù',
    'baothu': 'báo thù',
    'vungtrom': 'vụng trộm',
    'tinhnhan': 'tình nhân',
    'nhantinh': 'nhân tình',
    'mangthai': 'mang thai',
    'mangtrinh': 'màng trinh',
    'tinhduc': 'tình dục',
    'ducvong': 'dục vọng',
    'oannghiet': 'oan nghiệt',
    'lamdung': 'lạm dụng',
    'tainan': 'tai nạn',
    'dottu': 'đột tử',
    'baohiem': 'bảo hiểm',
    'thamnhung': 'tham nhũng',
    'chinhtri': 'chính trị',
    'dianguc': 'địa ngục',
    'tuinhuc': 'tủi nhục',
    'damnat': 'nát bấy',
    'treoco': 'treo cổ',
    'chet': 'chết',
    'giet': 'giết',
    'chiemdoat': 'chiếm đoạt',
    'ngoaitinh': 'ngoại tình',
    'xac': 'xác',
    'cuop': 'cướp',
    'bian': 'bí ẩn',
    'rungron': 'rùng rợn',
    'bomang': 'bỏ mạng',
    'khongdau': 'không đầu',
    'bikich': 'bi kịch',
}

def preserve_case(match, replacement):
    word = match.group(0)
    if word.isupper():
        return replacement.upper()
    elif word and word[0].isupper():
        return ' '.join(w.capitalize() for w in replacement.split())
    else:
        return replacement.lower()

def clean_script_text(raw_text):
    # 1. Unicode normalization and strip zero-width chars
    text = re.sub(r'[\u034f\u200b\u200c\u200d\u200e\u200f\ufeff]', '', raw_text)
    text = unicodedata.normalize('NFC', text)

    # 2. Extract title from first line
    lines = [l.strip() for l in text.splitlines()]
    title = ""
    start_idx = 0
    for idx, l in enumerate(lines):
        if not l:
            continue
        if l.startswith('# '):
            title = l[2:].strip()
            start_idx = idx + 1
            break
        elif not title:
            title = l
            start_idx = idx + 1
            break

    extra_body = ""

    # Split disclaimer if present in title
    if '/Bài viết thuật lại' in title or '/bài viết thuật lại' in title:
        parts = re.split(r'/[Bb]ài viết thuật lại[\s\S]*?(?:trước khi đọc\.|trước khi đọc)/?', title, maxsplit=1)
        title = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            extra_body = parts[1].strip()

    # Clean raw title
    t = re.sub(r'/[Bb]ài viết.*', '', title).strip()
    while True:
        nt = re.sub(r'(?<=[a-zA-ZÀ-ỹ\d])/+(?=[a-zA-ZÀ-ỹ])', '', t)
        if nt == t:
            break
        t = nt
    t = re.sub(r'\[(?:Những vụ án có thật|Vụ án có thật)\]', '', t, flags=re.IGNORECASE).strip()

    if len(t) > 70:
        if 'POV:' in t:
            parts = t.split('POV:', 1)
            title = parts[0].strip()
            extra_body = 'POV: ' + parts[1].strip() + ('\n\n' + extra_body if extra_body else '')
        elif '..' in t and t.find('..') < 80:
            parts = t.split('..', 1)
            title = (parts[0] + '..').strip()
            extra_body = parts[1].strip() + ('\n\n' + extra_body if extra_body else '')
        elif re.search(r'([A-ZÀ-Ỹ\s]{4,}[A-ZÀ-Ỹ])(?=\d{1,2}\.)', t):
            m = re.search(r'([A-ZÀ-Ỹ\s]{4,}[A-ZÀ-Ỹ])(?=\d{1,2}\.)', t)
            split_idx = m.end(1)
            extra_body = t[split_idx:].strip() + ('\n\n' + extra_body if extra_body else '')
            title = t[:split_idx].strip()
        elif re.search(r'([A-ZÀ-Ỹ\s]{4,}[A-ZÀ-Ỹ])(?=Phần \d+:)', t):
            m = re.search(r'([A-ZÀ-Ỹ\s]{4,}[A-ZÀ-Ỹ])(?=Phần \d+:)', t)
            split_idx = m.end(1)
            extra_body = t[split_idx:].strip() + ('\n\n' + extra_body if extra_body else '')
            title = t[:split_idx].strip()
        elif re.search(r'([A-ZÀ-Ỹ\s]{4,}[A-ZÀ-Ỹ])(?=[A-ZÀ-Ỹ][a-zà-ỹ]{2,})', t):
            m = re.search(r'([A-ZÀ-Ỹ\s]{4,}[A-ZÀ-Ỹ])(?=[A-ZÀ-Ỹ][a-zà-ỹ]{2,})', t)
            split_idx = m.end(1)
            extra_body = t[split_idx:].strip() + ('\n\n' + extra_body if extra_body else '')
            title = t[:split_idx].strip()
        else:
            title = t
    else:
        title = t

    # 3. Filter out metadata, disclaimers, repeated titles
    cleaned_lines = []
    seen_title = False
    for l in lines[start_idx:]:
        if not l:
            cleaned_lines.append('')
            continue
        # Skip metadata lines
        if l.startswith('>') or l.startswith('---') or l.startswith('===') or l.startswith('#'):
            continue
        # Strip disclaimer if line contains it
        if '/Bài viết thuật lại' in l or '/bài viết thuật lại' in l:
            l = re.sub(r'/[Bb]ài viết thuật lại[\s\S]*?(?:trước khi đọc\.|trước khi đọc)/?', '', l).strip()
            if not l:
                continue
        if l.startswith('/Bài viết') or 'Độc giả vui lòng cân nhắc' in l or 'không cổ súy bạo lực' in l:
            continue
        if 'Hồ sơ khép lại, nhưng câu chuyện thì vẫn còn đó' in l:
            continue
        if re.match(r'^(?:#[\w_]+\s*)+$', l):
            continue
        # Skip duplicate title right at beginning
        if not seen_title and (l.strip().lower() == title.strip().lower() or (len(title) > 20 and l.strip().lower().startswith(title.strip().lower()))):
            seen_title = True
            continue
        cleaned_lines.append(l)

    if extra_body:
        cleaned_lines.insert(0, extra_body)

    content = '\n'.join(cleaned_lines).strip()

    # 4. Remove photo references like (ảnh 1), (ảnh 2), (ảnh dưới), (Hình 1), (Ảnh 3: ...)
    content = re.sub(r'\s*\((?:ảnh|hình|vẫn là ảnh)\s*[^)]*\)', '', content, flags=re.IGNORECASE)

    # 5. Remove markdown formatting
    content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)
    content = re.sub(r'__([^_]+)__', r'\1', content)
    content = re.sub(r'`([^`]+)`', r'\1', content)
    content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
    # Remove markdown separators like ***** or ---
    content = re.sub(r'^\s*[*-_]{3,}\s*$', '', content, flags=re.MULTILINE)

    # 6. Asterisk evasion words
    def repl_gi_t(m):
        w = m.group(0)
        return 'GIẾT' if w.isupper() else ('Giết' if w[0].isupper() else 'giết')

    def repl_ch_t(m):
        w = m.group(0)
        return 'CHẾT' if w.isupper() else ('Chết' if w[0].isupper() else 'chết')

    content = re.sub(r'\bgi\*+t\b', repl_gi_t, content, flags=re.IGNORECASE)
    content = re.sub(r'\bch\*+t\b', repl_ch_t, content, flags=re.IGNORECASE)
    content = re.sub(r'\bc\*+ết\b', 'chết', content, flags=re.IGNORECASE)
    content = re.sub(r'\bđ\*+m\b', 'đâm', content, flags=re.IGNORECASE)
    content = re.sub(r'\bxá\*+', 'xác', content, flags=re.IGNORECASE)
    content = re.sub(r'\bthi\s+th\*+', 'thi thể', content, flags=re.IGNORECASE)
    content = re.sub(r'\btự\s+t\*+(\.+|\b)', r'tự tử\1', content, flags=re.IGNORECASE)
    content = re.sub(r'\bgi\*tnguoi\w*\b', 'giết người', content, flags=re.IGNORECASE)
    # Strip any remaining rogue asterisks
    content = content.replace('*', '')

    # 7. Slashes inside words (e.g. M///ÁU, M/áu, b//ắn, c/h/e/t, TH//Ể, t/h/i/t/h/e)
    # Preserve date slashes (DD/MM/YYYY) and units (km/h, USD/tháng)
    while True:
        new_content = re.sub(r'(?<=[a-zA-ZÀ-ỹ\d])/+(?=[a-zA-ZÀ-ỹ])', '', content)
        if new_content == content:
            break
        content = new_content

    # Fix glued date pattern: e.g. dương18/08/1993 -> dương 18/08/1993
    content = re.sub(r'([a-zA-ZÀ-ỹ])(\d{1,2}/\d{1,2}/\d{2,4})', r'\1 \2', content)

    # Section breaks for unformatted posts: e.g. "cao tốc01.Vào" -> "cao tốc\n\n01. Vào"
    content = re.sub(r'(\D)(\d{1,2}\.)([A-ZÀ-Ỹ])', r'\1\n\n\2 \3', content)
    content = re.sub(r'(\D)(Phần \d+:)', r'\1\n\n\2', content)

    # 8. Clean title
    title_clean = re.sub(r'\s*\((?:ảnh|hình|vẫn là ảnh)\s*[^)]*\)', '', title, flags=re.IGNORECASE)
    title_clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', title_clean)
    title_clean = re.sub(r'\bgi\*+t\b', repl_gi_t, title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'\bch\*+t\b', repl_ch_t, title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'\bxá\*+', 'xác', title_clean, flags=re.IGNORECASE)
    title_clean = title_clean.replace('*', '')
    while True:
        new_title = re.sub(r'(?<=[a-zA-ZÀ-ỹ\d])/+(?=[a-zA-ZÀ-ỹ])', '', title_clean)
        if new_title == title_clean:
            break
        title_clean = new_title

    # 9. Apply evasion dictionary to content & title
    for evasion, replacement in EVASIONS.items():
        pattern = re.compile(r'\b' + re.escape(evasion) + r'\b', re.IGNORECASE)
        content = pattern.sub(lambda m: preserve_case(m, replacement), content)
        title_clean = pattern.sub(lambda m: preserve_case(m, replacement), title_clean)

    # 10. Whitespace and paragraph normalization
    # Normalize double dots: e.g. "..\n01." -> "01."
    content = re.sub(r'^\s*\.{2,}\s*$', '', content, flags=re.MULTILINE)
    # Multiple spaces to single space
    content = re.sub(r'[ \t]+', ' ', content)
    # Collapse 3+ newlines to 2
    content = re.sub(r'\n{3,}', '\n\n', content)
    # Strip each line
    content = '\n'.join(line.strip() for line in content.splitlines()).strip()

    final_text = f"{title_clean.strip()}\n\n{content}\n"
    return title_clean.strip(), final_text


# Suffix mapping for multi-part stories and series to avoid confusion (_1, _2, _3...)
MULTIPART_RENAME_MAP = {
    # 1. Áo da người
    '104_ao-da-nguoi-ky-1.txt': '104_ao-da-nguoi_1.txt',
    '102_ao-da-nguoi-ky-2.txt': '102_ao-da-nguoi_2.txt',

    # 2. Căn hộ ăn thịt người
    '240_can-ho-an-thit-nguoi.txt': '240_can-ho-an-thit-nguoi_1.txt',
    '236_can-ho-an-thit-nguoi-phan-2.txt': '236_can-ho-an-thit-nguoi_2.txt',
    '233_can-ho-an-thit-nguoi-phan-cuoi.txt': '233_can-ho-an-thit-nguoi_3.txt',

    # 3. Chung cư đẫm máu: Mười ngày ma quái
    '157_chung-cu-dam-mau-muoi-ngay-ma-quai-phan-1.txt': '157_chung-cu-dam-mau-muoi-ngay-ma-quai_1.txt',
    '155_chung-cu-dam-mau-muoi-ngay-ma-quai-phan-2.txt': '155_chung-cu-dam-mau-muoi-ngay-ma-quai_2.txt',
    '154_chung-cu-dam-mau-muoi-ngay-ma-quai-phan-3.txt': '154_chung-cu-dam-mau-muoi-ngay-ma-quai_3.txt',
    '152_chung-cu-dam-mau-muoi-ngay-ma-quai-phan-4.txt': '152_chung-cu-dam-mau-muoi-ngay-ma-quai_4.txt',
    '150_chung-cu-dam-mau-muoi-ngay-ma-quai-phan-ket.txt': '150_chung-cu-dam-mau-muoi-ngay-ma-quai_5.txt',

    # 4. Đêm trong bảo tàng
    '200_dem-trong-bao-tang---phan-1.txt': '200_dem-trong-bao-tang_1.txt',
    '198_dem-trong-bao-tang---phan-3.txt': '198_dem-trong-bao-tang_3.txt',
    '196_dem-trong-bao-tang---phan-cuoi.txt': '196_dem-trong-bao-tang_4.txt',

    # 5. Khi chương trình truyền hình thực tế biến thành show sinh tử
    '100_khi-chuong-trinh-truyen-hinh-thuc-te-bien-thanh-sh.txt': '100_khi-chuong-trinh-truyen-hinh-thuc-te-bien-thanh-sh_3.txt',
    '098_khi-chuong-trinh-truyen-hinh-thuc-te-bien-thanh-sh.txt': '098_khi-chuong-trinh-truyen-hinh-thuc-te-bien-thanh-sh_4.txt',

    # 6. Lòng người
    '116_long-nguoi-ky-1.txt': '116_long-nguoi_1.txt',
    '113_long-nguoi-ky-cuoi.txt': '113_long-nguoi_2.txt',

    # 7. Ngủ thử nhà ma
    '188_ngu-thu-nha-ma---tap-1.txt': '188_ngu-thu-nha-ma_1.txt',
    '186_ngu-thu-nha-ma---phan-2.txt': '186_ngu-thu-nha-ma_2.txt',
    '184_ngu-thu-nha-ma---phan-cuoi.txt': '184_ngu-thu-nha-ma_3.txt',

    # 8. Người mẹ quỳ gối van xin, nào ngờ kẻ thủ ác lại là..
    '228_nguoi-me-quy-goi-van-xin-nao-ngo-ke-thu-ac-lai-la.txt': '228_nguoi-me-quy-goi-van-xin-nao-ngo-ke-thu-ac-lai-la_1.txt',
    '010_nguoi-me-quy-goi-van-xin-nao-ngo-ke-thu-ac-lai-lat.txt': '010_nguoi-me-quy-goi-van-xin-nao-ngo-ke-thu-ac-lai-la_2.txt',

    # 9. Nhân chứng
    '253_nhan-chung-phan-1.txt': '253_nhan-chung_1.txt',
    '251_nhan-chung-phan-cuoi.txt': '251_nhan-chung_2.txt',

    # 10. Những bí ẩn nửa đêm qua lời kể của tài xế xe đường dài
    '206_nhung-bi-an-nua-dem-qua-loi-ke-cua-tai-xe-xe-duong.txt': '206_nhung-bi-an-nua-dem-qua-loi-ke-cua-tai-xe-xe-duong_1.txt',
    '204_nhung-bi-an-nua-dem-qua-loi-ke-cua-tai-xe-xe-duong.txt': '204_nhung-bi-an-nua-dem-qua-loi-ke-cua-tai-xe-xe-duong_2.txt',

    # 11. Những địa điểm "ma ám" nổi tiếng tại Trung Quốc
    '229_nhung-dia-diem-ma-am-noi-tieng-tai-trung-quoc---ph.txt': '229_nhung-dia-diem-ma-am-noi-tieng-tai-trung-quoc_1.txt',
    '227_nhung-dia-diem-ma-am-noi-tieng-tai-trung-quoc---ph.txt': '227_nhung-dia-diem-ma-am-noi-tieng-tai-trung-quoc_2.txt',

    # 12. Những trải nghiệm kinh dị có thật
    '244_nhung-trai-nghiem-kinh-di-co-that---phan-2.txt': '244_nhung-trai-nghiem-kinh-di-co-that_2.txt',
    '237_nhung-trai-nghiem-kinh-di-co-that---phan-3.txt': '237_nhung-trai-nghiem-kinh-di-co-that_3.txt',

    # 13. Phòng chat đào thoát
    '002_phong-chat-dao-thoat-phan-1pov-ban-thuc-day-o-mot.txt': '002_phong-chat-dao-thoat_1.txt',
    '222_phong-chat-dao-thoat-phan-1.txt': '222_phong-chat-dao-thoat_1.txt',
    '246_phong-chat-dao-thoat-phan-2.txt': '246_phong-chat-dao-thoat_2.txt',

    # 14. Sư tử đá trấn mộ
    '209_su-tu-da-tran-mo-phan-1.txt': '209_su-tu-da-tran-mo_1.txt',
    '208_su-tu-da-tran-mo-phan-cuoi.txt': '208_su-tu-da-tran-mo_2.txt',

    # 15. Tế rắn hoài thai
    '097_te-ran-hoai-thai---ky-3.txt': '097_te-ran-hoai-thai_3.txt',
    '095_te-ran-hoai-thai---ky-4.txt': '095_te-ran-hoai-thai_4.txt',
    '092_te-ran-hoai-thai---ky-5.txt': '092_te-ran-hoai-thai_5.txt',

    # 16. Theo dấu hung thủ
    '270_theo-dau-hung-thu-phan-1.txt': '270_theo-dau-hung-thu_1.txt',
    '266_theo-dau-hung-thu-phan-2.txt': '266_theo-dau-hung-thu_2.txt',
    '263_theo-dau-hung-thu-phan-cuoi.txt': '263_theo-dau-hung-thu_3.txt',

    # 17. Thượng cổ trấn sát kính hay bí mật về tục tế người
    '132_thuong-co-tran-sat-kinh-hay-bi-mat-ve-tuc-te-nguoi.txt': '132_thuong-co-tran-sat-kinh-hay-bi-mat-ve-tuc-te-nguoi_1.txt',
    '130_thuong-co-tran-sat-kinh-hay-bi-mat-ve-tuc-te-nguoi.txt': '130_thuong-co-tran-sat-kinh-hay-bi-mat-ve-tuc-te-nguoi_2.txt',

    # 18. Tôi không thể quên lần bị đánh 17 năm trước
    '249_toi-khong-the-quen-lan-bi-danh-17-nam-truoc-phan-1.txt': '249_toi-khong-the-quen-lan-bi-danh-17-nam-truoc_1.txt',
    '242_toi-khong-the-quen-lan-bi-danh-17-nam-truoc-phan-c.txt': '242_toi-khong-the-quen-lan-bi-danh-17-nam-truoc_2.txt',

    # 19. Topic: Có câu chuyện ma nào cực kỳ đáng sợ không?
    '175_topic-co-cau-chuyen-ma-nao-cuc-ky-dang-so-khong.txt': '175_topic-co-cau-chuyen-ma-nao-cuc-ky-dang-so-khong_1.txt',
    '124_topic-co-cau-chuyen-ma-nao-cuc-ky-dang-so-khong.txt': '124_topic-co-cau-chuyen-ma-nao-cuc-ky-dang-so-khong_2.txt',

    # 20. Tuyển tập truyện ngắn kinh dị rợn tóc gáy
    '145_tuyen-tap-truyen-ngan-kinh-di-ron-toc-gay-ky-1.txt': '145_tuyen-tap-truyen-ngan-kinh-di-ron-toc-gay_1.txt',
    '143_tuyen-tap-truyen-ngan-kinh-di-ron-toc-gay-ky-2.txt': '143_tuyen-tap-truyen-ngan-kinh-di-ron-toc-gay_2.txt',
    '142_tuyen-tap-truyen-ngan-kinh-di-ron-toc-gay-ky-3.txt': '142_tuyen-tap-truyen-ngan-kinh-di-ron-toc-gay_3.txt',

    # Single stories with explicit part tags
    '012_vu-an-tham-sat-gia-dinh-chi-cuc-truong-thuephan-1.txt': '012_vu-an-tham-sat-gia-dinh-chi-cuc-truong-thue_1.txt',
    '080_ghi-chep-ve-nhung-cau-chuyen-ky-di-o-dong-nam-a-no.txt': '080_ghi-chep-ve-nhung-cau-chuyen-ky-di-o-dong-nam-a-no_3.txt',
    '084_chuyen-la-do-thi-ghi-chep-ve-cac-vu-viec-tam-linh.txt': '084_chuyen-la-do-thi-ghi-chep-ve-cac-vu-viec-tam-linh_1.txt',
    '087_mot-ngay-no-sadako-bi-ket-trong-tivi-ky-cuoi.txt': '087_mot-ngay-no-sadako-bi-ket-trong-tivi_cuoi.txt',
    '090_nguoi-kham-liem-ky-2.txt': '090_nguoi-kham-liem_2.txt',
    '105_muon-xac-hoan-hon-ky-cuoi.txt': '105_muon-xac-hoan-hon_cuoi.txt',
    '108_topic-neu-ban-di-dem-ma-bat-ngo-gap-hoang-bi-tu-ch.txt': '108_topic-neu-ban-di-dem-ma-bat-ngo-gap-hoang-bi-tu-ch_cuoi.txt',
    '111_tuyen-tap-truyen-ma-dan-gian-ky-1.txt': '111_tuyen-tap-truyen-ma-dan-gian_1.txt',
    '118_topic-dieu-tam-toi-nhat-ma-ban-tung-chung-kien-la.txt': '118_topic-dieu-tam-toi-nhat-ma-ban-tung-chung-kien-la_cuoi.txt',
    '126_topic-o-que-cac-ban-co-giai-thoai-hay-cam-ky-kinh.txt': '126_topic-o-que-cac-ban-co-giai-thoai-hay-cam-ky-kinh_cuoi.txt',
    '136_topic-co-cau-chuyen-nao-ve-cuong-thi-rat-loi-cuon.txt': '136_topic-co-cau-chuyen-nao-ve-cuong-thi-rat-loi-cuon_2.txt',
    '139_tien-giu-mang-ky-1.txt': '139_tien-giu-mang_1.txt',
    '147_trang-nguyen-quy-mong-ky-cuoi.txt': '147_trang-nguyen-quy-mong_cuoi.txt',
    '159_topic-co-cau-chuyen-nao-ve-ma-quy-rat-loi-cuon-va.txt': '159_topic-co-cau-chuyen-nao-ve-ma-quy-rat-loi-cuon-va_cuoi.txt',
    '162_chuyen-la-tren-xa-lo-tan-cuong-ky-3.txt': '162_chuyen-la-tren-xa-lo-tan-cuong_3.txt',
    '166_nhat-ky-dao-quan-do-de-xui-xeo-truong-sieu-ky-1.txt': '166_nhat-ky-dao-quan-do-de-xui-xeo-truong-sieu_1.txt',
    '168_tuyen-tap-truyen-ma-ky-tuc-xa-nu.txt': '168_tuyen-tap-truyen-ma-ky-tuc-xa-nu_1.txt',
    '177_topic---lieu-ma-quy-co-thuc-su-ton-tai-khong.txt': '177_topic---lieu-ma-quy-co-thuc-su-ton-tai-khong_2.txt',
    '179_tuyen-tap-truyen-linh-di---ky-4.txt': '179_tuyen-tap-truyen-linh-di_4.txt',
    '190_vai-mau-chuyen-ke-cua-quy-sai---phan-2.txt': '190_vai-mau-chuyen-ke-cua-quy-sai_2.txt',
    '192_cuoc-goi-luc-rang-sang---phan-cuoi.txt': '192_cuoc-goi-luc-rang-sang_cuoi.txt',
    '211_hon-nhan-hoan-my-phan-cuoi.txt': '211_hon-nhan-hoan-my_cuoi.txt',
    '218_thi-tran-cuc-lac-phan-cuoi.txt': '218_thi-tran-cuc-lac_cuoi.txt',
    '231_bao-ung-phan-2.txt': '231_bao-ung_2.txt',
    '259_ten-bat-coc-bi-bo-toi-dan-nguoi-chan-o-cong-lang-d.txt': '259_ten-bat-coc-bi-bo-toi-dan-nguoi-chan-o-cong-lang-d_cuoi.txt'
}


def get_file_num(p):
    m = re.match(r'^(\d+)_', p.name)
    return int(m.group(1)) if m else 99999


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_files = [f for f in SRC_DIR.glob('*.md') if f.name != 'README.md']
    md_files_sorted = sorted(md_files, key=get_file_num)

    print(f"[*] Bắt đầu xử lý {len(md_files_sorted)} file kịch bản thô sang văn bản thuần sạch...")

    combined_path = OUT_DIR / "all_cases_clean.txt"
    combined_file = combined_path.open('w', encoding='utf-8')

    index_lines = [
        "================================================================================",
        "MỤC LỤC KỊCH BẢN CÁC VỤ ÁN (THUẦN TEXT - ĐÃ CHUẨN HÓA & SỬA LỖI)",
        f"Thời gian tạo: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Tổng số vụ án: {len(md_files_sorted)}",
        "================================================================================\n"
    ]

    for idx, fpath in enumerate(md_files_sorted, 1):
        raw_text = fpath.read_text(encoding='utf-8')
        title_clean, clean_text = clean_script_text(raw_text)

        # Output file name: 001_..., 002_... .txt
        num_str = f"{idx:03d}"
        slug = fpath.stem
        # Replace original number prefix in slug with our clean 3-digit index
        slug = re.sub(r'^\d+_', '', slug)
        default_fname = f"{num_str}_{slug}.txt"
        out_fname = MULTIPART_RENAME_MAP.get(default_fname, default_fname)
        out_path = OUT_DIR / out_fname

        out_path.write_text(clean_text, encoding='utf-8')

        words = len(clean_text.split())
        chars = len(clean_text)

        index_lines.append(f"{num_str}. {title_clean} [{out_fname}] ({words:,} từ / {chars:,} ký tự)")

        # Write to combined file
        combined_file.write("=" * 80 + "\n")
        combined_file.write(f"VỤ ÁN {num_str}: {title_clean}\n")
        combined_file.write("=" * 80 + "\n\n")
        combined_file.write(clean_text + "\n\n\n")

        if idx % 30 == 0 or idx == len(md_files_sorted):
            print(f"  [+] Đã xử lý {idx}/{len(md_files_sorted)}: '{title_clean[:50]}' ({words:,} từ)")

    combined_file.close()

    # Write INDEX.txt
    (OUT_DIR / "INDEX.txt").write_text('\n'.join(index_lines), encoding='utf-8')

    print(f"\n[+] HOÀN TẤT XỬ LÝ TOÀN BỘ!")
    print(f"[+] Thư mục chứa {len(md_files_sorted)} file thuần text: {OUT_DIR}")
    print(f"[+] File gộp tất cả vụ án sạch: {combined_path}")
    print(f"[+] File mục lục: {OUT_DIR / 'INDEX.txt'}")


if __name__ == '__main__':
    main()
