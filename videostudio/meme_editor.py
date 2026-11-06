"""Meme Episode Dynamic Editor and Asset Ingestion Service.

Provides:
- Detection of missing prop assets with auto-generated production-grade prompts.
- Ingestion of custom single PNG assets into the persistent prop library.
- Dynamic script editing (props, backgrounds, actor emotions, wardrobe).
- Fast re-rendering (~15-30s) directly from updated HyperFrames script.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from PIL import Image
from memestudio.engine.prop_layer import default_prop_layout, prop_layout, prop_layout_preset

ROOT = Path(__file__).resolve().parents[1]
MS = ROOT / 'memestudio'
CATALOG_DIR = ROOT / 'assets' / 'Meme_Animation_Asset_Pack' / 'catalog'
LIBRARY_JSON = CATALOG_DIR / 'library.json'
LIBRARY_DIR = CATALOG_DIR / 'library'
MS_PROPS_DIR = MS / 'assets' / 'props'
BACKGROUNDS_DIR = MS / 'assets' / 'backgrounds'
FACES_JSON = MS / 'assets' / 'rig' / 'faces' / 'faces.json'
WARDROBE_JSON = MS / 'assets' / 'rig' / 'wardrobe' / 'wardrobe.json'

_LIB_LOCK = threading.RLock()
_EDITOR_RENDERS = set()

# Older uploads predate the explicit marker and have only a label and file.
def _uploaded_prop(item):
    return item.get('uploaded') is True or (
        item.get('kind') == 'prop' and 'label' in item and 'scale' not in item and 'size' not in item
    )


def _prop_search_terms(pid, item):
    terms = [item.get(key, '') for key in ('tags', 'label_en', 'label_vi')]
    terms.extend(KEYWORD_TRANSLATIONS.get(pid, ()))
    terms.extend({
        'app': ('expense tracker', 'budget app', 'ứng dụng ghi chi tiêu'),
        'test_tool_axe': ('axe', 'rìu'),
    }.get(pid, ()))
    return [term for term in terms if isinstance(term, str) and term.strip()]


def _write_json(path, data):
    temporary = path.with_suffix('.tmp.' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _editable_script(job_output_dir):
    output = Path(job_output_dir)
    script = output / 'episode' / 'script.json'
    if not script.is_file():
        script = output / 'animation-script.json'
    if not script.is_file():
        raise FileNotFoundError(f'Cannot find script in {output}')
    return script

# English keyword dictionary for translating Vietnamese prop terms into accurate English prompts
KEYWORD_TRANSLATIONS = {
    'can_cau': ('bamboo fishing rod with string and hook', 'cần câu cá mộc mạc bằng tre/trúc, có dây cước và lưỡi câu'),
    'cuoc': ('gardening hoe with wooden handle', 'cái cuốc làm vườn cán gỗ truyền thống'),
    'xeng': ('gardening shovel or spade with wooden handle', 'cái xẻng xúc đất cán gỗ'),
    'choi': ('Asian straw broom', 'cái chổi rơm quét nhà'),
    'dien_thoai': ('modern smartphone with blank screen', 'chiếc điện thoại thông minh màn hình tắt'),
    'smartphone': ('modern smartphone with blank screen', 'chiếc điện thoại thông minh màn hình tắt'),
    'loa': ('smart speaker cylinder or box', 'chiếc loa thông minh dáng trụ để bàn'),
    'loa_thong_minh': ('compact smart home speaker', 'chiếc loa thông minh mini để bàn'),
    'thia': ('metal soup spoon', 'chiếc thìa kim loại mộc mạc'),
    'muong': ('metal soup spoon', 'chiếc muỗng kim loại'),
    'bat_com': ('bowl of white steamed rice with chopsticks', 'bát cơm trắng kèm đôi đũa'),
    'bat_pho': ('bowl of Vietnamese noodle soup pho', 'bát phở nóng hổi'),
    'coc_bia': ('mug of iced beer with foam', 'cốc bia hơi có bọt mát lạnh'),
    'ly_tra': ('cup of hot green tea', 'tách trà xanh nóng'),
    'tra_sua': ('plastic cup of boba bubble milk tea with straw', 'ly trà sữa trân châu có ống hút'),
    'tien': ('stack of Vietnamese Dong cash banknotes', 'xấp tiền giấy polymer'),
    'vi_tien': ('leather pocket wallet', 'chiếc ví da gấp cầm tay'),
    'hoa_don': ('paper receipt invoice bill', 'tờ hóa đơn thanh toán dài'),
    'so_do': ('red house ownership land certificate booklet', 'cuốn sổ đỏ giấy chứng nhận nhà đất'),
    'khoa': ('door padlock with key', 'ổ khóa đồng kèm chìa khóa'),
    'chia_khoa': ('car or house key', 'chùm chìa khóa nhà'),
    'dep_to_ong': ('classic Vietnamese honeycomb plastic slipper', 'đôi dép tổ ong màu trắng kem huyền thoại'),
    'tui_xach': ('casual shoulder handbag', 'chiếc túi xách đeo vai đơn giản'),
    'balo': ('school backpack', 'chiếc ba lô học sinh đơn giản'),
    'chao': ('cooking frying pan with handle', 'chiếc chảo rán có tay cầm'),
    'noi': ('metal cooking pot with lid', 'chiếc nồi nấu ăn có nắp vung'),
    'dao': ('kitchen cleaver knife', 'con dao bếp đơn giản'),
    'thot': ('round wooden cutting board', 'chiếc thớt gỗ tròn'),
    'kinh_ram': ('black sunglasses', 'kính râm gọng đen'),
    'non_la': ('Vietnamese conical palm leaf hat', 'chiếc nón lá truyền thống'),
    'mu_bao_hiem': ('motorcycle half-helmet', 'mũ bảo hiểm xe máy nửa đầu'),
}


def build_prop_prompt(label: str, prop_id: str) -> dict:
    """Generate comprehensive, production-grade design prompts in Vietnamese and English."""
    clean_id = (prop_id or '').lower().strip()
    clean_label = (label or clean_id).strip()

    # Match translation from dictionary or fallback to label
    matched_en, matched_vi = None, None
    for k, (en_desc, vi_desc) in KEYWORD_TRANSLATIONS.items():
        if k in clean_id or clean_id in k or k in clean_label.lower():
            matched_en, matched_vi = en_desc, vi_desc
            break

    subject_en = matched_en or f"{clean_label} (prop object)"
    subject_vi = matched_vi or clean_label

    prompt_vi = (
        f"Vẽ MỘT vật thể đơn lẻ trên nền trong suốt (transparent PNG, tỉ lệ vuông 512x512 pixels):\n"
        f"- Vật thể: {subject_vi}\n"
        f"- Phong cách: Hoạt hình 2D phẳng (flat 2D cartoon meme), phong cách sticker meme gấu trúc biaoqing hài hước.\n"
        f"- Nét viền: Nét viền đơn mảnh, sạch, màu nâu đậm (#3d2b1f hoặc #49352d), dứt khoát, không run, không sketch chì thô.\n"
        f"- Màu sắc: Tô mảng phẳng (flat color fills) bằng các gam màu đất xỉn tự nhiên (nâu nhạt, be, kem, xanh rêu xỉn, vàng nhạt, xám xanh).\n"
        f"- QUY TẮC BẮT BUỘC:\n"
        f"  1. Nền TRONG SUỐT 100% (Alpha channel), viền mép vật thể được cắt tỉa sạch sẽ.\n"
        f"  2. KHÔNG đổ bóng, KHÔNG vẽ bóng phản chiếu dưới đất, KHÔNG hiệu ứng gradient chuyển màu.\n"
        f"  3. KHÔNG phong cách 3D, KHÔNG phát sáng, KHÔNG bóng bẩy hiện đại.\n"
        f"  4. KHÔNG có bàn tay cầm, KHÔNG có nhân vật hay người xung quanh.\n"
        f"  5. TUYỆT ĐỐI KHÔNG có chữ, số, ký tự, nhãn hiệu hoặc logo thương hiệu.\n"
        f"  6. Giữ trọn vật thể, để thấy rõ chỗ tay sẽ nắm. Cạnh dài chiếm khoảng 90% khung; chừa ít viền trong suốt và không cắt đầu vật thể."
    )

    prompt_en = (
        f"Create a single isolated prop on a pure transparent background (PNG with alpha channel, 512x512 square):\n"
        f"- Subject: {subject_en}\n"
        f"- Art style: Simple flat 2D cartoon, humorous meme sticker style matching Chinese biaoqing / Vietnamese panda meme animations.\n"
        f"- Outlines: Thin, clean, single continuous solid dark brown outline (#3d2b1f), no sketch lines, no pencil texture, no jitter.\n"
        f"- Colors: Flat solid cell-shaded fills only in muted dull earthy tones (warm beige, cream, dull moss green, light earth brown, dusty grey-blue).\n"
        f"- STRICT NEGATIVE CONSTRAINTS:\n"
        f"  1. 100% pure transparent background (clean cutout, absolutely NO white or checkered background).\n"
        f"  2. NO drop shadows, NO cast ground shadows, NO color gradients, NO glossy highlights.\n"
        f"  3. NO 3D rendering, NO photorealism, NO glows, NO bevels.\n"
        f"  4. NO human characters, NO hands holding the object, NO background scenery.\n"
        f"  5. Absolutely NO text, letters, numbers, watermarks, or brand logos.\n"
        f"  6. Show the whole object and a clear grip area. Let its longest dimension fill about 90% of the canvas, with a small transparent margin and no clipped ends."
    )

    return {
        'prop_id': clean_id,
        'label': clean_label,
        'subject_vi': subject_vi,
        'subject_en': subject_en,
        'prompt_vi': prompt_vi,
        'prompt_en': prompt_en,
        'spec': {
            'format': 'PNG',
            'transparency': 'RGBA (alpha channel)',
            'recommended_size': '512x512 pixels',
            'style': 'Flat 2D cartoon, dark brown outline (#3d2b1f), muted earthy colors'
        }
    }


def load_prop_library() -> dict[str, dict]:
    """Load all indexed prop items from library.json and memestudio props."""
    items = {}
    with _LIB_LOCK:
        if LIBRARY_JSON.is_file():
            try:
                data = json.loads(LIBRARY_JSON.read_text(encoding='utf-8'))
                for it in data.get('items', []):
                    if it.get('kind') == 'prop':
                        pid = it['id']
                        file_rel = it.get('file', f'library/{pid}.png')
                        full_p = (CATALOG_DIR / file_rel).resolve()
                        items[pid] = {
                            'id': pid,
                            'label': it.get('label', pid),
                            'file': file_rel,
                            'exists': full_p.is_file(),
                            'source': 'catalog',
                            'uploaded': _uploaded_prop(it),
                            'handheld_layout': it.get('handheld_layout'),
                            'search_terms': _prop_search_terms(pid, it),
                        }
            except (OSError, ValueError):
                pass

        if MS_PROPS_DIR.is_dir():
            for p in MS_PROPS_DIR.glob('*.png'):
                pid = p.stem
                if pid not in items:
                    items[pid] = {
                        'id': pid,
                        'label': pid,
                        'file': f'props/{p.name}',
                        'exists': True,
                        'source': 'memestudio',
                        'search_terms': _prop_search_terms(pid, {}),
                    }
    return items


def detect_missing_props(script: dict) -> dict:
    """Scan script for props, identifying which are missing real image assets."""
    library = load_prop_library()
    props = script.get('props', {})
    result = {'missing': [], 'available': [], 'all': []}

    for pid, card in props.items():
        label = card.get('label', pid)
        aid = card.get('asset')
        has_asset = bool(aid and aid in library and library[aid]['exists'])
        asset_layout = library.get(aid, {}).get('handheld_layout')

        item_info = {
            'id': pid,
            'label': label,
            'asset': aid,
            'has_asset': has_asset,
            'default_layout': default_prop_layout(pid, card, asset_layout),
            'layout_preset': prop_layout_preset(asset_layout),
            'prompts': build_prop_prompt(label, pid)
        }

        if has_asset:
            item_info['file'] = library[aid]['file']
            result['available'].append(item_info)
        else:
            result['missing'].append(item_info)
        result['all'].append(item_info)

    return result


def save_prop_asset(prop_id: str, image_bytes: bytes, label: str | None = None) -> dict:
    """Process an uploaded prop image, ensure transparency, and register it in the permanent library."""
    pid = re.sub(r'[^a-z0-9_]', '', prop_id.lower().strip())
    if not pid:
        raise ValueError('Invalid prop ID (must be alphanumeric or underscores)')

    label = (label or pid).strip()

    # 1. Process image with Pillow
    try:
        im = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise ValueError(f'Cannot decode image: {e}')

    im = im.convert('RGBA')

    # If the user uploaded an image with a solid white or checkered background,
    # auto-detect if the 4 corners are pure white/near white and convert near white to transparent
    w, h = im.size
    corners = [im.getpixel((0, 0)), im.getpixel((w - 1, 0)), im.getpixel((0, h - 1)), im.getpixel((w - 1, h - 1))]
    all_white_corners = all(c[0] > 240 and c[1] > 240 and c[2] > 240 and c[3] > 200 for c in corners)

    if all_white_corners:
        datas = im.getdata()
        new_data = []
        for pixel in datas:
            # Change white / near white background to transparent
            if pixel[0] > 242 and pixel[1] > 242 and pixel[2] > 242:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(pixel)
        im.putdata(new_data)

    # Resize/fit into square 512x512 max while preserving aspect ratio
    max_dim = 512
    if w > max_dim or h > max_dim:
        im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    # 2. Save to catalog/library/{pid}.png and memestudio/assets/props/{pid}.png
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    MS_PROPS_DIR.mkdir(parents=True, exist_ok=True)

    target_file = LIBRARY_DIR / f"{pid}.png"
    target_ms = MS_PROPS_DIR / f"{pid}.png"

    buf = io.BytesIO()
    im.save(buf, format='PNG')
    png_bytes = buf.getvalue()

    with _LIB_LOCK:
        lib_data = {'items': []}
        if LIBRARY_JSON.is_file():
            try:
                lib_data = json.loads(LIBRARY_JSON.read_text(encoding='utf-8'))
            except (OSError, ValueError) as error:
                raise ValueError('Không đọc được danh mục đạo cụ.') from error

        items = lib_data.get('items', [])
        if any(it.get('id') == pid for it in items) or target_file.exists() or target_ms.exists():
            source_id = pid
            pid = f'{pid[:48]}_{uuid.uuid4().hex[:10]}'
            target_file = LIBRARY_DIR / f'{pid}.png'
            target_ms = MS_PROPS_DIR / f'{pid}.png'
        else:
            source_id = pid
        target_file.write_bytes(png_bytes)
        target_ms.write_bytes(png_bytes)
        items.append({
            'id': pid,
            'kind': 'prop',
            'file': f'library/{pid}.png',
            'label': label,
            'tags': ' '.join(_prop_search_terms(source_id, {})),
            'uploaded': True,
        })
        lib_data['items'] = items

        _write_json(LIBRARY_JSON, lib_data)

    return {
        'ok': True,
        'prop_id': pid,
        'label': label,
        'file': f"library/{pid}.png",
        'path': str(target_file)
    }


def update_job_prop_asset(job_output_dir: Path | str, prop_id: str, asset_id: str | None) -> dict:
    """Update a specific episode's script to link a prop to an asset, and copy the asset into episode."""
    ep_dir = Path(job_output_dir) / 'episode'
    script_path = ep_dir / 'script.json'
    if not script_path.is_file():
        # Check parent data/
        script_path = Path(job_output_dir) / 'animation-script.json'
        if not script_path.is_file():
            raise FileNotFoundError(f'Cannot find script in {job_output_dir}')

    script = json.loads(script_path.read_text(encoding='utf-8'))
    if 'props' not in script:
        script['props'] = {}

    if prop_id not in script['props']:
        script['props'][prop_id] = {'label': prop_id, 'asset': asset_id}
    else:
        card = script['props'][prop_id]
        if card.get('asset') != asset_id:
            card.pop('layout', None)
            card.pop('layout_preset', None)
        card['asset'] = asset_id

    # If asset_id exists in library, copy to episode/assets/
    if asset_id:
        lib = load_prop_library()
        if asset_id in lib:
            ep_assets = ep_dir / 'assets'
            ep_assets.mkdir(parents=True, exist_ok=True)
            src_file = CATALOG_DIR / lib[asset_id]['file']
            if not src_file.is_file():
                src_file = MS_PROPS_DIR / f"{asset_id}.png"
            if src_file.is_file():
                dest_file = ep_assets / f"prop_{asset_id}.png"
                shutil.copyfile(src_file, dest_file)

    _write_json(script_path, script)
    if (ep_dir / 'script.json').is_file() and script_path != (ep_dir / 'script.json'):
        (ep_dir / 'script.json').write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding='utf-8')

    return script


