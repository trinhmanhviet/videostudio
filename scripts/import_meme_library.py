"""Import newly drawn meme assets from assets/Meme_Animation_Asset_Pack/new/ into the catalog.

    python scripts/import_meme_library.py

- bg_<name>.png/jpg are used directly by the catalog (nothing to do here).
- Known sticker sheets (prop_food.png, fx_stickers.png, ... as named by scripts/make_meme_assets.py)
  are cut into single objects and named in grid order (left->right, top->bottom).
- Any other prop_<name>.png / fx_<name>.png holding exactly one object becomes item <name>.
A magenta (#FF00FF) or plain white backdrop is keyed out when the PNG has no transparency.
Sheets whose object count does not match the expected list are skipped and reported,
never guessed. Output: catalog/library/<id>.png + catalog/library.json (Pillow only).
"""
import json
import re
import sys
from collections import deque
from pathlib import Path

from PIL import Image

PACK = Path(__file__).resolve().parents[1] / 'assets' / 'Meme_Animation_Asset_Pack'

SHEETS = {
    'prop_furniture': ['plastic_stool', 'office_chair', 'small_table', 'sofa', 'bed', 'wardrobe', 'door_wood', 'window'],
    'prop_home': ['standing_fan', 'tv', 'floor_lamp', 'fridge', 'wall_clock', 'pillow', 'blanket', 'umbrella_open'],
    'prop_food': ['noodles', 'rice_plate', 'banh_mi', 'bubble_tea', 'coffee_cup', 'beer_can', 'water_bottle', 'birthday_cake'],
    'prop_kitchen_tech': ['cooking_pot', 'frying_pan', 'smartphone', 'laptop_open', 'headphones', 'tv_remote', 'phone_charger', 'game_controller'],
    'prop_study_office': ['book', 'notebook', 'pen', 'school_backpack', 'paper_stack', 'briefcase', 'desktop_computer', 'whiteboard'],
    'prop_vehicles': ['scooter', 'bicycle', 'car', 'bus', 'taxi', 'delivery_tricycle'],
    'prop_daily': ['paper_money', 'wallet', 'handbag', 'toilet_paper', 'toothbrush', 'medicine_box', 'gift_box', 'cardboard_box'],
    'fx_stickers': ['sweat_drop', 'question_mark', 'exclamation_mark', 'red_heart', 'broken_heart', 'star_ring', 'smoke_puff', 'lightning', 'water_splash'],
}
TAGS = {
    'plastic_stool': 'ghế nhựa', 'office_chair': 'ghế văn phòng', 'small_table': 'bàn nhỏ', 'sofa': 'ghế sofa', 'bed': 'giường',
    'wardrobe': 'tủ quần áo', 'door_wood': 'cửa gỗ', 'window': 'cửa sổ', 'standing_fan': 'quạt cây', 'tv': 'TV', 'floor_lamp': 'đèn cây',
    'fridge': 'tủ lạnh', 'wall_clock': 'đồng hồ treo tường', 'pillow': 'gối', 'blanket': 'chăn', 'umbrella_open': 'ô mở',
    'noodles': 'bát mì', 'rice_plate': 'đĩa cơm', 'banh_mi': 'bánh mì', 'bubble_tea': 'trà sữa', 'coffee_cup': 'cốc cà phê',
    'beer_can': 'lon bia', 'water_bottle': 'chai nước', 'birthday_cake': 'bánh sinh nhật', 'cooking_pot': 'nồi', 'frying_pan': 'chảo',
    'smartphone': 'điện thoại', 'laptop_open': 'laptop', 'headphones': 'tai nghe', 'tv_remote': 'điều khiển TV',
    'phone_charger': 'sạc điện thoại', 'game_controller': 'tay cầm game', 'book': 'sách', 'notebook': 'vở', 'pen': 'bút',
    'school_backpack': 'cặp sách', 'paper_stack': 'xấp giấy', 'briefcase': 'cặp tài liệu', 'desktop_computer': 'máy tính bàn',
    'whiteboard': 'bảng trắng', 'scooter': 'xe máy', 'bicycle': 'xe đạp', 'car': 'ô tô', 'bus': 'xe buýt', 'taxi': 'taxi',
    'delivery_tricycle': 'xe ba gác giao hàng', 'paper_money': 'tiền giấy', 'wallet': 'ví', 'handbag': 'túi xách',
    'toilet_paper': 'cuộn giấy vệ sinh', 'toothbrush': 'bàn chải', 'medicine_box': 'hộp thuốc', 'gift_box': 'hộp quà',
    'cardboard_box': 'thùng carton', 'sweat_drop': 'giọt mồ hôi', 'question_mark': 'dấu hỏi', 'exclamation_mark': 'dấu chấm than',
    'red_heart': 'trái tim', 'broken_heart': 'tim vỡ', 'star_ring': 'vòng sao chóng mặt', 'smoke_puff': 'làn khói',
    'lightning': 'tia sét', 'water_splash': 'nước bắn',
}
def _extra_sheets():
    """Sheets defined next to their prompts in make_meme_assets.py (single source of item order)."""
    import importlib.util
    path = Path(__file__).resolve().parent / 'make_meme_assets.py'
    try:
        spec = importlib.util.spec_from_file_location('make_meme_assets', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, 'SHEET_ITEMS', {})
    except Exception:
        return {}


