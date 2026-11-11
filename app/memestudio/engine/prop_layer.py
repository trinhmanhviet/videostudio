"""Visible comic props: held, on a table, or hidden, following the scene camera.

Only image assets appear on the stage. Held items render inside the arm joint.
"""
from html import escape
from functools import lru_cache
import math
import re
from pathlib import Path

from PIL import Image

HELD_BOX = (56, 64)
# Standing rig height from the crown of the base head to the soles, in rig units.
STANDING_CHARACTER_HEIGHT = 192


def held_scale_for_ratio(visible_size, ratio):
    width, height = visible_size
    fit = min(HELD_BOX[0] / width, HELD_BOX[1] / height)
    return round(ratio * STANDING_CHARACTER_HEIGHT / (max(width, height) * fit), 4)


def default_prop_layout(pid, card, asset_layout=None):
    if asset_layout is not None:
        return {field: asset_layout[field] for field in ('scale', 'grip_x', 'grip_y')}
    name = f'{pid} {card.get("asset") or ""} {card.get("label", "")}'.lower()
    is_rod = any(term in name for term in ('can_cau', 'cần câu', 'fishing rod', 'fishing_rod'))
    return {'scale': 2.2, 'grip_x': 0.22, 'grip_y': 0.72} if is_rod else {
        'scale': 1.0, 'grip_x': 0.5, 'grip_y': 0.72,
    }


def prop_layout_preset(asset_layout):
    if asset_layout is None:
        return None
    return asset_layout.get('revision') or ':'.join(str(asset_layout[field]) for field in ('scale', 'grip_x', 'grip_y'))


# Grip point (fraction of the image) per way of holding; underarm = crutch top at the armpit.
HOLD_GRIP = {'hand': (0.5, 0.62), 'two_hand': (0.5, 0.45), 'underarm': (0.5, 0.3)}


def load_sizes(path):
    """prop_sizes.json -> {asset: (ratio of character height, hold)}; missing file = no sizes."""
    import json
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    sizes = {}
    for key, value in raw.items():
        if (not key.startswith('_') and isinstance(value, list) and len(value) == 2
                and type(value[0]) in (int, float) and 0.02 <= value[0] <= 2
                and value[1] in ('hand', 'two_hand', 'underarm', 'ground')):
            sizes[key] = (float(value[0]), value[1])
    return sizes


def sized_layout(path, size):
    """Handheld layout from a real size, for assets without a reviewed handheld_layout."""
    ratio, hold = size
    _, bounds = _image_geometry(path)
    if bounds is None or hold == 'ground':
        return None
    left, top, right, bottom = bounds
    grip_x, grip_y = HOLD_GRIP[hold]
    (width, height), _ = _image_geometry(path)
    return {'scale': min(5.0, max(0.25, held_scale_for_ratio((right - left, bottom - top), ratio))),
            'grip_x': (left + (right - left) * grip_x) / width, 'grip_y': (top + (bottom - top) * grip_y) / height}


def prop_layout(pid, card, asset_layout=None):
    layout = default_prop_layout(pid, card, asset_layout)
    custom = card.get('layout', {})
    if not isinstance(custom, dict):
        raise ValueError('Căn ảnh đạo cụ không hợp lệ.')
    if asset_layout is not None:
        if card.get('layout_preset') != prop_layout_preset(asset_layout):
            custom = {}
        custom = {**layout, **custom}
    for field, low, high in (('scale', 0.25, 5), ('grip_x', 0, 1), ('grip_y', 0, 1)):
        if field not in custom:
            continue
        value = custom[field]
        if type(value) not in (float, int) or not low <= value <= high or not math.isfinite(value):
            raise ValueError('Kích thước hoặc điểm cầm nằm ngoài giới hạn.')
        layout[field] = value
    return layout


@lru_cache(maxsize=128)
def _image_geometry(path):
    with Image.open(path) as image:
        alpha = image.convert('RGBA').getchannel('A')
        bounds = alpha.point(lambda value: 255 if value > 16 else 0).getbbox()
        return image.size, bounds


def _image_position(path, layout, owner, number):
    (width, height), bounds = _image_geometry(path)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    box_width, box_height = HELD_BOX if owner is not None else (130, 110)
    scale = min(box_width / (right - left), box_height / (bottom - top)) * layout['scale']
    if owner is None:
        x = 680 + number * 150 - (left + right) * scale / 2
        y = 720 - bottom * scale
    else:
        x = -width * layout['grip_x'] * scale
        y = -height * layout['grip_y'] * scale
    return f'left:{x:.2f}px;top:{y:.2f}px;width:{width * scale:.2f}px;height:{height * scale:.2f}px'


def _ground_position(path, size, x_center, stage):
    """Real-size object standing on the stage floor; x_center in stage px."""
    (width, height), bounds = _image_geometry(path)
    if bounds is None:
        return None, 0
    left, top, right, bottom = bounds
    scale = size[0] * STANDING_CHARACTER_HEIGHT * stage['unit'] / max(right - left, bottom - top)
    x = x_center - (left + right) * scale / 2
    y = stage['ground_y'] - bottom * scale
    return (f'left:{x:.2f}px;top:{y:.2f}px;width:{width * scale:.2f}px;height:{height * scale:.2f}px',
            (right - left) * scale)


