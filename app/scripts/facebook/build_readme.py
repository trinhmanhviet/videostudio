import re
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
INDEX_FILE = ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "clean_txt" / "INDEX.txt"
README_FILE = ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "README.md"

def main():
    lines = INDEX_FILE.read_text(encoding='utf-8').splitlines()
    entries = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('#'):
            # #001  | -        | 176 từ / 778 kt        | 001_tong-hop-cac-series-dang-lam-de-cac-ban-de-theo-do.txt
            parts = [p.strip() for p in line.split('|')]
            stt = parts[0]
            suffix = parts[1]
            length = parts[2]
            fname = parts[3]
            
            title = ""
            if i + 1 < len(lines) and '↳' in lines[i+1]:
                title = lines[i+1].split('↳', 1)[1].strip()
                i += 1
            entries.append({
                'stt': stt,
                'suffix': suffix,
                'length': length,
                'fname': fname,
                'title': title
            })
        i += 1

    md = []
    md.append("# KHO KỊCH BẢN: SỬ TA VÀ HỌ (FACEBOOK PAGE)\n")
    md.append("Dữ liệu kịch bản lịch sử được thu thập và vét cạn kiệt toàn bộ từ trang Facebook **Sử ta và họ - chuyện xưa kể lại**:")
    md.append("- **Trang Facebook**: [https://www.facebook.com/profile.php?id=61583850062328](https://www.facebook.com/profile.php?id=61583850062328)")
    md.append(f"- **Tổng số bài viết đã cào**: **{len(entries)} bài** (100% toàn bộ dòng thời gian, từ bài mới nhất đến tận cùng bài viết đầu tiên của trang)")
    md.append("- **Tổng dung lượng văn bản**: **77.279 từ / 367.282 ký tự**")
    md.append("- **Thời gian hoàn thành**: 09/11/2026\n")
    md.append("---\n")
    md.append("## Cấu trúc thư mục\n")
    md.append("```text")
    md.append("data/facebook_cases/su-ta-va-ho/")
    md.append("├── README.md                 # Tài liệu tổng quan bộ dữ liệu này")
    md.append("├── raw_md/                   # 100% BẢN GỐC THÔ CÀO TỪ FACEBOOK (.md)")
    md.append("│   ├── README.md             # Mục lục bản thô")
    md.append("│   ├── all_cases_combined.txt# File gộp toàn bộ bài thô")
    md.append(f"│   └── 001_*.md ... {len(entries):03d}_*.md # {len(entries)} file markdown nguyên bản")
    md.append("└── clean_txt/                # BẢN CHUẨN HOÁ DÙNG NGAY CHO VIDEO / TTS (.txt)")
    md.append("    ├── INDEX.txt             # Danh mục kịch bản sạch kèm số từ, ký tự, hậu tố")
    md.append(f"    ├── all_cases_clean.txt   # File gộp toàn bộ {len(entries)} kịch bản sạch, phân cách rõ ràng")
    md.append(f"    └── [001-{len(entries):03d}]_*.txt      # {len(entries)} file thuần văn bản (plain text)")
    md.append("```\n")
    md.append("---\n")
    md.append("## Quy chuẩn xử lý bản sạch (`clean_txt/`)\n")
    md.append("1. **Thuần văn bản (Plain Text)**: Loại bỏ hoàn toàn cú pháp Markdown (`#`, `**`, `*`, `__`, `>`, `---`, `[link](url)`).")
    md.append("2. **Loại bỏ quảng cáo & rác mạng xã hội**:")
    md.append("   - Xoá triệt để các link tiếp thị liên kết Shopee (`https://s.shopee.vn/...`), lời mời mua sách ủng hộ tác giả.")
    md.append("   - Xoá các nhãn Facebook (`See more`, `Xem thêm`, `Thu gọn`, số giờ/ngày, v.v.).")
    md.append("   - Xoá chú thích ảnh (`(Ảnh: ...)`, `[Ảnh ...]`).")
    md.append("3. **Sửa lỗi chính tả & lách kiểm duyệt (Censor Evasion)**:")
    md.append("   - Thay thế các từ viết tắt né kiểm duyệt Facebook: `gi*t` → `giết`, `c*t` → `cắt`, `ch*t` → `chết`, `m*u` → `máu`, `t*nh d*c` → `tình dục`, `tự t*` → `tự tử`, `rsan phẳng` → `san phẳng`.")
    md.append("   - Chuẩn hoá dấu câu, xoá khoảng trắng thừa, xoá ký tự vô hình zero-width (`\\u200b`, `\\u200c`, `\\ufeff`).")
    md.append("4. **Hậu tố cho series / truyện nhiều phần (`_1`, `_2`, `_{tập}`)**:")
    md.append("   - Các series dài tập được thêm hậu tố số tập vào cuối tên file để phân loại chính xác, tránh nhầm lẫn:")
    md.append("     - `ngay-nay-nam-xua_118.txt` đến `_138.txt` (đầy đủ các tập)")
    md.append("     - `giai-su-fake_7.txt` đến `_10.txt`")
    md.append("     - `guom-thue-mau-that-bien-nien-su-linh-danh-thue-phuong-tay_1.txt`, `_2.txt`, `_3.txt` (đầy đủ các phần)")
    md.append("     - `total-war-shogun-2-nguon-goc-vinh-quang_11.txt`, `_12.txt`, `_cuoi.txt`")
    md.append("     - `neu-lich-su-la-mot-bay-meo_21.txt`, `_23.txt`, `_24.txt`, `_25.txt`, `_26.txt`")
    md.append("   - Các bài độc lập giữ tiền tố số thứ tự gốc từ `001_` đến `095_` để sắp xếp thứ tự chuẩn xác.\n")
    md.append("---\n")
    md.append(f"## Danh mục toàn bộ {len(entries)} bài viết\n")
    md.append("| STT | Tên file sạch | Hậu tố | Số từ / Ký tự | Tiêu đề bài viết |")
    md.append("|:---:|:---|:---:|:---:|:---|")

    for e in entries:
        suf = f"`{e['suffix']}`" if e['suffix'] != '-' else '-'
        title_esc = e['title'].replace('|', '-').replace('\n', ' ')
        md.append(f"| {e['stt']} | `{e['fname']}` | {suf} | {e['length']} | {title_esc} |")

    README_FILE.write_text('\n'.join(md), encoding='utf-8')
    print(f"[+] Updated {README_FILE} with {len(entries)} entries.")

if __name__ == '__main__':
    main()
