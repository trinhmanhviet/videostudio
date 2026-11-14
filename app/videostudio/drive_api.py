"""Routes and the background sync that moves finished videos to Google Drive."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .drive_storage import CATEGORIES, DriveError, DriveStorage, local_md5


def register_drive_routes(app, store, factory, same_origin, stop_event=None, background=True):
    drive = DriveStorage(store)
    state = {'running': False, 'last': None, 'current': None}

    def call(function, *args):
        try:
            return function(*args)
        except (ValueError, DriveError) as error:
            raise HTTPException(422, str(error))

    @app.get('/api/drive/status')
    def status():
        return {**drive.status(), 'sync': {k: state[k] for k in ('running', 'last', 'current')}}

    @app.put('/api/drive/client')
    def client(data: dict, request: Request):
        same_origin(request)
        return call(drive.configure_client, data)

    @app.post('/api/drive/accounts/start')
    def start(request: Request):
        same_origin(request)
        return call(drive.oauth_start, callback_url(request))

    def callback_url(request):
        host = request.headers.get('x-forwarded-host') or request.headers.get('host') or '127.0.0.1:8877'
        name = host.split(':')[0]
        proto = request.headers.get('x-forwarded-proto') or ('http' if name in ('localhost', '127.0.0.1', '::1') else 'https')
        return f'{proto}://{host}/api/drive/oauth/callback'

    @app.get('/api/drive/callback-url')
    def show_callback(request: Request):
        return {'url': callback_url(request)}

    @app.get('/api/drive/oauth/callback')
    def callback(request: Request):
        params = request.query_params
        try:
            if params.get('error'):
                raise ValueError('Google báo: ' + params.get('error'))
            email = drive.oauth_finish(params.get('state', ''), params.get('code', ''))
            message = f'Đã kết nối Google Drive: {email}. Có thể đóng tab này.'
        except Exception as failure:
            message = 'Chưa kết nối được Google Drive: ' + str(failure)[:300]
        return HTMLResponse(f'<!doctype html><meta charset=utf-8><body style="font-family:sans-serif;background:#101827;color:#f3f6fa;padding:40px">'
                            f'<h2>{message}</h2><p><a style="color:#79c9ef" href="/?view=settings">Về Cài đặt</a></p>')

    @app.delete('/api/drive/accounts/{account}')
    def remove(account: str, request: Request):
        same_origin(request)
        return drive.remove(account)

    @app.post('/api/drive/accounts/order')
    def order(data: dict, request: Request):
        same_origin(request)
        return drive.reorder(data.get('ids') or [])

    @app.patch('/api/drive/settings')
    def settings(data: dict, request: Request):
        same_origin(request)
        for key in ('auto_upload', 'delete_local', 'include_old'):
            if key in data:
                if type(data[key]) is not bool:
                    raise HTTPException(422, key + ' phải là bật/tắt')
                drive.set_setting(key, data[key])
        return drive.status()

    @app.post('/api/drive/sync')
    def sync_now(request: Request):
        same_origin(request)
        with store.db() as db:
            db.execute('UPDATE drive_failures SET next_at=0')
        threading.Thread(target=sync_once, daemon=True).start()
        return {'started': True}

    @app.get('/api/drive/jobs/{job_id}/files/{name}')
    def stream(job_id: str, name: str, request: Request, download: bool = False):
        """Play or download a video that now lives on Drive (Range requests are passed through)."""
        with store.db() as db:
            row = db.execute('SELECT * FROM drive_files WHERE job_id=? AND name=?', (job_id, name)).fetchone()
        if not row:
            raise HTTPException(404, 'Không có tệp này trên Drive')
        client, response = drive.stream(row['account'], row['file_id'], request.headers.get('range'))
        if response.status_code not in (200, 206):
            client.close()
            raise HTTPException(502, f'Drive không trả tệp (mã {response.status_code})')
        headers = {k: v for k, v in response.headers.items() if k.lower() in ('content-length', 'content-range', 'accept-ranges')}
        headers['Accept-Ranges'] = 'bytes'
        if download:
            headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{name}"

        def body():
            try:
                yield from response.iter_bytes(1024 * 1024)
            finally:
                response.close()
                client.close()
        kind = 'video/mp4' if name.endswith('.mp4') else 'audio/mpeg' if name.endswith('.mp3') else 'text/plain; charset=utf-8'
        return StreamingResponse(body(), status_code=response.status_code, headers=headers, media_type=kind)

    def drive_versions(job):
        """Library entries for a job whose files were moved to Drive."""
        with store.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM drive_files WHERE job_id=? AND local_deleted=1', (job['id'],))]
        videos = [r for r in rows if r['name'].endswith('.mp4')]
        if not videos:
            return None
        primary = next((r for r in videos if r['name'].endswith('_doc.mp4')), videos[0])
        wide = next((r for r in videos if r['name'].endswith('_ngang.mp4')), None)
        url = lambda r: f'/api/drive/jobs/{job["id"]}/files/{r["name"]}'
        version = {'job_id': job['id'], 'version_id': 'drive-' + primary['md5'][:24], 'id': 'drive-' + primary['md5'][:24], 'path': primary['local_path'],
                   'sha256': primary['md5'], 'duration_seconds': primary['duration'] or 0, 'size': primary['size'], 'created': primary['uploaded'],
                   'latest': True, 'name': primary['name'], 'url': url(primary), 'captions_available': False, 'drive': True,
                   'drive_link': primary['web_link']}
        return {'versions': [version], 'wide_url': url(wide) if wide and wide is not primary else None,
                'drive_files': [{'name': r['name'], 'url': url(r), 'download': url(r) + '?download=true', 'link': r['web_link'], 'size': r['size']} for r in rows]}
    factory.drive_versions = drive_versions

    # --- background sync -------------------------------------------------------------------------------------
    def candidates():
        from .output_layout import job_deliverables
        with store.db() as db:
            done = {r['job_id'] for r in db.execute('SELECT job_id FROM drive_files WHERE local_deleted=1')}
            waiting = {r['job_id']: r['next_at'] for r in db.execute('SELECT job_id,next_at FROM drive_failures')}
            scheduled = set()
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publishing_schedules'").fetchone():
                scheduled = {r[0] for r in db.execute("SELECT job_id FROM publishing_schedules WHERE state IN ('scheduled','processing','uploading','blocked','needs_attention')")}
            since = 0 if drive.setting('include_old', False) else (drive.setting('since') or time.time())
            ids = [r['id'] for r in db.execute("SELECT id FROM jobs WHERE state='completed' AND updated>=? ORDER BY updated", (since,))]
        for job_id in ids:
            if job_id in done or job_id in scheduled or waiting.get(job_id, 0) > time.time():
                continue
            try:
                job = store.get(job_id)
            except KeyError:
                continue
            if job['checkpoints'].get('verify', {}).get('verified') is not True:
                continue
            files = [p for p in job_deliverables(job) if p.is_file()]
            if files:
                yield job, files

    def category(job):
        with store.db() as db:
            row = db.execute('SELECT b.style FROM factory_items i JOIN factory_batches b ON b.id=i.batch_id WHERE i.job_id=?', (job['id'],)).fetchone()
        style = (row['style'] if row else None) or job['request'].get('content_style') or ('meme' if job['request'].get('workflow_mode') == 'meme' else 'news')
        return CATEGORIES.get(style, 'khac')

    def duration(path):
        if not str(path).endswith('.mp4'):
            return None
        try:
            out = subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)], timeout=30)
            return float(out.strip())
        except Exception:
            return None

    def upload_job(job, files):
        project = job['request'].get('project') or 'Dự án mặc định'
        account = drive.pick_account(sum(p.stat().st_size for p in files))
        folder = drive.folder(account, ['Video', category(job), project])
        for path in files:
            with store.db() as db:
                old = db.execute('SELECT * FROM drive_files WHERE job_id=? AND kind=?', (job['id'], path.name)).fetchone()
            md5 = local_md5(path)
            if old and old['md5'] == md5 and old['size'] == path.stat().st_size:
                continue  # already on Drive from an earlier attempt
            state['current'] = f'{project} · {path.name}'
            result = drive.upload(account, path, folder)
            if int(result.get('size', -1)) != path.stat().st_size or result.get('md5Checksum') != md5:
                raise DriveError(f'{path.name}: tệp trên Drive không khớp bản trên máy; giữ nguyên bản trên máy')
            with store.db() as db:
                db.execute('INSERT OR REPLACE INTO drive_files VALUES(?,?,?,?,?,?,?,?,?,?,?,0)', (job['id'], path.name, path.name, str(path), account,
                           result['id'], path.stat().st_size, md5, duration(path), result.get('webViewLink'), time.time()))
        if drive.setting('delete_local', True):
            for path in files:
                path.unlink(missing_ok=True)
            with store.db() as db:
                db.execute('UPDATE drive_files SET local_deleted=1 WHERE job_id=?', (job['id'],))
                db.execute('DELETE FROM drive_failures WHERE job_id=?', (job['id'],))

    def sync_once():
        if state['running'] or not drive.setting('auto_upload', True) or not drive.accounts():
            return
        state['running'] = True
        try:
            for job, files in candidates():
                try:
                    upload_job(job, files)
                except Exception as error:
                    with store.db() as db:
                        row = db.execute('SELECT attempts FROM drive_failures WHERE job_id=?', (job['id'],)).fetchone()
                        attempts = (row['attempts'] if row else 0) + 1
                        db.execute('INSERT OR REPLACE INTO drive_failures VALUES(?,?,?,?)', (job['id'], str(error)[:500], attempts, time.time() + min(3600, 60 * 2 ** attempts)))
                break  # one job per round keeps uploads gentle; the loop comes back soon
        finally:
            state['running'] = False
            state['current'] = None
            state['last'] = time.time()

    def loop():
        while not (stop_event and stop_event.is_set()):
            try:
                sync_once()
            except Exception:
                pass
            time.sleep(60)

    if background:
        threading.Thread(target=loop, name='drive-sync', daemon=True).start()
    return drive
