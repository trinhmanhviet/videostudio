"""HTTP routes for the "Kể truyện" workspace. Writes require the same origin; nothing accepts a filesystem path."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import Header, HTTPException, Request
from fastapi.responses import FileResponse

from .paths import APP_ROOT
from .story_library import ConflictError, StoryLibrary, estimate_seconds, natural_key

SOURCES_ROOT = Path(os.getenv('VS_STORY_SOURCES', str(APP_ROOT.parent / 'wikicv_auto_v3_2_mixed_titles' / 'du_lieu_truyen')))
MAX_UPLOAD = 20 * 1024 ** 3


def register_story_routes(app, store, factory, pipeline, voices, same_origin):
    library = StoryLibrary(ffprobe=getattr(pipeline, 'ffprobe', 'ffprobe'), ffmpeg=getattr(pipeline, 'ffmpeg', 'ffmpeg'))
    editing = {}  # source name -> {'thread', 'log': [...], 'error', 'done'}

    def call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'"))
        except ConflictError as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))

    # --- books & chapters ----------------------------------------------------------------------------------
    @app.get('/api/story/books')
    def books():
        return {'items': library.books()}

    @app.post('/api/story/books')
    def create_book(data: dict, request: Request):
        same_origin(request)
        return call(library.create_book, data.get('title'))

    @app.get('/api/story/books/{book_id}')
    def book(book_id: str):
        return call(library.book, book_id)

    @app.patch('/api/story/books/{book_id}')
    def update_book(book_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.update_book, book_id, data)

    @app.delete('/api/story/books/{book_id}')
    def delete_book(book_id: str, request: Request):
        same_origin(request)
        return call(library.delete_book, book_id)

    @app.get('/api/story/books/{book_id}/chapters')
    def chapters(book_id: str, q: str = '', page: int = 1, page_size: int = 50):
        return call(library.chapters, book_id, q, page, page_size)

    @app.post('/api/story/books/{book_id}/chapters/import')
    def import_chapters(book_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.import_files, book_id, data.get('files'), data.get('split', True) is not False)

    @app.post('/api/story/books/{book_id}/chapters/order')
    def order(book_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.reorder, book_id, data.get('chapter_ids') or [])

    @app.post('/api/story/books/{book_id}/chapters/delete')
    def delete_chapters(book_id: str, data: dict, request: Request):
        same_origin(request)
        if data.get('confirm') is not True:
            raise HTTPException(422, 'Cần xác nhận xoá chương')
        return call(library.delete_chapters, book_id, data.get('chapter_ids') or [])

    @app.get('/api/story/chapters/{chapter_id}')
    def chapter(chapter_id: str):
        return call(library.chapter, chapter_id)

    @app.put('/api/story/chapters/{chapter_id}')
    def save_chapter(chapter_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.save_chapter, chapter_id, data)

    @app.get('/api/story/chapters/{chapter_id}/history')
    def chapter_history(chapter_id: str):
        call(library.chapter, chapter_id)
        return {'items': library.history(chapter_id)}

    @app.post('/api/story/chapters/{chapter_id}/restore')
    def restore_chapter(chapter_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.restore, chapter_id, data.get('revision'))

    # --- gameplay ------------------------------------------------------------------------------------------
    @app.get('/api/story/gameplay')
    def gameplay(book_id: str = ''):
        return call(library.gameplay, book_id or None)

    @app.put('/api/story/gameplay')
    async def upload_gameplay(request: Request, name: str):
        """Raw streamed body (no base64, no multipart); hashed while it is written; stored once by content."""
        same_origin(request)
        suffix = Path(name).suffix.lower()
        if suffix not in ('.mp4', '.mkv', '.mov', '.webm'):
            raise HTTPException(422, 'Chỉ nhận MP4, MKV, MOV hoặc WebM')
        temporary = library.gameplay_root / '.incoming' / (uuid.uuid4().hex + '.part')
        digest, size = hashlib.sha256(), 0
        try:
            with open(temporary, 'wb') as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, 'Video quá lớn (tối đa 20 GB)')
                    digest.update(chunk)
                    handle.write(chunk)
            if size == 0:
                raise HTTPException(422, 'Tệp rỗng')
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return call(library.add_gameplay, temporary, name, digest.hexdigest())

    @app.put('/api/story/books/{book_id}/gameplay')
    def playlist(book_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.set_playlist, book_id, data.get('clips'))

    @app.delete('/api/story/gameplay/{clip_id}')
    def remove_clip(clip_id: str, request: Request):
        same_origin(request)
        return call(library.remove_gameplay, clip_id, clips_in_use())

    @app.get('/api/story/gameplay/{clip_id}/thumbnail')
    def thumbnail(clip_id: str):
        try:
            return FileResponse(call(library.thumbnail, clip_id), media_type='image/jpeg')
        except Exception as error:
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(404, 'Không tạo được ảnh xem trước')

    def clips_in_use():
        used = set()
        snapshots = set()
        with store.db() as db:
            for row in db.execute("SELECT request FROM jobs WHERE state NOT IN ('completed','cancelled')"):
                request = json.loads(row['request'] or '{}')
                if request.get('story_snapshot'):
                    snapshots.add(request['story_snapshot'])
            for row in db.execute("SELECT request FROM factory_items WHERE job_id IS NULL AND state IN ('pending','waiting','dispatching')"):
                request = json.loads(row['request'] or '{}')
                if request.get('story_snapshot'):
                    snapshots.add(request['story_snapshot'])
        for digest in snapshots:
            try:
                used.update(c['id'] for c in library.snapshot(digest)['gameplay'])
            except (OSError, ValueError):
                continue
        return used

    # --- backgrounds & previews ------------------------------------------------------------------------------
    @app.get('/api/story/backgrounds')
    def backgrounds():
        return {'items': library.backgrounds()}

    @app.put('/api/story/backgrounds')
    async def upload_background(request: Request, name: str):
        same_origin(request)
        return call(library.add_background, await request.body(), name)

    @app.get('/api/story/backgrounds/{background_id}/image')
    def background_image(background_id: str):
        path = library.background_path(background_id)
        if not path:
            raise HTTPException(404, 'Không có ảnh nền')
        return FileResponse(path)

    @app.post('/api/story/books/{book_id}/preview')
    def layout_preview(book_id: str, data: dict, request: Request):
        """A still frame of each layout (first frame of the playlist + titles + a sample caption). Never moves the gameplay cursor."""
        same_origin(request)
        from .story_preview import still, test_clip
        kind = data.get('kind', 'still')
        orientation = data.get('orientation', 'ngang')
        if orientation not in ('ngang', 'doc') or kind not in ('still', 'clip'):
            raise HTTPException(422, 'Kiểu xem trước không hợp lệ')
        try:
            path = (still if kind == 'still' else test_clip)(library, pipeline, book_id, data.get('chapter_id'), orientation)
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'"))
        except (ValueError, RuntimeError) as error:
            raise HTTPException(422, str(error)[:500])
        return {'url': f'/api/story/previews/{path.name}', 'kind': kind, 'orientation': orientation}

    @app.get('/api/story/previews/{name}')
    def preview_file(name: str):
        if not re.fullmatch(r'[a-z0-9\-]+\.(png|mp4)', name):
            raise HTTPException(404, 'Không có bản xem trước')
        path = library.root / 'previews' / name
        if not path.is_file():
            raise HTTPException(404, 'Không có bản xem trước')
        return FileResponse(path)

    # --- queue -----------------------------------------------------------------------------------------------
    @app.post('/api/story/books/{book_id}/enqueue')
    def enqueue(book_id: str, data: dict, request: Request, idempotency_key: str | None = Header(default=None)):
        """Each selected chapter becomes one queued video (or all selected chapters one merged episode).
        Every episode is frozen first, so later edits never change what was queued."""
        same_origin(request)
        if not idempotency_key or not re.fullmatch(r'[A-Za-z0-9_\-:.]{8,120}', idempotency_key):
            raise HTTPException(422, 'Idempotency-Key required')
        chapter_ids = data.get('chapter_ids')
        mode = data.get('mode', 'each')
        if not isinstance(chapter_ids, list) or not chapter_ids or len(chapter_ids) > 100 or mode not in ('each', 'merge'):
            raise HTTPException(422, 'Chọn 1–100 chương và cách tạo video')
        book_data = call(library.book, book_id)
        settings, layout = book_data['settings'], book_data['layout']
        if not layout.get('horizontal', True) and not layout.get('vertical', True):
            raise HTTPException(422, 'Chọn ít nhất một định dạng: ngang hoặc dọc')
        clips = [c for c in library.gameplay(book_id)['items'] if c['available']]
        if not clips:
            raise HTTPException(422, 'Chưa có clip gameplay cho truyện này. Mở Gameplay → Thêm clip trước khi xếp hàng (nghe thử giọng vẫn dùng được).')
        import shutil
        free = shutil.disk_usage(store.outputs).free
        outputs = int(bool(layout.get('horizontal', True))) + int(bool(layout.get('vertical', True)))
        order = {c: i for i, c in enumerate(library.chapters(book_id, page_size=200)['all_ids'])}
        if any(c not in order for c in chapter_ids):
            raise HTTPException(409, 'Có chương không còn trong truyện. Tải lại danh sách.')
        chapter_ids = sorted(dict.fromkeys(chapter_ids), key=order.get)
        listing = {c['id']: c['words'] for c in library.chapters(book_id, page_size=200)['items']}
        biggest = max(listing.get(c, 0) for c in chapter_ids) if mode == 'each' else sum(listing.get(c, 0) for c in chapter_ids)
        minutes = biggest / 4.2 / 60
        need = (300 + minutes * (45 + 25 * outputs + 5)) * 1024 * 1024
        if free < need:
            raise HTTPException(422, f'Ổ lưu video ({store.outputs}) chỉ còn {free / 2**30:.1f} GB, cần khoảng {need / 2**30:.1f} GB cho một video. Giải phóng ổ trước khi xếp hàng.')
        groups = [[c] for c in chapter_ids] if mode == 'each' else [chapter_ids]
        items = []
        for index, group in enumerate(groups):
            snapshot = call(library.freeze, book_id, group, f'{idempotency_key}:{index}:{",".join(group)}')
            words = sum(len(c['text'].split()) for c in snapshot['chapters'])
            seconds = estimate_seconds(' '.join(c['text'] for c in snapshot['chapters']), speed=settings.get('speech_speed', 1))
            from .story_pipeline import episode_title
            title = f'{book_data["title"]} · {episode_title(snapshot)}'
            request_body = {'idea': f'Kể truyện · {title} · {words} từ', 'voice_id': settings['voice_id'],
                            'duration_seconds': int(min(7200, max(8, round(seconds)))), 'project': book_data['title'],
                            'content_style': 'story', 'workflow_mode': 'story_narration', 'story_snapshot': snapshot['sha256'],
                            'image_provider': 'comfy', 'speech_engine': settings.get('speech_engine', 'vieneu'),
                            'speech_rhythm': settings.get('speech_rhythm', 'story'), 'speech_speed': float(settings.get('speech_speed', 1)),
                            'speech_batch_size': int(settings.get('speech_batch_size', 256))}
            if request_body['speech_engine'] == 'khanhtts':
                request_body['khanh_steps'] = int(settings.get('khanh_steps', 32))
                if settings.get('speech_reference_text'):
                    request_body['speech_reference_text'] = settings['speech_reference_text']
            items.append({'title': title, 'content': f'{title}\n{words} từ · snapshot {snapshot["sha256"][:12]}', 'request': request_body})
        try:
            batch = factory.create_prepared_batch(book_data['title'], 'story', items, 'story:' + idempotency_key)
        except ValueError as error:
            raise HTTPException(409 if 'already used' in str(error) else 422, str(error))
        return {'batch': batch, 'videos': len(items)}

    # --- crawled sources + ChatGPT editing ----------------------------------------------------------------------
    def source_dir(name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_\-]{0,200}', name or ''):
            raise HTTPException(404, 'Không có truyện nguồn này')
        path = (SOURCES_ROOT / name).resolve()
        if path.parent != SOURCES_ROOT.resolve() or not (path / 'truyen_gop.txt').is_file():
            raise HTTPException(404, 'Không có truyện nguồn này')
        return path

    def source_info(path):
        def read(file, fallback):
            try:
                return json.loads((path / file).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return fallback
        meta = read('truyen.json', {})
        profile = read('bien_tap/ho_so.json', {})
        progress = read('bien_tap/tien_do.json', {}).get('chapters', {})
        state = editing.get(path.name) or {}
        from .story_editor import split_chapters
        try:
            total = len(split_chapters((path / 'truyen_gop.txt').read_text(encoding='utf-8'))[1])
        except (OSError, ValueError):
            total = 0
        with library.db() as db:
            book_row = db.execute('SELECT id FROM books WHERE source=? AND deleted=0', ('source:' + path.name,)).fetchone()
        return {'name': path.name, 'title': profile.get('ten_truyen') or meta.get('title') or path.name, 'chapters': total,
                'edited': len(progress), 'needs_review': sorted(int(k) for k, v in progress.items() if v.get('problems')),
                'merged': (path / 'truyen_gop_bien_tap.txt').is_file(), 'running': bool(state.get('thread') and state['thread'].is_alive()),
                'log': (state.get('log') or [])[-8:], 'error': state.get('error'), 'book_id': book_row['id'] if book_row else None}

    @app.get('/api/story/sources')
    def sources():
        if not SOURCES_ROOT.is_dir():
            return {'items': [], 'root_missing': True}
        folders = sorted((p for p in SOURCES_ROOT.iterdir() if p.is_dir() and (p / 'truyen_gop.txt').is_file()), key=lambda p: natural_key(p.name))
        return {'items': [source_info(p) for p in folders]}

    def import_edited(path):
        """Bring the edited merged file into the library (one book per source); unchanged chapters are skipped."""
        merged = path / 'truyen_gop_bien_tap.txt'
        if not merged.is_file():
            return None
        info = source_info(path)
        book_data = library.create_book(info['title'], source='source:' + path.name)
        result = library.import_files(book_data['id'], [{'name': path.name + '.txt', 'text': merged.read_text(encoding='utf-8')}], True)
        return {'book': library.book(book_data['id']), **result}

    def start_edit(path, first=None, last=None):
        name = path.name
        marker = path / 'bien_tap' / '.dang-bien-tap'
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'from': first, 'to': last}), encoding='utf-8')
        log = []

        def chapter_done(number):
            try:
                result = import_edited(path)
                if result and (result['added'] or result['updated']):
                    log.append(time.strftime('%H:%M ') + f'  Chương {number} đã vào Kể truyện, có thể duyệt và tạo video.')
            except Exception as error:
                log.append('Chưa thêm được chương vào Kể truyện: ' + str(error)[:200])

        def work():
            from .story_editor import StoryEditor
            try:
                StoryEditor(path, log=lambda line: log.append(time.strftime('%H:%M ') + str(line))).run(first, last, on_chapter=chapter_done)
                marker.unlink(missing_ok=True)  # finished: nothing to resume
            except Exception as error:
                editing[name]['error'] = str(error)[:500]
                log.append('Dừng: ' + str(error)[:300])

        thread = threading.Thread(target=work, name='story-edit-' + name, daemon=True)
        editing[name] = {'thread': thread, 'log': log, 'error': None}
        thread.start()

    @app.post('/api/story/sources/{name}/edit')
    def edit_source(name: str, data: dict, request: Request):
        """Start (or continue) the chapter-by-chapter ChatGPT edit in the background; finished chapters are never resent.
        Every finished chapter is added to the book at once, so it can be reviewed and queued while the rest runs."""
        same_origin(request)
        path = source_dir(name)
        state = editing.get(name)
        if state and state['thread'].is_alive():
            return source_info(path)
        if any(s['thread'].is_alive() for s in editing.values()):
            raise HTTPException(409, 'Đang biên tập một truyện khác. Chờ xong rồi chạy tiếp truyện này.')
        start_edit(path, data.get('from'), data.get('to'))
        return source_info(path)

    # An edit interrupted by a server restart continues by itself (the daemon journal prevents resending a chapter).
    if SOURCES_ROOT.is_dir():
        for marker in SOURCES_ROOT.glob('*/bien_tap/.dang-bien-tap'):
            try:
                saved = json.loads(marker.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                saved = {}
            if not editing:
                start_edit(marker.parent.parent, saved.get('from'), saved.get('to'))

    @app.get('/api/story/sources/{name}')
    def source_status(name: str):
        return source_info(source_dir(name))

    @app.post('/api/story/sources/{name}/import')
    def import_source(name: str, request: Request):
        """Bring the edited merged file into the library as a book (once); importing again only updates changed chapters."""
        same_origin(request)
        path = source_dir(name)
        try:
            result = import_edited(path)
        except ValueError as error:
            raise HTTPException(422, str(error))
        if result is None:
            raise HTTPException(422, 'Truyện này chưa có bản biên tập. Bấm Biên tập bằng ChatGPT trước.')
        return result

    return library
