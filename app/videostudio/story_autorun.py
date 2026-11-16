""""Làm dần cả truyện": the chapters not yet made go into the shared video queue one episode at a time, in reading order.

Before each episode the tool checks that the gameplay not yet used is enough for that episode's narration. When it is
not (and "Dùng lại clip đã dùng" is off), the book stops there instead of making an episode that repeats old footage,
and says so in the page and on Telegram. Every check (about twice a minute, and right after "Lấy clip mới") looks
again, so the book goes on by itself once enough new clips arrive.

The run state of each book is a small file (lam-dan/<book>.json in the story library), so a server restart picks it up
where it was. This only queues jobs: the GPU work still runs one job at a time in the shared queue.
"""
from __future__ import annotations

import json
import threading
import time

from .notify import emit
from .story_library import estimate_seconds

# Extra narration allowed for when the real voice reads a little slower than the estimate.
MARGIN = 1.05
CHECK_EVERY = 30


def minutes(seconds):
    value = max(0.0, seconds) / 60
    text = f'{value:.0f}' if value >= 10 else f'{value:.1f}'
    return text[:-2] if text.endswith('.0') else text


def fresh_seconds(library, book_id, layout):
    """Gameplay this book can still play before cut_plan would loop back to footage already shown: from the cursor to
    the end of the playable list. A list made only of used Drive clips (the fallback) has none."""
    items, fell_back = library.playable(book_id)
    if fell_back:
        return 0.0
    usable = [c for c in items if c['end'] - c['start'] >= 1]
    if not usable:
        return 0.0
    cursor = library.cursor(book_id) if layout.get('continue_gameplay', True) else {'clip': 0, 'offset': 0.0}
    index = min(int(cursor.get('clip', 0)), len(usable) - 1)
    first = usable[index]
    left = first['end'] - (first['start'] + max(0.0, float(cursor.get('offset', 0.0))))
    return (left if left >= .5 else 0.0) + sum(c['end'] - c['start'] for c in usable[index + 1:])


