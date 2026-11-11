"""Durable, single-dispatch request mailbox for the opt-in Flow extension."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
import threading
import uuid

from .protocol import FlowRPCError, build_command, decode_result, parse_response

TERMINAL = frozenset(('completed', 'blocked', 'failed', 'uncertain'))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def secret_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class FlowRequestBridge:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._proof_lock = threading.Lock()
        self._proofs = {}
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS clients(
                    id TEXT PRIMARY KEY, secret TEXT NOT NULL, origin TEXT NOT NULL,
                    updated REAL NOT NULL, info TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(
                    id TEXT PRIMARY KEY, client TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    command TEXT NOT NULL, state TEXT NOT NULL, dispatch TEXT,
                    result TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            ''')

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def invitation(self):
        code = secrets.token_urlsafe(12)
        expires = time.time() + 300
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',
                       ('invitation', json.dumps({'hash': secret_hash(code), 'expires': expires})))
        return {'code': code, 'expires': expires}

    def pair(self, code, origin):
        if not isinstance(code, str):
            raise PermissionError('Mã kết nối không hợp lệ')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM settings WHERE key='invitation'").fetchone()
            invitation = json.loads(row['value']) if row else {}
            if invitation.get('expires', 0) < time.time() or not secrets.compare_digest(invitation.get('hash', ''), secret_hash(code)):
                raise PermissionError('Mã kết nối đã hết hạn hoặc không đúng')
            client, key = str(uuid.uuid4()), secrets.token_urlsafe(32)
            db.execute('INSERT INTO clients VALUES(?,?,?,?,?)',
                       (client, secret_hash(key), origin, time.time(), '{}'))
            db.execute("DELETE FROM settings WHERE key='invitation'")
        return {'client_id': client, 'key': key}

    def authenticate(self, client, key, origin):
        with self.db() as db:
            row = db.execute('SELECT secret,origin FROM clients WHERE id=?', (client,)).fetchone()
        if not row or row['origin'] != origin or not isinstance(key, str) or not secrets.compare_digest(row['secret'], secret_hash(key)):
            raise PermissionError('Extension chưa được ghép nối với hệ thống này')

    def status(self):
        now = time.time()
        with self.db() as db:
            rows = db.execute('SELECT id,updated,info FROM clients ORDER BY updated DESC LIMIT 10').fetchall()
            counts = dict(db.execute('SELECT state,COUNT(*) FROM commands GROUP BY state').fetchall())
        clients = [{'client_id': row['id'], 'age_seconds': round(max(0, now-row['updated']), 1),
                    'connected': now-row['updated'] <= 90, **json.loads(row['info'])} for row in rows]
        return {'experimental': True, 'production_enabled': False, 'clients': clients, 'counts': counts}

    def poll(self, client, info):
        # Only readiness flags are sent to Python; cookies/CSRF/session values stay inside Chrome.
        allowed = ('tab_open', 'session_ready', 'project_id', 'build', 'version', 'enabled',
                   'verification_sdk', 'verification_key_available', 'verification_guard_detected')
        safe = {key: info[key] for key in allowed if key in info}
        for key in ('tab_open', 'session_ready', 'enabled', 'verification_sdk', 'verification_key_available', 'verification_guard_detected'):
            if key in safe and type(safe[key]) is not bool:
                raise ValueError('Trạng thái extension không hợp lệ')
        if any(not isinstance(safe[key], str) or len(safe[key]) > 200 for key in ('project_id', 'build', 'version') if key in safe):
            raise ValueError('Thông tin phiên không hợp lệ')
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE clients SET updated=?,info=? WHERE id=?', (now, json.dumps(safe), client))
            # A lost callback never makes a write eligible for dispatch a second time.
            db.execute("UPDATE commands SET state='uncertain',updated=?,result=? WHERE client=? AND state='dispatching' AND updated<?",
                       (now, json.dumps({'code': 'callback_missing', 'message': 'Chưa nhận được biên nhận; không gửi lại request'}), client, now-180))
            db.execute("UPDATE commands SET state='failed',updated=?,result=? WHERE client=? AND state='queued' AND created<?",
                       (now, json.dumps({'code': 'not_dispatched', 'message': 'Request hết hạn trước khi được gửi'}), client, now-300))
            if not safe.get('enabled') or not safe.get('session_ready'):
                return {'command': None}
            if db.execute("SELECT 1 FROM commands WHERE client=? AND state='dispatching'", (client,)).fetchone():
                return {'command': None}
            row = db.execute("SELECT * FROM commands WHERE client=? AND state='queued' ORDER BY created LIMIT 1", (client,)).fetchone()
            if not row:
                return {'command': None}
            dispatch = secrets.token_urlsafe(24)
            db.execute("UPDATE commands SET state='dispatching',dispatch=?,updated=? WHERE id=?", (dispatch, now, row['id']))
        return {'command': {**json.loads(row['command']), 'dispatch': dispatch}}

    def enqueue(self, client, operation, arguments, request_id, confirm_generation=False):
        command = build_command(operation, arguments, request_id)
        if operation == 'generate_image' and confirm_generation is not True:
            raise ValueError('Cần chủ động xác nhận gửi một prompt tạo x1 ảnh')
        mark = fingerprint({'client': client, **command})
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM commands WHERE id=?', (command['id'],)).fetchone()
            if old:
                if old['fingerprint'] != mark:
                    raise ValueError('Request ID đã gắn với nội dung hoặc phiên khác')
                return self.public(old)
            row = db.execute('SELECT * FROM clients WHERE id=?', (client,)).fetchone()
            if not row or now-row['updated'] > 90 or not json.loads(row['info']).get('session_ready') or not json.loads(row['info']).get('enabled'):
                raise ValueError('Extension Flow chưa sẵn sàng; kiểm tra kết nối trước')
            if operation in ('generate_image', 'prepare_generation') and json.loads(row['info']).get('verification_guard_detected') is True:
                raise ValueError('verification_guarded: SDK công khai của Flow đổi action xác minh; generation chưa gửi')
            if db.execute("SELECT COUNT(*) FROM commands WHERE state='queued'").fetchone()[0] >= 100:
                raise ValueError('Hàng đợi thử nghiệm đã đầy')
            db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?)',
                       (command['id'], client, mark, json.dumps(command, ensure_ascii=False), 'queued', None, None, now, now))
        return self.get(command['id'])

    def get(self, request_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM commands WHERE id=?', (request_id,)).fetchone()
        if not row:
            raise KeyError(request_id)
        return self.public(row)

    @staticmethod
    def public(row):
        command = json.loads(row['command'])
        return {'id': row['id'], 'client_id': row['client'], 'operation': command['operation'],
                'state': row['state'], 'result': json.loads(row['result']) if row['result'] else None,
                'created': row['created'], 'updated': row['updated']}

    def complete(self, client, request_id, dispatch, result):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM commands WHERE id=? AND client=?', (request_id, client)).fetchone()
            if not row or not isinstance(dispatch, str) or not secrets.compare_digest(row['dispatch'] or '', dispatch):
                raise PermissionError('Biên nhận không thuộc lần gửi request này')
            if row['state'] in ('completed', 'blocked', 'failed'):
                return self.public(row)
            if row['state'] not in ('dispatching', 'uncertain'):
                raise ValueError('Request chưa được giao cho extension')
            command = json.loads(row['command'])
            transport_error = result.get('transport_error')
            if transport_error:
                reasons = {
                    'session_unavailable': 'Phiên Flow chưa sẵn sàng; request chưa gửi',
                    'wrong_project': 'Tab Flow không nằm trong đúng dự án; request chưa gửi',
                    'tab_unavailable': 'Tab Flow đã đóng hoặc điều hướng trước khi gửi',
                    'extension_paused': 'Extension đã ngừng nhận lệnh trước khi gửi request',
                    'verification_unavailable': 'Flow chưa cung cấp đủ thư viện/thông tin xác minh cho request tạo ảnh; chưa gửi generation',
                    'verification_failed': 'Bước xác minh gốc của Flow chưa thành công; chưa gửi generation',
                    'verification_guarded': 'SDK công khai của Flow đổi action thành extension_hijack_detected; generation chưa gửi',
                    'network_uncertain': 'Mất phản hồi mạng; giữ request và không gửi lại',
                    'previous_attempt': 'Đã có lần gửi trước; không tạo thêm ảnh',
                    'extension_interrupted': 'Extension bị ngắt khi đang gửi; không gửi lại',
                    'verification_handoff_uncertain': 'Chưa rõ kết quả bàn giao xác minh; không tự thực hiện lại',
                }
                if transport_error not in reasons:
                    raise ValueError('Mã lỗi transport không hợp lệ')
                state = 'failed' if transport_error in ('session_unavailable', 'wrong_project', 'tab_unavailable', 'extension_paused', 'verification_unavailable', 'verification_failed', 'verification_guarded') else 'uncertain'
                decoded = {'code': transport_error, 'message': reasons[transport_error]}
            elif command['operation'] == 'prepare_generation':
                proof = result.get('verification_token')
                ua = result.get('user_agent')
                if (result.get('request_id') != request_id or not isinstance(proof, str) or not 100 <= len(proof) <= 32000
                        or not isinstance(ua, str) or not ua or len(ua) > 512 or any(c in ua for c in '\r\n')):
                    raise ValueError('Kết quả xác minh không hợp lệ')
                expires = time.time() + 90
                with self._proof_lock:
                    self._proofs = {key: value for key, value in self._proofs.items() if value['expires'] > time.time()}
                    self._proofs[request_id] = {'token': proof, 'user_agent': ua, 'expires': expires}
                # Only the acknowledgement is durable; the proof stays in RAM.
                decoded = {'verification_ready': True, 'expires_at': expires}
                state = 'completed'
            else:
                try:
                    payload = parse_response(result.get('body'), command['rpcid'], result.get('http_status'))
                    decoded = decode_result(command['operation'], payload)
                    state = 'completed'
                except FlowRPCError as error:
                    state = 'uncertain' if error.uncertain else 'blocked'
                    decoded = {'code': error.code, 'message': str(error)}
            db.execute('UPDATE commands SET state=?,result=?,updated=? WHERE id=?',
                       (state, json.dumps(decoded, ensure_ascii=False), time.time(), request_id))
        return self.get(request_id)

    def consume_verification(self, request_id, key):
        if not isinstance(key, str) or len(key) > 256:
            raise PermissionError('Khóa bàn giao không hợp lệ')
        with self.db() as db:
            row = db.execute('SELECT command,state FROM commands WHERE id=?', (request_id,)).fetchone()
        if not row:
            raise KeyError(request_id)
        command = json.loads(row['command'])
        if command['operation'] != 'prepare_generation' or not secrets.compare_digest(command['arguments']['handoff_hash'], secret_hash(key)):
            raise PermissionError('Xác minh không thuộc yêu cầu này')
        if row['state'] != 'completed':
            raise ValueError('Bước xác minh chưa hoàn tất')
        with self._proof_lock:
            proof = self._proofs.pop(request_id, None)
        if not proof or proof['expires'] <= time.time():
            raise ValueError('Kết quả xác minh đã dùng/hết hạn hoặc dịch vụ đã restart; không tự tạo lại')
        return proof
