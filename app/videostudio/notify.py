"""Phone notifications through a Telegram bot the user creates: a video finished, a video failed, a book edit finished.

The bot token and chat id are entered by the user in Settings and stored in the jobs database. Messages carry only the
video title, length and a short error line. On start every current state is recorded first, so old jobs never notify.
"""
from __future__ import annotations

import json
import threading
import time

import httpx
from fastapi import HTTPException, Request


def _get(store, key, default=None):
    with store.db() as db:
        row = db.execute('SELECT value FROM notify_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default


def _set(store, key, value):
    with store.db() as db:
        db.execute('INSERT OR REPLACE INTO notify_settings VALUES(?,?)', (key, json.dumps(value)))


def send(store, text):
    token, chat = _get(store, 'telegram_token'), _get(store, 'telegram_chat')
    if not token or not chat:
        return False
    response = httpx.post(f'https://api.telegram.org/bot{token}/sendMessage', timeout=20,
                          json={'chat_id': chat, 'text': text[:3900], 'disable_web_page_preview': True})
    if response.status_code != 200:
        raise RuntimeError('Telegram từ chối: ' + response.text[:200])
    return True


def register_notify_routes(app, store, same_origin, stop_event=None, background=True):
    with store.db() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS notify_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notify_seen(job_id TEXT PRIMARY KEY, state TEXT NOT NULL);''')

    def status():
        return {'configured': bool(_get(store, 'telegram_token') and _get(store, 'telegram_chat')),
                'has_token': bool(_get(store, 'telegram_token')), 'chat': _get(store, 'telegram_chat'),
                'enabled': _get(store, 'enabled', True)}

    @app.get('/api/notify')
    def get_settings():
        return status()

    @app.put('/api/notify')
    def put_settings(data: dict, request: Request):
        same_origin(request)
        if 'token' in data:
            token = str(data['token'] or '').strip()
            if token and (':' not in token or len(token) > 200):
                raise HTTPException(422, 'Token bot Telegram có dạng 123456789:ABC…')
            _set(store, 'telegram_token', token or None)
        if 'chat' in data:
            _set(store, 'telegram_chat', str(data['chat'] or '').strip()[:50] or None)
        if 'enabled' in data:
            _set(store, 'enabled', bool(data['enabled']))
        return status()

    @app.post('/api/notify/detect-chat')
    def detect_chat(request: Request):
        """After the user sends any message to their bot, read it to learn the chat id (no typing needed)."""
        same_origin(request)
        token = _get(store, 'telegram_token')
        if not token:
            raise HTTPException(422, 'Nhập token bot trước')
        updates = httpx.get(f'https://api.telegram.org/bot{token}/getUpdates', timeout=20).json()
        chats = [u.get('message', {}).get('chat', {}).get('id') for u in updates.get('result', []) if u.get('message')]
        if not chats:
            raise HTTPException(422, 'Chưa thấy tin nhắn nào. Mở Telegram, nhắn bất kỳ chữ gì cho bot của bạn rồi bấm lại.')
        _set(store, 'telegram_chat', str(chats[-1]))
        return status()

    @app.post('/api/notify/test')
    def test(request: Request):
        same_origin(request)
        try:
            if not send(store, '🔔 VideoStudio: thông báo đã hoạt động.'):
                raise HTTPException(422, 'Nhập token bot và chat ID trước')
        except RuntimeError as error:
            raise HTTPException(422, str(error))
        return {'sent': True}

    def title(job):
        with store.db() as db:
            row = db.execute('SELECT title FROM factory_items WHERE job_id=?', (job['id'],)).fetchone()
        return (row['title'] if row else None) or job['request'].get('idea', 'Video').splitlines()[0][:120]

    def tick(first):
        with store.db() as db:
            seen = {r['job_id']: r['state'] for r in db.execute('SELECT * FROM notify_seen')}
            rows = [dict(r) for r in db.execute("SELECT id,state,error,stage FROM jobs WHERE state IN ('completed','failed') ORDER BY updated DESC LIMIT 200")]
        for row in rows:
            if seen.get(row['id']) == row['state']:
                continue
            with store.db() as db:
                db.execute('INSERT OR REPLACE INTO notify_seen VALUES(?,?)', (row['id'], row['state']))
            if first or not _get(store, 'enabled', True):
                continue
            try:
                job = store.get(row['id'])
                if row['state'] == 'completed':
                    seconds = job['checkpoints'].get('verify', {}).get('duration_seconds') or 0
                    send(store, f'✅ Video xong: {title(job)}' + (f' ({int(seconds // 60)} phút {int(seconds % 60)} giây)' if seconds else ''))
                else:
                    send(store, f'❌ Video lỗi ở bước {row["stage"]}: {title(job)}\n{(row["error"] or "")[:300]}')
            except Exception:
                continue

    def loop():
        first = True
        while not (stop_event and stop_event.is_set()):
            try:
                tick(first)
                first = False
            except Exception:
                pass
            time.sleep(20)

    if background:
        threading.Thread(target=loop, name='notify', daemon=True).start()
    return status