class AutoRun:
    """queue(book_id, chapter_ids, key) -> snapshot digest of the queued episode (raises with a readable message).
    episode_states(digests) -> {digest: (state, message)}, state 'done' | 'active' | 'failed'; a digest with no job
    and no queue item is left out."""

    def __init__(self, library, queue, episode_states, notify=None):
        self.library, self.queue, self.episode_states = library, queue, episode_states
        self.notify = notify or (lambda text: emit('story', text))
        self.folder = library.root / 'lam-dan'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.thread = None

    # --- state files -------------------------------------------------------------------------------------------
    def _path(self, book_id):
        return self.folder / f'{book_id}.json'

    def load(self, book_id):
        try:
            value = json.loads(self._path(book_id).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _save(self, state):
        state['updated'] = time.time()
        path = self._path(state['book_id'])
        part = path.with_suffix('.part')
        part.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        part.replace(path)

    # --- owner actions -----------------------------------------------------------------------------------------
    def start(self, book_id, mode='each', target_minutes=30):
        if mode not in ('each', 'group'):
            raise ValueError('Làm dần cả truyện dùng "Mỗi chương một video" hoặc "Gộp thành tập theo độ dài"')
        if mode == 'group' and (type(target_minutes) is not int or not 5 <= target_minutes <= 180):
            raise ValueError('Độ dài mỗi tập từ 5 đến 180 phút')
        book = self.library.book(book_id)
        with self.lock:
            old = self.load(book_id) or {}
            state = {'book_id': book_id, 'title': book['title'], 'mode': mode, 'target_minutes': int(target_minutes),
                     'state': 'running', 'message': 'Bắt đầu làm dần cả truyện.', 'current': old.get('current'),
                     'run': int(old.get('run', 0)) + 1, 'sequence': 0, 'started': time.time()}
            self._save(state)
            self.notify(f'🎬 Bắt đầu làm dần cả truyện: {book["title"]}')
            return self.tick_book(book_id)

    def pause(self, book_id):
        with self.lock:
            state = self._require(book_id)
            state.update(state='paused', message='Đã tạm dừng. Tập đang trong hàng đợi vẫn làm xong; bấm Tiếp tục để làm tiếp.')
            self._save(state)
            return self.status(book_id)

    def resume(self, book_id):
        """Tiếp tục: after a pause, an error or a stop for gameplay. An episode that failed is queued again."""
        with self.lock:
            state = self._require(book_id)
            if state['state'] == 'error':
                state['current'] = None
                state['run'] = int(state.get('run', 0)) + 1  # a fresh queue key: the failed batch is not reused
                state['sequence'] = 0
            state.update(state='running', message='Tiếp tục làm dần cả truyện.')
            self._save(state)
            return self.tick_book(book_id)

    def stop(self, book_id):
        """Dừng hẳn: the run ends; an episode already in the queue is left to finish."""
        with self.lock:
            state = self.load(book_id)
            self._path(book_id).unlink(missing_ok=True)
            if state:
                self.notify(f'⏹ Đã dừng hẳn làm dần cả truyện: {state.get("title") or book_id}')
            return {'state': 'off'}

    def _require(self, book_id):
        state = self.load(book_id)
        if not state:
            raise KeyError('Truyện này chưa bật Làm dần cả truyện')
        return state

    def status(self, book_id):
        state = self.load(book_id)
        if not state:
            return {'state': 'off'}
        return {key: state.get(key) for key in ('state', 'message', 'mode', 'target_minutes', 'current', 'todo',
                                                'fresh_seconds', 'need_seconds', 'reuse', 'stopped_at', 'updated')}

    # --- the check ---------------------------------------------------------------------------------------------
    def tick(self):
        """Look at every book with a run: queue its next episode when the previous one is done and gameplay allows."""
        with self.lock:
            for path in sorted(self.folder.glob('*.json')):
                try:
                    self.tick_book(path.stem)
                except Exception as error:  # one book never blocks the others
                    state = self.load(path.stem)
                    if state and state.get('state') == 'running':
                        state.update(state='error', message=f'Lỗi khi xếp tập tiếp theo: {str(error)[:300]}')
                        self._save(state)

    def tick_book(self, book_id):
        with self.lock:
            state = self.load(book_id)
            if not state:
                return {'state': 'off'}
            if state['state'] not in ('running', 'waiting_gameplay'):
                return self.status(book_id)
            try:
                book = self.library.book(book_id)
            except KeyError:
                self._path(book_id).unlink(missing_ok=True)  # the book was deleted
                return {'state': 'off'}
            state['title'] = book['title']
            # Episodes of this book still in the queue (this run's and any queued by hand): wait for them, so the
            # gameplay position already includes their footage.
            with self.library.db() as db:
                rows = db.execute('SELECT snapshot_sha256, chapter_ids FROM episodes WHERE book_id=? AND done IS NULL',
                                  (book_id,)).fetchall()
            known = self.episode_states([r['snapshot_sha256'] for r in rows]) if rows else {}
            finished = [digest for digest, (kind, _) in known.items() if kind == 'done']
            if finished:
                self.library.mark_done(finished)
            current = state.get('current')
            if current:
                kind, detail = known.get(current['snapshot'], ('done', '') if current['snapshot'] in self._done_digests(book_id) else (None, ''))
                if kind == 'active':
                    state.update(state='running', message=f'Đang làm tập {current["label"]} trong hàng đợi.')
                    self._save(state)
                    return self.status(book_id)
                if kind in ('failed', None):
                    why = detail or 'không còn trong hàng đợi'
                    state.update(state='error', message=f'Tập {current["label"]} chưa xong ({why[:300]}). Bấm Tiếp tục để làm lại tập này.')
                    self._save(state)
                    self.notify(f'⚠️ {book["title"]}: tập {current["label"]} lỗi, làm dần cả truyện tạm dừng.\n{why[:300]}')
                    return self.status(book_id)
                state['current'] = None
            if any(kind == 'active' for kind, _ in known.values()):
                state.update(state='running', message='Chờ tập của truyện này đang trong hàng đợi làm xong.')
                self._save(state)
                return self.status(book_id)
            return self._next(state, book)

    def _done_digests(self, book_id):
        with self.library.db() as db:
            return {r['snapshot_sha256'] for r in db.execute('SELECT snapshot_sha256 FROM episodes WHERE book_id=? AND done IS NOT NULL', (book_id,))}

    def _next(self, state, book):
        book_id = book['id']
        done = self.library.done_chapter_ids(book_id)
        todo = [c for c in self.library.index(book_id) if c['id'] not in done]
        state['todo'] = len(todo)
        if not todo:
            if state.get('message') != IDLE:
                self.notify(f'✅ {book["title"]}: đã làm hết các chương hiện có. Chương mới thêm vào sẽ tự được làm tiếp.')
            state.update(state='running', message=IDLE, stopped_at=None)
            self._save(state)
            return self.status(book_id)
        speed = float(book['settings'].get('speech_speed', 1) or 1)
        if state['mode'] == 'group':
            from .story_api import group_by_length
            ids = group_by_length([c['id'] for c in todo], {c['id']: c['words'] for c in todo}, state['target_minutes'], speed)[0]
        else:
            ids = [todo[0]['id']]
        chosen = [c for c in todo if c['id'] in set(ids)]
        text = ' '.join(self.library.chapter(c['id'])['text'] for c in chosen)
        need = estimate_seconds(text, speed=speed) * MARGIN
        label = f'chương {chosen[0]["order"]}' + (f'–{chosen[-1]["order"]}' if len(chosen) > 1 else '')
        reuse = bool(self.library.gameplay_setting('reuse', False))
        fresh = fresh_seconds(self.library, book_id, book['layout'])
        state.update(need_seconds=round(need, 1), fresh_seconds=round(fresh, 1), reuse=reuse)
        if not reuse and fresh < need:
            message = (f'Truyện {book["title"]} dừng ở chương {chosen[0]["order"]}: gameplay mới còn {minutes(fresh)} phút, '
                       f'tập cần {minutes(need)} phút. Thêm clip vào thư mục Drive (hoặc tab Gameplay); đủ clip thì tool tự chạy tiếp.')
            if state['state'] != 'waiting_gameplay' or state.get('stopped_at') != chosen[0]['id']:
                self.notify('⏸ ' + message)
            state.update(state='waiting_gameplay', message=message, stopped_at=chosen[0]['id'])
            self._save(state)
            return self.status(book_id)
        if state['state'] == 'waiting_gameplay':
            self.notify(f'▶️ {book["title"]}: đã đủ gameplay mới, làm tiếp từ {label}.')
        key = f'lam-dan-{book_id[:16]}-{state.get("run", 1)}-{state.get("sequence", 0)}'
        state['sequence'] = int(state.get('sequence', 0)) + 1
        self._save(state)  # the key is taken before queueing: a crash in between never queues the same key twice
        try:
            digest = self.queue(book_id, ids, key)
        except Exception as error:
            why = str(getattr(error, 'detail', '') or error)[:300]
            state.update(state='error', message=f'Chưa đưa được {label} vào hàng đợi: {why}. Bấm Tiếp tục để thử lại.')
            self._save(state)
            self.notify(f'⚠️ {book["title"]}: chưa đưa được {label} vào hàng đợi, làm dần cả truyện tạm dừng.\n{why}')
            return self.status(book_id)
        state.update(state='running', current={'snapshot': digest, 'chapter_ids': ids, 'label': label, 'minutes': round(need / 60, 1)},
                     message=f'Đã đưa tập {label} vào hàng đợi.', stopped_at=None, todo=len(todo))
        self._save(state)
        return self.status(book_id)

    # --- background --------------------------------------------------------------------------------------------
    def start_loop(self, stop=None):
        """The real server only (lifespan): a check every CHECK_EVERY seconds; a restart picks up every saved run."""
        if self.thread and self.thread.is_alive():
            return
        stop = stop or threading.Event()

        def loop():
            while True:
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - the next check tries again
                    import logging
                    logging.getLogger(__name__).exception('Story auto run check will retry')
                if stop.wait(CHECK_EVERY):
                    return
        self.thread = threading.Thread(target=loop, name='story-autorun', daemon=True)
        self.thread.start()


IDLE = 'Đã làm hết các chương hiện có. Chương mới thêm vào (ví dụ từ biên tập ChatGPT) sẽ tự được làm tiếp.'
