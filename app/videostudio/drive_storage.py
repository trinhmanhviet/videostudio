"""Google Drive storage: several accounts, finished videos moved to Drive, gameplay clips read from Drive links.

- Accounts are connected with the user's own Google OAuth client (Desktop/Web JSON from Google Cloud). The same
  client JSON as YouTube publishing is reused when it was already uploaded there.
- Uploads go to the first account (in the user's order) with enough free space; when it is nearly full the next
  account is used. Folders: Video/<category>/<project or book>/<file>.
- A local file is deleted only after Drive reports the same size and MD5. Nothing is ever deleted on Drive.
- Gameplay links are downloaded into a bounded cache on the data drive and re-downloaded when evicted.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from .paths import DATA_ROOT

SCOPES = 'openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly'
API = 'https://www.googleapis.com/drive/v3'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
CHUNK = 64 * 1024 * 1024
FREE_MARGIN = 2 * 1024 ** 3          # switch account when less than this would remain
CACHE_LIMIT = 20 * 1024 ** 3         # gameplay downloaded from Drive
CACHE = DATA_ROOT / 'media-library' / 'gameplay-cache'
CATEGORIES = {'case': 'vu-an', 'story': 'truyen-doc', 'news': 'tin-tuc', 'meme': 'meme-hai'}
FILE_ID = re.compile(r'(?:/d/|[?&]id=|/file/d/|/open\?id=)([A-Za-z0-9_-]{20,})')


class DriveError(RuntimeError):
    pass


def file_id_from_link(link):
    link = str(link or '').strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{20,}', link):
        return link
    match = FILE_ID.search(link)
    if not match or urlparse(link).hostname not in ('drive.google.com', 'docs.google.com'):
        raise ValueError('Dán link Google Drive của video (dạng https://drive.google.com/file/d/…)')
    return match.group(1)


class DriveStorage:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.tokens = {}  # account id -> (access token, expiry)
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS drive_accounts(id TEXT PRIMARY KEY, email TEXT NOT NULL, refresh_token TEXT NOT NULL,
                position INTEGER NOT NULL, created REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS drive_oauth(state TEXT PRIMARY KEY, expires REAL NOT NULL, redirect TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drive_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drive_folders(account TEXT NOT NULL, path TEXT NOT NULL, folder_id TEXT NOT NULL, PRIMARY KEY(account, path));
            CREATE TABLE IF NOT EXISTS drive_files(job_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, local_path TEXT NOT NULL,
                account TEXT NOT NULL, file_id TEXT NOT NULL, size INTEGER NOT NULL, md5 TEXT NOT NULL, duration REAL,
                web_link TEXT, uploaded REAL NOT NULL, local_deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id, kind));
            CREATE TABLE IF NOT EXISTS drive_failures(job_id TEXT PRIMARY KEY, message TEXT NOT NULL, attempts INTEGER NOT NULL, next_at REAL NOT NULL);
            ''')

    # --- settings & client -------------------------------------------------------------------------------
    def setting(self, key, default=None):
        with self.store.db() as db:
            row = db.execute('SELECT value FROM drive_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    def set_setting(self, key, value):
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO drive_settings VALUES(?,?)', (key, json.dumps(value)))

    def configure_client(self, raw):
        client = (raw or {}).get('web') or (raw or {}).get('installed') or raw
        if not isinstance(client, dict) or not str(client.get('client_id', '')).endswith('.apps.googleusercontent.com') or not client.get('client_secret'):
            raise ValueError('Cần tệp OAuth client JSON của Google Cloud (có client_id và client_secret)')
        self.set_setting('client', {'client_id': client['client_id'], 'client_secret': client['client_secret']})
        return self.status()

    def client(self):
        own = self.setting('client')
        if own:
            return own
        with self.store.db() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publishing_settings'").fetchone():
                row = db.execute("SELECT value FROM publishing_settings WHERE key='youtube_client'").fetchone()
                if row:
                    return json.loads(row['value'])
        raise ValueError('Chưa có OAuth client Google. Tải tệp OAuth client JSON (loại Desktop app) lên trước.')

    # --- accounts ------------------------------------------------------------------------------------------
    def oauth_start(self, redirect):
        parsed = urlparse(redirect)
        loopback = parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
        # The public HTTPS address of this tool (e.g. a tunnel) works too, when it is listed as an
        # "Authorized redirect URI" of a Web application OAuth client; Google enforces that list.
        if not loopback and parsed.scheme != 'https':
            raise ValueError('Mở tool bằng địa chỉ https (hoặc http://127.0.0.1:8877 trên máy) rồi thêm tài khoản lại.')
        client = self.client()
        state = secrets.token_urlsafe(32)
        with self.store.db() as db:
            db.execute('DELETE FROM drive_oauth WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO drive_oauth VALUES(?,?,?)', (state, time.time() + 600, redirect))
        return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(dict(
            client_id=client['client_id'], redirect_uri=redirect, response_type='code', state=state, scope=SCOPES,
            access_type='offline', prompt='consent select_account', include_granted_scopes='true'))}

    def oauth_finish(self, state, code):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM drive_oauth WHERE state=? AND expires>?', (state, time.time())).fetchone()
            db.execute('DELETE FROM drive_oauth WHERE state=?', (state,))
        if not row:
            raise ValueError('Phiên kết nối hết hạn; bấm Thêm tài khoản lại')
        tokens = self._post_token(dict(code=code, redirect_uri=row['redirect'], grant_type='authorization_code'))
        if not tokens.get('refresh_token'):
            raise DriveError('Google chưa cấp quyền chạy nền; thử lại và đồng ý quyền Drive')
        about = httpx.get(API + '/about', params={'fields': 'user(emailAddress)'}, headers={'Authorization': 'Bearer ' + tokens['access_token']}, timeout=30).json()
        email = about.get('user', {}).get('emailAddress') or 'tai-khoan'
        if self.setting('since') is None:
            # Only videos finished from now on move to Drive; older ones stay unless the user asks (include_old).
            self.set_setting('since', time.time())
        with self.store.db() as db:
            position = db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM drive_accounts').fetchone()[0]
            old = db.execute('SELECT position FROM drive_accounts WHERE id=?', (email,)).fetchone()
            db.execute('INSERT OR REPLACE INTO drive_accounts VALUES(?,?,?,?,?,0)', (email, email, tokens['refresh_token'], old['position'] if old else position, time.time()))
        self.tokens[email] = (tokens['access_token'], time.time() + int(tokens.get('expires_in', 3000)) - 60)
        return email

    def accounts(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute('SELECT id,email,position,disabled FROM drive_accounts ORDER BY position')]

    def reorder(self, ids):
        with self.store.db() as db:
            for index, identifier in enumerate(ids):
                db.execute('UPDATE drive_accounts SET position=? WHERE id=?', (index, identifier))
        return self.status()

    def remove(self, identifier):
        with self.store.db() as db:
            db.execute('DELETE FROM drive_accounts WHERE id=?', (identifier,))
            db.execute('DELETE FROM drive_folders WHERE account=?', (identifier,))
        self.tokens.pop(identifier, None)
        return self.status()

    def _post_token(self, data):
        client = self.client()
        response = httpx.post('https://oauth2.googleapis.com/token', data={**data, 'client_id': client['client_id'], 'client_secret': client['client_secret']}, timeout=30)
        if response.status_code != 200:
            raise DriveError('Google từ chối đăng nhập: ' + response.text[:200])
        return response.json()

    def token(self, account):
        with self.lock:
            cached = self.tokens.get(account)
            if cached and cached[1] > time.time():
                return cached[0]
            with self.store.db() as db:
                row = db.execute('SELECT refresh_token FROM drive_accounts WHERE id=?', (account,)).fetchone()
            if not row:
                raise DriveError('Tài khoản Drive không còn kết nối: ' + account)
            tokens = self._post_token(dict(refresh_token=row['refresh_token'], grant_type='refresh_token'))
            self.tokens[account] = (tokens['access_token'], time.time() + int(tokens.get('expires_in', 3000)) - 60)
            return tokens['access_token']

    def _headers(self, account):
        return {'Authorization': 'Bearer ' + self.token(account)}

    def quota(self, account):
        data = httpx.get(API + '/about', params={'fields': 'storageQuota'}, headers=self._headers(account), timeout=30).json().get('storageQuota', {})
        limit = int(data.get('limit') or 0)
        usage = int(data.get('usage') or 0)
        return {'limit': limit, 'usage': usage, 'free': (limit - usage) if limit else 10 ** 15}

    def status(self):
        try:
            self.client()
            has_client = True
        except ValueError:
            has_client = False
        accounts = []
        for account in self.accounts():
            try:
                q = self.quota(account['id'])
                accounts.append({**account, 'free_gb': round(q['free'] / 2**30, 1) if q['limit'] else None,
                                 'total_gb': round(q['limit'] / 2**30, 1) if q['limit'] else None, 'ok': True})
            except Exception as error:
                accounts.append({**account, 'ok': False, 'error': str(error)[:200]})
        with self.store.db() as db:
            uploaded = db.execute('SELECT COUNT(DISTINCT job_id), COALESCE(SUM(size),0) FROM drive_files').fetchone()
            failures = [dict(r) for r in db.execute('SELECT * FROM drive_failures ORDER BY next_at LIMIT 5')]
        return {'has_client': has_client, 'accounts': accounts, 'auto_upload': self.setting('auto_upload', True),
                'include_old': self.setting('include_old', False),
                'delete_local': self.setting('delete_local', True), 'uploaded_videos': uploaded[0],
                'uploaded_gb': round(uploaded[1] / 2**30, 1), 'failures': failures}

    # --- folders & upload ----------------------------------------------------------------------------------
    def folder(self, account, parts):
        parent, path = 'root', ''
        for part in parts:
            name = re.sub(r'[\\/]+', '-', str(part)).strip()[:200] or 'khac'
            path = f'{path}/{name}'
            with self.store.db() as db:
                row = db.execute('SELECT folder_id FROM drive_folders WHERE account=? AND path=?', (account, path)).fetchone()
            if row:
                parent = row['folder_id']
                continue
            escaped = name.replace("'", "\\'")
            found = httpx.get(API + '/files', headers=self._headers(account), timeout=30, params={
                'q': f"name='{escaped}' and '{parent}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id)', 'spaces': 'drive'}).json().get('files', [])
            if found:
                parent = found[0]['id']
            else:
                created = httpx.post(API + '/files', headers=self._headers(account), timeout=30, params={'fields': 'id'},
                                     json={'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent]})
                if created.status_code >= 300:
                    raise DriveError('Không tạo được thư mục trên Drive: ' + created.text[:200])
                parent = created.json()['id']
            with self.store.db() as db:
                db.execute('INSERT OR REPLACE INTO drive_folders VALUES(?,?,?)', (account, path, parent))
        return parent

    def pick_account(self, size):
        problems = []
        for account in self.accounts():
            if account['disabled']:
                continue
            try:
                if self.quota(account['id'])['free'] - size > FREE_MARGIN:
                    return account['id']
                problems.append(account['email'] + ' sắp đầy')
            except Exception as error:
                problems.append(account['email'] + ': ' + str(error)[:80])
        raise DriveError('Không còn tài khoản Drive đủ chỗ' + (' (' + '; '.join(problems) + ')' if problems else '. Thêm tài khoản trong Cài đặt.'))

    def upload(self, account, path, folder_id, check=lambda: None):
        """Resumable upload in 64 MB parts; returns Drive's id, size and md5Checksum."""
        path = Path(path)
        size = path.stat().st_size
        start = httpx.post(UPLOAD, params={'uploadType': 'resumable', 'fields': 'id,size,md5Checksum,webViewLink'}, timeout=60,
                           headers={**self._headers(account), 'X-Upload-Content-Length': str(size)},
                           json={'name': path.name, 'parents': [folder_id]})
        if start.status_code >= 300 or 'location' not in start.headers:
            raise DriveError('Drive không nhận tải lên: ' + start.text[:200])
        session, offset = start.headers['location'], 0
        with open(path, 'rb') as handle:
            while True:
                check()
                handle.seek(offset)
                chunk = handle.read(CHUNK)
                end = offset + len(chunk) - 1
                response = httpx.put(session, content=chunk, timeout=600,
                                     headers={'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {offset}-{end}/{size}' if chunk else f'bytes */{size}'})
                if response.status_code in (200, 201):
                    return response.json()
                if response.status_code == 308:
                    received = response.headers.get('range')
                    offset = int(received.split('-')[1]) + 1 if received else 0
                    continue
                raise DriveError(f'Tải lên bị ngắt ({response.status_code}): {response.text[:200]}')

    # --- download (gameplay links, streaming finished videos) -------------------------------------------------
    def metadata(self, file_id):
        last = None
        for account in self.accounts():
            response = httpx.get(f'{API}/files/{file_id}', headers=self._headers(account), timeout=30,
                                 params={'fields': 'id,name,size,md5Checksum,mimeType', 'supportsAllDrives': 'true'})
            if response.status_code == 200:
                return account['id'], response.json()
            last = response.status_code
        raise DriveError('Không tài khoản Drive nào mở được link này' + (f' (mã {last})' if last else '. Thêm tài khoản trong Cài đặt.'))

    def download(self, file_id, target, check=lambda: None, account=None, progress=None):
        if account is None:
            account, _ = self.metadata(file_id)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + '.part')
        digest, size = hashlib.sha256(), 0
        with httpx.stream('GET', f'{API}/files/{file_id}', params={'alt': 'media', 'supportsAllDrives': 'true'},
                          headers=self._headers(account), timeout=httpx.Timeout(60, read=600)) as response:
            if response.status_code != 200:
                raise DriveError(f'Không tải được từ Drive (mã {response.status_code})')
            with open(part, 'wb') as handle:
                for chunk in response.iter_bytes(4 * 1024 * 1024):
                    check()
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    if progress:
                        progress(size)
        part.replace(target)
        return digest.hexdigest(), size

    def stream(self, account, file_id, range_header=None):
        headers = self._headers(account)
        if range_header:
            headers['Range'] = range_header
        client = httpx.Client(timeout=httpx.Timeout(60, read=600))
        request = client.build_request('GET', f'{API}/files/{file_id}', params={'alt': 'media'}, headers=headers)
        response = client.send(request, stream=True)
        return client, response


def local_md5(path):
    digest = hashlib.md5()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def cache_trim(keep=()):
    """Keep the Drive gameplay cache under CACHE_LIMIT, removing least recently used files first."""
    CACHE.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in CACHE.iterdir() if p.is_file() and not p.name.endswith('.part')), key=lambda p: p.stat().st_atime)
    total = sum(p.stat().st_size for p in files)
    keep = {str(Path(k).resolve()) for k in keep}
    for path in files:
        if total <= CACHE_LIMIT:
            break
        if str(path.resolve()) in keep:
            continue
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
