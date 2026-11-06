"""Visible comic props: held, on a table, or hidden, following the scene camera.

Only image assets appear on the stage. Held items render inside the arm joint.
"""
from html import escape
from functools import lru_cache
import math
import re

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
    return errors


def layer(definitions, scene, library, copy, owner=None, asset_layouts=None):
    html = []
    for beat in scene['beats']:
        states = beat.get('_prop_states', beat.get('props', {}))
        end = min(beat.get('display_end', beat['end']), scene['end'])
        if end <= beat['start']:
            continue
        visible = []
        for pid, state in states.items():
            asset = definitions.get(pid, {}).get('asset')
            if asset not in library:
                continue
            if owner is None:
                if state['placement'] != 'table' or state.get('_location', scene.get('location')) != scene.get('location'):
                    continue
            elif state['placement'] != 'held' or state.get('owner') != owner:
                continue
            visible.append((pid, asset))
        if owner is not None:
            visible = visible[-1:]
        for number, (pid, asset) in enumerate(visible):
            card = definitions[pid]
            asset_layout = (asset_layouts or {}).get(asset) if owner is not None else None
            position = _image_position(library[asset], prop_layout(pid, card, asset_layout), owner, number)
            if position is None:
                continue
            src = copy(library[asset], 'prop_' + asset + '.png')
            label = escape(card['label'])
            html.append(
                f'<div id="{scene["id"]}_prop_{pid}_{beat["i"]}" class="clip" '
                f'data-start="{beat["start"]:.3f}" data-duration="{end - beat["start"]:.3f}" '
                f'style="position:absolute;{position};z-index:3">'
                f'<img src="{src}" alt="{label}" style="width:100%;height:100%;object-fit:contain;object-position:top left"></div>'
            )
    return ''.join(html)
