"""Direct desktop HTTP transport for Flow experiments.

Cookies come from the user's local export, session/CSRF from a fresh Flow page.
Generation verification is supplied per request by a separate approved browser
adapter. This module never reads Chrome's cookie database or modifies its SDK.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

import httpx

from .protocol import READ_OPERATIONS, FlowRPCError, build_command, decode_result, parse_response

ORIGIN = 'https://flow.google.com'
ENDPOINT = ORIGIN + '/_/AiSandboxAngularFrontend/data/batchexecute'
DEFAULT_JOURNAL = Path(__file__).resolve().parents[1] / 'data' / 'flow-desktop.sqlite3'


def load_exported_cookies(path):
    records = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(records, list):
        raise ValueError('Cần file export cookie dạng JSON array')
    jar = httpx.Cookies()
    loaded = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        domain = str(record.get('domain', '')).lower()
        if domain.lstrip('.') not in ('google.com', 'flow.google.com'):
            continue
        expiry = record.get('expirationDate')
        if isinstance(expiry, (int, float)) and expiry > 0 and expiry < time.time():
            continue
        name, value = record.get('name'), record.get('value')
        if not isinstance(name, str) or not isinstance(value, str) or not name or any(c in name+value for c in '\r\n'):
            continue
        jar.set(name, value, domain=domain, path=record.get('path', '/'))
        loaded += 1
    if not loaded:
        raise ValueError('File không có cookie Google/Flow còn dùng được')
    return jar, loaded


class DesktopFlowClient:
    def __init__(self, cookie_path, *, user_agent=None, journal=None, transport=None):
        cookies, self.cookie_count = load_exported_cookies(cookie_path)
        self.cookie_presence = {name: any(cookie.name == name for cookie in cookies.jar) for name in ('SID', 'HSID', 'SAPISID', '__Secure-1PSID', '__Secure-3PSID')}
        headers = {'Accept-Language': 'vi,en;q=0.8'}
        if user_agent:
            if not isinstance(user_agent, str) or len(user_agent) > 512 or any(c in user_agent for c in '\r\n'):
                raise ValueError('User-Agent không hợp lệ')
            headers['User-Agent'] = user_agent
        self.http = httpx.Client(cookies=cookies, headers=headers, transport=transport,
                                 timeout=90, trust_env=False, follow_redirects=False)
        self._session = None
        self.journal = Path(journal or DEFAULT_JOURNAL)
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT, updated REAL NOT NULL)')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.journal, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        self.http.close()

    def _authentication_error(self):
        missing = [name for name in ('SID', 'HSID') if not self.cookie_presence[name]]
        detail = (' File export hiện thiếu ' + ', '.join(missing) + '.') if missing else ''
        return FlowRPCError('fresh_cookie_required', 'HTTP desktop chưa nhận được phiên Flow đã đăng nhập.' + detail + ' Cần kiểm tra bản export cookie đầy đủ của đúng tài khoản.')

    def bootstrap(self):
        try:
            response = self.http.get(ORIGIN + '/', timeout=20)
        except httpx.HTTPError as error:
            raise FlowRPCError('desktop_connection_failed', 'Không kết nối được Flow bằng HTTP desktop') from error
        if response.status_code != 200:
            raise self._authentication_error()
        match = re.search(r'(?:window\.)?WIZ_global_data\s*=\s*(\{.*?\});', response.text, re.S)
        try:
            wiz = json.loads(match.group(1)) if match else {}
        except ValueError:
            wiz = {}
        csrf, sid, build = (wiz.get(key) for key in ('SNlM0e', 'FdrFJe', 'cfb2h'))
        if not isinstance(csrf, str) or not csrf or not isinstance(sid, (str, int)) or not sid or not isinstance(build, str) or not build:
            raise self._authentication_error()
        self._session = {'at': csrf, 'f.sid': str(sid), 'bl': build}
        return {'ready': True, 'build': build, 'loaded_cookie_count': self.cookie_count}

    def _reserve(self, command):
        mark = hashlib.sha256(json.dumps(command, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT fingerprint,state,result FROM requests WHERE id=?', (command['id'],)).fetchone()
            if old:
                if old[0] != mark:
                    raise ValueError('Request ID đã gắn với nội dung khác')
                if old[1] == 'completed':
                    return json.loads(old[2])
                if old[1] == 'failed':
                    saved = json.loads(old[2])
                    raise FlowRPCError(saved['code'], saved['message'])
                raise FlowRPCError('desktop_delivery_uncertain', 'Request đã được chuẩn bị/gửi; cần đối chiếu cùng ID, không gửi lại', uncertain=True)
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)', (command['id'], mark, 'submitting', None, time.time()))
        return None

    def _record(self, request_id, state, result):
        with self.db() as db:
            db.execute('UPDATE requests SET state=?,result=?,updated=? WHERE id=?',
                       (state, json.dumps(result, ensure_ascii=False), time.time(), request_id))

    def submit(self, operation, arguments, request_id, *, verification_provider=None):
        if operation == 'prepare_generation':
            raise ValueError('Bước xác minh phải do adapter trình duyệt thực hiện')
        command = build_command(operation, arguments, request_id)
        writing = operation not in READ_OPERATIONS
        if writing:
            # Check the journal before requesting more credentials/verification.
            with self.db() as db:
                exists = db.execute('SELECT 1 FROM requests WHERE id=?', (command['id'],)).fetchone()
            if exists:
                return self._reserve(command)
        if not self._session:
            self.bootstrap()
        if operation == 'generate_image' and verification_provider is None:
            raise FlowRPCError('verification_provider_required', 'Cần bộ xác minh cho từng request trước khi gửi generation')
        if writing:
            cached = self._reserve(command)
            if cached is not None:
                return cached
        try:
            payload = copy.deepcopy(command['payload'])
            if operation == 'generate_image':
                try:
                    proof = verification_provider({'request_id': command['id'], 'project_id': arguments['project_id'], 'action': 'IMAGE_GENERATION'})
                except FlowRPCError:
                    raise
                except Exception:
                    raise FlowRPCError('verification_failed', 'Bộ xác minh chưa hoàn tất; generation chưa gửi') from None
                if not isinstance(proof, str) or not 100 <= len(proof) <= 32000:
                    raise FlowRPCError('verification_failed', 'Bộ xác minh chưa trả kết quả hợp lệ; generation chưa gửi')
                payload[1][0][7][10] = [proof, 1]
                payload[3][10] = [proof, 1]
            params = {'rpcids': command['rpcid'], 'source-path': command['source_path'], 'bl': self._session['bl'],
                      'f.sid': self._session['f.sid'], 'hl': 'vi', '_reqid': str(time.time_ns() % 900000000), 'rt': 'c'}
            form = {'at': self._session['at'], 'f.req': json.dumps([[[command['rpcid'], json.dumps(payload, ensure_ascii=False), None, 'generic']]], ensure_ascii=False)}
            try:
                response = self.http.post(ENDPOINT, params=params, data=form,
                                          headers={'Origin': ORIGIN, 'Referer': ORIGIN + command['source_path'], 'X-Same-Domain': '1'})
            except httpx.HTTPError:
                raise FlowRPCError('desktop_delivery_uncertain', 'Mất phản hồi HTTP; giữ request để đối chiếu, không gửi lại', uncertain=True) from None
            raw = parse_response(response.text, command['rpcid'], response.status_code)
            decoded = decode_result(operation, raw)
            if writing:
                self._record(command['id'], 'completed', decoded)
            return decoded
        except FlowRPCError as error:
            if writing:
                self._record(command['id'], 'uncertain' if error.uncertain else 'failed', {'code': error.code, 'message': str(error)})
            raise