for _sheet, _items in _extra_sheets().items():
    SHEETS.setdefault(_sheet, [ident for ident, _, _ in _items])
    for _ident, _, _tag in _items:
        TAGS.setdefault(_ident, _tag)

BIG = {'atm', 'wheelchair', 'buffalo', 'ladder', 'shopping_cart', 'kumquat_tree', 'beer_crate', 'guitar', 'speaker', 'sofa', 'bed', 'wardrobe', 'door_wood', 'window', 'fridge', 'scooter', 'bicycle', 'car', 'bus', 'taxi', 'delivery_tricycle', 'whiteboard', 'desktop_computer'}


def key_out(image):
    image = image.convert('RGBA')
    alpha = image.getchannel('A')
    if alpha.getextrema()[0] < 250:  # already has real transparency
        return image
    pixels = image.load()
    corner = image.getpixel((2, 2))[:3]
    magenta = corner[0] > 200 and corner[1] < 90 and corner[2] > 200
    white = min(corner) > 235
    if not (magenta or white):
        return None
    out = Image.new('RGBA', image.size)
    data = []
    for r, g, b, a in image.getdata():
        if magenta and r > 170 and g < 120 and b > 170 and abs(r - b) < 70:
            data.append((0, 0, 0, 0))
        elif white and min(r, g, b) > 238:
            data.append((0, 0, 0, 0))
        else:
            data.append((r, g, b, 255))
    out.putdata(data)
    return out