def _free_slot(anchor, width, taken, stage):
    """Closest floor position to `anchor` (stage px) where an object of `width` overlaps nothing."""
    lo, hi = 30 + width / 2, stage.get('world_w', 1600) - 30 - width / 2
    for step in range(0, 1600, 10):
        for x in ((anchor + step, anchor - step) if step else (anchor,)):
            if lo <= x <= hi and all(x + width / 2 <= a or x - width / 2 >= b for a, b in taken):
                return x
    return min(max(anchor, lo), hi)


def validate(script, library):
    errors=[];props=script.get('props',{})
    if not isinstance(props,dict):return ['props must be an object']
    for pid,card in props.items():
        if not isinstance(pid,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',pid) or not isinstance(card,dict):errors.append('Invalid prop definition');continue
        if card.get('asset') is not None and card.get('asset') not in library:errors.append('Unknown prop asset')
        if not isinstance(card.get('label'),str) or not card['label'].strip():errors.append('Prop label required')
        try:
            prop_layout(pid, card)
        except ValueError as error:
            errors.append(str(error))
    for beat in script.get('beats',[]):
        notes=beat.get('notes',[])
        if not isinstance(notes,list):errors.append('State notes must be a list');notes=[]
        for note in notes:
            if not isinstance(note,dict) or not isinstance(note.get('prop'),str) or note['prop'] not in props or not isinstance(note.get('text'),str):errors.append('Invalid state note')
        for pid,value in beat.get('props',{}).items():
            if pid not in props or not isinstance(value,dict) or value.get('placement') not in ('held','table','hidden'):errors.append('Invalid prop state')
            elif value['placement']=='held' and value.get('owner') not in script['scenes'][beat['scene']]['cast']:errors.append('Prop owner absent from scene')
            elif value.get('near') is not None and value['near'] not in script['scenes'][beat['scene']]['cast']:errors.append('Prop near: character absent from scene')
    return errors


def layer(definitions, scene, library, copy, owner=None, asset_layouts=None, sizes=None, stage=None):
    """Held props for one owner (inside the hand), or the world layer (owner None).

    With sizes and stage (make_episode), world objects stand on the floor at real size next to the
    character named by `near` (or their owner), and objects too big to hold stay on the floor."""
    sizes = sizes or {}
    html = []
    for beat in scene['beats']:
        states = beat.get('_prop_states', beat.get('props', {}))
        end = min(beat.get('display_end', beat['end']), scene['end'])
        if end <= beat['start']:
            continue
        visible = []
        for pid, state in states.items():
            asset = definitions.get(pid, {}).get('asset')
            if asset not in library or pid in beat.get('_seats', ()):
                continue
            grounded = stage is not None and sizes.get(asset, (0, ''))[1] == 'ground' and state['placement'] == 'held'
            if owner is None:
                if not grounded and (state['placement'] != 'table' or state.get('_location', scene.get('location')) != scene.get('location')):
                    continue
            elif state['placement'] != 'held' or state.get('owner') != owner or grounded:
                continue
            visible.append((pid, asset, state))
        if owner is not None:
            visible = visible[-1:]
        # Floor slots already taken this beat: the characters' bodies, then each placed object.
        taken = [(x - stage['body_half'], x + stage['body_half']) for x in scene.get('x', {}).values()] if stage else []
        for number, (pid, asset, state) in enumerate(visible):
            card = definitions[pid]
            src_path = library[asset]
            if owner is None and stage is not None and asset in sizes:
                near = state.get('near') or state.get('owner')
                width = _ground_position(src_path, sizes[asset], 0, stage)[1]
                anchor = scene['x'][near] if near in scene.get('x', {}) else stage['center']
                x_center = _free_slot(anchor, width, taken, stage)
                taken.append((x_center - width / 2 - 6, x_center + width / 2 + 6))
                position = _ground_position(src_path, sizes[asset], x_center, stage)[0]
            else:
                asset_layout = (asset_layouts or {}).get(asset) if owner is not None else None
                if owner is not None and asset_layout is None and asset in sizes:
                    asset_layout = sized_layout(src_path, sizes[asset])
                position = _image_position(src_path, prop_layout(pid, card, asset_layout), owner, number)
            if position is None:
                continue
            src = copy(src_path, 'prop_' + asset + '.png')
            label = escape(card['label'])
            html.append(
                f'<div id="{scene["id"]}_prop_{pid}_{beat["i"]}" class="clip" '
                f'data-start="{beat["start"]:.3f}" data-duration="{end - beat["start"]:.3f}" '
                f'style="position:absolute;{position};z-index:3">'
                f'<img src="{src}" alt="{label}" style="width:100%;height:100%;object-fit:contain;object-position:top left"></div>'
            )
    return ''.join(html)
