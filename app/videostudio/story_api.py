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
# Stories edited by ChatGPT at the same time; each has its own ChatGPT tab (the daemon's 'story-<source>' lane).
PARALLEL_EDITS = 2


def group_by_length(chapter_ids, words, target_minutes, speed=1.0, rate=4.2):
    """Consecutive chapters fill an episode until adding the next would pass the target by more than half of that
    chapter (estimated from word count), so episodes land near the target without splitting a chapter."""
    groups, current, length = [], [], 0.0
    for chapter_id in chapter_ids:
        seconds = words.get(chapter_id, 0) / (rate * speed)
        if current and length + seconds / 2 > target_minutes * 60:
            groups.append(current)
            current, length = [], 0.0
        current.append(chapter_id)
        length += seconds
    if current:
        groups.append(current)
    return groups


def register_story_routes(app, store, factory, pipeline, voices, same_origin, resume_editing=True):
    library = StoryLibrary(ffprobe=getattr(pipeline, 'ffprobe', 'ffprobe'), ffmpeg=getattr(pipeline, 'ffmpeg', 'ffmpeg'))
    editing = {}  # source name -> {'thread', 'log': [...], 'error', 'stop': Event (Pause), 'status': live request state}

    def edit_marker(path):
        """bien_tap/.dang-bien-tap: an edit to continue after a restart ({'from','to'}); 'paused': true keeps it
        stopped (a restart never resumes a story the owner paused)."""
        marker = path / 'bien_tap' / '.dang-bien-tap'
        try:
            saved = json.loads(marker.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = None
        return marker, saved if isinstance(saved, dict) else ({} if marker.is_file() else None)

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
    def chapters(book_id: str, q: str = '', page: int = 1, page_size: int = 50, status: str = '', view: str = ''):
        sync_done()
        return call(library.chapters, book_id, q, page, page_size, status, view)

    def sync_done():
        """Finished story videos mark their chapters done (Đã xong tab), merged episodes included."""
        with store.db() as db:
            rows = db.execute("SELECT json_extract(request,'$.story_snapshot') AS digest FROM jobs WHERE state='completed' "
                              "AND json_extract(request,'$.story_snapshot') IS NOT NULL").fetchall()
        library.mark_done(row['digest'] for row in rows)

    @app.get('/api/story/chapters/{chapter_id}/source')
    def chapter_source(chapter_id: str):
        """The machine-translated (convert) text of a chapter that came from a crawled source, for side-by-side review."""
        chapter = call(library.chapter, chapter_id)
        book = call(library.book, chapter['book_id'])
        source = (book.get('source') or '')
        if not source.startswith('source:') or not chapter.get('number'):
            raise HTTPException(404, 'Chương này không có bản convert gốc (không nhập từ Truyện nguồn)')
        path = source_dir(source[len('source:'):])
        from .story_editor import split_chapters
        _, raw = split_chapters((path / 'truyen_gop.txt').read_text(encoding='utf-8'))
        match = next((c for c in raw if c['number'] == chapter['number']), None)
        if not match:
            raise HTTPException(404, 'Không tìm thấy chương này trong bản convert')
        return {'number': match['number'], 'title': match['title'], 'text': match['text']}

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

    link_jobs = {}

    @app.post('/api/story/gameplay/link')
    def gameplay_link(data: dict, request: Request):
        """A gameplay video on Google Drive: downloaded in the background into the bounded cache (fetched again
        later if trimmed). Returns a task to poll, so a slow download never times out the page."""
        same_origin(request)
        from .drive_storage import CACHE, DriveError, DriveStorage, cache_trim, file_id_from_link
        url = str(data.get('url') or '')
        try:
            file_id = file_id_from_link(url)
            drive = DriveStorage(store)
            account, meta = drive.metadata(file_id)
        except (ValueError, DriveError) as error:
            raise HTTPException(422, str(error))
        name = meta.get('name') or (file_id + '.mp4')
        suffix = Path(name).suffix.lower() or '.mp4'
        if suffix not in ('.mp4', '.mkv', '.mov', '.webm'):
            raise HTTPException(422, 'Link này không phải video MP4/MKV/MOV/WebM')
        task = {'id': uuid.uuid4().hex, 'name': name, 'size': int(meta.get('size') or 0), 'received': 0, 'state': 'running', 'error': None, 'clip': None}
        link_jobs[task['id']] = task

        def work():
            try:
                target = CACHE / f'{file_id}{suffix}'
                sha, _ = drive.download(file_id, target, account=account, progress=lambda n: task.update(received=n))
                cache_trim(keep=[target])
                task.update(clip=library.add_gameplay_cached(target, name, sha, file_id, url), state='done')
            except Exception as error:
                task.update(state='failed', error=str(error)[:300])
        threading.Thread(target=work, daemon=True).start()
        return task

    @app.get('/api/story/gameplay/link/{task_id}')
    def gameplay_link_status(task_id: str):
        if task_id not in link_jobs:
            raise HTTPException(404, 'Không có lượt tải này')
        return link_jobs[task_id]

    # The Drive gameplay folder: new clips are fetched by themselves, used ones are moved into "Used".
    from .gameplay_drive import GameplayFolder
    gameplay_folder = GameplayFolder(store, library)
    app.state.gameplay_folder = gameplay_folder

    def folder_call(function, *args):
        from .drive_storage import DriveError
        try:
            return call(function, *args)
        except DriveError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/story/gameplay/drive-folder')
    def drive_folder_status():
        return gameplay_folder.status()

    @app.put('/api/story/gameplay/drive-folder')
    def drive_folder_set(data: dict, request: Request):
        same_origin(request)
        result = folder_call(gameplay_folder.configure, data)
        if data.get('link') and result['folder']:
            gameplay_folder.start_sync()  # fetch the clips already there right away
        return gameplay_folder.status()

    @app.get('/api/story/gameplay/drive-folders')
    def drive_folder_browse(account: str = '', parent: str = 'root'):
        return folder_call(gameplay_folder.browse, account or None, parent)

    @app.post('/api/story/gameplay/drive-folder/sync')
    def drive_folder_sync(request: Request):
        same_origin(request)
        return folder_call(gameplay_folder.start_sync)

    @app.put('/api/story/books/{book_id}/gameplay')
    def playlist(book_id: str, data: dict, request: Request):
        same_origin(request)
        return call(library.set_playlist, book_id, data.get('clips'))

    @app.delete('/api/story/gameplay/{clip_id}')
    def remove_clip(clip_id: str, request: Request):
        same_origin(request)
        # Deleted for good: out of every book, off this computer, and into Drive's trash (asked first on the thumbnail).
        return call(gameplay_folder.delete_clip, clip_id, clips_in_use())

    @app.get('/api/story/gameplay/{clip_id}/video')
    def clip_video(clip_id: str, request: Request):
        """Play a clip in the clip viewer: the file on this computer, or straight from Drive when only Drive has it
        (Range requests pass through, so the player can seek)."""
        from fastapi.responses import StreamingResponse
        from .drive_storage import DriveError
        try:
            where = call(gameplay_folder.playback, clip_id)
        except DriveError as error:
            raise HTTPException(502, str(error))
        if where[0] == 'file':
            return FileResponse(where[1], media_type='video/mp4' if where[1].suffix != '.webm' else 'video/webm')
        client, response = gameplay_folder.drive.stream(where[1], where[2], request.headers.get('range'))
        if response.status_code not in (200, 206):
            client.close()
            raise HTTPException(502, f'Drive không trả clip (mã {response.status_code})')
        headers = {k: v for k, v in response.headers.items() if k.lower() in ('content-length', 'content-range')}
        headers['Accept-Ranges'] = 'bytes'

        def body():
            try:
                yield from response.iter_bytes(1024 * 1024)
            finally:
                response.close()
                client.close()
        return StreamingResponse(body(), status_code=response.status_code, headers=headers, media_type='video/mp4')

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

    @app.post('/api/story/books/{book_id}/retake')
    def retake(book_id: str, data: dict, request: Request):
        """Mark a sentence the voice read wrong; adding the chapter to the queue again re-reads only that part."""
        same_origin(request)
        try:
            return library.retake(book_id, data.get('text'))
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy truyện')
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/story/books/{book_id}/issues')
    def book_issues(book_id: str, code: str = '', limit: int = 1000):
        """Soát chữ for the whole book: every spot to check, in reading order."""
        try:
            return library.issues(book_id, code, limit)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy truyện')

    @app.post('/api/story/books/{book_id}/strip-notes')
    def strip_notes(book_id: str, request: Request):
        """Xoá lời bình: every author/translator note in the book; the old text stays in Bản cũ."""
        same_origin(request)
        try:
            return library.strip_notes(book_id)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy truyện')

    @app.get('/api/story/books/{book_id}/pronunciation-suggestions')
    def pronunciation_suggestions(book_id: str):
        """Abbreviations, numbers glued to units, clock times and symbols across the book, with a proposed reading."""
        from .story_pronounce import suggest
        try:
            book_data = library.book(book_id)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy truyện')
        with library.db() as db:
            texts = [r['text'] for r in db.execute('SELECT text FROM chapters WHERE book_id=? AND deleted=0', (book_id,))]
        existing = [r.get('from') for r in (book_data.get('settings') or {}).get('pronunciations') or []]
        return {'items': suggest(texts, existing), 'chapters': len(texts)}

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
        target = data.get('target_minutes', 30)
        if not isinstance(chapter_ids, list) or not chapter_ids or len(chapter_ids) > 500 or mode not in ('each', 'merge', 'group'):
            raise HTTPException(422, 'Chọn 1–500 chương và cách tạo video')
        if mode == 'group' and (type(target) is not int or not 5 <= target <= 180):
            raise HTTPException(422, 'Độ dài mỗi tập từ 5 đến 180 phút')
        audio_only = data.get('audio_only', False)
        if type(audio_only) is not bool:
            raise HTTPException(422, 'audio_only phải là bật/tắt')
        book_data = call(library.book, book_id)
        settings, layout = book_data['settings'], book_data['layout']
        if not audio_only and not layout.get('horizontal', True) and not layout.get('vertical', True):
            raise HTTPException(422, 'Chọn ít nhất một định dạng: ngang hoặc dọc')
        clips, _ = library.playable(book_id)
        if not clips and not audio_only:
            raise HTTPException(422, 'Chưa có clip gameplay cho truyện này. Mở Gameplay → Thêm clip trước khi xếp hàng (nghe thử giọng vẫn dùng được).')
        import shutil
        free = shutil.disk_usage(store.outputs).free
        outputs = int(bool(layout.get('horizontal', True))) + int(bool(layout.get('vertical', True)))
        index = library.index(book_id)
        order = {c['id']: c['order'] for c in index}
        if any(c not in order for c in chapter_ids):
            raise HTTPException(409, 'Có chương không còn trong truyện. Tải lại danh sách.')
        chapter_ids = sorted(dict.fromkeys(chapter_ids), key=order.get)
        listing = {c['id']: c['words'] for c in index}
        biggest = max(listing.get(c, 0) for c in chapter_ids) if mode == 'each' else sum(listing.get(c, 0) for c in chapter_ids)
        minutes = biggest / 4.2 / 60
        from .story_pipeline import space_needed
        need = space_needed(minutes * 60, 0 if audio_only else outputs)
        if free < need:
            raise HTTPException(422, f'Ổ lưu video ({store.outputs}) chỉ còn {free / 2**30:.1f} GB, cần khoảng {need / 2**30:.1f} GB cho một video. Giải phóng ổ trước khi xếp hàng.')
        if mode == 'group':
            groups = group_by_length(chapter_ids, listing, target, float(settings.get('speech_speed', 1) or 1))
        else:
            groups = [[c] for c in chapter_ids] if mode == 'each' else [chapter_ids]
        if len(groups) > 100:
            raise HTTPException(422, 'Tối đa 100 video mỗi lần xếp hàng; chọn ít chương hơn')
        items = []
        for index, group in enumerate(groups):
            snapshot = call(library.freeze, book_id, group, f'{idempotency_key}:{index}:{"audio:" if audio_only else ""}{",".join(group)}', audio_only)
            words = sum(len(c['text'].split()) for c in snapshot['chapters'])
            seconds = estimate_seconds(' '.join(c['text'] for c in snapshot['chapters']), speed=settings.get('speech_speed', 1))
            from .story_pipeline import episode_title
            title = f'{book_data["title"]} · {episode_title(snapshot)}' + (' (lời đọc)' if audio_only else '')
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

    @app.post('/api/story/jobs/{job_id}/rerender')
    def rerender(job_id: str, request: Request):
        """Re-make a finished chapter video with the book's current look: same text, voice and gameplay footage."""
        same_origin(request)
        try:
            job = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Không tìm thấy video')
        if job['request'].get('workflow_mode') != 'story_narration' or job['state'] != 'completed':
            raise HTTPException(422, 'Chỉ dựng lại được video Kể truyện đã xong')
        folder = Path(job['output'])
        try:
            old = json.loads((folder / 'story-snapshot.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise HTTPException(409, 'Không còn dữ liệu nội dung của video này')
        plan_file = folder / 'story-gameplay' / 'plan.json'
        plan = json.loads(plan_file.read_text(encoding='utf-8')) if plan_file.is_file() else None
        snapshot = call(library.freeze_rerender, old, f'rerender:{job_id}:{time.time_ns()}', plan)
        from .story_pipeline import episode_title
        title = f'{snapshot["book"]["title"]} · {episode_title(snapshot)} (dựng lại)'
        body = {**{k: v for k, v in job['request'].items() if k not in ('story_snapshot', 'idea')}, 'idea': f'Kể truyện · {title}', 'story_snapshot': snapshot['sha256']}
        try:
            batch = factory.create_prepared_batch(job['request'].get('project') or snapshot['book']['title'], 'story',
                                                  [{'title': title, 'content': f'{title}\nsnapshot {snapshot["sha256"][:12]}', 'request': body}],
                                                  'story-rerender:' + snapshot['sha256'])
        except ValueError as error:
            raise HTTPException(422, str(error))
        return {'batch': batch, 'videos': 1}

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
        running = bool(state.get('thread') and state['thread'].is_alive())
        _, saved = edit_marker(path)
        from .story_editor import split_chapters
        try:
            total = len(split_chapters((path / 'truyen_gop.txt').read_text(encoding='utf-8'))[1])
        except (OSError, ValueError):
            total = 0
        with library.db() as db:
            book_row = db.execute('SELECT id FROM books WHERE source=? AND deleted=0', ('source:' + path.name,)).fetchone()
        return {'name': path.name, 'title': profile.get('ten_truyen') or meta.get('title') or path.name, 'chapters': total,
                'edited': len(progress), 'needs_review': sorted(int(k) for k, v in progress.items() if v.get('problems')),
                'merged': (path / 'truyen_gop_bien_tap.txt').is_file(), 'running': running,
                'pausing': running and bool(state.get('stop') and state['stop'].is_set()),
                'paused': not running and bool(saved and saved.get('paused')),
                'status': (state.get('status') or '') if running else '',
                'log': (state.get('log') or [])[-8:], 'error': state.get('error'), 'book_id': book_row['id'] if book_row else None,
                'url': meta.get('introduction_url'), 'downloaded': meta.get('downloaded_chapters')}

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
        # The log of a paused run goes on, so the owner sees where it stopped and where it went on.
        log = (editing.get(name) or {}).get('log') or []
        stop = threading.Event()

        def chapter_done(number):
            try:
                result = import_edited(path)
                if result and (result['added'] or result['updated']):
                    log.append(time.strftime('%H:%M ') + f'  Chương {number} đã vào Kể truyện, có thể duyệt và tạo video.')
            except Exception as error:
                log.append('Chưa thêm được chương vào Kể truyện: ' + str(error)[:200])

        def work():
            from .story_editor import Paused, StoryEditor
            try:
                StoryEditor(path, log=lambda line: log.append(time.strftime('%H:%M ') + str(line)),
                            status=lambda text: editing[name].update(status=text), stop=stop).run(first, last, on_chapter=chapter_done)
                marker.unlink(missing_ok=True)  # finished: nothing to resume
                try:
                    from .notify import send
                    send(store, f'📚 Đã biên tập xong truyện: {source_info(path)["title"]}')
                except Exception:
                    pass
            except Paused:
                log.append(time.strftime('%H:%M ') + 'Đã tạm dừng. Các chương đã xong vẫn giữ; bấm Tiếp tục để biên tập tiếp.')
            except Exception as error:
                editing[name]['error'] = str(error)[:500]
                log.append('Dừng: ' + str(error)[:300])
            finally:
                editing[name]['status'] = ''

        del log[:-40]
        thread = threading.Thread(target=work, name='story-edit-' + name, daemon=True)
        editing[name] = {'thread': thread, 'log': log, 'error': None, 'stop': stop, 'status': ''}
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
        if sum(s['thread'].is_alive() for s in editing.values()) >= PARALLEL_EDITS:
            raise HTTPException(409, f'Đang biên tập {PARALLEL_EDITS} truyện cùng lúc. Chờ một truyện xong rồi chạy tiếp truyện này.')
        _, saved = edit_marker(path)
        saved = saved or {}
        if saved.get('paused') and (state or {}).get('log') is not None:
            state['log'].append(time.strftime('%H:%M ') + 'Tiếp tục biên tập.')
        start_edit(path, data.get('from', saved.get('from')), data.get('to', saved.get('to')))
        return source_info(path)

    @app.post('/api/story/sources/{name}/pause')
    def pause_source(name: str, request: Request):
        """Tạm dừng: stops after the request in flight reaches a safe point (a chapter not yet typed is withdrawn; one
        already sent keeps being read by the daemon, so Tiếp tục reads its answer without sending it again).
        Finished chapters stay; a server restart does not resume a paused story."""
        same_origin(request)
        path = source_dir(name)
        marker, saved = edit_marker(path)
        state = editing.get(name)
        running = bool(state and state['thread'].is_alive())
        if not running and saved is None:
            raise HTTPException(409, 'Truyện này không đang biên tập')
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({**(saved or {}), 'paused': True}), encoding='utf-8')
        if running and not state['stop'].is_set():
            state['stop'].set()
            state['log'].append(time.strftime('%H:%M ') + 'Đang tạm dừng…')
        return source_info(path)

    # An edit interrupted by a server restart continues by itself (the daemon journal prevents resending a chapter).
    # Only the real server resumes, from its startup (lifespan): importing the app (tests, helper apps) must never
    # start ChatGPT requests. 2026-11-16: resuming at import made every full test run edit the live story a second
    # time in the test process, sending each chapter twice.
    def resume_edits():
        if not resume_editing or not SOURCES_ROOT.is_dir():
            return
        for marker in SOURCES_ROOT.glob('*/bien_tap/.dang-bien-tap'):
            try:
                saved = json.loads(marker.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                saved = {}
            if isinstance(saved, dict) and saved.get('paused'):
                continue  # paused by the owner: stays paused until Tiếp tục
            running = editing.get(marker.parent.parent.name)
            if running and running['thread'].is_alive():
                continue
            if sum(s['thread'].is_alive() for s in editing.values()) < PARALLEL_EDITS:
                start_edit(marker.parent.parent, saved.get('from'), saved.get('to'))
    app.state.resume_story_edits = resume_edits

    # --- WikiCV downloader (the user's own crawl_wikicv.py, run as is) -----------------------------------------
    from .story_crawl import Crawler

    def crawl_done(result):
        if result.get('stopped'):
            return
        try:
            from .notify import send
            title = result.get('title') or result.get('url')
            if result.get('error'):
                send(store, f'⚠️ Tải truyện dừng: {title}\n{result["error"][:300]}')
            else:
                send(store, f'📥 Đã tải {result.get("saved", 0)} chương mới: {title}' + (' (đến chương mới nhất)' if result.get('complete') else ''))
        except Exception:
            pass
    crawler = Crawler(SOURCES_ROOT.parent / 'crawl_wikicv.py', SOURCES_ROOT, on_finish=crawl_done)

    @app.get('/api/story/crawl')
    def crawl_status():
        return crawler.status()

    @app.post('/api/story/crawl')
    def crawl_start(data: dict, request: Request):
        """Download a WikiCV book (or only its new chapters) into the sources folder; saved chapters are never fetched again."""
        same_origin(request)
        try:
            return crawler.start(data.get('url'), data.get('max_chapters', 0))
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.post('/api/story/crawl/stop')
    def crawl_stop(request: Request):
        same_origin(request)
        return crawler.stop()

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
