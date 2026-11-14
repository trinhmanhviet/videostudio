"""Layout previews for "Kể truyện": a still frame per orientation, or a 10-second test clip the user asks for.

Both use the same layout code as the real render (story_pipeline.write_ass / LAYOUTS) and the first clip of the book's
playlist. They never move the gameplay cursor, never run TTS and never write into the book's output folder.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .media import run
from .story_library import PRESET_BACKGROUNDS
from .story_pipeline import FPS, LAYOUTS, _background_input, layout_for, write_ass


def _context(library, book_id, chapter_id):
    book = library.book(book_id)
    listing = library.chapters(book_id, page_size=200)
    if not listing['items']:
        raise ValueError('Truyện chưa có chương nào')
    chosen = next((c for c in listing['items'] if c['id'] == chapter_id), listing['items'][0])
    chapter = library.chapter(chosen['id'])
    clips = [c for c in library.gameplay(book_id)['items'] if c['available']]
    if not clips:
        raise ValueError('Chưa có clip gameplay để xem bố cục. Thêm clip trong tab Gameplay.')
    text = re.sub(r'\s+', ' ', chapter['text']).strip()
    sentence = re.split(r'(?<=[.!?…])\s+', text)[0][:160]
    snapshot = {'book': {'id': book['id'], 'title': book['title']}, 'layout': book['layout'],
                'chapters': [{'id': chapter['id'], 'order': chosen['order'], 'number': chapter['number'], 'title': chapter['title'],
                              'read_title': chapter['read_title'], 'text': chapter['text']}],
                'background': str(library.background_path(book['layout'].get('background')) or '') or None,
                'background_preset': PRESET_BACKGROUNDS.get(book['layout'].get('background'), PRESET_BACKGROUNDS['preset:dem-xanh'])}
    return snapshot, clips[0], sentence


def _cues(sentence, orientation, seconds):
    from .story_pipeline import _wrap
    groups = _wrap(sentence, LAYOUTS[orientation]['line_chars'])[:1] or [['']]
    return [{'start': 0.0, 'end': seconds, 'lines': groups[0]}]


def _name(prefix, value, suffix):
    return f'{prefix}-' + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:20] + suffix


def _compose(library, pipeline, snapshot, clip, sentence, orientation, seconds, target, still):
    layout = layout_for(orientation, snapshot.get('layout'))
    width, height = layout['size']
    gx, gy, gw, gh = layout['game']
    folder = library.root / 'previews'
    ass = write_ass(folder / (target.stem + '.ass'), orientation, snapshot, _cues(sentence, orientation, seconds), True)
    background, bg_filter = _background_input(snapshot, width, height, seconds, folder, getattr(pipeline, 'ffmpeg', 'ffmpeg'))
    start = min(max(clip['start'], 0) + 3, max(0, clip['end'] - seconds - .5))
    gameplay = ['-ss', f'{start:.2f}', '-t', f'{seconds:.2f}', '-i', clip_path(library, clip['id'])]
    graph = (f'{bg_filter};[1:v]fps={FPS},scale={gw}:{gh}:force_original_aspect_ratio=decrease,setsar=1[g];'
             f'[bg][g]overlay=x={gx}+({gw}-w)/2:y={gy}+({gh}-h)/2:eof_action=repeat,ass={ass.name}[v]')
    args = [getattr(pipeline, 'ffmpeg', 'ffmpeg'), '-v', 'error', '-y', *background, *gameplay, '-filter_complex', graph, '-map', '[v]']
    if still:
        args += ['-frames:v', '1', target.name]
    else:
        from .story_pipeline import video_codec
        args += ['-t', f'{seconds:.2f}', '-r', str(FPS), *video_codec(getattr(pipeline, 'ffmpeg', 'ffmpeg')), '-pix_fmt', 'yuv420p',
                 '-an', '-movflags', '+faststart', target.name]
    from .media import _run_in
    _run_in(folder, args, lambda: None, timeout=180)
    ass.unlink(missing_ok=True)
    return target


def clip_path(library, clip_id):
    return library._clip_path(clip_id)


def still(library, pipeline, book_id, chapter_id, orientation):
    snapshot, clip, sentence = _context(library, book_id, chapter_id)
    key = {'o': orientation, 'snapshot': {k: v for k, v in snapshot.items() if k != 'chapters'}, 'chapter': snapshot['chapters'][0]['title'],
           'sentence': sentence, 'clip': clip['sha256'], 'start': clip['start'], 'v': 1}
    target = library.root / 'previews' / _name('still', key, '.png')
    if not target.is_file():
        _compose(library, pipeline, snapshot, clip, sentence, orientation, 1.0, target, True)
    return target


def test_clip(library, pipeline, book_id, chapter_id, orientation):
    snapshot, clip, sentence = _context(library, book_id, chapter_id)
    key = {'o': orientation, 'snapshot': {k: v for k, v in snapshot.items() if k != 'chapters'}, 'chapter': snapshot['chapters'][0]['title'],
           'sentence': sentence, 'clip': clip['sha256'], 'start': clip['start'], 'v': 1}
    target = library.root / 'previews' / _name('test', key, '.mp4')
    if not target.is_file():
        _compose(library, pipeline, snapshot, clip, sentence, orientation, 10.0, target, False)
    return target
