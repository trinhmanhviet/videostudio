"""Clean and normalize crawled Facebook posts for 'Sử ta và họ'.
Converts raw Markdown files to pure plain text suitable for video script generation/TTS:
- Removes Markdown syntax (#, **, *, >, ---, etc.)
- Strips affiliate book links, Shopee URLs, photo credits, and social media disclaimers
- Normalizes punctuation, removes zero-width characters, fixes Vietnamese spelling/censor evasions
- Appends _1, _2 suffixes for series / multi-part stories
- Generates INDEX.txt and all_cases_clean.txt
"""
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "raw_md"
CLEAN_DIR = ROOT.parent / "data" / "facebook_cases" / "clean" / "su-ta-va-ho"

# Vietnamese censor evasion dictionary
CENSOR_EVASIONS = [
    (r'\bgi\*t\b', 'giết'),
    (r'\bc\*t\b', 'cắt'),
    (r'\bch\*t\b', 'chết'),
    (r'\bm\*u\b', 'máu'),
    (r'\bt\*nh\s+d\*c\b', 'tình dục'),
    (r'\bk\*ch\s+th\*ch\b', 'kích thích'),
    (r'\btự\s+t\*\b', 'tự tử'),
    (r'\bx\*c\b', 'xác'),
    (r'\bhi\*p\b', 'hiếp'),
    (r'\btù\s+nh\*n\b', 'tù nhân'),
    (r'\bđ\*n\b', 'đạn'),
    (r'\bl\*u\s+đạn\b', 'lựu đạn'),
    (r'\bchiến\s+tr\*nh\b', 'chiến tranh'),
    (r'\bc\*ng\s+k\*ch\b', 'công kích'),
]


def strip_invisible_chars(text: str) -> str:
    # Zero-width spaces, joiners, markers, byte-order marks
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff\u034f\u00ad]', '', text)
    # Normalize unicode to NFC
    text = unicodedata.normalize('NFC', text)
    return text


