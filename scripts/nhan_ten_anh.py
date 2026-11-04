"""Dat ten cho anh vua tai tu ChatGPT va chuyen vao assets/Meme_Animation_Asset_Pack/new/.

Dung ngay sau khi tai mot dot anh ve (thu muc Downloads):
    python scripts/nhan_ten_anh.py bg_kitchen bg_bathroom bg_office bg_classroom
Lay N anh moi nhat trong Downloads, theo thu tu tai ve (cu nhat -> ten dau tien), doi ten theo danh sach.
Them --xem de chi in ra, khong chuyen file.  --tu THUMUC de chon thu muc khac.
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets' / 'Meme_Animation_Asset_Pack' / 'new'
EXT = {'.png', '.jpg', '.jpeg', '.webp'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('names', nargs='+')
    parser.add_argument('--tu', default=str(Path.home() / 'Downloads'))
    parser.add_argument('--xem', action='store_true')
    args = parser.parse_args()
    folder = Path(args.tu)
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXT), key=lambda p: p.stat().st_mtime)
    if len(files) < len(args.names):
        print('Chi co %d anh trong %s, can %d.' % (len(files), folder, len(args.names)))
        return 1
    picked = files[-len(args.names):]
    OUT.mkdir(parents=True, exist_ok=True)
    for source, name in zip(picked, args.names):
        target = OUT / (name.removesuffix('.png') + '.png')
        print('%s  ->  %s' % (source.name, target.name))
        if args.xem:
            continue
        if source.suffix.lower() == '.png':
            shutil.move(str(source), str(target))
        else:
            from PIL import Image
            Image.open(source).convert('RGBA').save(target)
            source.unlink()
    print('Xong.' if not args.xem else '(chi xem, chua chuyen)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
