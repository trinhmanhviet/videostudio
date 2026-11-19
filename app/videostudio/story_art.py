"""Tranh nền theo diễn biến: ComfyUI pictures behind a story video, changing as the story moves on.

Why (owner, 2026-11-19): a whole chapter over one fixed background is monotonous; the chapter's own pictures, with the
same characters as its YouTube thumbnail, make the video worth watching. A book turns it on with layout['story_art'].

How, in the story "images" step (after the narration is read, so its timing is known and the GPU is free):
- ChatGPT reads the chapter's sentences with their times and splits it into 4–6 stretches of the story (new place,
  new event, a clear change of mood). For each: the moment to draw, who is in it (the book's cast grows as in
  story_promo), how they look different, and one stretch marked as the chapter's key moment;
- ComfyUI draws one landscape picture per stretch with the portraits of the people in it as references, characters in
  the right half (the gameplay window covers the lower-left quarter);
- the key moment's picture also becomes the chapter's YouTube thumbnail (story_promo), so nothing is drawn twice.
Render (story_pipeline.compose) then crossfades the pictures at the stretches' times:
- landscape: picture full frame, gameplay in the lower-left quarter, titles small at the top left, no burned
  subtitles (YouTube shows the uploaded .srt);
- vertical: the picture sharp at the top (1080x608), the gameplay in the middle, below it the same picture blurred
  and darkened under the titles and the burned subtitles.
Any failure here never stops the video: the book's usual background is used instead (logged)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ART_LAYOUT = {
    # Gameplay in the lower-left quarter; titles at the top left, over the picture's open left side.
    'ngang': {'game': (40, 1080 - 40 - 506, 900, 506), 'titles': 'left'},
    # Picture at the top (0..608), gameplay from 640, titles and captions in the blurred lower part.
    'doc': {'game': (36, 640, 1008, 567), 'titles': 'low', 'caption_bottom': 1920 - 1640},
}
TOP_ART = (1080, 608)
FADE = 1.0
MIN_STRETCH = 40.0      # seconds; a shorter stretch is joined to the one before it

SEGMENT_PROMPT = """Bạn chia một tập truyện audio thành các đoạn diễn biến để vẽ tranh nền cho video (mỗi đoạn một bức tranh).
Bộ truyện: "{book}" (thể loại {genre}). Tập {number}. Nhân vật đã biết: {people}.
Dưới đây là các câu của tập, mỗi câu có số thứ tự và mốc thời gian.
Chia tập thành {lo} đến {hi} đoạn liền nhau theo diễn biến: đổi bối cảnh, có sự kiện mới, hoặc cảm xúc đổi hẳn. Đoạn đầu bắt đầu ở câu 0. Mỗi đoạn dài ít nhất 60 giây.
Chỉ trả lời JSON: {{"doan": [{{"tu": <số câu bắt đầu>, "canh": "...", "nhan_vat_trong_anh": ["..."], "nhan_vat_moi": [{{"ten": "...", "vai": "...", "ngoai_hinh": "..."}}], "ngoai_hinh_chuong": {{"<tên>": "..."}}, "chinh": false}}]}}
- canh: tiếng Anh, 2–3 câu tả khung cảnh của đoạn để vẽ: bối cảnh, ánh sáng, nhân vật nào đang làm gì, cảm xúc. Không có chữ trong tranh, không máu me, không gợi dục.
- nhan_vat_trong_anh: 0–3 nhân vật có mặt trong cảnh, người quan trọng nhất trước, viết đúng tên như trong truyện. Chỉ nhân vật chính hoặc người gắn bó mật thiết với nhân vật chính; nhân vật quá phụ chỉ tả trong canh, không ghi tên ở đây.
- nhan_vat_moi: những người trong nhan_vat_trong_anh CHƯA có trong danh sách nhân vật đã biết: ten, vai (nói rõ quan hệ với nhân vật chính), ngoai_hinh (tiếng Anh, cụ thể và cố định: giới tính, tuổi, khuôn mặt, tóc, mắt, dáng, trang phục thường mặc). Không có thì [].
- ngoai_hinh_chuong: chỉ cho người trong cảnh mà ở đoạn này trông KHÁC thường lệ (trang phục, vết thương, tuổi, kiểu tóc): tên → một câu tiếng Anh. Không có thì {{}}.
- chinh: true cho đúng MỘT đoạn là khoảnh khắc gây tò mò nhất của tập (dùng làm ảnh bìa YouTube), các đoạn khác false.