def remove_prop_upload(store, job, asset_id):
    """Detach from this episode and move the uploaded copies to a recoverable folder."""
    if not re.fullmatch(r'[a-z0-9_]+', asset_id):
        raise ValueError('Mã ảnh không hợp lệ.')
    with _LIB_LOCK:
        data = json.loads(LIBRARY_JSON.read_text(encoding='utf-8'))
        items = data['items']
        item = next((it for it in items if it.get('id') == asset_id and it.get('kind') == 'prop'), None)
        if item is None or not _uploaded_prop(item) or item.get('file') != f'library/{asset_id}.png':
            raise ValueError('Chỉ xóa được ảnh đã tải lên kho.')
        if _EDITOR_RENDERS:
            raise ValueError('Chờ tập đang xuất video hoàn tất rồi xóa ảnh.')
        for other in store.list():
            if other['request'].get('workflow_mode') != 'meme':
                continue
            if other['state'] in ('queued', 'running', 'retrying', 'cancelling'):
                raise ValueError('Chờ tác vụ hoạt hình đang chạy hoàn tất rồi xóa ảnh.')
            if other['id'] == job['id']:
                continue
            try:
                path = _editable_script(other['output'])
            except FileNotFoundError:
                script = other['checkpoints'].get('script', {}).get('animation_script', {})
            else:
                script = json.loads(path.read_text(encoding='utf-8'))
            if any(card.get('asset') == asset_id for card in script.get('props', {}).values()):
                raise ValueError('Ảnh đang được tập khác sử dụng. Bạn có thể bỏ ảnh riêng khỏi tập này.')

        script_path = _editable_script(job['output'])
        script = json.loads(script_path.read_text(encoding='utf-8'))
        original_script = script_path.read_bytes()
        for card in script.get('props', {}).values():
            if card.get('asset') == asset_id:
                card['asset'] = None
        trash = CATALOG_DIR / '_removed_uploads' / uuid.uuid4().hex
        paths = [(LIBRARY_DIR / f'{asset_id}.png', 'catalog'),
                 (MS_PROPS_DIR / f'{asset_id}.png', 'memestudio'),
                 (Path(job['output']) / 'episode' / 'assets' / f'prop_{asset_id}.png', 'episode')]
        moved = []
        try:
            trash.mkdir(parents=True)
            _write_json(trash / 'entry.json', {'item': item, 'job_id': job['id']})
            for path, source in paths:
                if path.is_file():
                    destination = trash / f'{source}-{asset_id}.png'
                    shutil.move(str(path), str(destination))
                    moved.append((path, destination))
            _write_json(script_path, script)
            _write_json(LIBRARY_JSON, {**data, 'items': [entry for entry in items if entry is not item]})
        except OSError:
            if script_path.read_bytes() != original_script:
                _write_json(script_path, json.loads(original_script))
            for path, destination in reversed(moved):
                shutil.move(str(destination), str(path))
            raise
        return script