def components(image, step=4, min_cells=6):
    """Bounding boxes of opaque blobs, found on a coarse grid (fast, Pillow only)."""
    small = image.getchannel('A').resize((image.width // step, image.height // step), Image.BOX)
    w, h = small.size
    px = small.load()
    seen = [[False] * w for _ in range(h)]
    boxes = []
    for y in range(h):
        for x in range(w):
            if seen[y][x] or px[x, y] < 40:
                continue
            queue = deque([(x, y)])
            seen[y][x] = True
            x0 = x1 = x
            y0 = y1 = y
            cells = 0
            while queue:
                cx, cy = queue.popleft()
                cells += 1
                x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                for nx in range(cx - 2, cx + 3):  # 2-cell reach bridges thin gaps inside one drawing
                    for ny in range(cy - 2, cy + 3):
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and px[nx, ny] >= 40:
                            seen[ny][nx] = True
                            queue.append((nx, ny))
            if cells >= min_cells:
                boxes.append([x0 * step, y0 * step, (x1 + 1) * step, (y1 + 1) * step, cells])
    return boxes


def reading_order(boxes):
    boxes = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    rows = []
    for box in boxes:
        cy = (box[1] + box[3]) / 2
        if rows and abs(cy - rows[-1][0]) < (box[3] - box[1]) * 0.5:
            rows[-1][1].append(box)
        else:
            rows.append([cy, [box]])
    return [b for _, row in rows for b in sorted(row)]


GRIDS = {6: (2, 3), 8: (2, 4), 9: (3, 3)}  # columns, rows the sheet prompts ask for


def merge_by_grid(boxes, count, size):
    """Objects drawn in several pieces (a dot under a mark, a split heart): merge the pieces that fall in
    the same grid cell. Returns boxes in reading order, or None when the cells do not give `count` objects."""
    if count not in GRIDS:
        return None
    cols, rows = GRIDS[count]
    cells = {}
    for box in boxes:
        col = min(cols - 1, int((box[0] + box[2]) / 2 / (size[0] / cols)))
        row = min(rows - 1, int((box[1] + box[3]) / 2 / (size[1] / rows)))
        old = cells.get((row, col))
        cells[(row, col)] = box[:4] + [box[4]] if old is None else [min(old[0], box[0]), min(old[1], box[1]), max(old[2], box[2]), max(old[3], box[3]), old[4] + box[4]]
    if len(cells) != count:
        return None
    return [cells[key] for key in sorted(cells)]


def crop(image, box, pad=4):
    x0, y0, x1, y1 = max(0, box[0] - pad), max(0, box[1] - pad), min(image.width, box[2] + pad), min(image.height, box[3] + pad)
    piece = image.crop((x0, y0, x1, y1))
    bbox = piece.getchannel('A').point(lambda a: 255 if a > 20 else 0).getbbox()
    return piece.crop(bbox) if bbox else piece


def main(pack=PACK):
    pack = Path(pack)
    NEW, OUT = pack / 'new', pack / 'catalog' / 'library'
    OUT.mkdir(parents=True, exist_ok=True)
    existing_ids = set()
    panda = pack / 'catalog' / 'panda.json'
    if panda.is_file():
        existing_ids = {i['id'] for i in json.loads(panda.read_text(encoding='utf-8'))['items']}
    items, report = [], []
    for path in sorted(list(NEW.glob('prop_*.png')) + list(NEW.glob('fx_*.png'))):
        stem = path.stem.lower()
        kind = 'fx' if stem.startswith('fx_') else 'prop'
        with Image.open(path) as source:
            image = key_out(source)
        if image is None:
            report.append(f'{path.name}: no transparent/magenta/white backdrop, skipped')
            continue
        found = components(image)
        if not found:
            report.append(f'{path.name}: no objects found, skipped')
            continue
        largest = max(b[4] for b in found)
        boxes = [b for b in found if b[4] >= 0.08 * largest]  # drop specks and stray dots
        names = SHEETS.get(stem)
        if names is None:
            if len(boxes) != 1:
                report.append(f'{path.name}: {len(boxes)} objects but not a known sheet, skipped')
                continue
            names = [re.sub(r'^(prop|fx)_', '', stem)]
        ordered = None
        if len(boxes) != len(names):
            ordered = merge_by_grid(boxes, len(names), image.size)
            if ordered is not None:
                boxes = ordered
        if len(boxes) != len(names):
            report.append(f'{path.name}: found {len(boxes)} objects, expected {len(names)}; skipped (redraw or name single items)')
            continue
        for name, box in zip(names, ordered if ordered is not None else reading_order(boxes)):
            ident = name if name not in existing_ids else name + '_2'
            piece = crop(image, box)
            file = OUT / f'{ident}.png'
            piece.save(file, optimize=True)
            target = 70 if kind == 'fx' else 190 if name in BIG else 95
            items.append({'id': ident, 'kind': kind, 'tags': TAGS.get(name, name.replace('_', ' ')), 'file': 'library/' + file.name,
                          'size': [piece.width, piece.height], 'scale': round(target / max(piece.width, piece.height), 4)})
            existing_ids.add(ident)
        report.append(f'{path.name}: {len(names)} objects imported')
    (pack / 'catalog' / 'library.json').write_text(json.dumps({'version': 1, 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\n'.join(report) or 'no prop_/fx_ files in new/')
    print(len(items), 'library items')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else PACK))
