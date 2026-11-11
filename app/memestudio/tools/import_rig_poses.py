"""Cut ChatGPT pose sheets into headless body sprites for the meme rig.

A sheet (memestudio/assets/rig/poses/sheets/<costume>.png) is a 5 x 2 grid of the same costume drawn without a
head on a white background, in the order of POSES, against the standing reference in poses/reference/.
Output per costume:
  poses/<costume>/<pose>.png   transparent crop
  poses/poses.json             per sprite: file, size, neck (px), ground (px), scale (rig units per px), head
  poses/preview_<costume>.png  every sprite with the rig head attached, next to the standing character

Rig coordinates match the HyperFrames rig: origin = hip, rig units; soles at GROUND_UNITS below the hip.
The neck point and head angle of each pose are set by eye in NECKS (fractions of the crop) and checked in the
preview; the scale is set per sheet so a pose reads the same size as the standing figure.
Run from memestudio/:  python tools/import_rig_poses.py
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MS = Path(__file__).resolve().parents[1]
POSES_DIR = MS / 'assets' / 'rig' / 'poses'
POSES = ['kneel', 'crawl', 'butt', 'lie_front', 'lie_back', 'sit', 'sit_ground', 'pick', 'fall', 'run']

# Per sheet: rig units per sheet pixel, and per pose the neck point (fraction of the crop) + head rotation
# (degrees, clockwise) + whether the face shows (False = back of the head). Filled in by eye from the preview.
GROUND_UNITS = 52.6
HEAD_SCALE, HEAD_CHIN = 0.6372, (86.5, 143)
SHEETS: dict[str, dict] = {
    'ao_ba_lo_trang': {'scale': 0.46, 'poses': {
        'kneel': {'neck': (0.6, 0.04)},
        'crawl': {'neck': (0.81, 0.07), 'rotation': 15},
        'butt': {'neck': (0.86, 0.08), 'rotation': 35},
        'lie_front': {'neck': (0.6, 0.32), 'rotation': 90, 'face': False, 'lift': 24, 'stub': False},
        'lie_back': {'neck': (0.04, 0.5), 'rotation': -90, 'lift': 38, 'stub': False},
        'sit': {'neck': (0.5, 0.04), 'seat': (0.3, 0.6)},
        'sit_ground': {'neck': (0.5, 0.04)},
        'pick': {'neck': (0.88, 0.2), 'rotation': 60},
        'fall': {'neck': (0.42, 0.93), 'rotation': -90, 'lift': 40, 'stub': False},
        'run': {'neck': (0.58, 0.05), 'rotation': 8},
    }},
}
CANONICAL = 'ao_ba_lo_trang'      # every other sheet is drawn as "this exact sheet" in another costume
# Later sheets were drawn in the same chat as "the exact same sprite sheet" in another costume: same layout and
# neck points (checked in their previews).
for _costume in ('ao_phong_xanh', 'so_mi_hoc_sinh', 'ao_ba_ba_nau'):
    SHEETS[_costume] = SHEETS['ao_ba_lo_trang']


CHIN_INTO_BODY_UNITS = 4      # standing rig: the chin sits 4 units below the top of the torso (neck hidden)


def seat_neck(image: Image.Image, neck: tuple[float, float], rotation: float, scale: float) -> tuple[float, float]:
    """From the top of the drawn neck stub, walk into the body (against the head direction) until the outline
    widens into the shoulders, then go a little further: the rig head then covers the stub like a standing pose."""
    import math
    alpha = np.asarray(image.getchannel('A')) > 16
    h, w = alpha.shape
    r = math.radians(rotation)
    dx, dy = math.sin(r), -math.cos(r)                       # head direction (rotation clockwise from up)
    px, py = math.cos(r), math.sin(r)                         # across the neck

    def width(t):
        cx, cy = neck[0] - dx * t, neck[1] - dy * t
        if not (0 <= cx < w and 0 <= cy < h) or not alpha[int(cy), int(cx)]:
            return 0
        n = 0
        for sign in (1, -1):
            for s in range(1, 120):
                x, y = int(cx + sign * px * s), int(cy + sign * py * s)
                if not (0 <= x < w and 0 <= y < h) or not alpha[y, x]:
                    break
                n += 1
        return n + 1

    widths = [width(t) for t in range(0, 90)]
    stub = sorted(v for v in widths[3:12] if v) or [0]
    stub_w = stub[len(stub) // 2]
    base = next((t for t in range(8, 90) if widths[t] > 1.7 * stub_w), 12)
    depth = base + CHIN_INTO_BODY_UNITS / scale
    return neck[0] - dx * depth, neck[1] - dy * depth


def head_placement(item):
    """Neck position in rig units (origin = hip, sprite centred on x = 0, standing on the floor)."""
    k = item['scale']
    w, _ = item['size']
    nx, ny = item['neck']
    return ((nx - w / 2) * k, GROUND_UNITS - (item['ground'] - ny) * k - item.get('lift', 0))


def preview(costume, items):
    import sys
    sys.path.insert(0, str(MS / 'tools'))
    import import_rig_wardrobe as W
    wardrobe = {i['id']: i for i in json.loads((MS / 'assets/rig/wardrobe/wardrobe.json').read_text(encoding='utf-8'))['items']}
    S = 2.0
    cards = [W.character(wardrobe.get(costume), [], 'noi', S=S)]
    head = Image.open(MS / 'assets/rig/faces/head_base.png').convert('RGBA')
    face = Image.open(MS / 'assets/rig/faces/face_noi.png').convert('RGBA')
    for item in items:
        canvas = Image.new('RGBA', (int(260 * S), int(270 * S)), (236, 230, 214, 255))
        origin = (130 * S, 180 * S)
        sprite = Image.open(POSES_DIR / item['file']).convert('RGBA')
        W.paste(canvas, sprite, (item['size'][0] / 2, item['ground']), (0, GROUND_UNITS), item['scale'], origin, S)
        neck = head_placement(item)
        W.paste(canvas, head, HEAD_CHIN, neck, HEAD_SCALE, origin, S, rotation=item['head_rotation'])
        if item['face']:
            W.paste(canvas, face, HEAD_CHIN, neck, HEAD_SCALE, origin, S, rotation=item['head_rotation'])
        ImageDraw.Draw(canvas).line([(0, origin[1] + GROUND_UNITS * S), (canvas.width, origin[1] + GROUND_UNITS * S)], fill=(150, 120, 90, 255), width=2)
        cards.append(canvas)
    width = sum(c.width for c in cards)
    sheet = Image.new('RGB', (width, max(c.height for c in cards)), (255, 255, 255))
    x = 0
    for card in cards:
        sheet.paste(card.convert('RGB'), (x, 0)); x += card.width
    sheet.save(POSES_DIR / f'preview_{costume}.jpg', quality=88)


def background_mask(rgb: np.ndarray, threshold: int = 232) -> np.ndarray:
    """White pixels connected to the border = background (white clothing inside an outline is kept)."""
    h, w, _ = rgb.shape
    light = (rgb >= threshold).all(axis=2)
    bg = np.zeros((h, w), bool)
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if light[y, x] and not bg[y, x]:
                bg[y, x] = True
                queue.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if light[y, x] and not bg[y, x]:
                bg[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and light[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                queue.append((ny, nx))
    return bg


def components(mask: np.ndarray) -> list[tuple[int, int, int, int, int, float, float]]:
    """Connected foreground blobs: (area, top, bottom, left, right, centre y, centre x)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    blobs = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        queue, ys, xs = deque([(y0, x0)]), [], []
        while queue:
            y, x = queue.popleft()
            ys.append(y); xs.append(x)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        blobs.append((len(ys), min(ys), max(ys), min(xs), max(xs), sum(ys) / len(ys), sum(xs) / len(xs)))
    return blobs