def update_episode_script(job_output_dir: Path | str, updates: dict) -> dict:
    """Safely apply user modifications to an episode's script."""
    ep_dir = Path(job_output_dir) / 'episode'
    script_path = ep_dir / 'script.json'
    if not script_path.is_file():
        script_path = Path(job_output_dir) / 'animation-script.json'
        if not script_path.is_file():
            raise FileNotFoundError(f'Cannot find script in {job_output_dir}')

    script = json.loads(script_path.read_text(encoding='utf-8'))
    if 'title' in updates:
        title = updates['title']
        if not isinstance(title, list) or len(title) != 2 or any(not isinstance(line, str) or not line.strip() for line in title):
            raise ValueError('Tiêu đề cần hai dòng có nội dung.')
        script['title'] = [' '.join(line.split()) for line in title]

    # 1. Update scenes (backgrounds)
    if 'scenes' in updates:
        for sid, sc_data in updates['scenes'].items():
            if sid in script.get('scenes', {}):
                if 'bg' in sc_data:
                    script['scenes'][sid]['bg'] = sc_data['bg']

    # 2. Update props (labels, assets)
    if 'props' in updates:
        library = load_prop_library()
        for pid, pdata in updates['props'].items():
            if 'layout' in pdata:
                asset_layout = library.get(pdata.get('asset'), {}).get('handheld_layout')
                pdata['layout'] = prop_layout(pid, pdata, asset_layout)
            aid = pdata.get('asset')
            current = script.get('props', {}).get(pid, {}).get('asset')
            if aid and aid != current and not library.get(aid, {}).get('exists'):
                raise ValueError('Ảnh này không còn trong kho. Hãy tải lại trang trước khi lưu.')
        if 'props' not in script:
            script['props'] = {}
        for pid, pdata in updates['props'].items():
            if pid not in script['props']:
                script['props'][pid] = pdata
            else:
                script['props'][pid].update(pdata)
            aid = pdata.get('asset')
            if aid:
                lib = load_prop_library()
                if aid in lib:
                    ep_assets = ep_dir / 'assets'
                    ep_assets.mkdir(parents=True, exist_ok=True)
                    src_file = CATALOG_DIR / lib[aid]['file']
                    if not src_file.is_file():
                        src_file = MS_PROPS_DIR / f"{aid}.png"
                    if src_file.is_file():
                        dest_file = ep_assets / f"prop_{aid}.png"
                        shutil.copyfile(src_file, dest_file)

    # 3. Update beats (emotions, props placements, captions)
    if 'beats' in updates:
        existing_beats = script.get('beats', [])
        for ubeat in updates['beats']:
            idx = ubeat.get('i')
            if idx is not None and 0 <= idx < len(existing_beats):
                b = existing_beats[idx]
                if 'emo' in ubeat:
                    b['emo'] = ubeat['emo']
                if 'props' in ubeat:
                    b['props'] = ubeat['props']
                if 'caption' in ubeat:
                    b['caption'] = ubeat['caption']

    # 4. Update cast (costume, acc, face)
    if 'cast' in updates:
        if 'cast' not in script:
            script['cast'] = {}
        for cid, cdata in updates['cast'].items():
            if cid in script['cast']:
                script['cast'][cid].update(cdata)

    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding='utf-8')
    if (ep_dir / 'script.json').is_file() and script_path != (ep_dir / 'script.json'):
        (ep_dir / 'script.json').write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding='utf-8')

    return script


