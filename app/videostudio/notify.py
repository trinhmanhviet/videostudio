"""Telegram notices for everything the tool does: videos, story edits, posts, Drive, the server and the ChatGPT service.

The owner's own bot token and chat id are entered in Settings and kept in the jobs database (data/, never in git);
the token is never written to a log or an error text. Work code only calls emit(group, text): it puts the line in an
in-memory queue and returns at once. One background thread sends: lines that arrive close together go out as one
message, finished chapters of a story are merged into one line, Telegram's speed limits are kept, and a refused or
failed send is retried with growing pauses. Whatever happens to Telegram or the network, emit() never raises and never
waits, so a video, an edit or a post is never slowed or broken by a notice.

Watch reads what already gets recorded (the job event log, the publishing schedule, the ChatGPT service status, free
disk space) and turns changes into notices, so most of the tool needs no notice code of its own. On start the current
state is taken as known, so old jobs never notify again.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import HTTPException, Request

GROUPS = {
    'video': ('Video', 'Vào hàng đợi, bắt đầu, xong, lỗi, huỷ, tự dùng phương án dự phòng.'),
    'story': ('Truyện', 'Biên tập bằng ChatGPT (bắt đầu, từng chương, tạm dừng, kẹt, lỗi, xong) và tải truyện.'),
    'publish': ('Đăng bài', 'Đăng YouTube, Facebook xong kèm link, hoặc lỗi.'),
    'drive': ('Drive và gameplay', 'Đưa video lên Drive, lấy clip gameplay, xoá clip.'),
    'system': ('Hệ thống', 'Server, dịch vụ ChatGPT khởi động lại, ChatGPT cần đăng nhập, ổ đĩa sắp đầy.'),
}
STAGES = {'plan': 'lên kế hoạch', 'research': 'tìm tư liệu', 'script': 'viết kịch bản', 'speech': 'giọng đọc',
          'images': 'hình ảnh', 'subtitles': 'phụ đề', 'music': 'nhạc nền', 'render': 'dựng video', 'verify': 'kiểm tra'}
# Lines of the job log that say the tool switched to a fallback by itself.
FALLBACK = re.compile(r'dự phòng|bị chặn|hết lượt|hết clip|ComfyUI thay thế|chuyển sang CPU|vẽ bằng ComfyUI|gửi lại một lần', re.I)
DAEMON = 'http://127.0.0.1:' + os.getenv('VS_CDP_PORT', '8879')
LOW_DISK, DISK_OK = 10 * 2**30, 15 * 2**30
LIMIT = 3800  # Telegram allows 4096 characters per message


class TelegramError(Exception):
    def __init__(self, message, retry_after=None, permanent=False):
        super().__init__(message)
        self.retry_after, self.permanent = retry_after, permanent


def clean(text, token):
    """An error text with the bot token taken out (httpx errors quote the request URL)."""
    text = str(text)
    return text.replace(token, '***') if token else text


def telegram_send(token, chat, text):
    try:
        response = httpx.post(f'https://api.telegram.org/bot{token}/sendMessage', timeout=20, trust_env=True,
                              json={'chat_id': chat, 'text': text[:4000], 'disable_web_page_preview': True})
    except httpx.HTTPError as error:
        raise TelegramError(clean(f'Không kết nối được Telegram ({type(error).__name__})', token)) from None
    if response.status_code == 200:
        return
    try:
        data = response.json()
    except ValueError:
        data = {}
    description = clean(str(data.get('description') or response.text)[:200], token)
    if response.status_code == 429:
        raise TelegramError('Telegram bảo gửi chậm lại', retry_after=(data.get('parameters') or {}).get('retry_after') or 5)
    if response.status_code >= 500:
        raise TelegramError(f'Telegram đang lỗi (HTTP {response.status_code})')
    if response.status_code in (401, 404):
        raise TelegramError('Token bot sai hoặc đã bị thu hồi. Lấy lại token ở @BotFather.', permanent=True)
    if 'blocked' in description:
        raise TelegramError('Bạn đã chặn bot. Mở bot trong Telegram và bấm Start.', permanent=True)
    if 'chat not found' in description:
        raise TelegramError('Chat ID sai, hoặc bạn chưa nhắn cho bot lần nào.', permanent=True)
    raise TelegramError('Telegram từ chối: ' + description, permanent=True)


class Notifier:
    """The send queue. settings() gives {'token','chat','enabled','groups'}; send(token, chat, text) raises TelegramError."""

    def __init__(self, settings, send=telegram_send, *, window=4.0, hold=90.0, interval=3.0, per_minute=18, limit=400,
                 retries=5, clock=time.monotonic, stop=None):
        self.settings, self.send = settings, send
        self.window, self.hold, self.interval, self.per_minute, self.limit, self.retries = window, hold, interval, per_minute, limit, retries
        self.clock, self.stop_event = clock, stop or threading.Event()
        self.cond = threading.Condition()
        self.items = deque()
        self.carry = []          # messages a network failure kept back, sent first next round
        self.sends = deque()     # clock() of recent sends, for the speed limits
        self.dropped = 0
        self.thread = None
        self.last_error = self.last_sent = None
        self.sent = 0

    # --- the work side: never raises, never waits ------------------------------------------------------------
    def emit(self, group, text, merge=None):
        """merge=(key, head, part): lines with the same key are sent as one, head + 'part, part, part'."""
        try:
            with self.cond:
                if len(self.items) >= self.limit:
                    self.items.popleft()
                    self.dropped += 1
                now = self.clock()
                due = now + self.window
                if merge:
                    first = next((i['due'] for i in self.items if i['merge'] and i['merge'][0] == merge[0]), None)
                    due = first if first is not None else now + self.hold
                self.items.append({'group': group, 'text': str(text), 'merge': merge, 'due': due})
                self.cond.notify()
        except Exception:  # noqa: BLE001 - a notice must never break the work that sent it
            pass

    # --- the sending side ------------------------------------------------------------------------------------
    def take(self, block=True):
        """The lines due now, plus any line merged with one of them. block waits for the first due line."""
        with self.cond:
            while True:
                now = self.clock()
                ready = [i for i in self.items if i['due'] <= now]
                if ready or not block or self.stop_event.is_set():
                    break
                wait = min(i['due'] for i in self.items) - now if self.items else 30
                self.cond.wait(max(.05, min(wait, 30)))
            keys = {i['merge'][0] for i in ready if i['merge']}
            taken = [i for i in self.items if i['due'] <= now or (i['merge'] and i['merge'][0] in keys)]
            for item in taken:
                self.items.remove(item)
            dropped, self.dropped = self.dropped, 0
        if dropped:
            taken.insert(0, {'group': None, 'text': f'(Bỏ bớt {dropped} tin cũ vì gửi không kịp)', 'merge': None})
        return taken

    @staticmethod
    def compose(items, groups):
        """Short readable messages: merged lines joined, repeated lines counted, split under Telegram's size limit."""
        lines, merged, counts = [], {}, {}
        for item in items:
            if item['group'] is not None and not groups.get(item['group'], True):
                continue
            if item['merge']:
                key, head, part = item['merge']
                if key not in merged:
                    merged[key] = [head, []]
                    lines.append(('merge', key))
                if str(part) not in merged[key][1]:
                    merged[key][1].append(str(part))
            elif item['text'] in counts:
                counts[item['text']] += 1
            else:
                counts[item['text']] = 1
                lines.append(('text', item['text']))
        texts = []
        for kind, value in lines:
            if kind == 'merge':
                head, parts = merged[value]
                texts.append(head + ', '.join(parts))
            else:
                texts.append(value + (f' (×{counts[value]})' if counts[value] > 1 else ''))
        messages, current = [], ''
        for text in texts:
            text = text[:LIMIT]
            if current and len(current) + 2 + len(text) > LIMIT:
                messages.append(current)
                current = ''
            current = current + '\n\n' + text if current else text
        if current:
            messages.append(current)
        return messages

    def _pace(self):
        """Wait so that sends stay under Telegram's limits (about one a second, 20 a minute to a group)."""
        while not self.stop_event.is_set():
            now = self.clock()
            while self.sends and now - self.sends[0] > 60:
                self.sends.popleft()
            waits = []
            if self.sends:
                waits.append(self.interval - (now - self.sends[-1]))
            if len(self.sends) >= self.per_minute:
                waits.append(60 - (now - self.sends[0]))
            wait = max(waits, default=0)
            if wait <= 0:
                return
            self.stop_event.wait(wait)

    def deliver(self, text, settings):
        """True: sent. False: dropped for good (wrong token, chat). None: network still failing; try again later."""
        token, chat = settings.get('token'), settings.get('chat')
        for attempt in range(self.retries + 1):
            self._pace()
            if self.stop_event.is_set():
                return None
            try:
                self.send(token, chat, text)
            except TelegramError as error:
                self.last_error = clean(error, token)
                if error.permanent:
                    return False
                delay = error.retry_after or min(60, 2 * 2 ** attempt)
            except Exception as error:  # noqa: BLE001 - any other failure is treated like a network one
                self.last_error = clean(f'{type(error).__name__}: {error}', token)[:300]
                delay = min(60, 2 * 2 ** attempt)
            else:
                self.sends.append(self.clock())
                self.sent += 1
                self.last_sent, self.last_error = time.time(), None
                return True
            if attempt < self.retries:
                self.stop_event.wait(delay)
        return None

    def pump(self, block=True):
        """One round: take due lines, send them. Returns how many messages were sent."""
        items = self.take(block)
        try:
            settings = self.settings() or {}
        except Exception:  # noqa: BLE001
            settings = {}
        if not (settings.get('enabled', True) and settings.get('token') and settings.get('chat')):
            self.carry = []
            return 0
        messages = self.carry + (self.compose(items, settings.get('groups') or {}) if items else [])
        self.carry, sent = [], 0
        for index, message in enumerate(messages):
            result = self.deliver(message, settings)
            if result is None:  # still offline: keep what is left (bounded) and pause before the next round
                self.carry = messages[index:][-30:]
                self.stop_event.wait(60)
                break
            sent += bool(result)
        return sent

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.pump()
            except Exception:  # noqa: BLE001 - the sender never dies
                self.stop_event.wait(5)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, name='telegram-notify', daemon=True)
            self.thread.start()

    def waiting(self):
        with self.cond:
            return len(self.items) + len(self.carry)


