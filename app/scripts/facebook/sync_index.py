import re, time, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
output_dir = Path(r'D:\Projects\videostudio\data\facebook_cases\dem-nay-lai-co-chuyen')
md_files = [f for f in output_dir.glob('*.md') if f.name != 'README.md']

def get_file_num(p):
    m = re.match(r'^(\d+)_', p.name)
    return int(m.group(1)) if m else 99999

collected_meta = []
for p in sorted(md_files, key=get_file_num):
    try:
        content = p.read_text(encoding='utf-8')
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if lines and lines[0].startswith('# '):
            title = lines[0][2:].strip()
            words = len(content.split())
            chars = len(content)
            collected_meta.append((title, p.name, words, chars))
    except Exception:
        pass

summary_lines = [
    '# KỊCH BẢN THÔ CÁC VỤ ÁN - FACEBOOK PAGE',
    '- **Nguồn**: https://www.facebook.com/profile.php?id=61580506574495',
    f'- **Thời gian hoàn thành**: {time.strftime("%Y-%m-%d %H:%M:%S")}',
    f'- **Tổng số bài viết đã cào hoàn tất**: {len(collected_meta)} vụ án',
    '',
    '## Danh mục toàn bộ bài viết:',
    ''
]
for idx, (title, fname, words, chars) in enumerate(collected_meta, 1):
    summary_lines.append(f'{idx}. [{title}](./{fname}) — *{words:,} từ / {chars:,} ký tự*')

(output_dir / 'README.md').write_text('\n'.join(summary_lines), encoding='utf-8')
print(f'Đã đồng bộ README.md với đầy đủ {len(collected_meta)} vụ án.')
