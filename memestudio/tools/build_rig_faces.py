"""Split the panda expression heads into ONE blank head + separate face layers with measured landmarks.

Source: memestudio/assets/rig/source/faces_fx  (#5 blank front head, #9-#18 expressions; originally copied from
        the old Meme_Animation_Asset_Pack/Panda pack, removed 2026-11-06; this folder is now the only source).
Output: memestudio/assets/rig/faces/
  head_base.png         blank head #5 without the little neck stubs
  face_<name>.png       face features only (eyes, brows, nose, mouth, tears), same canvas as head_base
  faces.json            head chin pivot + per-face landmarks (eyes, nose, mouth) in head_base pixels
  preview_landmarks.jpg every face on the base head with its landmarks marked

Every face is aligned to the base head by its head interior (convex hull of the white face area): same width,
same centre. Face accessories (glasses, moustache...) are then placed per face from its landmarks, so a
moustache follows the mouth when the expression changes.
Run from memestudio/:  python tools/build_rig_faces.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MS = Path(__file__).resolve().parents[1]
SRC = MS / 'assets' / 'rig' / 'source' / 'faces_fx'
OUT = MS / 'assets' / 'rig' / 'faces'
BASE = 5
FACES = {9: 'noi', 10: 'lo', 11: 'gian', 12: 'soc', 13: 'khoc', 14: 'buon', 15: 'cuoi', 16: 'cuoi_deu',
         17: 'ngap', 18: 'chu_moi'}


def hull(points):
    pts = sorted(set(points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def load(n):
    """Image, rgba array, luminance and the head interior (convex hull of the white face area)."""
    im = Image.open(SRC / f'component_{n:03}.png').convert('RGBA')
    a = np.asarray(im).astype(int)
    lum = a[..., :3].mean(-1)
    white = (lum > 200) & (a[..., 3] > 128)
    h, w = lum.shape
    ys, xs = np.where(white)
    i = int(np.argmin((xs - w / 2) ** 2 + (ys - h * 0.25) ** 2))
    region = Image.fromarray((white * 255).astype('uint8')).copy()
    ImageDraw.floodfill(region, (int(xs[i]), int(ys[i])), 128)
    ys, xs = np.where(np.array(region) == 128)
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).polygon(hull(list(zip(xs.tolist(), ys.tolist()))), fill=255)
    return im, a, lum, np.array(mask) > 128


def bbox(mask):
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# Feature components of each aligned face (index = scan order of blobs with >= 6 px at alpha > 150), picked
# by eye on a numbered overlay. Eyes: 'c' = blob centre, 'b' = bottom of a blob where brow and eye are merged.
# nose None = nose merged with laugh lines; the nose bottom is then taken 3 px above the mouth.
FEATURES = {
    'noi': {'eyes': [(2, 'c'), (3, 'c')], 'nose': [4, 5], 'mouth': [6, 7]},
    'lo': {'eyes': [(1, 'b'), (2, 'c')], 'nose': [3, 4], 'mouth': [5, 6]},
    'gian': {'eyes': [(0, 'b'), (1, 'b')], 'nose': [2, 3], 'mouth': [4, 5]},
    'soc': {'eyes': [(2, 'c'), (3, 'c')], 'nose': [8, 6, 7], 'mouth': [9]},
    'khoc': {'eyes': [(1, 'b'), (0, 'b')], 'nose': [5, 7], 'mouth': [8, 9]},
    'buon': {'eyes': [(1, 'b'), (2, 'c')], 'nose': [4, 3], 'mouth': [5, 6]},
    'cuoi': {'eyes': [(2, 'c'), (3, 'c')], 'nose': None, 'mouth': [5, 6]},
    'cuoi_deu': {'eyes': [(0, 'b'), (1, 'b')], 'nose': [2, 3], 'mouth': [4, 5]},
    'ngap': {'eyes': [(3, 'c'), (2, 'c')], 'nose': [4], 'mouth': [5]},
    'chu_moi': {'eyes': [(3, 'c'), (2, 'c')], 'nose': [4], 'mouth': [5]},
}


def components(alpha):
    """Connected blobs (8-neighbour) of alpha > 150 in scan order; blobs under 6 px are dropped."""
    from collections import deque
    mask = alpha > 150
    h, w = mask.shape
    seen = np.zeros((h, w), bool)
    blobs = []
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not seen[y, x]:
                queue, pts = deque([(y, x)]), []
                seen[y, x] = True
                while queue:
                    cy, cx = queue.popleft()
                    pts.append((cy, cx))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                queue.append((ny, nx))
                if len(pts) >= 6:
                    blobs.append(np.array(pts))
    return blobs


def landmarks(alpha, spec):
    blobs = components(alpha)
    box = lambda b: (int(b[:, 1].min()), int(b[:, 0].min()), int(b[:, 1].max()), int(b[:, 0].max()))
    eyes = []
    for idx, mode in spec['eyes']:
        b = blobs[idx]
        if mode == 'c':
            eyes.append([round(float(b[:, 1].mean()), 1), round(float(b[:, 0].mean()), 1)])
        else:
            bottom = box(b)[3]
            low = b[b[:, 0] >= bottom - 7]
            eyes.append([round(float(low[:, 1].mean()), 1), round(bottom - 3.0, 1)])
    mouth_boxes = [box(blobs[i]) for i in spec['mouth']]
    m = (min(b[0] for b in mouth_boxes), min(b[1] for b in mouth_boxes), max(b[2] for b in mouth_boxes), max(b[3] for b in mouth_boxes))
    if spec['nose']:
        nb = [box(blobs[i]) for i in spec['nose']]
        nose = [round((nb[0][0] + nb[0][2]) / 2, 1), max(b[3] for b in nb)]
    else:
        nose = [round((m[0] + m[2]) / 2, 1), m[1] - 3]
    return {'eye_l': eyes[0], 'eye_r': eyes[1], 'eye_y': round((eyes[0][1] + eyes[1][1]) / 2, 1),
            'nose_bottom': nose, 'mouth_top': m[1], 'mouth_bottom': m[3], 'mouth_x': round((m[0] + m[2]) / 2, 1),
            'mouth_width': m[2] - m[0]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base_img, _, _, base_in = load(BASE)
    B = bbox(base_in)
    head = base_img.copy()
    px = head.load()
    for y in range(B[3] + 5, head.height):          # drop the two little neck stubs under the chin
        for x in range(head.width):
            px[x, y] = (0, 0, 0, 0)
    head.save(OUT / 'head_base.png')
    data = {'version': 1, 'head': {'file': 'head_base.png', 'size': head.size, 'interior': B,
                                   'chin': [round((B[0] + B[2]) / 2, 1), B[3] + 4]}, 'faces': {}}
    cards = []
    for n, name in FACES.items():
        im, a, lum, inside = load(n)
        inner = np.array(Image.fromarray((inside * 255).astype('uint8')).filter(ImageFilter.MinFilter(7))) > 128
        alpha = np.clip((232 - lum) / 45, 0, 1) * inner          # dark strokes inside the outline = the face
        layer = np.zeros_like(a)
        layer[..., :3] = a[..., :3]
        layer[..., 3] = (alpha * 255).astype(int)
        I = bbox(inside)
        k = (B[2] - B[0]) / (I[2] - I[0])
        small = Image.fromarray(layer.astype('uint8'), 'RGBA')
        small = small.resize((round(small.width * k), round(small.height * k)), Image.LANCZOS)
        face = Image.new('RGBA', head.size, (0, 0, 0, 0))
        face.alpha_composite(small, (round((B[0] + B[2]) / 2 - (I[0] + I[2]) / 2 * k),
                                     round((B[1] + B[3]) / 2 - (I[1] + I[3]) / 2 * k)))
        face.save(OUT / f'face_{name}.png')
        marks = landmarks(np.asarray(face.getchannel('A')), FEATURES[name])
        # Lip sync: split the mouth blobs (grown 3 px to take the soft lip edge) into their own layer.
        blobs = components(np.asarray(face.getchannel('A')))
        grow = np.zeros(face.size[::-1], np.uint8)
        for i in FEATURES[name]['mouth']:
            grow[blobs[i][:, 0], blobs[i][:, 1]] = 255
        mouth_mask = np.asarray(Image.fromarray(grow).filter(ImageFilter.MaxFilter(7))).astype(float) / 255
        rgba = np.asarray(face).astype(float)
        mouth = rgba.copy()
        mouth[..., 3] *= mouth_mask
        rest = rgba.copy()
        rest[..., 3] *= 1 - mouth_mask
        Image.fromarray(mouth.astype('uint8'), 'RGBA').save(OUT / f'mouth_{name}.png')
        Image.fromarray(rest.astype('uint8'), 'RGBA').save(OUT / f'face_{name}_nomouth.png')
        data['faces'][name] = {'file': f'face_{name}.png', 'file_nomouth': f'face_{name}_nomouth.png',
                               'mouth_file': f'mouth_{name}.png', 'source': f'faces_fx/component_{n:03}.png',
                               'mouth_pivot': [marks['mouth_x'], marks['mouth_top']], **marks}
        card = head.copy()
        card.alpha_composite(face)
        card = card.resize((head.width * 3, head.height * 3), Image.LANCZOS)
        d = ImageDraw.Draw(card)
        dot = lambda x, y, c: d.ellipse((x * 3 - 5, y * 3 - 5, x * 3 + 5, y * 3 + 5), outline=c, width=3)
        dot(*marks['eye_l'], (0, 160, 255))
        dot(*marks['eye_r'], (0, 160, 255))
        dot(*marks['nose_bottom'], (0, 200, 0))
        d.line((marks['mouth_x'] * 3 - 30, marks['mouth_top'] * 3, marks['mouth_x'] * 3 + 30, marks['mouth_top'] * 3), fill=(255, 0, 0), width=3)
        d.line((marks['mouth_x'] * 3 - 30, marks['mouth_bottom'] * 3, marks['mouth_x'] * 3 + 30, marks['mouth_bottom'] * 3), fill=(255, 120, 0), width=3)
        d.text((8, 8), name, fill=(0, 0, 0))
        cards.append(card)
    (OUT / 'faces.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    w, h = cards[0].size
    sheet = Image.new('RGB', (w * 5, h * 2), (210, 200, 180))
    for i, card in enumerate(cards):
        sheet.paste(card, ((i % 5) * w, (i // 5) * h), card)
    sheet.save(OUT / 'preview_landmarks.jpg', quality=88)
    print(json.dumps({k: (v['eye_y'], v['nose_bottom'][1], v['mouth_top'], v['mouth_bottom']) for k, v in data['faces'].items()}))


if __name__ == '__main__':
    main()
