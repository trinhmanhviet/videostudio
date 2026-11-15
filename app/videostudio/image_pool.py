"""Real pictures for a video instead of drawn ones (image_provider 'pool').

A pool is a folder of pictures found for one source, today a Facebook post (social_import): ChatGPT searched the web
for photos related to the post, the tool downloaded the ones that open as real pictures, and the post's own pictures
were added. pool.json lists them: [{"file", "mo_ta", "nguon", "kind": "web" | "post"}].

At the images stage ChatGPT picks the best picture for each scene from the descriptions (a picture is not reused in
the next scene when another fits). Each scene image is the photo whole, on a blurred and darkened copy of itself, so
nothing is cropped away. The user can still replace any scene's picture in the video's page (scene editor).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from .paths import DATA_ROOT

ROOT = DATA_ROOT / 'social-posts'
CANVAS = (1920, 1080)
MIN_SIDE = 300
MIN_POOL = 3


def pool_folder(pool_id, root=None):
    if not isinstance(pool_id, str) or not re.fullmatch(r'[0-9a-f]{32}', pool_id):
        raise ValueError('image_pool must be the id of a picture pool')
    return Path(root or ROOT) / pool_id


def load_pool(pool_id, root=None):
    """The pool's pictures that still exist (only files inside the pool's own folder)."""
    folder = pool_folder(pool_id, root).resolve()
    manifest = folder / 'pool.json'
    if not manifest.is_file():
        return []
    items = []
    for item in json.loads(manifest.read_text(encoding='utf-8')):
        path = (folder / str(item.get('file', ''))).resolve()
        if path.parent == folder / 'pool' and path.is_file():
            items.append({**item, 'path': str(path)})
    return items


def save_pool(pool_id, items, root=None):
    folder = pool_folder(pool_id, root)
    (folder / 'pool.json').write_text(json.dumps([{k: v for k, v in i.items() if k != 'path'} for i in items], ensure_ascii=False, indent=1),
                                      encoding='utf-8')


def add_picture(pool_id, raw, description, source, kind, number, root=None):
    """Keep one downloaded picture if it is a real picture of a useful size; returns its pool entry or None."""
    import io
    folder = pool_folder(pool_id, root) / 'pool'
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(io.BytesIO(raw)) as picture:
            picture.load()
            if min(picture.size) < MIN_SIDE or picture.size[0] / picture.size[1] > 4 or picture.size[1] / picture.size[0] > 4:
                return None
            name = f'{kind}-{number:02d}.jpg'
            picture.convert('RGB').save(folder / name, quality=92)
    except Exception:
        return None
    return {'file': f'pool/{name}', 'mo_ta': str(description or '').strip()[:300], 'nguon': str(source or '').strip()[:500], 'kind': kind}


def compose(source, target, size=CANVAS):
    """The photo whole and centred on a blurred, darker copy of itself that fills the frame."""
    with Image.open(source) as picture:
        photo = picture.convert('RGB')
    width, height = size
    cover = max(width / photo.width, height / photo.height)
    background = photo.resize((max(1, round(photo.width * cover)), max(1, round(photo.height * cover))), Image.LANCZOS)
    left, top = (background.width - width) // 2, (background.height - height) // 2
    background = background.crop((left, top, left + width, top + height)).filter(ImageFilter.GaussianBlur(40))
    background = ImageEnhance.Brightness(background).enhance(0.45)
    fit = min(width / photo.width, height / photo.height)
    front = photo.resize((max(1, round(photo.width * fit)), max(1, round(photo.height * fit))), Image.LANCZOS)
    background.paste(front, ((width - front.width) // 2, (height - front.height) // 2))
    background.save(target)


def round_robin(scene_count, picture_count):
    return [i % picture_count for i in range(scene_count)]


MATCH_PROMPT = """Ghép ảnh cho từng cảnh của một video. Mỗi cảnh chọn MỘT ảnh hợp nội dung nhất trong danh sách ảnh; tránh dùng cùng một ảnh cho hai cảnh liền nhau khi có ảnh khác hợp; ảnh nào cũng nên được dùng ít nhất một lần nếu có chỗ hợp.

Ảnh (số thứ tự: mô tả):
{pictures}

Cảnh (số thứ tự: lời đọc / nội dung hình):
{scenes}

Trả về đúng một đối tượng JSON: {{"chon": [số thứ tự ảnh cho cảnh 0, cho cảnh 1, ...]}} với đúng {count} số."""


def match(scenes, pictures, ask):
    """ChatGPT's choice of picture per scene; round robin when the answer is missing or malformed."""
    fallback = round_robin(len(scenes), len(pictures))
    try:
        prompt = MATCH_PROMPT.format(
            pictures='\n'.join(f'{i}: {p.get("mo_ta") or "ảnh liên quan"}' for i, p in enumerate(pictures)),
            scenes='\n'.join(f'{i}: {str(s.get("narration") or s.get("text") or "")[:220]} / {str(s.get("visual_prompt") or "")[:160]}'
                             for i, s in enumerate(scenes)), count=len(scenes))
        answer = ask(prompt)
        chosen = answer.get('chon') if isinstance(answer, dict) else None
        if isinstance(chosen, list) and len(chosen) == len(scenes) and all(type(c) is int and 0 <= c < len(pictures) for c in chosen):
            return chosen, 'chatgpt'
    except Exception:
        pass
    return fallback, 'round_robin'
