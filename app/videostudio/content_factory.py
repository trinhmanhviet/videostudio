"""Durable batch requests and hash-bound finished video versions.

Factory items are requests, not jobs. Admission stays at the normal API boundary;
the factory allocates at most one job while the existing worker is idle.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from .core import digest, validate_request
from .output_layout import final_video_path, job_video_files


STYLES = {'news', 'case', 'meme'}
PENDING = ('pending', 'waiting')
ACTIVE = ('queued', 'running', 'retrying', 'awaiting_visual_review', 'awaiting_flow_account')
MAX_BATCH_ITEMS = 100
MAX_IMPORT_CHARACTERS = 1_000_000
_DIGESTS = {}


def _cached_digest(path):
    """The queue page polls every few seconds; rehash a thumbnail only when the file changes."""
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _DIGESTS:
        if len(_DIGESTS) > 512:
            _DIGESTS.clear()
        _DIGESTS[key] = digest(path)
    return _DIGESTS[key]


REQUEST_FIELDS = {'voice_id', 'duration_seconds', 'music_volume', 'pitch', 'quality_mode',
                  'image_provider', 'flow_batch_size', 'meta_batch_size', 'speech_batch_size', 'text_provider',
                  'edit_preset', 'references_enabled', 'captions_enabled', 'music_enabled', 'sfx_enabled'}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _text(value, label, maximum, default=None):
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label} phải có 1–{maximum} ký tự')
    return value.strip()


def _message(error):
    detail = getattr(error, 'detail', str(error))
    if isinstance(detail, dict):
        parts = [str(detail.get('message', 'Chờ hệ thống sẵn sàng'))]
        for check in detail.get('checks', [])[:4]:
            if isinstance(check, dict):
                parts.append(str(check.get('detail') or check.get('message') or check.get('name') or check))
        detail = ' · '.join(parts)
    return str(detail)[:2000]


class ContentFactory:
    def __init__(self, store, submit_job, public_job=None, validate_submission=None, video_probe=None, retry_job=None):
        self.store = store
        self.submit_job = submit_job
        self.public_job = public_job or (lambda job: job)
        self.validate_submission = validate_submission
        self.video_probe = video_probe
        self.retry_job = retry_job
        # Optional: name_video(content, request) asks the text provider for a title.
        self.name_video = None
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS factory_batches(
                    id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    scope TEXT, project TEXT NOT NULL, style TEXT NOT NULL, input_mode TEXT NOT NULL,
                    defaults TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS factory_items(
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, position INTEGER NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL, request TEXT NOT NULL,
                    idem TEXT UNIQUE NOT NULL, job_id TEXT, dispatch_scope TEXT, state TEXT NOT NULL DEFAULT 'pending',
                    message TEXT, lease_until REAL NOT NULL DEFAULT 0, claim_token TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS factory_items_queue ON factory_items(state,position);
                CREATE INDEX IF NOT EXISTS factory_items_job ON factory_items(job_id);
                CREATE TABLE IF NOT EXISTS factory_settings(
                    id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL NOT NULL DEFAULT 0, claim_token TEXT);
                INSERT OR IGNORE INTO factory_settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS factory_video_versions(
                    job_id TEXT NOT NULL, version_id TEXT NOT NULL, path TEXT NOT NULL,
                    sha256 TEXT NOT NULL, duration_seconds REAL NOT NULL, size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL, created REAL NOT NULL, verified_at REAL NOT NULL,
                    PRIMARY KEY(job_id,version_id));
                CREATE TABLE IF NOT EXISTS factory_video_approvals(
                    job_id TEXT PRIMARY KEY, version_id TEXT NOT NULL, path TEXT NOT NULL,
                    sha256 TEXT NOT NULL, duration_seconds REAL NOT NULL, approved_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS factory_video_attestations(
                    job_id TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
                    duration_seconds REAL NOT NULL, verified_at REAL NOT NULL,
                    PRIMARY KEY(job_id,path,sha256));
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(factory_items)')}
            if 'dispatch_scope' not in columns:
                db.execute('ALTER TABLE factory_items ADD COLUMN dispatch_scope TEXT')
            if 'auto_name' not in columns:
                # The AI names the video (and its project) right before it runs.
                db.execute('ALTER TABLE factory_items ADD COLUMN auto_name INTEGER NOT NULL DEFAULT 0')
            if 'retry_requested' not in columns:
                # A retry pressed while another video runs waits here and is
                # dispatched before pending items once the worker is idle.
                db.execute('ALTER TABLE factory_items ADD COLUMN retry_requested INTEGER NOT NULL DEFAULT 0')

    def create_batch(self, data, key, scope=None):
        key = _text(key, 'Idempotency-Key', 200)
        if not isinstance(data, dict):
            raise ValueError('Lô phải là một đối tượng')
        if set(data) - {'project', 'style', 'input_mode', 'defaults', 'items', 'auto_name'}:
            raise ValueError('Trường lô không được hỗ trợ')
        auto_name = data.get('auto_name', False)
        if type(auto_name) is not bool:
            raise ValueError('auto_name phải là boolean')
        project = _text(data.get('project'), 'Dự án', 200, 'Dự án mặc định')
        style, mode = data.get('style', 'news'), data.get('input_mode', 'idea')
        if not isinstance(style, str) or style not in STYLES or mode not in ('idea', 'script'):
            raise ValueError('Phong cách hoặc chế độ nhập không hợp lệ')
        defaults = data.get('defaults', {})
        if not isinstance(defaults, dict) or set(defaults) - REQUEST_FIELDS:
            raise ValueError('Thiết lập chung không hợp lệ')
        items = data.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
            raise ValueError('Mỗi lô cần 1–100 video')
        if len(_json(data)) > MAX_IMPORT_CHARACTERS:
            raise ValueError('Nội dung nhập vượt quá 1.000.000 ký tự')
        if scope is not None:
            scope = _text(scope, 'Connector scope', 200)
        normalized = []
        for index, item in enumerate(items):
            if isinstance(item, str):
                item = {'content': item}
            if not isinstance(item, dict) or set(item) - (REQUEST_FIELDS | {'content', 'text', 'title', 'overrides'}):
                raise ValueError(f'Mục {index + 1}: trường nhập không hợp lệ')
            content = _text(item.get('content', item.get('text')), f'Nội dung mục {index + 1}', 100000)
            title = _text(item.get('title'), 'Tiêu đề', 300, content.splitlines()[0][:120])
            overrides = item.get('overrides', {})
            if not isinstance(overrides, dict) or set(overrides) - REQUEST_FIELDS:
                raise ValueError(f'Mục {index + 1}: thiết lập riêng không hợp lệ')
            request = {**defaults, **{k: v for k, v in item.items() if k in REQUEST_FIELDS}, **overrides,
                       'idea': content, 'project': project, 'content_style': style,
                       'workflow_mode': 'meme' if style == 'meme' else ('provided_narration' if mode == 'script' else 'research')}
            if style == 'meme':
                request['meme_input_mode'] = mode
            request = validate_request(request)
            normalized.append({'title': title, 'content': content, 'request': request})
        fingerprint = hashlib.sha256(_json({'project': project, 'style': style, 'input_mode': mode,
                                           'defaults': defaults, 'items': normalized, 'scope': scope,
                                           **({'auto_name': True} if auto_name else {})}).encode()).hexdigest()
        with self.store.db() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_retired_batches'").fetchone() and db.execute('SELECT 1 FROM publication_retired_batches WHERE idem=?',(key,)).fetchone():
                raise ValueError('Lô này đã đăng và dọn; không tạo lại bằng khóa yêu cầu cũ')
            old = db.execute('SELECT id,fingerprint FROM factory_batches WHERE idem=?', (key,)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint:
                raise ValueError('Idempotency key already used for a different batch')
            return self.get_batch(old['id'])
        # Availability validation is injected by the API. It must not create jobs
        # or contact providers; full preflight still runs at each dispatch.
        if self.validate_submission:
            for item in normalized:
                self.validate_submission(item['request'])
        now, batch_id = time.time(), uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_retired_batches'").fetchone() and db.execute('SELECT 1 FROM publication_retired_batches WHERE idem=?',(key,)).fetchone():
                raise ValueError('Lô này đã đăng và dọn; không tạo lại bằng khóa yêu cầu cũ')
            old = db.execute('SELECT id,fingerprint FROM factory_batches WHERE idem=?', (key,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise ValueError('Idempotency key already used for a different batch')
                batch_id = old['id']
            else:
                from .project_lifecycle import reject_deleted_project
                reject_deleted_project(db, project)
                db.execute('INSERT OR IGNORE INTO projects VALUES(?,?)', (project, now))
                db.execute('INSERT INTO factory_batches VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (batch_id, key, fingerprint, scope, project, style, mode, _json(defaults), now, now))
                position = db.execute('SELECT COALESCE(MAX(position),0) FROM factory_items').fetchone()[0]
                for index, item in enumerate(normalized, 1):
                    identifier = uuid.uuid4().hex
                    db.execute('''INSERT INTO factory_items
                        (id,batch_id,position,title,content,request,idem,created,updated,auto_name)
                        VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (identifier, batch_id, position + index, item['title'], item['content'],
                         _json(item['request']), 'factory:' + identifier, now, now, int(auto_name)))
        return self.get_batch(batch_id)

    def _sync(self, db):
        # Reconcile committed receipts even before an expired dispatch lease.
        # Reusing the exact stable key recovers a crash after Store.create.
        db.execute('''UPDATE factory_items SET job_id=(SELECT id FROM jobs WHERE jobs.idem=factory_items.idem),
            state=COALESCE((SELECT state FROM jobs WHERE jobs.idem=factory_items.idem),state),
            message=(SELECT error FROM jobs WHERE jobs.idem=factory_items.idem),lease_until=0,claim_token=NULL
            WHERE job_id IS NULL AND EXISTS(SELECT 1 FROM jobs WHERE jobs.idem=factory_items.idem)''')
        db.execute('''UPDATE factory_items SET
            state=(SELECT state FROM jobs WHERE jobs.id=factory_items.job_id),
            message=(SELECT error FROM jobs WHERE jobs.id=factory_items.job_id)
            WHERE job_id IS NOT NULL AND EXISTS(SELECT 1 FROM jobs WHERE jobs.id=factory_items.job_id)''')

    def _item(self, row, include_job=True):
        item = dict(row)
        item['request'] = json.loads(item['request'])
        item['idempotency_key'] = item.pop('idem')
        item.pop('claim_token', None)
        if include_job and item.get('job_id'):
            try:
                item['job'] = self.public_job(self.store.get(item['job_id']))
            except KeyError:
                item['job'] = None
        return item

    def queue(self):
        with self.store.db() as db:
            self._sync(db)
            paused = bool(db.execute('SELECT paused FROM factory_settings WHERE id=1').fetchone()[0])
            rows = db.execute('''SELECT i.*,b.project,b.style,b.input_mode FROM factory_items i
                JOIN factory_batches b ON b.id=i.batch_id ORDER BY i.position,i.created''').fetchall()
            from .project_lifecycle import deleted_job_ids
            hidden = deleted_job_ids(db)
            rows = [row for row in rows if row['job_id'] not in hidden]
            active = db.execute("SELECT id FROM jobs WHERE state IN ('queued','running','retrying','awaiting_visual_review','awaiting_flow_account') ORDER BY created LIMIT 1").fetchone()
        items = [self._item(row) for row in rows]
        for item in items:
            job = item.get('job')
            item['thumbnail'] = self._thumbnail(job) if job else None
            speech = (job or {}).get('checkpoints', {}).get('speech', {})
            measured = speech.get('duration_seconds') if isinstance(speech, dict) else None
            item['duration_seconds'] = measured if isinstance(measured, (int, float)) and measured > 0                 else item['request'].get('duration_seconds')
        counts = {}
        for item in items:
            counts[item['state']] = counts.get(item['state'], 0) + 1
        return {'paused': paused, 'items': items, 'counts': counts,
                'active_job': self.public_job(self.store.get(active['id'])) if active else None}

    def get_batch(self, batch_id):
        with self.store.db() as db:
            self._sync(db)
            row = db.execute('SELECT * FROM factory_batches WHERE id=?', (batch_id,)).fetchone()
            if not row:
                raise KeyError(batch_id)
            rows = db.execute('SELECT * FROM factory_items WHERE batch_id=? ORDER BY position', (batch_id,)).fetchall()
        batch = dict(row)
        for field in ('fingerprint', 'scope', 'idem'):
            batch.pop(field, None)
        batch['defaults'] = json.loads(batch['defaults'])
        batch['items'] = [self._item(row) for row in rows]
        batch['total'] = len(rows)
        batch['counts'] = {state: sum(row['state'] == state for row in rows) for state in {row['state'] for row in rows}}
        states = set(batch['counts'])
        batch['state'] = ('completed' if states <= {'completed', 'skipped', 'cancelled'} else
                          'running' if states & set(ACTIVE + ('dispatching',)) else
                          'waiting' if 'waiting' in states else 'pending' if 'pending' in states else 'failed')
        return batch

    def list_batches(self):
        with self.store.db() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM factory_batches ORDER BY created DESC LIMIT 200')]
        return {'items': [self.get_batch(identifier) for identifier in ids]}

    def set_paused(self, paused):
        if type(paused) is not bool:
            raise ValueError('paused phải là boolean')
        with self.store.db() as db:
            db.execute('UPDATE factory_settings SET paused=? WHERE id=1', (int(paused),))
        return self.queue()

    def reorder(self, item_ids):
        if not isinstance(item_ids, list) or any(not isinstance(value, str) for value in item_ids) or len(set(item_ids)) != len(item_ids):
            raise ValueError('Danh sách thứ tự không hợp lệ')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._sync(db)
            rows = db.execute("SELECT id,position FROM factory_items WHERE state IN ('pending','waiting') AND job_id IS NULL ORDER BY position").fetchall()
            if set(item_ids) != {row['id'] for row in rows}:
                raise ValueError('Chỉ đổi thứ tự toàn bộ mục đang chờ; video đang xử lý được giữ nguyên')
            for identifier, position in zip(item_ids, sorted(row['position'] for row in rows)):
                db.execute('UPDATE factory_items SET position=?,updated=? WHERE id=?', (position, time.time(), identifier))
        return self.queue()

    def item_action(self, item_id, action, scope=None):
        if action not in ('cancel', 'retry', 'skip'):
            raise ValueError('Thao tác không hợp lệ')
        if scope is not None:
            scope = _text(scope, 'Connector scope', 200)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._sync(db)
            row = db.execute('SELECT * FROM factory_items WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise KeyError(item_id)
            if row['job_id']:
                if action == 'skip':
                    raise ValueError('Chỉ bỏ qua mục chưa bắt đầu; hãy hủy video đang xử lý')
                if action == 'retry':
                    if row['state'] not in ('failed', 'cancelled'):
                        raise ValueError('Chỉ thử lại video đã lỗi hoặc tiếp tục video đã hủy; checkpoint được giữ nguyên')
                    if not self.retry_job:
                        raise ValueError('Video đã có checkpoint. Dùng Thử lại trong video để xác thực connector và tiếp tục chính job này')
                    if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','retrying','awaiting_visual_review','awaiting_flow_account') LIMIT 1").fetchone():
                        db.execute('''UPDATE factory_items SET retry_requested=1,
                            dispatch_scope=COALESCE(?,dispatch_scope),updated=? WHERE id=?''', (scope, time.time(), item_id))
                        return self._item(db.execute('SELECT * FROM factory_items WHERE id=?', (item_id,)).fetchone())
                elif row['state'] not in ACTIVE + ('failed',):
                    raise ValueError('Chỉ hủy video chưa hoàn tất')
                # Cancel goes through Store below, never edits live jobs here.
                job_id = row['job_id']
                db.execute('UPDATE factory_items SET retry_requested=0,updated=? WHERE id=?', (time.time(), item_id))
            else:
                if row['state'] == 'dispatching':
                    raise ValueError('Mục đang được tiếp nhận; chờ nhận mã video rồi hủy')
                if action == 'retry':
                    if row['state'] not in ('waiting', 'failed', 'cancelled', 'skipped'):
                        raise ValueError('Mục chưa cần thử lại')
                    state = 'pending'
                else:
                    state = 'cancelled' if action == 'cancel' else 'skipped'
                db.execute('''UPDATE factory_items SET state=?,message=NULL,next_at=0,attempts=0,
                    dispatch_scope=CASE WHEN ?='retry' THEN COALESCE(?,dispatch_scope) ELSE dispatch_scope END,
                    updated=? WHERE id=?''', (state, action, scope, time.time(), item_id))
                job_id = None
        if job_id:
            if action == 'retry':
                if row['state'] == 'cancelled':
                    self.retry_job(job_id, scope, resume_cancelled=True)
                else:
                    self.retry_job(job_id, scope)
            else:
                self.store.cancel(job_id)
        with self.store.db() as db:
            self._sync(db)
            result = db.execute('SELECT * FROM factory_items WHERE id=?', (item_id,)).fetchone()
        return self._item(result)

    def tick(self):
        """Claim one idle admission slot; return whether a job was allocated.

        A global bounded lease prevents two API processes dispatching different
        requests concurrently. Receipt reconciliation does not require admission.
        """
        now, token = time.time(), uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._sync(db)
            settings = db.execute('SELECT * FROM factory_settings WHERE id=1').fetchone()
            if settings['paused'] or settings['lease_until'] > now:
                return False
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','retrying','awaiting_visual_review','awaiting_flow_account') LIMIT 1").fetchone():
                return False
            again = db.execute('''SELECT i.id,i.job_id,j.state AS job_state,COALESCE(i.dispatch_scope,b.scope) AS scope
                FROM factory_items i JOIN factory_batches b ON b.id=i.batch_id JOIN jobs j ON j.id=i.job_id
                WHERE i.retry_requested=1 ORDER BY i.updated LIMIT 1''').fetchone()
            if again:
                db.execute('UPDATE factory_items SET retry_requested=0,updated=? WHERE id=?', (now, again['id']))
                if again['job_state'] in ('failed', 'cancelled'):
                    db.execute('UPDATE factory_settings SET lease_until=?,claim_token=? WHERE id=1', (now + 120, token))
        if again:
            if again['job_state'] not in ('failed', 'cancelled'):
                return False
            try:
                if again['job_state'] == 'cancelled':
                    self.retry_job(again['job_id'], again['scope'], resume_cancelled=True)
                else:
                    self.retry_job(again['job_id'], again['scope'])
                return True
            except Exception as error:
                with self.store.db() as db:
                    db.execute('UPDATE factory_items SET message=?,updated=? WHERE id=?', (_message(error), time.time(), again['id']))
                return False
            finally:
                with self.store.db() as db:
                    self._sync(db)
                    db.execute('UPDATE factory_settings SET lease_until=0,claim_token=NULL WHERE id=1 AND claim_token=?', (token,))
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            settings = db.execute('SELECT * FROM factory_settings WHERE id=1').fetchone()
            if settings['paused'] or settings['lease_until'] > now:
                return False
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','retrying','awaiting_visual_review','awaiting_flow_account') LIMIT 1").fetchone():
                return False
            # Preserve strict order while the head waits on transient admission.
            row = db.execute('''SELECT i.*,COALESCE(i.dispatch_scope,b.scope) AS scope FROM factory_items i JOIN factory_batches b ON b.id=i.batch_id
                WHERE i.job_id IS NULL AND i.state IN ('pending','waiting','dispatching')
                ORDER BY i.position,i.created LIMIT 1''').fetchone()
            if not row or row['next_at'] > now or (row['state'] == 'dispatching' and row['lease_until'] > now):
                return False
            db.execute('UPDATE factory_settings SET lease_until=?,claim_token=? WHERE id=1', (now + 120, token))
            db.execute("UPDATE factory_items SET state='dispatching',lease_until=?,claim_token=?,updated=? WHERE id=?", (now + 120, token, now, row['id']))
        try:
            request = json.loads(row['request'])
            if row['auto_name'] and self.name_video:
                request = self._apply_ai_name(row, request, token)
            result = self.submit_job(request, row['idem'], row['scope'])
            job = result.get('job', result)
            job_id = job['id']
            # Confirm admission returned the durable receipt belonging to this item.
            with self.store.db() as db:
                receipt = db.execute('SELECT id,state,error FROM jobs WHERE idem=?', (row['idem'],)).fetchone()
                if not receipt or receipt['id'] != job_id:
                    raise ValueError('Admission không trả về receipt bền vững đúng mục')
                db.execute('UPDATE factory_items SET job_id=?,state=?,message=?,lease_until=0,claim_token=NULL,updated=? WHERE id=?',
                           (job_id, receipt['state'], receipt['error'], time.time(), row['id']))
            return True
        except Exception as error:
            code = getattr(error, 'status_code', None)
            transient = code in (409, 429, 503) or code is None
            attempts = row['attempts'] + 1
            delay = min(300, 5 * 2 ** min(attempts - 1, 6)) if transient else 0
            with self.store.db() as db:
                self._sync(db)
                db.execute('''UPDATE factory_items SET state=?,message=?,attempts=?,next_at=?,lease_until=0,
                    claim_token=NULL,updated=? WHERE id=? AND job_id IS NULL AND claim_token=?''',
                    ('waiting' if transient else 'failed', _message(error), attempts, time.time() + delay,
                     time.time(), row['id'], token))
            return False
        finally:
            with self.store.db() as db:
                db.execute('UPDATE factory_settings SET lease_until=0,claim_token=NULL WHERE id=1 AND claim_token=?', (token,))

    def _apply_ai_name(self, row, request, token):
        """Ask once; any failure keeps the temporary name so the queue never waits on it."""
        with self.store.db() as db:
            until = time.time() + 600
            db.execute('UPDATE factory_settings SET lease_until=? WHERE id=1 AND claim_token=?', (until, token))
            db.execute('UPDATE factory_items SET lease_until=? WHERE id=? AND claim_token=?', (until, row['id'], token))
        try:
            name = ' '.join(str(self.name_video(row['content'], request) or '').split()).strip(' "\'“”')[:100]
        except Exception:
            name = ''
        from .project_lifecycle import reject_deleted_project
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE factory_items SET auto_name=0 WHERE id=?', (row['id'],))
            if not name:
                return request
            final, number = name, 1
            while True:
                taken = db.execute('SELECT 1 FROM projects WHERE name=?', (final,)).fetchone()
                try:
                    reject_deleted_project(db, final)
                except ValueError:
                    taken = True
                if not taken:
                    break
                number += 1
                final = f'{name} ({number})'
            old, now = request.get('project'), time.time()
            request = {**request, 'project': final}
            db.execute('INSERT INTO projects VALUES(?,?)', (final, now))
            db.execute('UPDATE factory_items SET request=?,title=?,updated=? WHERE id=?', (_json(request), final, now, row['id']))
            if db.execute('SELECT COUNT(*) FROM factory_items WHERE batch_id=?', (row['batch_id'],)).fetchone()[0] == 1:
                db.execute('UPDATE factory_batches SET project=?,updated=? WHERE id=?', (final, now, row['batch_id']))
            in_use = db.execute("SELECT 1 FROM jobs WHERE json_extract(request,'$.project')=? LIMIT 1", (old,)).fetchone() or \
                db.execute('SELECT 1 FROM factory_batches WHERE project=? LIMIT 1', (old,)).fetchone()
            if old and not in_use:
                db.execute('DELETE FROM projects WHERE name=?', (old,))
        return request

    def _owned_videos(self, job):
        output = Path(job['output']).resolve()
        if not output.is_relative_to(self.store.outputs.resolve()):
            return []
        latest_path = final_video_path(job)
        final = latest_path.resolve()
        # output_layout limits names to this job's video-<uuid>[-N].mp4 family.
        paths = []
        candidates = [latest_path] + [path for path in job_video_files(job) if path.resolve() != final]
        for candidate in candidates[:100]:
            if candidate.is_symlink():
                continue
            path = candidate.resolve()
            if path.parent == final.parent and path.is_relative_to(self.store.outputs.resolve()) and path.is_file():
                paths.append(path)
        return paths

    def _probe_video(self, path):
        if self.video_probe:
            report = self.video_probe(path)
        else:
            from .media import probe
            report = probe(path)
        streams = report.get('streams', [])
        if not any(stream.get('codec_type') == 'video' for stream in streams) or not any(stream.get('codec_type') == 'audio' for stream in streams):
            raise ValueError('Bản xuất thiếu luồng hình hoặc tiếng')
        seconds = float(report.get('format', {}).get('duration', 0))
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Thời lượng bản xuất không hợp lệ')
        return seconds

    def _discover_versions(self, job, strict=True):
        if job['state'] != 'completed' or job['checkpoints'].get('verify', {}).get('verified') is not True:
            return []
        latest = final_video_path(job).resolve()
        recorded = job['checkpoints'].get('render', {}).get('video')
        if recorded and Path(recorded).resolve() != latest:
            return []
        attestations = [asset for stage in ('render', 'verify') for asset in job['checkpoints'].get(stage, {}).get('assets', [])]
        expected = {asset.get('sha256') for asset in attestations if Path(asset.get('path', '')).resolve() == latest}
        result = []
        for path in self._owned_videos(job):
            try:
                stat = path.stat()
                with self.store.db() as db:
                    cached = db.execute('''SELECT * FROM factory_video_versions
                        WHERE job_id=? AND path=? AND size=? AND mtime_ns=?
                        ORDER BY verified_at DESC LIMIT 1''',
                        (job['id'], str(path), stat.st_size, stat.st_mtime_ns)).fetchone()
                # Listing may reuse the already inspected file identity. Every
                # approval, direct download, pack and publishing lookup rehashes
                # bytes, even when an external edit preserves size and mtime.
                sha = cached['sha256'] if cached and not strict else digest(path)
                if path == latest and sha not in expected:
                    continue
                if path != latest:
                    with self.store.db() as db:
                        attested = db.execute('''SELECT 1 FROM factory_video_attestations
                            WHERE job_id=? AND path=? AND sha256=?''',
                            (job['id'], str(path), sha)).fetchone()
                    if not attested:
                        continue
                identifier = hashlib.sha256((str(path) + '\0' + sha).encode()).hexdigest()[:32]
                with self.store.db() as db:
                    old = db.execute('SELECT * FROM factory_video_versions WHERE job_id=? AND version_id=?', (job['id'], identifier)).fetchone()
                duration = old['duration_seconds'] if old and old['size'] == stat.st_size and old['mtime_ns'] == stat.st_mtime_ns else self._probe_video(path)
                # Bind a stable file, not bytes changed during inspection.
                if path.stat().st_mtime_ns != stat.st_mtime_ns or ((strict or not cached) and digest(path) != sha):
                    continue
                record = {'job_id': job['id'], 'version_id': identifier, 'path': str(path), 'sha256': sha,
                          'duration_seconds': duration, 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                          'created': stat.st_mtime, 'verified_at': time.time()}
                unchanged = (not strict and old is not None and old['sha256'] == sha and old['path'] == str(path)
                             and old['size'] == stat.st_size and old['mtime_ns'] == stat.st_mtime_ns)
                # Listing an unchanged, already recorded version needs no write.
                if not unchanged:
                    with self.store.db() as db:
                        db.execute('INSERT OR REPLACE INTO factory_video_versions VALUES(?,?,?,?,?,?,?,?,?)', tuple(record.values()))
                        if path == latest:
                            db.execute('INSERT OR IGNORE INTO factory_video_attestations VALUES(?,?,?,?,?)',
                                       (job['id'], str(path), sha, duration, record['verified_at']))
                record.update(id=identifier, name=path.name, latest=path == latest,
                              captions_available=path == latest and any(
                                  Path(asset.get('path', '')).suffix.lower() in ('.srt', '.vtt', '.ass')
                                  for asset in job['checkpoints'].get('subtitles', {}).get('assets', [])),
                              url=f"/api/factory/videos/{job['id']}/versions/{identifier}/file")
                result.append(record)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                continue
            except Exception:
                # ffprobe failures are not playable finished versions.
                continue
        return sorted(result, key=lambda item: (item['latest'], item['created']), reverse=True)

    def remember_verified(self, job_id):
        """Retain current checkpoint proof before a later render replaces it."""
        return next((version for version in self._discover_versions(self.store.get(job_id))
                     if version['latest']), None)

    def get_video_version(self, job_id, version_id=None):
        job = self.store.get(job_id)
        versions = self._discover_versions(job)
        selected = next((item for item in versions if item['version_id'] == version_id), None) if version_id else next((item for item in versions if item['latest']), None)
        if not selected:
            raise ValueError('Bản video chưa được xác minh, không tồn tại hoặc đã thay đổi')
        return selected

    def approve(self, job_id, version_id, sha256):
        version_id = _text(version_id, 'Phiên bản', 64)
        sha256 = _text(sha256, 'SHA-256', 64)
        version = self.get_video_version(job_id, version_id)
        if version['sha256'] != sha256:
            raise ValueError('Bản video đã thay đổi; hãy xem lại trước khi duyệt')
        record = {key: version[key] for key in ('job_id', 'version_id', 'path', 'sha256', 'duration_seconds')}
        record['approved_at'] = time.time()
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO factory_video_approvals VALUES(?,?,?,?,?,?)', tuple(record.values()))
        return record

    def approved_version(self, job_id, versions=None):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM factory_video_approvals WHERE job_id=?', (job_id,)).fetchone()
        if not row:
            return None
        try:
            current = (next((version for version in versions if version['version_id'] == row['version_id']), None)
                       if versions is not None else self.get_video_version(job_id, row['version_id']))
        except (KeyError, ValueError, OSError):
            return None
        if not current or current['path'] != row['path'] or current['sha256'] != row['sha256']:
            return None
        return dict(row)

    def _thumbnail(self, job):
        root = Path(job['output']).resolve()
        for stage in ('images', 'render'):
            for asset in job['checkpoints'].get(stage, {}).get('assets', []):
                path = Path(asset.get('path', '')).resolve()
                if path.parent == root and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') and path.is_file():
                    try:
                        if _cached_digest(path) == asset.get('sha256'):
                            return f"/api/jobs/{job['id']}/files/{path.name}"
                    except OSError:
                        pass
        return None

    def videos(self, q='', style='', project='', review_state='', status='', channel='', page=1, page_size=20):
        if type(page) is not int or page < 1 or page_size not in (10, 20, 30):
            raise ValueError('Phân trang phải dùng 10, 20 hoặc 30 video')
        if style and style not in STYLES:
            raise ValueError('Phong cách không hợp lệ')
        if review_state and review_state not in ('pending', 'approved'):
            raise ValueError('Trạng thái duyệt không hợp lệ')
        with self.store.db() as db:
            from .project_lifecycle import deleted_job_ids
            hidden = deleted_job_ids(db)
            ids = [row[0] for row in db.execute("SELECT id FROM jobs WHERE state='completed' ORDER BY created DESC") if row[0] not in hidden]
            metadata = {row['job_id']: dict(row) for row in db.execute('''SELECT i.job_id,i.title,b.style,b.input_mode FROM factory_items i
                JOIN factory_batches b ON b.id=i.batch_id WHERE i.job_id IS NOT NULL''')}
            # Publisher registers this optional query hook for per-channel state.
        records = []
        for identifier in ids:
            try:job = self.store.get(identifier)
            except KeyError:continue
            request = job['request']
            meta = metadata.get(identifier, {})
            item_style = meta.get('style') or ('meme' if request.get('workflow_mode') == 'meme' else 'news')
            item_project = request.get('project') or 'Dự án mặc định'
            title = meta.get('title') or request['idea'].splitlines()[0][:120]
            if style and style != item_style or project and project != item_project:
                continue
            if q.strip().casefold() not in (title + ' ' + item_project + ' ' + request['idea']).casefold():
                continue
            if status and status not in ('completed', 'ready'):
                continue
            versions = self._discover_versions(job, strict=False)
            if not versions or not any(version['latest'] for version in versions):
                continue
            approved = self.approved_version(identifier, versions)
            review = 'approved' if approved else 'pending'
            if review_state and review_state != review:
                continue
            channels = self.channel_states(identifier) if hasattr(self, 'channel_states') else []
            if channel and not any(item.get('channel') == channel for item in channels):
                continue
            for version in versions:
                version['approved'] = bool(approved and approved['version_id'] == version['version_id'])
            records.append({'id': identifier, 'job_id': identifier, 'title': title, 'project': item_project,
                            'style': item_style, 'input_mode': meta.get('input_mode') or ('script' if request.get('workflow_mode') == 'provided_narration' else request.get('meme_input_mode', 'idea')),
                            'state': 'completed', 'status': 'completed', 'created': job['created'],
                            'duration_seconds': versions[0]['duration_seconds'], 'thumbnail': self._thumbnail(job),
                            'output_url': versions[0]['url'], 'review_state': review, 'approved': approved,
                            'wide_url': f"/api/jobs/{identifier}/files/video-ngang.mp4" if job['checkpoints'].get('render', {}).get('video_ngang') else None,
                            'versions': versions, 'channels': channels})
        total = len(records)
        return {'items': records[(page - 1) * page_size:page * page_size], 'page': page, 'page_size': page_size,
                'total': total, 'total_pages': max(1, (total + page_size - 1) // page_size)}

    def pack(self, job_id, version_id=None, include=('video', 'captions', 'sidecar')):
        if not include or set(include) - {'video', 'captions', 'sidecar'}:
            raise ValueError('Thành phần tải không hợp lệ')
        version = self.get_video_version(job_id, version_id)
        job = self.store.get(job_id)
        # Keep large exports out of RAM; ZIP members are copied in bounded chunks.
        stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
        try:
            self._write_pack(stream, job, version, include)
            stream.seek(0)
            return stream
        except BaseException:
            stream.close()
            raise

    def _write_pack(self, stream, job, version, include):
        job_id = job['id']
        root = Path(job['output']).resolve()
        caption_names = []
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            if 'video' in include:
                checksum = hashlib.sha256()
                with open(version['path'], 'rb') as source, archive.open(Path(version['path']).name, 'w', force_zip64=True) as destination:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        checksum.update(chunk)
                        destination.write(chunk)
                if checksum.hexdigest() != version['sha256']:
                    raise ValueError('Bản video đã thay đổi trong lúc tải')
            if 'captions' in include and version['latest']:
                assets = job['checkpoints'].get('subtitles', {}).get('assets', [])
                seen = set()
                for asset in assets:
                    path = Path(asset.get('path', '')).resolve()
                    if path.parent != root or path.suffix.lower() not in ('.srt', '.vtt', '.ass') or path.name in seen or not path.is_file():
                        continue
                    if path.stat().st_size > 10 * 1024 * 1024:
                        raise ValueError('Tệp phụ đề vượt quá giới hạn 10 MB')
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != asset.get('sha256'):
                        raise ValueError('Tệp phụ đề đã thay đổi')
                    archive.writestr(path.name, raw)
                    seen.add(path.name)
                    caption_names.append(path.name)
            if 'sidecar' in include:
                archive.writestr('video-metadata.json', _json({'job_id': job_id, 'version_id': version['version_id'],
                    'sha256': version['sha256'], 'duration_seconds': version['duration_seconds'],
                    'request': job['request'] if version['latest'] else None,
                    'request_provenance': 'current_job' if version['latest'] else 'historical_request_unavailable',
                    'captions': {'status': ('not_selected' if 'captions' not in include else
                        'unavailable_for_older_version' if not version['latest'] else 'included' if caption_names else 'unavailable'),
                        'files': caption_names},
                    'approved': self.approved_version(job_id)}))
