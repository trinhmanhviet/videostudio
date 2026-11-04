"""Cut the ChatGPT wardrobe sheets into rig parts and fit them to the panda rig.

Sheets live in memestudio/assets/rig/sheets (transparent PNG grids drawn in the ChatGPT app
against the torso template rig/base/torso_core.png and the blank head faces_fx #5). Output:
  rig/wardrobe/<kind>/<id>.png   full-resolution crops
  rig/wardrobe/wardrobe.json     per item: kind, file, anchor (item px), place (rig units), scale (units per px)
  rig/wardrobe/preview_*.png     every item composited on the rig for review

Rig coordinates (same as the HyperFrames rig): origin = hip, units = rig-sheet pixels. Torso top centre is
(1, -56); the neck joint is (3, -52); the head is rig/faces/head_base.png + a face layer, scaled 0.6372 with the
chin on the neck. Hair/hats sit at one place on the head; face items are placed per face from its landmarks.
Run from memestudio/:  python tools/import_rig_wardrobe.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

MS = Path(__file__).resolve().parents[1]
RIG = MS / 'assets' / 'rig'
OUT = RIG / 'wardrobe'

# Costume sheets: 3 x 2 grids drawn on the torso template, all at the same scale.
COSTUMES = {
    'sheet_C1_thuong_ngay.png': ['ao_ba_lo_trang', 'ao_phong_xanh', 'so_mi_ca_vat', 'so_mi_caro', 'ao_len_nau', 'ao_khoac_da'],
    'sheet_C2_nghe_nghiep.png': ['blouse_bac_si', 'ao_cong_nhan', 'tap_de_dau_bep', 'vest_den', 'ao_bao_ve', 'ao_ba_ba_nau'],
    'sheet_C3_hoc_sinh_the_thao.png': ['so_mi_hoc_sinh', 'ao_da_bong', 'hoodie_xam', 'ao_mua_vang', 'ao_phao_den', 'ao_the_duc'],
    'sheet_C4_ao_nu.png': ['ao_hoa_hong', 'ao_ba_ba_hoa', 'so_mi_co_no', 'ao_len_co_lo', 'ao_hai_day', 'cardigan_be'],
    'sheet_C5_vay.png': ['vay_hoa_dai', 'dam_do', 'ao_dai_trang', 'vay_yem', 'dam_ngu_hong', 'vay_cuoi'],
}
DRESS_SHEETS = {'sheet_C5_vay.png'}
TORSO_TOP = (1.0, -56.0)        # rig units: top centre of torso_core
TORSO_HEIGHT = 55.0             # torso_core height in rig units (bust y 85..140)

# Heads: ONE blank head (rig/faces/head_base.png, from faces_fx #5) + swappable face layers with landmarks
# (scripts/build_rig_faces.py). Head pixels are scaled by HEAD_SCALE with the chin on the neck joint; the size
# matches the old expression heads (#9 interior 123 px x 0.72 = base interior 139 px x 0.6372).
FACES = json.loads((RIG / 'faces' / 'faces.json').read_text(encoding='utf-8'))
HEAD_CHIN = tuple(FACES['head']['chin'])
HEAD_SCALE = 0.6372
NECK = (3.0, -52.0)
# Hair and hats: same place on every face. id, target width (head px), anchor ('top'|'bottom'|'center' or a
# 0..1 fraction of the item height), anchor point (head px, head_base frame; head centre x = 86.5).
HEAD_SHEETS = {
    'sheet_A1_toc.png': ('hair', 4, [
        ('toc_xoan_ngan', 165, 'top', (86.5, -6)), ('toc_dai_thang', 160, 'top', (86.5, -9)), ('toc_bui_cao', 158, 'top', (86.5, -24)),
        ('toc_hui_cua', 156, 'top', (86.5, 0)), ('toc_dung_nguoc', 158, 'top', (86.5, -16)), ('hoi_toc_bac', 165, 'top', (86.5, 14)),
        ('toc_tet_bim', 160, 'top', (86.5, -9)), ('toc_mai_ngo', 158, 'top', (86.5, -9))]),
    'sheet_A2_mu.png': ('hat', 4, [
        ('non_la', 215, 0.42, (86.5, 37)), ('mu_bao_hiem', 165, 0.6, (86.5, 55)), ('mu_luoi_trai', 158, 'bottom', (86.5, 55)),
        ('mu_len', 158, 'bottom', (86.5, 52)), ('mu_dau_bep', 136, 'bottom', (86.5, 48)), ('mu_coi', 181, 'bottom', (86.5, 59)),
        ('vuong_mien', 102, 'bottom', (86.5, 32)), ('bang_do', 158, 'center', (86.5, 37))]),
    # face items: placed per face from its landmarks by face_place()
    'sheet_A3_do_deo_mat.png': ('face', 4, [(i, None, None, None) for i in (
        'kinh_ram', 'kinh_can', 'rau_mep', 'rau_quai_non', 'rau_de', 'khau_trang', 'bang_ca_nhan', 'ma_hong')]),
}


def face_place(ident, lm, img):
    """anchor (item px), at (head px), scale (head px per item px), rotation (deg) of a face item on one face."""
    import math
    (lx, ly), (rx, ry) = lm['eye_l'], lm['eye_r']
    mid = ((lx + rx) / 2, (ly + ry) / 2)
    d = math.hypot(rx - lx, ry - ly)
    tilt = math.degrees(math.atan2(ry - ly, rx - lx))
    nose_y = lm['nose_bottom'][1]
    mx, mt, mb, mw = lm['mouth_x'], lm['mouth_top'], lm['mouth_bottom'], lm['mouth_width']
    w, h = img.size
    centre = [w / 2, h / 2]
    rules = {
        'kinh_ram': (centre, (mid[0], mid[1] + 1.5), 2.15 * d, tilt),
        'kinh_can': (centre, (mid[0], mid[1] + 1.0), 2.1 * d, tilt),
        'rau_mep': (centre, (mx, (nose_y + mt) / 2 + 0.5), max(0.95 * mw, 30), tilt * 0.5),
        'rau_quai_non': (centre, (mx, (mt + mb) / 2 + 6), 138, 0),
        'rau_de': ([w / 2, 0], (mx, mb + 1), max(0.55 * mw, 24), 0),
        'khau_trang': (centre, (mx, (nose_y - 6 + mb + 4) / 2), 112, tilt * 0.5),
        'bang_ca_nhan': (centre, (rx + 4, ry - 16), 45, 0),
        'ma_hong': (centre, (mid[0], mid[1] + 0.6 * (mt - mid[1])), 1.65 * d, tilt),
    }
    anchor, at, width, rot = rules[ident]
    return {'anchor': [round(v, 2) for v in anchor], 'at': [round(v, 2) for v in at], 'scale': round(width / w, 5),
            'rotation': round(rot, 2)}


def bands(profile, expected, min_gap=6):
    """Split a 1-D occupancy profile into `expected` runs by closing the smallest gaps first."""
    filled = profile > 0
    runs, start = [], None
    for i, on in enumerate(filled):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(filled)])
    runs = [r for r in runs if r[1] - r[0] >= 3]
    if len(runs) > expected:             # pieces of one item (two blush dots): group runs by equal grid cell
        lo, hi = runs[0][0], runs[-1][1]
        cells = {}
        for r in runs:
            cell = min(expected - 1, int(((r[0] + r[1]) / 2 - lo) / (hi - lo) * expected))
            cells.setdefault(cell, []).append(r)
        if len(cells) == expected:
            runs = [[min(r[0] for r in rs), max(r[1] for r in rs)] for _, rs in sorted(cells.items())]
    while len(runs) > expected:          # fallback: merge the closest pair
        gaps = [runs[i + 1][0] - runs[i][1] for i in range(len(runs) - 1)]
        i = int(np.argmin(gaps))
        runs[i:i + 2] = [[runs[i][0], runs[i + 1][1]]]
    if len(runs) != expected:
        raise ValueError(f'expected {expected} bands, found {len(runs)}')
    return runs


def cut(sheet: Path, cols: int, rows: int):
    im = Image.open(sheet).convert('RGBA')
    alpha = np.asarray(im.getchannel('A')) > 40
    items = []
    for y0, y1 in bands(alpha.sum(axis=1), rows):
        row = alpha[y0:y1]
        for x0, x1 in bands(row.sum(axis=0), cols):
            box = im.crop((x0, y0, x1, y1))
            bb = box.getchannel('A').point(lambda v: 255 if v > 40 else 0).getbbox()
            items.append(box.crop(bb))
    return items


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = {'version': 2, 'rig': {'torso_top': TORSO_TOP, 'neck': NECK, 'head_scale': HEAD_SCALE,
                                     'head': 'faces/head_base.png', 'head_chin': HEAD_CHIN,
                                     'faces': {k: 'faces/' + v['file'] for k, v in FACES['faces'].items()}}, 'items': []}
    # costumes: one shared scale from the median top height of the shirt sheets
    cut_costumes = {name: cut(RIG / 'sheets' / name, 3, 2) for name in COSTUMES}
    heights = [img.height for name, imgs in cut_costumes.items() if name not in DRESS_SHEETS for img in imgs]
    k = TORSO_HEIGHT / float(np.median(heights))
    shoulder = lambda img: img.getchannel('A').crop((0, int(img.height * 0.12), img.width, int(img.height * 0.12) + 1)).getbbox()
    width_at = lambda imgs: float(np.median([(lambda b: b[2] - b[0])(shoulder(i)) for i in imgs]))
    tops = [i for n, imgs in cut_costumes.items() if n not in DRESS_SHEETS for i in imgs]
    dresses = [i for n, imgs in cut_costumes.items() if n in DRESS_SHEETS for i in imgs]
    k_dress = k * width_at([t.crop((0, 0, t.width, int(t.height * 0.4))) for t in tops]) / width_at([d.crop((0, 0, d.width, int(d.height * 0.25))) for d in dresses]) if dresses else k
    for name, ids in COSTUMES.items():
        for ident, img in zip(ids, cut_costumes[name]):
            path = OUT / 'costume' / f'{ident}.png'
            path.parent.mkdir(exist_ok=True)
            img.save(path)
            catalog['items'].append({'id': ident, 'kind': 'costume', 'file': f'costume/{ident}.png', 'size': img.size,
                                     'anchor': [img.width / 2, 0], 'place': list(TORSO_TOP),
                                     'scale': round(k_dress if name in DRESS_SHEETS else k, 5),
                                     'hides_legs': name in DRESS_SHEETS, 'sheet': name})
    for name, (kind, cols, specs) in HEAD_SHEETS.items():
        imgs = cut(RIG / 'sheets' / name, cols, 2)
        for (ident, width, mode, point), img in zip(specs, imgs):
            path = OUT / kind / f'{ident}.png'
            path.parent.mkdir(exist_ok=True)
            img.save(path)
            entry = {'id': ident, 'kind': kind, 'file': f'{kind}/{ident}.png', 'size': img.size, 'frame': 'head', 'sheet': name}
            if kind == 'face':
                entry['per_face'] = {f: face_place(ident, lm, img) for f, lm in FACES['faces'].items()}
            else:
                fy = mode if isinstance(mode, float) else {'top': 0.0, 'bottom': 1.0, 'center': 0.5}[mode]
                entry.update(anchor=[img.width / 2, round(img.height * fy, 2)], at=list(point),
                             scale=round(width / img.width, 5), rotation=0)
            catalog['items'].append(entry)
    (OUT / 'wardrobe.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"{len(catalog['items'])} items, costume scale {k:.4f} units/px")
    previews(catalog)


# ------------------------------------------------------------------ preview compositor (Pillow, review only)
def paste(canvas, img, anchor, pos, scale, origin, S, flip=False, rotation=0.0):
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        anchor = (img.width - anchor[0], anchor[1])
    if rotation:
        r = int((img.width ** 2 + img.height ** 2) ** 0.5) + 2
        pad = Image.new('RGBA', (2 * r, 2 * r), (0, 0, 0, 0))
        pad.alpha_composite(img, (round(r - anchor[0]), round(r - anchor[1])))
        img, anchor = pad.rotate(-rotation, resample=Image.BICUBIC), (r, r)
    f = scale * S
    w, h = max(1, round(img.width * f)), max(1, round(img.height * f))
    small = img.resize((w, h), Image.LANCZOS)
    x = origin[0] + pos[0] * S - anchor[0] * f
    y = origin[1] + pos[1] * S - anchor[1] * f
    canvas.alpha_composite(small, (round(x), round(y)))


def head_item(item, face):
    """(anchor, body position, units per item px, rotation) of a head-frame item for the shown face."""
    p = item['per_face'][face] if 'per_face' in item else item
    pos = (NECK[0] + (p['at'][0] - HEAD_CHIN[0]) * HEAD_SCALE, NECK[1] + (p['at'][1] - HEAD_CHIN[1]) * HEAD_SCALE)
    return p['anchor'], pos, p['scale'] * HEAD_SCALE, p.get('rotation', 0)


def character(costume=None, accessories=(), face='noi', S=3.0):
    canvas = Image.new('RGBA', (int(150 * S), int(270 * S)), (236, 230, 214, 255))
    origin = (75 * S, 180 * S)
    rig = lambda n: Image.open(RIG / 'parts' / f'component_{n:03}.png').convert('RGBA')
    if not (costume and costume.get('hides_legs')):
        paste(canvas, rig(40), (66.5, 40), (0, 0), 0.72, origin, S)
    arm = rig(17)
    paste(canvas, arm, (19, 10), (-29, -52), 0.66, origin, S, flip=True)
    paste(canvas, arm, (19, 10), (31, -52), 0.66, origin, S)
    if costume:
        paste(canvas, Image.open(OUT / costume['file']).convert('RGBA'), costume['anchor'], costume['place'], costume['scale'], origin, S)
    else:
        paste(canvas, Image.open(RIG / 'base' / 'torso_core.png').convert('RGBA'), (58, 141), (0, 0), 1.0, origin, S)
    paste(canvas, Image.open(RIG / 'faces' / 'head_base.png').convert('RGBA'), HEAD_CHIN, NECK, HEAD_SCALE, origin, S)
    paste(canvas, Image.open(RIG / 'faces' / f'face_{face}.png').convert('RGBA'), HEAD_CHIN, NECK, HEAD_SCALE, origin, S)
    for item in accessories:
        anchor, pos, scale, rot = head_item(item, face)
        paste(canvas, Image.open(OUT / item['file']).convert('RGBA'), anchor, pos, scale, origin, S, rotation=rot)
    return canvas


def grid(cards, cols, path):
    w, h = cards[0].size
    sheet = Image.new('RGBA', (w * cols, h * ((len(cards) + cols - 1) // cols)), (255, 255, 255, 255))
    for i, card in enumerate(cards):
        sheet.alpha_composite(card, ((i % cols) * w, (i // cols) * h))
    sheet.convert('RGB').save(path, quality=88)


def previews(catalog):
    items = catalog['items']
    grid([character(c) for c in items if c['kind'] == 'costume'], 6, OUT / 'preview_costume.jpg')
    grid([character(None, [a]) for a in items if a['kind'] != 'costume'], 8, OUT / 'preview_accessories.jpg')
    by_id = {i['id']: i for i in items}
    # sample cast: costume, accessories (drawn in order), expression head
    cast = [('ao_ba_lo_trang', ['hoi_toc_bac', 'rau_mep'], 'gian'),
            ('ao_ba_ba_hoa', ['toc_xoan_ngan'], 'cuoi_deu'),
            ('so_mi_hoc_sinh', ['toc_hui_cua'], 'cuoi'),
            ('blouse_bac_si', ['kinh_can'], 'noi'),
            ('tap_de_dau_bep', ['mu_dau_bep'], 'soc'),
            ('vay_cuoi', ['toc_bui_cao', 'ma_hong'], 'chu_moi'),
            ('ao_ba_ba_nau', ['non_la'], 'ngap'),
            ('vest_den', ['kinh_ram'], 'cuoi_deu'),
            ('ao_cong_nhan', ['mu_bao_hiem'], 'khoc'),
            ('ao_da_bong', ['bang_do'], 'cuoi'),
            ('dam_do', ['toc_dai_thang'], 'buon'),
            ('ao_phao_den', ['mu_len', 'khau_trang'], 'lo')]
    grid([character(by_id[c], [by_id[a] for a in acc], face) for c, acc, face in cast if c in by_id], 6,
         OUT / 'preview_characters.jpg')
    # every face item on every face: the moustache must follow the mouth when the expression changes
    faces = list(FACES['faces'])
    grid([character(None, [a], f) for a in items if a['kind'] == 'face' for f in faces], len(faces),
         OUT / 'preview_face_items.jpg')


if __name__ == '__main__':
    main()