def cut(sheet: Path, cols: int = 5, rows: int = 2) -> dict[str, Image.Image]:
    """Each pose = the blobs whose centre falls in its grid cell (figures may overhang a cell edge)."""
    rgb = np.asarray(Image.open(sheet).convert('RGB'))
    fg = ~background_mask(rgb)
    h, w = fg.shape
    small = fg[::2, ::2]                                   # labelling on half resolution is plenty for bboxes
    out = {}
    cells: dict[int, list] = {}
    for blob in components(small):
        area, top, bottom, left, right, cy, cx = blob
        if area < 30:
            continue                                        # specks
        cell = int(cy * 2 // (h / rows)) * cols + int(cx * 2 // (w / cols))
        cells.setdefault(cell, []).append(blob)
    for index, pose in enumerate(POSES):
        blobs = cells.get(index)
        if not blobs:
            continue
        top = max(0, min(b[1] for b in blobs) * 2 - 4); bottom = min(h, max(b[2] for b in blobs) * 2 + 6)
        left = max(0, min(b[3] for b in blobs) * 2 - 4); right = min(w, max(b[4] for b in blobs) * 2 + 6)
        # keep only this pose's blobs inside the crop (a neighbour's foot may reach into the box)
        keep = np.zeros((h, w), bool)
        for b in blobs:
            keep[b[1] * 2:b[2] * 2 + 2, b[3] * 2:b[4] * 2 + 2] = True
        alpha = (fg & keep).astype(np.uint8) * 255
        rgba = np.dstack([rgb, alpha])[top:bottom, left:right]
        out[pose] = Image.fromarray(np.ascontiguousarray(rgba), 'RGBA')
    return out


def ground_y(image: Image.Image) -> int:
    alpha = np.asarray(image.getchannel('A'))
    return int(np.nonzero(alpha.max(axis=1) > 16)[0].max())


def marked(image: Image.Image, step: float = 0.1) -> Image.Image:
    """Crop on a grey board with a 10% grid, to read neck points by eye."""
    board = Image.new('RGBA', image.size, (200, 200, 200, 255))
    board.alpha_composite(image)
    draw = ImageDraw.Draw(board)
    for k in range(1, int(1 / step)):
        x, y = round(image.width * k * step), round(image.height * k * step)
        draw.line([(x, 0), (x, image.height)], fill=(255, 0, 0, 110))
        draw.line([(0, y), (image.width, y)], fill=(0, 0, 255, 110))
    return board


def main():
    catalog = {'version': 1, 'poses': POSES, 'items': []}
    for sheet in sorted((POSES_DIR / 'sheets').glob('*.png')):
        costume = sheet.stem
        crops = cut(sheet)
        folder = POSES_DIR / costume
        folder.mkdir(parents=True, exist_ok=True)
        boards = []
        for pose, image in crops.items():
            image.save(folder / f'{pose}.png')
            boards.append(marked(image))
            sheet_spec = SHEETS.get(costume, SHEETS[CANONICAL])         # generated sheets copy the canonical layout
            spec = sheet_spec['poses'].get(pose)
            if spec:
                catalog['items'].append({
                    'costume': costume, 'pose': pose, 'file': f'{costume}/{pose}.png', 'size': list(image.size),
                    'neck': [round(v, 1) for v in (seat_neck(image, (spec['neck'][0] * image.width, spec['neck'][1] * image.height),
                                                               spec.get('rotation', 0), sheet_spec['scale'])
                                                     if spec.get('stub', True) else
                                                     (spec['neck'][0] * image.width, spec['neck'][1] * image.height))],
                    'ground': ground_y(image), 'scale': sheet_spec['scale'],
                    'head_rotation': spec.get('rotation', 0), 'face': spec.get('face', True), 'lift': spec.get('lift', 0),
                    'seat': [round(spec['seat'][0] * image.width, 1), round(spec['seat'][1] * image.height, 1)] if 'seat' in spec else None})
        width = sum(b.width for b in boards) + 10 * len(boards)
        strip = Image.new('RGBA', (width, max(b.height for b in boards)), (255, 255, 255, 255))
        x = 0
        for board in boards:
            strip.alpha_composite(board, (x, 0))
            x += board.width + 10
        strip.convert('RGB').save(POSES_DIR / f'marks_{costume}.png')
        preview(costume, [i for i in catalog['items'] if i['costume'] == costume])
    (POSES_DIR / 'poses.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"{len(catalog['items'])} pose sprites")


if __name__ == '__main__':
    main()