Các câu:
{lines}"""


def _clock(seconds):
    return f'{int(seconds // 60)}:{int(seconds % 60):02d}'


def stretch_count(seconds):
    """(lo, hi) stretches for a chapter of this length: about one per two and a half minutes, 3–6."""
    middle = max(3, min(6, round(seconds / 150)))
    return max(3, middle - 1), min(6, middle + 1)


def numbered(ledger, limit=60000):
    lines = '\n'.join(f'[{i}] {_clock(unit["start"])} {unit["text"]}' for i, unit in enumerate(ledger))
    return lines[:limit]


def check_segments(data, ledger, sheet, seconds):
    """Stretches in order, starting at sentence 0, none shorter than MIN_STRETCH, exactly one key moment."""
    from .story_promo import _clean, check_people
    items = data.get('doan') if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError('ChatGPT không chia đoạn diễn biến')
    stretches = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get('tu'))
        except (TypeError, ValueError):
            continue
        scene = _clean(item.get('canh'), 700)
        if not scene or not 0 <= index < len(ledger):
            continue
        people = check_people(item, sheet) if item.get('nhan_vat_trong_anh') else {'people': [], 'looks_now': {}, 'new': []}
        stretches.append({'index': index, 'start': float(ledger[index]['start']), 'scene': scene, 'key': item.get('chinh') is True, **people})
    stretches.sort(key=lambda s: s['index'])
    kept = []
    for stretch in stretches:
        if kept and (stretch['index'] == kept[-1]['index'] or stretch['start'] - kept[-1]['start'] < MIN_STRETCH):
            kept[-1]['key'] = kept[-1]['key'] or stretch['key']
            continue
        kept.append(stretch)
    if not kept:
        raise ValueError('Các đoạn diễn biến không hợp lệ')
    kept[0].update(index=0, start=0.0)
    if seconds - kept[-1]['start'] < MIN_STRETCH and len(kept) > 1:
        kept[-2]['key'] = kept[-2]['key'] or kept[-1]['key']
        kept.pop()
    keys = [s for s in kept if s['key']]
    for stretch in kept:
        stretch['key'] = False
    (keys[0] if keys else max(kept, key=lambda s: len(s['people'])))['key'] = True
    return kept


def plan_and_draw(promo, job, ledger, seconds, check=lambda: None, log=lambda text: None):
    """The chapter's stretches and their pictures, kept with the chapter (story-promo/<book>/<episode>/story-art/:
    plan.json + seg-NN.png), so "Dựng lại khung hình" reuses the same pictures instead of drawing new ones.
    Returns {'segments': [{'start', 'path', 'sha256', 'key'}], 'plan': path}."""
    from .story_promo import episode
    from .core import digest
    info = episode(job)
    if not info:
        raise ValueError('Không đọc được chương của video')
    folder = promo._book(info['book_id']) / info['key'] / 'story-art'
    folder.mkdir(parents=True, exist_ok=True)
    plan_path = folder / 'plan.json'
    texts = hashlib.sha256(json.dumps([u['text'] for u in ledger], ensure_ascii=False).encode('utf-8')).hexdigest()
    plan = json.loads(plan_path.read_text(encoding='utf-8')) if plan_path.is_file() else None
    if not plan or plan.get('texts') != texts:
        sheet = promo.make_sheet(info)
        lo, hi = stretch_count(seconds)
        people = ', '.join(f'{c["name"]} ({c["role"]})' for c in sheet['characters'])
        log('Đang nhờ ChatGPT chia chương thành các đoạn diễn biến để vẽ tranh nền…')
        answer = promo.chatgpt.ask(f'story-art-{job["id"]}-{promo._round()}', SEGMENT_PROMPT.format(
            book=info['book'], genre=sheet['genre'], number=info['number'], people=people, lo=lo, hi=hi, lines=numbered(ledger)))
        stretches = check_segments(answer, ledger, sheet, seconds)
        for stretch in stretches:
            promo.add_cast(info['book_id'], stretch.pop('new'))
        plan = {'texts': texts, 'stretches': stretches, 'made': time.time()}
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding='utf-8')
    sheet = promo.sheet(info['book_id'])
    segments = []
    try:
        for number, stretch in enumerate(plan['stretches']):
            check()
            target = folder / f'seg-{number:02d}.png'
            if not target.is_file():
                log(f'Comfy vẽ tranh nền {number + 1}/{len(plan["stretches"])}…')
                promo.draw_scene(info, sheet, stretch, target, framing='background', salt=f'seg{number}:')
            segments.append({'start': stretch['start'], 'path': str(target), 'sha256': digest(target), 'key': stretch['key']})
    finally:
        promo.comfy.free()
    key = next(s for s in segments if s['key'])
    _thumbnail_from(promo, info, key['path'])
    return {'segments': segments, 'plan': str(plan_path)}


def _thumbnail_from(promo, info, picture):
    """The key moment's picture as the chapter's YouTube thumbnail (its words and title are kept)."""
    import shutil
    from .story_promo import compose, _sha, _write
    record = promo.promo(info)
    if not record or not record.get('hook'):
        return
    folder = promo._book(info['book_id']) / info['key']
    shutil.copyfile(picture, folder / 'art.png')
    compose(folder / 'art.png', record['hook'], info['number'], folder / 'thumb.jpg')
    _write(folder / 'promo.json', dict(record, state='ready', art='story-art', thumb_sha=_sha(folder / 'thumb.jpg'), updated=time.time()))


def frames(segments, orientation, folder):
    """One prepared still per stretch for this orientation (made once, reused by re-renders)."""
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    Path(folder).mkdir(parents=True, exist_ok=True)   # the pictures live with the chapter; the stills with the job
    out = []
    for number, segment in enumerate(segments):
        target = Path(folder) / f'frame-{orientation}-{number:02d}-{segment["sha256"][:12]}.png'
        if not target.is_file():
            with Image.open(segment['path']) as picture:
                picture = picture.convert('RGB')
                if orientation == 'ngang':
                    frame = ImageOps.fit(picture, (1920, 1080), Image.LANCZOS)
                else:
                    frame = ImageOps.fit(picture, (1080, 1920), Image.LANCZOS, centering=(0.65, 0.5))
                    frame = ImageEnhance.Brightness(frame.filter(ImageFilter.GaussianBlur(28))).enhance(0.45)
                    frame.paste(ImageOps.fit(picture, TOP_ART, Image.LANCZOS), (0, 0))
            part = target.with_name(target.name + '.part.png')
            frame.save(part, format='PNG')
            part.replace(target)
        out.append(str(target))
    return out


def background(segments, orientation, folder, seconds, intro, fps):
    """(ffmpeg inputs, filter producing [bg]): the stills crossfading at the stretches' times on the video clock."""
    stills = frames(segments, orientation, folder)
    times = [0.0] + [intro + s['start'] for s in segments[1:]]
    inputs, graph = [], []
    for number, still in enumerate(stills):
        end = times[number + 1] + FADE if number + 1 < len(stills) else seconds
        inputs += ['-loop', '1', '-framerate', str(fps), '-t', f'{max(end - times[number], FADE + 0.1):.3f}', '-i', still]
        graph.append(f'[{number}:v]format=yuv420p,setsar=1[s{number}]')
    current = 's0'
    for number in range(1, len(stills)):
        graph.append(f'[{current}][s{number}]xfade=transition=fade:duration={FADE}:offset={times[number]:.3f}[x{number}]')
        current = f'x{number}'
    graph.append(f'[{current}]null[bg]')
    return inputs, ';'.join(graph), len(stills)