_notifier: Notifier | None = None


def emit(group, text, merge=None):
    """Queue a notice. Never raises, never waits; without a configured notifier it does nothing."""
    notifier = _notifier
    if notifier is not None:
        notifier.emit(group, text, merge)


def _minutes(seconds):
    seconds = int(seconds or 0)
    return f'{seconds // 60} phút {seconds % 60} giây' if seconds >= 60 else f'{seconds} giây'


def _size(n):
    return f'{n / 2**30:.1f} GB'.replace('.', ',') if n >= 2**30 else f'{round(n / 2**20)} MB'


# --- turning recorded state into notices ---------------------------------------------------------------------------
def video_notice(event, title, job=None):
    """(text, extra) for one row of the job event log, or None when it is not worth a notice."""
    kind, stage, detail = event['event'], event['stage'], (event['detail'] or '')
    where = STAGES.get(stage, stage or '')
    if kind == 'created':
        return '🎬 Vào hàng đợi: ' + title
    if kind == 'started':
        return '▶️ Bắt đầu làm video: ' + title
    if kind == 'completed' and stage == 'verify':
        checkpoints = (job or {}).get('checkpoints') or {}
        seconds = (checkpoints.get('verify') or {}).get('duration_seconds')
        path = (checkpoints.get('render') or {}).get('video')
        return '✅ Video xong: ' + title + (f' ({_minutes(seconds)})' if seconds else '') + (f'\n📁 {path}' if path else '')
    if kind == 'failed':
        return f'❌ Video lỗi ở bước {where}: {title}\n{detail[:300]}'.rstrip()
    if kind == 'retry':
        return f'🔁 Lỗi tạm ở bước {where}, tool tự thử lại: {title}\n{detail[:200]}'.rstrip()
    if kind == 'retried':
        return f'🔁 Làm lại bước {where}: {title}'
    if kind == 'cancel_requested':
        return '🛑 Đã huỷ video: ' + title
    if kind == 'awaiting_visual_review':
        return '👀 Chờ bạn duyệt ảnh: ' + title
    if kind == 'awaiting_flow_account':
        return '⏸ Chờ đổi tài khoản Flow: ' + title
    if kind == 'service_crash_resume':
        return '♻️ Server tắt giữa chừng, video tự chạy tiếp: ' + title
    if kind == 'job_deleted':
        return '🗑 Đã xoá video: ' + title
    if kind == 'progress' and FALLBACK.search(detail):
        return f'🛟 Tự dùng phương án dự phòng ({where}): {title}\n{detail[:250]}'
    return None