def re_render_job(job: dict, store=None, check=None) -> dict:
    """Synchronously re-render an existing episode with updated script. Takes ~15-25 seconds."""
    from .meme_animation import episode, command, mix_legacy_music
    from .media import ensure_clean_audio, verify as verify_media, asset
    from .output_layout import publish_video

    check = check or (lambda: None)
    ep = episode(job)
    script_path = ep / 'script.json'
    if not script_path.is_file():
        raise FileNotFoundError('episode/script.json not found in job output')

    script = json.loads(script_path.read_text(encoding='utf-8'))
    voice_path = ep / 'voice.json'
    if not voice_path.is_file():
        raise FileNotFoundError('episode/voice.json not found; cannot re-render without audio')

    # 1. Re-build index.html and staging.json with make_episode.py
    build_log = ep / 'build_rerender.log'
    command([sys.executable, '-I', MS / 'engine/make_episode.py', ep], check, build_log)

    staging_path = ep / 'staging.json'
    staging = json.loads(staging_path.read_text(encoding='utf-8'))
    seconds = float(staging['duration'])

    # 2. Re-mix SFX if enabled
    if script.get('sfx_enabled', True):
        command([sys.executable, '-I', MS / 'engine/make_sfx.py', ep], check, ep / 'sfx_rerender.log')

    # 3. HyperFrames render to video.part.mp4
    target = Path(job['output']) / 'video.part.mp4'
    render_log = ep / 'render_rerender.log'
    node_bin = shutil.which('node') or 'node'
    hf_bin = MS / 'node_modules/hyperframes/bin/hyperframes.mjs'

    command([node_bin, str(hf_bin), 'render', str(ep), '--quiet', '--fps', '30', '-o', str(target)],
            check, render_log, timeout=max(180, int(seconds * 12 + 120)))

    # 4. Optional legacy music mix and audio verification
    from .voices import Voices
    ffmpeg_bin = shutil.which('ffmpeg') or 'ffmpeg'
    ffprobe_bin = shutil.which('ffprobe') or 'ffprobe'

    soundtrack = mix_legacy_music(type('PipelineStub', (), {'ffmpeg': ffmpeg_bin})(), job, target, seconds, check)
    audio = ensure_clean_audio(str(target), check, ffmpeg_bin)
    verify_media(str(target), seconds, ffprobe_bin)

    result = publish_video(job, {
        'video': str(target),
        'assets': [asset(target)],
        'renderer': 'meme-hyperframes-v1-rerender',
        'beats': len(script.get('beats', [])),
        'duration_seconds': seconds,
        'audio_quality': audio,
        'legacy_music': soundtrack
    })

    if store:
        with store.db() as c:
            c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',
                      (job['id'], 'render', json.dumps(result, ensure_ascii=False)))
            verify_data = {'verified': True, 'duration_seconds': seconds, 'video': result['video']}
            c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',
                      (job['id'], 'verify', json.dumps(verify_data, ensure_ascii=False)))
            c.execute('UPDATE jobs SET updated=? WHERE id=?', (time.time(), job['id']))

    return result