def clean_markdown_and_links(text: str) -> str:
    # Remove header metadata block if present
    lines = text.splitlines()
    body_lines = []
    in_meta_header = True

    for line in lines:
        stripped = line.strip()
        if in_meta_header:
            if stripped.startswith('# ') or stripped.startswith('> ') or stripped == '---':
                continue
            elif stripped == '':
                continue
            else:
                in_meta_header = False
        body_lines.append(line)

    text = '\n'.join(body_lines)

    # 1. Remove Shopee, book links, affiliate disclaimers
    # Typical: Link mua sách: https://s.shopee.vn/... or Mua sách tại:...
    text = re.sub(r'(?i)(?:link\s+(?:mua\s+)?sách|mua\s+sách|đặt\s+mua\s+sách|link\s+shopee|shopee)[\s:]*[^\n]+', '', text)
    text = re.sub(r'https?://(?:s\.)?shopee\.[^\s]+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'https?://[^\s]+', '', text)

    # 2. Remove photo notes, source credits at end or inside parentheses
    text = re.sub(r'(?i)\((?:ảnh|nguồn\s+ảnh|hình|nguồn|nguồn\s+ảnh\s+minh\s+họa)[\s:][^)]*\)', '', text)
    text = re.sub(r'(?i)\[(?:ảnh|nguồn\s+ảnh|hình|nguồn)[\s:][^\]]*\]', '', text)

    # 3. Remove Facebook UI artifacts
    text = re.sub(r'(?i)^\s*(?:See more|Xem thêm|See less|Thu gọn)\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(?i)^\s*(?:Facebook|Shopee)\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(?i)^\s*\d+\s+(?:hours?|days?|mins?|phút|giờ|ngày)\s+ago\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(#[\w_]+\s*)+$', '', text).strip()

    # 4. Remove Markdown syntax
    # Bold / Italic: **text** or *text* or __text__ or _text_
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    # Backticks
    text = re.sub(r'`(.*?)`', r'\1', text)
    # Blockquotes
    text = re.sub(r'^[ \t]*>[ \t]?', '', text, flags=re.MULTILINE)
    # Headings #, ##, ###
    text = re.sub(r'^[ \t]*#{1,6}[ \t]+', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[ \t]*[-*_]{3,}[ \t]*$', '', text, flags=re.MULTILINE)
    # Markdown links [anchor](url) -> anchor
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # 5. Fix censor evasions
    for pat, rep in CENSOR_EVASIONS:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)

    # 6. Punctuation cleanup
    text = re.sub(r'\.\s*\.\s*\.', '…', text)
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    text = re.sub(r'([,.:;?!])([^\s0-9"\')\]])', r'\1 \2', text)
    text = re.sub(r'["""]', '"', text)
    text = re.sub(r"[''']", "'", text)
    text = re.sub(r'…{2,}', '…', text)
    text = re.sub(r'\brsan phẳng\b', 'san phẳng', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 7. Normalize line breaks (no more than 2 consecutive newlines)
    lines = [l.strip() for l in text.splitlines()]
    cleaned_lines = []
    prev_blank = False
    for l in lines:
        if not l:
            if not prev_blank:
                cleaned_lines.append('')
                prev_blank = True
        else:
            cleaned_lines.append(l)
            prev_blank = False

    return '\n'.join(cleaned_lines).strip()


def slugify(title: str) -> str:
    s = unicodedata.normalize('NFD', title)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ', 'd').replace('Đ', 'd').replace('ß', 'ss')
    s = re.sub(r'[^a-zA-Z0-9\s_-]', '', s).strip().lower()
    return re.sub(r'[\s_]+', '-', s)


def detect_series_and_slug(title: str, file_stem: str, body_text: str = "") -> tuple[str, str]:
    """Detects if title/body belongs to a series and extracts suffix e.g. _1, _2, _136...
    Returns (clean_base_slug, suffix)
    """
    head_context = f"{title}\n{body_text[:400]}"

    # 1. Match 'Ngày này năm xưa tập (\d+)'
    m = re.search(r'(?i)ngày\s+này\s+năm\s+xưa\s+tập\s+(\d+)', head_context)
    if m:
        tap_num = m.group(1)
        return 'ngay-nay-nam-xua', f"_{tap_num}"

    # 2. Match '(Giải) Sử Fake - [Tt]ập (\d+)'
    m = re.search(r'(?i)(?:giải\s+)?sử\s+fake.*?tập\s+(\d+)', head_context)
    if m:
        tap_num = m.group(1)
        return 'giai-su-fake', f"_{tap_num}"

    # 3. Match 'Gươm Thuê, Máu Thật'
    if re.search(r'(?i)gươm\s+thuê,\s+máu\s+thật', head_context):
        m = re.search(r'(?i)(?:tập|phần)\s*(\d+)', head_context)
        part = m.group(1) if m else "1"
        return 'guom-thue-mau-that-bien-nien-su-linh-danh-thue-phuong-tay', f"_{part}"

    # 4. Match general 'phần (\d+)' or 'tập (\d+)' or 'P(\d+)'
    m = re.search(r'(?i)(?:phần|tập|part|vol|hồi)\s*(\d+)', head_context)
    if m:
        part_num = m.group(1)
        base_title = re.sub(r'(?i)[-–—:]?\s*(?:phần|tập|part|vol|hồi)\s*\d+.*', '', title).strip()
        slug = slugify(base_title)[:45].strip('-')
        return slug or 'truyen', f"_{part_num}"

    # 5. Standard slug
    clean_stem = re.sub(r'^\d+_', '', file_stem)
    return clean_stem[:50].strip('-'), ""


MIN_WORDS = 80  # Bỏ qua các bài viết quá ngắn (meme 1 câu, tiêu đề album ảnh, thông báo vặt)


def process_all(min_words=MIN_WORDS):
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    for old_txt in CLEAN_DIR.glob('*.txt'):
        old_txt.unlink()
    raw_files = sorted(RAW_DIR.glob('*.md'), key=lambda p: p.name)
    raw_files = [p for p in raw_files if p.name != 'README.md']

    print(f"[*] Tìm thấy {len(raw_files)} file raw markdown trong {RAW_DIR}")
    print(f"[*] Điều kiện lọc: Độ dài tối thiểu {min_words} từ.")

    cleaned_entries = []
    combined_clean_lines = []

    # First pass: collect metadata to handle series groupings
    posts_data = []
    skipped_count = 0
    for f in raw_files:
        m = re.match(r'^(\d+)_', f.name)
        idx = int(m.group(1)) if m else len(posts_data) + 1
        raw_text = f.read_text(encoding='utf-8')
        raw_text = strip_invisible_chars(raw_text)

        # Extract title from raw file (first line of markdown header # Title)
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        title = lines[0][2:].strip() if lines and lines[0].startswith('# ') else f.stem

        cleaned_text = clean_markdown_and_links(raw_text)
        words_count = len(cleaned_text.split())
        if words_count < min_words:
            skipped_count += 1
            continue

        base_slug, suffix = detect_series_and_slug(title, f.stem, cleaned_text)
        posts_data.append({
            'idx': idx,
            'orig_file': f.name,
            'title': title,
            'base_slug': base_slug,
            'suffix': suffix,
            'cleaned_text': cleaned_text
        })

    # Group series that share the same base_slug if no explicit suffix was assigned
    slug_groups = defaultdict(list)
    for p in posts_data:
        slug_groups[p['base_slug']].append(p)

    for base_slug, group in slug_groups.items():
        if len(group) > 1:
            # Check if any missing suffix
            has_explicit_suffix = any(p['suffix'] != '' for p in group)
            if not has_explicit_suffix:
                # Assign _1, _2 sequentially
                for seq, p in enumerate(group, 1):
                    p['suffix'] = f"_{seq}"

    # Second pass: write cleaned files
    for p in posts_data:
        idx = p['idx']
        suffix = p['suffix']
        base_slug = p['base_slug']
        out_fname = f"{idx:03d}_{base_slug}{suffix}.txt"
        out_path = CLEAN_DIR / out_fname

        # Title at the top in uppercase plain text
        title_header = p['title'].upper()
        full_content = f"{title_header}\n\n{p['cleaned_text']}\n"

        out_path.write_text(full_content, encoding='utf-8')

        words = len(full_content.split())
        chars = len(full_content)
        cleaned_entries.append((idx, p['title'], out_fname, words, chars, suffix))

        # Add to combined clean text
        divider = "=" * 60
        combined_clean_lines.append(divider)
        combined_clean_lines.append(f"KỊCH BẢN #{idx:03d}: {title_header}")
        if suffix:
            combined_clean_lines.append(f"(Phần / Tập: {suffix.lstrip('_')})")
        combined_clean_lines.append(divider)
        combined_clean_lines.append("")
        combined_clean_lines.append(p['cleaned_text'])
        combined_clean_lines.append("\n\n")

        print(f"  [+] Đã lưu sạch #{idx:03d}: {out_fname} ({words:,} từ | {chars:,} ký tự)")

    # Write all_cases_clean.txt
    combined_clean_path = CLEAN_DIR / "all_cases_clean.txt"
    combined_clean_path.write_text('\n'.join(combined_clean_lines), encoding='utf-8')

    # Write INDEX.txt
    index_lines = [
        "================================================================================",
        "DANH MỤC KỊCH BẢN CHUẨN HOÁ - SỬ TA VÀ HỌ (FACEBOOK PAGE)",
        "Thư mục: data/facebook_cases/clean/su-ta-va-ho/",
        f"Tổng số bài viết: {len(cleaned_entries)}",
        "Đặc tả định dạng: Thuần văn bản (plain text), không markdown, đã sửa lỗi,",
        "loại bỏ quảng cáo/link Shopee, hậu tố _1, _2... cho các phần của series.",
        "================================================================================\n",
        f"{'STT':<5} | {'HẬU TỐ':<8} | {'ĐỘ DÀI (TỪ / KÝ TỰ)':<22} | {'TÊN FILE / TIÊU ĐỀ'}",
        "-" * 80
    ]

    for idx, title, fname, words, chars, suffix in cleaned_entries:
        suf_disp = suffix if suffix else "-"
        len_disp = f"{words:,} từ / {chars:,} kt"
        index_lines.append(f"#{idx:03d}  | {suf_disp:<8} | {len_disp:<22} | {fname}\n       ↳ {title}")

    (CLEAN_DIR / "INDEX.txt").write_text('\n'.join(index_lines), encoding='utf-8')

    print(f"\n[+] HOÀN TẤT CHUẨN HOÁ!")
    print(f"[+] Giữ lại: {len(cleaned_entries)} bài đủ chuẩn | Bỏ qua: {skipped_count} bài quá ngắn (< {min_words} từ).")
    print(f"[+] Thư mục file sạch: {CLEAN_DIR}")
    print(f"[+] File tổng hợp: {combined_clean_path}")
    print(f"[+] File mục lục: {CLEAN_DIR / 'INDEX.txt'}")


if __name__ == '__main__':
    process_all()