def publish_notice(row, before):
    """A change of state of one scheduled post, or None."""
    state = row['state']
    if state == before:
        return None
    platform = {'youtube': 'YouTube', 'facebook': 'Facebook'}.get(row['platform'], row['platform'])
    title, link = row['title'] or 'Video', row.get('remote_url') or ''
    if state == 'published':
        return f'📢 Đã đăng {platform}: {title}' + (f'\n{link}' if link else '')
    if state == 'scheduled_remote':
        when = time.strftime('%H:%M %d/%m', time.localtime(row['publish_at']))
        return f'📤 Đã tải lên {platform}, hẹn đăng lúc {when}: {title}' + (f'\n{link}' if link else '')
    if state == 'processing' and before in ('scheduled', 'uploading'):
        return f'📤 Đã tải lên {platform}, đang chờ nền tảng xử lý: {title}' + (f'\n{link}' if link else '')
    if state in ('blocked', 'needs_attention', 'failed'):
        return f'⚠️ Đăng {platform} lỗi: {title}\n{(row.get("error") or "")[:300]}'.rstrip()
    if state == 'cancelled':
        return f'🛑 Đã huỷ lịch đăng {platform}: {title}'
    return None


class Watch:
    """Polls what the tool already records and emits notices for changes. Every check survives its own errors."""

    def __init__(self, store, emit=emit, daemon=DAEMON, http=None, disks=None, get_setting=None, set_setting=None):
        self.store, self.emit, self.daemon = store, emit, daemon
        self.http = http or (lambda url: httpx.get(url, timeout=5, trust_env=False).json())
        self.disks = disks
        self.get_setting = get_setting or (lambda key, default=None: _get(store, key, default))
        self.set_setting = set_setting or (lambda key, value: _set(store, key, value))
        self.cursor = None
        self.posts = None
        self.fallbacks = set()
        self.daemon_state = None   # {'up':bool, 'started':..., 'auth':bool}
        self.daemon_misses = 0
        self.low = set()

    def title(self, job_id):
        try:
            with self.store.db() as db:
                row = db.execute('SELECT title FROM factory_items WHERE job_id=?', (job_id,)).fetchone()
            if row and row['title']:
                return row['title']
        except Exception:  # noqa: BLE001 - no factory table in some setups
            pass
        try:
            job = self.store.get(job_id)
            request = job.get('request') or {}
            text = request.get('title') or request.get('idea') or 'Video'
            return str(text).strip().splitlines()[0][:120] if str(text).strip() else 'Video'
        except Exception:  # noqa: BLE001 - deleted job
            return 'Video'

    def videos(self):
        with self.store.db() as db:
            if self.cursor is None:
                saved = self.get_setting('events_seq')
                top = db.execute('SELECT COALESCE(MAX(seq),0) m FROM events').fetchone()['m']
                self.cursor = saved if isinstance(saved, int) and saved <= top else top
            rows = [dict(r) for r in db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT 500', (self.cursor,))]
        started = set()
        for row in rows:
            self.cursor = row['seq']
            kind = row['event']
            if kind == 'started':
                # one "bắt đầu" per job and run: only the first stage started after it was queued again
                with self.store.db() as db:
                    earlier = db.execute("""SELECT event FROM events WHERE job=? AND seq<? AND event IN
                        ('started','created','retried','failed','cancel_requested') ORDER BY seq DESC LIMIT 1""",
                                         (row['job'], row['seq'])).fetchone()
                if row['job'] in started or (earlier and earlier['event'] == 'started'):
                    continue
                started.add(row['job'])
            if kind == 'progress':
                if not FALLBACK.search(row['detail'] or ''):
                    continue
                same = (row['job'], re.sub(r'\d+', '#', row['detail'] or ''))
                if same in self.fallbacks:
                    continue
                self.fallbacks.add(same)
            job = None
            if kind == 'completed' and row['stage'] == 'verify':
                try:
                    job = self.store.get(row['job'])
                except Exception:  # noqa: BLE001
                    job = None
            text = video_notice(row, self.title(row['job']), job)
            if text:
                self.emit('system' if kind == 'service_crash_resume' else 'video', text)
        if rows:
            self.set_setting('events_seq', self.cursor)

    def publishing(self):
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publishing_schedules'").fetchone():
                return
            rows = [dict(r) for r in db.execute('SELECT id,platform,title,state,remote_url,error,publish_at FROM publishing_schedules')]
        current = {r['id']: r['state'] for r in rows}
        if self.posts is not None:
            for row in rows:
                before = self.posts.get(row['id'], 'scheduled')
                text = publish_notice(row, before)
                if text:
                    self.emit('publish', text)
        self.posts = current

    def chatgpt(self):
        try:
            status = self.http(self.daemon + '/api/status')
            up, started, auth = True, status.get('started_at'), status.get('last_error') == 'authentication_required'
            self.daemon_misses = 0
        except Exception:  # noqa: BLE001 - not answering
            self.daemon_misses += 1
            if self.daemon_misses < 2 or (self.daemon_state and not self.daemon_state['up']):
                return
            up, started, auth = False, None, False
        before, self.daemon_state = self.daemon_state, {'up': up, 'started': started, 'auth': auth}
        if before is None:
            return
        if before['up'] and not up:
            self.emit('system', '🔴 Dịch vụ ChatGPT (cổng 8879) không phản hồi.')
        elif up and (not before['up'] or (started and before['started'] and started != before['started'])):
            self.emit('system', '🔄 Dịch vụ ChatGPT đã khởi động lại.')
        if auth and not before['auth']:
            self.emit('system', '🔐 ChatGPT cần đăng nhập hoặc xác minh. Mở cửa sổ Chrome riêng của tool để làm.')

    def disk(self):
        for path in (self.disks() if self.disks else _disk_paths(self.store)):
            try:
                anchor = Path(path).anchor or str(path)
                free = shutil.disk_usage(anchor).free
            except OSError:
                continue
            if free < LOW_DISK and anchor not in self.low:
                self.low.add(anchor)
                self.emit('system', f'💾 Ổ {anchor.rstrip(chr(92))} sắp đầy: còn {_size(free)}.')
            elif free > DISK_OK:
                self.low.discard(anchor)

    def run(self, stop):
        checks = [(self.videos, 3), (self.publishing, 5), (self.chatgpt, 30), (self.disk, 300)]
        last = {check: 0.0 for check, _ in checks}
        while not stop.is_set():
            now = time.monotonic()
            for check, every in checks:
                if now - last[check] >= every:
                    last[check] = now
                    try:
                        check()
                    except Exception:  # noqa: BLE001 - one broken check never stops the others
                        pass
            stop.wait(1)


def _disk_paths(store):
    from .paths import DATA_ROOT
    paths = {str(DATA_ROOT)}
    try:
        paths.add(str(store.outputs))
    except Exception:  # noqa: BLE001
        pass
    return sorted(paths)


# --- settings ------------------------------------------------------------------------------------------------------
def _get(store, key, default=None):
    with store.db() as db:
        row = db.execute('SELECT value FROM notify_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default


def _set(store, key, value):
    with store.db() as db:
        db.execute('INSERT OR REPLACE INTO notify_settings VALUES(?,?)', (key, json.dumps(value)))


def settings_of(store):
    return {'token': _get(store, 'telegram_token'), 'chat': _get(store, 'telegram_chat'),
            'enabled': _get(store, 'enabled', True), 'groups': _get(store, 'groups', {}) or {}}


def send(store, text):
    """Send one message now (the Gửi thử button). Raises TelegramError with a readable reason."""
    settings = settings_of(store)
    if not settings['token'] or not settings['chat']:
        return False
    telegram_send(settings['token'], settings['chat'], text)
    return True


def register_notify_routes(app, store, same_origin, stop_event=None, background=True, send_function=telegram_send):
    with store.db() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS notify_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
    stop = stop_event or threading.Event()
    notifier = Notifier(lambda: settings_of(store), send_function, stop=stop)
    watch = Watch(store)

    def status():
        s = settings_of(store)
        return {'configured': bool(s['token'] and s['chat']), 'has_token': bool(s['token']), 'chat': s['chat'],
                'enabled': s['enabled'],
                'groups': [{'key': k, 'label': label, 'hint': hint, 'on': s['groups'].get(k, True)} for k, (label, hint) in GROUPS.items()],
                'last_error': notifier.last_error, 'last_sent': notifier.last_sent, 'waiting': notifier.waiting()}

    @app.get('/api/notify')
    def get_settings():
        return status()

    @app.put('/api/notify')
    def put_settings(data: dict, request: Request):
        same_origin(request)
        if 'token' in data:
            token = str(data['token'] or '').strip()
            if token and (not re.fullmatch(r'\d{5,15}:[\w-]{20,80}', token)):
                raise HTTPException(422, 'Token bot Telegram có dạng 123456789:ABC… (lấy ở @BotFather)')
            _set(store, 'telegram_token', token or None)
            notifier.last_error = None
        if 'chat' in data:
            chat = str(data['chat'] or '').strip()[:50]
            if chat and not re.fullmatch(r'-?\d{3,20}|@\w{4,40}', chat):
                raise HTTPException(422, 'Chat ID là một dãy số, ví dụ 123456789 (nhóm thì bắt đầu bằng -100)')
            _set(store, 'telegram_chat', chat or None)
            notifier.last_error = None
        if 'enabled' in data:
            _set(store, 'enabled', bool(data['enabled']))
        if isinstance(data.get('groups'), dict):
            groups = settings_of(store)['groups']
            groups.update({k: bool(v) for k, v in data['groups'].items() if k in GROUPS})
            _set(store, 'groups', groups)
        return status()

    @app.post('/api/notify/detect-chat')
    def detect_chat(request: Request):
        """After the owner sends any message to their bot, read it to learn the chat id (no typing needed)."""
        same_origin(request)
        token = _get(store, 'telegram_token')
        if not token:
            raise HTTPException(422, 'Nhập token bot trước')
        try:
            response = httpx.get(f'https://api.telegram.org/bot{token}/getUpdates', timeout=20)
            updates = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(422, clean(f'Không kết nối được Telegram ({type(error).__name__})', token)) from None
        if not updates.get('ok'):
            raise HTTPException(422, 'Token bot sai hoặc đã bị thu hồi. Lấy lại token ở @BotFather.')
        chats = [(u.get('message') or u.get('channel_post') or {}).get('chat', {}).get('id') for u in updates.get('result', [])]
        chats = [c for c in chats if c]
        if not chats:
            raise HTTPException(422, 'Chưa thấy tin nhắn nào. Mở Telegram, nhắn bất kỳ chữ gì cho bot của bạn rồi bấm lại.')
        _set(store, 'telegram_chat', str(chats[-1]))
        return status()

    @app.post('/api/notify/test')
    def test(request: Request):
        same_origin(request)
        settings = settings_of(store)
        if not settings['token'] or not settings['chat']:
            raise HTTPException(422, 'Nhập token bot và chat ID trước')
        try:
            send_function(settings['token'], settings['chat'], '🔔 VideoStudio: thông báo đã hoạt động. Từ giờ mọi việc của tool sẽ báo vào đây.')
        except TelegramError as error:
            raise HTTPException(422, clean(error, settings['token'])) from None
        except Exception as error:  # noqa: BLE001
            raise HTTPException(422, clean(f'Không gửi được: {type(error).__name__}', settings['token'])) from None
        notifier.last_error, notifier.last_sent = None, time.time()
        return {'sent': True}

    def start():
        """Called from the real server's startup: the sender, the watchers and the "server started" notice."""
        global _notifier
        _notifier = notifier
        notifier.start()
        threading.Thread(target=watch.run, args=(stop,), name='notify-watch', daemon=True).start()
        emit('system', '🟢 Server VideoStudio đã khởi động.')

    app.state.notify_start = start if background else None
    app.state.notifier = notifier
    return status
