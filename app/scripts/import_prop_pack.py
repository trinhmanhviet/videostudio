"""Merge a handheld prop manifest into the shared prop library.

Run from the VideoStudio root: python -m scripts.import_prop_pack PATH/manifest.json
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from PIL import Image

from memestudio.engine.prop_layer import held_scale_for_ratio, prop_layout

CATALOG = Path(__file__).resolve().parents[1] / 'assets/Meme_Animation_Asset_Pack/catalog'
EXISTING_PROP_IDS = {'dien_thoai': 'smartphone', 'vi': 'wallet', 'tuoc_no_vit': 'screwdriver'}


def _number(value, low, high, field):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f'Invalid {field}: {value!r}')
    return value


def _words(item, field):
    values = item.get(field, [])
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f'{field} must be an array of strings')
    return values


def _read_asset(folder, pack_id, item):
    if item.get('group') != 'handheld_prop':
        raise ValueError('This importer accepts handheld_prop assets.')
    prop_id = item['id'].removeprefix('prop_')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', prop_id):
        raise ValueError(f'Invalid prop ID: {prop_id}')
    filename = f'prop_{prop_id}.png'
    if item.get('file') != filename:
        raise ValueError(f'Expected filename {filename}')
    path = (folder / filename).resolve()
    if path.parent != folder or path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f'File outside the pack or too large: {filename}')
    content = path.read_bytes()
    with Image.open(BytesIO(content)) as image:
        if image.format != 'PNG' or image.mode != 'RGBA' or max(image.size) > 4096:
            raise ValueError(f'Expected PNG RGBA up to 4096 px: {filename}')
        size = image.size
        if size != (item.get('width', size[0]), item.get('height', size[1])):
            raise ValueError(f'PNG dimensions differ from manifest: {filename}')
        alpha = image.getchannel('A')
        bounds = alpha.point(lambda value: 255 if value > 16 else 0).getbbox()
        if not bounds or alpha.getextrema()[0] != 0:
            raise ValueError(f'Expected visible art on a transparent canvas: {filename}')

    ratio = _number(item['display_length_ratio_character_height'], 0.08, 1.4, 'display length ratio')
    x = _number(item['grip_x'], 0, 1, 'grip_x')
    y = _number(item['grip_y'], 0, 1, 'grip_y')
    left, top, right, bottom = bounds
    if not (left <= x * (size[0] - 1) < right and top <= y * (size[1] - 1) < bottom):
        raise ValueError(f'Grip outside visible bounds: {filename}')
    asset_id = EXISTING_PROP_IDS.get(prop_id, prop_id)
    layout = prop_layout(asset_id, {'layout': {
        'scale': held_scale_for_ratio((right - left, bottom - top), ratio),
        'grip_x': x,
        'grip_y': y,
    }})
    layout['revision'] = hashlib.sha256(content + json.dumps(layout, sort_keys=True).encode('utf-8')).hexdigest()
    label_vi, label_en = item['name_vi'].strip(), item['name_en'].strip()
    if not label_vi or not label_en:
        raise ValueError(f'Both labels are required: {filename}')
    return {
        'id': asset_id,
        'kind': 'prop',
        'pack_id': pack_id,
        'file': f'library/{asset_id}.png',
        'label': label_vi,
        'label_vi': label_vi,
        'label_en': label_en,
        'tags': ' '.join(_words(item, 'keywords_vi') + _words(item, 'keywords_en')),
        'size': list(size),
        'handheld_layout': layout,
        'display_length_ratio_character_height': ratio,
        'needs_review': item.get('needs_review') is True,
    }, content, f'{pack_id}_{prop_id}'


def _replace_file(target, content):
    temporary = target.with_suffix('.tmp.' + uuid4().hex)
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def import_pack(manifest_path, catalog=CATALOG):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    pack_id = manifest['pack_id'].lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,23}', pack_id):
        raise ValueError('Invalid pack ID')
    entries = manifest['assets']
    if not isinstance(entries, list) or not entries or manifest.get('asset_count', len(entries)) != len(entries):
        raise ValueError('Asset count does not match the manifest')
    assets = [_read_asset(manifest_path.parent, pack_id, item) for item in entries]
    if len({entry['id'] for entry, _, _ in assets}) != len(assets):
        raise ValueError('Duplicate prop IDs in manifest')

    index = catalog / 'library.json'
    data = json.loads(index.read_text(encoding='utf-8')) if index.is_file() else {'version': 1, 'items': []}
    existing = {item['id']: item for item in data['items']}
    pending, retired = [], []
    for entry, content, legacy_id in assets:
        target = catalog / entry['file']
        old = existing.get(entry['id'])
        if old is not None and (old.get('kind') != 'prop' or old.get('file') != entry['file']):
            raise ValueError(f"Asset ID already used by a different library entry: {entry['id']}")
        previous_tags = old.get('tags', '') if old else ''
        if previous_tags and previous_tags not in entry['tags']:
            entry['tags'] = previous_tags if entry['tags'] in previous_tags else f"{previous_tags} {entry['tags']}"
        if old != entry or not target.is_file() or target.read_bytes() != content:
            pending.append((entry, content, target))
        legacy = existing.get(legacy_id)
        if legacy and legacy.get('pack_id') == pack_id and legacy.get('file') == f'library/{legacy_id}.png':
            retired.append(legacy)

    if pending or retired:
        history = catalog / '_asset_history' / uuid4().hex
        history.mkdir(parents=True)
        if index.is_file():
            shutil.copyfile(index, history / index.name)
        for _, content, target in pending:
            if target.is_file() and target.read_bytes() != content:
                shutil.copyfile(target, history / target.name)
        for entry, content, target in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.read_bytes() != content:
                _replace_file(target, content)
            existing[entry['id']] = entry
        for entry in retired:
            existing.pop(entry['id'])
        data['items'] = list(existing.values())
        _replace_file(index, json.dumps(data, ensure_ascii=False, indent=1).encode('utf-8'))
        live_files = {entry.get('file') for entry in data['items']}
        for entry in retired:
            path = catalog / entry['file']
            if entry['file'] not in live_files and path.is_file():
                path.replace(history / path.name)
    return [entry for entry, _, _ in assets]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    for asset in import_pack(parser.parse_args().manifest):
        print(f"{asset['id']}  {asset['label_en']}  scale={asset['handheld_layout']['scale']:.2f}")
