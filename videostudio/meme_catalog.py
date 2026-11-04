"""Named sprites and backgrounds the meme script writer may choose from.

The catalog is data built offline by scripts/build_meme_catalog.py (Panda sprites cut from the
production sheets) plus any single-image backgrounds the user drops into
assets/Meme_Animation_Asset_Pack/new/ as bg_<name>.png. Procedural backgrounds are always
available, so a video never depends on assets that have not been drawn yet.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'assets' / 'Meme_Animation_Asset_Pack'
CATALOG_VERSION = 1

# Procedural backgrounds: id -> (top colour, bottom colour, style, description)
PROCEDURAL = {
    'plain_blue': ((168, 214, 247), (110, 170, 222), 'plain', 'nền xanh dương trơn, trung tính'),
    'plain_pink': ((252, 205, 222), (238, 150, 182), 'plain', 'nền hồng trơn, dễ thương, tình cảm'),
    'plain_yellow': ((255, 236, 150), (247, 200, 80), 'plain', 'nền vàng trơn, vui vẻ'),
    'plain_green': ((196, 236, 180), (130, 198, 120), 'plain', 'nền xanh lá trơn, thư thái'),
    'plain_purple': ((214, 196, 245), (160, 132, 214), 'plain', 'nền tím trơn, bí ẩn'),
    'plain_gray': ((222, 222, 222), (170, 170, 170), 'plain', 'nền xám trơn, chán nản, buồn'),
    'room_day': ((246, 232, 205), (196, 160, 118), 'room', 'trong nhà ban ngày (tường be, sàn gỗ)'),
    'room_night': ((58, 66, 108), (30, 32, 58), 'room', 'trong nhà ban đêm, tối'),
    'outdoor_day': ((150, 210, 250), (120, 190, 110), 'outdoor', 'ngoài trời ban ngày (trời xanh, cỏ)'),
    'outdoor_night': ((18, 24, 64), (40, 52, 70), 'night', 'ngoài trời ban đêm có sao'),
    'rays_yellow': ((255, 230, 120), (255, 170, 40), 'rays', 'tia sáng toả vàng: hào hứng, chiến thắng, ý tưởng'),
    'rays_red': ((255, 120, 100), (200, 30, 30), 'rays', 'tia toả đỏ: tức giận, sốc, cao trào'),
    'rays_blue': ((150, 200, 255), (60, 110, 220), 'rays', 'tia toả xanh: bất ngờ, choáng'),
    'flashback': ((236, 236, 236), (190, 190, 190), 'flashback', 'hồi tưởng, ký ức (xám mờ)'),
}

_SLUG = re.compile(r'^[a-z0-9_]{1,48}$')


class CatalogError(ValueError):
    pass


class Catalog:
    def __init__(self, pack: Path = PACK):
        self.pack = Path(pack)
        data = json.loads((self.pack / 'catalog' / 'panda.json').read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise CatalogError('Unsupported meme catalog version')
        self.items = {}
        for item in data['items']:
            self.items[item['id']] = {**item, 'path': self.pack / 'catalog' / item['file']}
        library = self.pack / 'catalog' / 'library.json'  # objects imported from new/ by scripts/import_meme_library.py
        if library.is_file():
            try:
                extra = json.loads(library.read_text(encoding='utf-8')).get('items', [])
            except ValueError:
                extra = []
            for item in extra:
                path = self.pack / 'catalog' / str(item.get('file', ''))
                if item.get('kind') in ('prop', 'fx') and _SLUG.match(str(item.get('id', ''))) and item['id'] not in self.items and path.is_file():
                    self.items[item['id']] = {**item, 'path': path}
        self.backgrounds = {}
        for ident, (top, bottom, style, tags) in PROCEDURAL.items():
            self.backgrounds[ident] = {'id': ident, 'kind': 'bg', 'source': 'procedural', 'tags': tags,
                                       'colors': (top, bottom), 'style': style}
        library = self.pack / 'new'
        if library.is_dir():
            for path in sorted(library.glob('bg_*.png')) + sorted(library.glob('bg_*.jpg')):
                ident = path.stem.lower()
                if not _SLUG.match(ident) or ident in self.backgrounds:
                    continue
                self.backgrounds[ident] = {'id': ident, 'kind': 'bg', 'source': 'file', 'path': path,
                                           'tags': ident[3:].replace('_', ' ')}

    # ---- queries -------------------------------------------------------------------------
    def ids(self, *kinds):
        return [i for i, item in self.items.items() if item['kind'] in kinds]

    def kind(self, ident):
        item = self.items.get(ident)
        return item['kind'] if item else None

    def describe_for_prompt(self):
        """Compact catalog listing for the script writer: id = meaning."""
        def block(kinds):
            return '\n'.join(f"- {i}: {self.items[i]['tags']}" for i in self.ids(*kinds))
        backgrounds = '\n'.join(f"- {b['id']}: {b['tags']}" for b in self.backgrounds.values())
        return ('POSES (full body, for wide shots):\n' + block(['pose']) +
                '\n\nHALF (waist-up, for medium shots):\n' + block(['half']) +
                '\n\nFACES (big head reaction, for close shots):\n' + block(['face']) +
                '\n\nFX (comic effects):\n' + block(['fx']) +
                '\n\nPROPS (objects):\n' + block(['prop']) +
                '\n\nBACKGROUNDS:\n' + backgrounds)

    def fingerprint(self):
        """Changes whenever the usable asset set changes (render cache key)."""
        parts = [str(CATALOG_VERSION)]
        for ident in sorted(self.items):
            parts.append(ident + ':' + str(self.items[ident]['size']))
        for ident in sorted(self.backgrounds):
            b = self.backgrounds[ident]
            if b['source'] == 'file':
                stat = Path(b['path']).stat()
                parts.append(ident + ':' + str(stat.st_size) + ':' + str(int(stat.st_mtime)))
            else:
                parts.append(ident)
        import hashlib
        return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]

    # ---- images --------------------------------------------------------------------------
    def sprite(self, ident) -> Image.Image:
        item = self.items.get(ident)
        if not item:
            raise CatalogError('Unknown meme asset: ' + str(ident))
        return _load_rgba(str(item['path']))

    def background(self, ident, size) -> Image.Image:
        info = self.backgrounds.get(ident)
        if not info:
            raise CatalogError('Unknown meme background: ' + str(ident))
        width, height = size
        if info['source'] == 'file':
            return _cover(_load_rgb(str(info['path'])), width, height)
        return procedural_background(ident, width, height)


@lru_cache(maxsize=256)
def _load_rgba(path):
    with Image.open(path) as image:
        return image.convert('RGBA')


@lru_cache(maxsize=64)
def _load_rgb(path):
    with Image.open(path) as image:
        return image.convert('RGB')


def _cover(image, width, height):
    scale = max(width / image.width, height / image.height)
    resized = image.resize((max(width, round(image.width * scale)), max(height, round(image.height * scale))), Image.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _gradient(width, height, top, bottom):
    column = Image.new('RGB', (1, height))
    for y in range(height):
        f = y / max(1, height - 1)
        column.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * f) for i in range(3)))
    return column.resize((width, height))


@lru_cache(maxsize=32)
def procedural_background(ident, width, height):
    top, bottom, style, _ = PROCEDURAL[ident]
    image = _gradient(width, height, top, bottom)
    draw = ImageDraw.Draw(image)
    floor = int(height * 0.74)
    if style == 'plain':
        draw.rectangle([0, floor, width, height], fill=tuple(max(0, c - 18) for c in bottom))
    elif style == 'room':
        wall = top
        draw.rectangle([0, 0, width, floor], fill=wall)
        draw.rectangle([0, floor, width, height], fill=bottom)
        draw.line([0, floor, width, floor], fill=(40, 30, 25), width=4)
        for x in range(-width, width * 2, 90):  # floor boards
            draw.line([x, height, x + (width / 2 - x) * 0.35, floor], fill=tuple(max(0, c - 28) for c in bottom), width=2)
        window = (int(width * 0.12), int(height * 0.18), int(width * 0.42), int(height * 0.48))
        sky = (160, 210, 250) if ident == 'room_day' else (20, 26, 60)
        draw.rectangle(window, fill=sky, outline=(40, 30, 25), width=5)
        mid_x = (window[0] + window[2]) // 2
        mid_y = (window[1] + window[3]) // 2
        draw.line([mid_x, window[1], mid_x, window[3]], fill=(40, 30, 25), width=4)
        draw.line([window[0], mid_y, window[2], mid_y], fill=(40, 30, 25), width=4)
        if ident == 'room_night':
            draw.ellipse([window[2] - 60, window[1] + 18, window[2] - 26, window[1] + 52], fill=(250, 240, 180))
    elif style == 'outdoor':
        horizon = int(height * 0.66)
        draw.rectangle([0, horizon, width, height], fill=bottom)
        draw.line([0, horizon, width, horizon], fill=(40, 70, 30), width=4)
        for cx, cy, r in ((width * 0.2, height * 0.18, 34), (width * 0.68, height * 0.12, 44)):
            for dx in (-r, 0, r):
                draw.ellipse([cx + dx - r, cy - r * 0.7, cx + dx + r, cy + r * 0.7], fill=(255, 255, 255), outline=(60, 60, 60), width=3)
        draw.ellipse([width * 0.8, height * 0.05, width * 0.8 + 70, height * 0.05 + 70], fill=(255, 220, 90), outline=(60, 50, 20), width=3)
    elif style == 'night':
        import random
        rng = random.Random(7)
        for _ in range(70):
            x, y = rng.randrange(width), rng.randrange(int(height * 0.65))
            r = rng.choice((1, 1, 2, 3))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 250, 220))
        draw.ellipse([width * 0.72, height * 0.08, width * 0.72 + 80, height * 0.08 + 80], fill=(250, 240, 190))
        draw.rectangle([0, floor, width, height], fill=bottom)
    elif style == 'rays':
        cx, cy = width / 2, height * 0.45
        radius = math.hypot(width, height)
        light = tuple(min(255, c + 25) for c in top)
        for k in range(24):
            a0 = 2 * math.pi * k / 24
            a1 = a0 + math.pi / 24
            draw.polygon([(cx, cy), (cx + radius * math.cos(a0), cy + radius * math.sin(a0)),
                          (cx + radius * math.cos(a1), cy + radius * math.sin(a1))], fill=light)
    elif style == 'flashback':
        draw.rectangle([0, floor, width, height], fill=tuple(c - 20 for c in bottom))
        image = image.filter(ImageFilter.GaussianBlur(2))
        draw = ImageDraw.Draw(image)
        for inset in range(0, min(70, min(width, height) // 2 - 8), 7):  # vignette
            shade = 120 + inset
            draw.rectangle([inset, inset, width - inset, height - inset], outline=(shade, shade, shade), width=7)
    return image


def refresh_library(pack: Path = PACK):
    """Re-import prop_/fx_ drawings dropped into new/ when they are newer than the library index."""
    new = Path(pack) / 'new'
    index = Path(pack) / 'catalog' / 'library.json'
    files = [*new.glob('prop_*.png'), *new.glob('fx_*.png')] if new.is_dir() else []
    if not files or (index.is_file() and index.stat().st_mtime >= max(f.stat().st_mtime for f in files)):
        return False
    import importlib.util
    spec = importlib.util.spec_from_file_location('import_meme_library', ROOT / 'scripts' / 'import_meme_library.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(pack)
    return True


def load_catalog() -> Catalog:
    return Catalog()
