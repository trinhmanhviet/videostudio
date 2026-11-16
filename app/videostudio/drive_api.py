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
from .notify import emit

DATA_FOLDER = 'data'


def in_main_folder(name):
    """A video's project folder on Drive holds only what a person opens: the videos and their subtitles."""
    return name.lower().endswith(('.mp4', '.srt'))


def register_drive_routes(app, store, factory, same_origin, stop_event=None, background=True):
    drive = DriveStorage(store)
    # Live progress of the sync, read by the Settings page every second or two.
    state = {'running': False, 'last': None, 'current': None, 'phase': None, 'started': None, 'jobs_total': 0, 'jobs_done': 0,
             'bytes_total': 0, 'bytes_done': 0, 'speed': 0.0, 'file': None, 'recent': [], 'result': None}
    meter = {'samples': []}

    def sent(total):
        """Record bytes moved in this run; speed is averaged over the last ~10 seconds."""
        now = time.time()
        if not meter.get('first'):
            meter['first'], meter['first_bytes'] = now, total
        meter['samples'] = [s for s in meter['samples'] if now - s[0] <= 10] + [(now, total)]
        first = meter['samples'][0]
        if now - first[0] >= 1:
            state['speed'] = (total - first[1]) / (now - first[0])

    def call(function, *args):
        try:
            return function(*args)
        except (ValueError, DriveError) as error:
            raise HTTPException(422, str(error))

    @app.get('/api/drive/status')
    def status():
        info = drive.status()
        for failure in info.get('failures') or []:
            try:
                job = store.get(failure['job_id'])
                failure['title'] = job['request'].get('title') or job['request'].get('project') or ''
            except Exception:
                failure['title'] = ''
        return {**info, 'sync': progress()}

    @app.get('/api/drive/progress')
    def progress():
        snapshot = json.loads(json.dumps(state))
        left = max(0, snapshot['bytes_total'] - snapshot['bytes_done'])
        # Time left from the average over the whole run: small subtitle files and per-file checks make the
        # last-ten-seconds speed jump around, the run average does not.
        elapsed = time.time() - (meter.get('first') or time.time())
        average = (snapshot['bytes_done'] - meter.get('first_bytes', 0)) / elapsed if elapsed > 3 else 0
        snapshot['average'] = average
        snapshot['eta'] = round(left / average) if snapshot['running'] and average > 1024 else None
        return snapshot

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
        for key in ('auto_upload', 'delete_local', 'include_old', 'delete_after_post'):
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
        if state['running']:
            return {'started': False, 'running': True}
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
            rows = [dict(r) for r in db.execute('SELECT * FROM drive_files WHERE job_id=? AND local_deleted=1 AND trashed=0', (job['id'],))]
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
        title = job['request'].get('title') or job.get('title') or project
        account = drive.pick_account(sum(p.stat().st_size for p in files))
        folder = drive.folder(account, ['Video', category(job), project])
        data_folder = None
        base = state['bytes_done']  # bytes of earlier jobs in this run
        for index, path in enumerate(files):
            size = path.stat().st_size
            info = {'job': title, 'project': project, 'name': path.name, 'index': index + 1, 'count': len(files), 'size': size, 'done': 0}
            state.update(file=info, phase='hash', current=f'{project} · {path.name}')
            with store.db() as db:
                old = db.execute('SELECT * FROM drive_files WHERE job_id=? AND kind=?', (job['id'], path.name)).fetchone()

            def hashed(done, info=info):
                info['done'] = done
            md5 = local_md5(path, hashed)
            if old and old['md5'] == md5 and old['size'] == size:
                base += size  # already on Drive from an earlier attempt
                state['bytes_done'] = base
                continue
            state['phase'] = 'upload'
            info['done'] = 0

            def moved(done, info=info, base=base):
                info['done'] = done
                state['bytes_done'] = base + done
                sent(base + done)
            # The project folder keeps what a person opens (the videos and their subtitles); the rest of a video's files
            # (cover, post text, MP3, other caption formats) go into its "data" folder.
            if in_main_folder(path.name):
                target = folder
            else:
                data_folder = data_folder or drive.folder(account, ['Video', category(job), project, DATA_FOLDER])
                target = data_folder
            result = drive.upload(account, path, target, progress=moved)
            state['phase'] = 'verify'
            if int(result.get('size', -1)) != size or result.get('md5Checksum') != md5:
                raise DriveError(f'{path.name}: tệp trên Drive không khớp bản trên máy; giữ nguyên bản trên máy')
            with store.db() as db:
                db.execute('''INSERT OR REPLACE INTO drive_files(job_id,kind,name,local_path,account,file_id,size,md5,duration,web_link,uploaded,local_deleted)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,0)''', (job['id'], path.name, path.name, str(path), account,
                           result['id'], size, md5, duration(path), result.get('webViewLink'), time.time()))
            base += size
            state['bytes_done'] = base
        if drive.setting('delete_local', True):
            state['phase'] = 'delete'
            for path in files:
                path.unlink(missing_ok=True)
            with store.db() as db:
                db.execute('UPDATE drive_files SET local_deleted=1 WHERE job_id=?', (job['id'],))
                db.execute('DELETE FROM drive_failures WHERE job_id=?', (job['id'],))
        return title

    def tidy_layout():
        """Files uploaded before the "data" folder existed: everything but the videos and subtitles moves into "data"
        beside them, and of a story's two .srt (one per video, same words and times) the landscape one stays as the
        shared one, named like the episode, the other goes to Drive's trash. Same file ids, so playing and posting
        from Drive go on working. Done once; anything Drive refuses is tried again on the next round."""
        if drive.setting('layout', 0) >= 2:
            return 0
        with store.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM drive_files WHERE local_deleted=1 AND trashed=0 ORDER BY job_id')]
        by_job = {}
        for row in rows:
            by_job.setdefault(row['job_id'], []).append(row)
        changed = problems = 0
        data_of = {}
        for job_rows in by_job.values():
            names = {r['name'] for r in job_rows}
            for row in job_rows:
                name = row['name']
                try:
                    if name.endswith('_doc.srt') and name[:-len('_doc.srt')] + '_ngang.srt' in names:
                        drive.trash(row['account'], row['file_id'])
                        with store.db() as db:
                            db.execute('UPDATE drive_files SET trashed=1 WHERE job_id=? AND kind=?', (row['job_id'], row['kind']))
                        changed += 1
                    elif name.endswith('_ngang.srt') and name[:-len('_ngang.srt')] + '_doc.srt' in names:
                        shared = name[:-len('_ngang.srt')] + '.srt'
                        drive.rename(row['account'], row['file_id'], shared)
                        with store.db() as db:
                            db.execute('UPDATE drive_files SET name=? WHERE job_id=? AND kind=?', (shared, row['job_id'], row['kind']))
                        changed += 1
                    elif not in_main_folder(name):
                        parent = drive.parent_of(row['account'], row['file_id'])
                        if not parent:
                            continue  # gone from Drive already
                        key = (row['account'], parent)
                        if key not in data_of:
                            data_of[key] = drive.child_folder(row['account'], parent, DATA_FOLDER)
                        if data_of[key] != parent:
                            drive.move(row['account'], row['file_id'], parent, data_of[key])
                            changed += 1
                except Exception:
                    problems += 1
        if not problems:
            drive.set_setting('layout', 2)
        if changed:
            emit('drive', f'🗂 Đã xếp lại {changed} tệp trên Drive: mỗi thư mục chỉ còn video và phụ đề, phần còn lại vào thư mục {DATA_FOLDER}.')
        return changed
    drive.tidy_layout = tidy_layout

    def sync_once():
        if state['running'] or not drive.setting('auto_upload', True) or not drive.accounts():
            return
        state.update(running=True, phase='scan', started=time.time(), jobs_total=0, jobs_done=0, bytes_total=0, bytes_done=0,
                     speed=0.0, file=None, recent=[], result=None)
        meter.clear()
        meter['samples'] = []
        uploaded = failed = 0
        try:
            work = list(candidates())  # every waiting video, one after another; new ones are picked up next round
            state['jobs_total'] = len(work)
            state['bytes_total'] = sum(p.stat().st_size for _, files in work for p in files if p.exists())
            for job, files in work:
                if stop_event and stop_event.is_set():
                    break
                start = state['bytes_done']
                try:
                    title = upload_job(job, files)
                    uploaded += 1
                    state['recent'] = ([{'job': title, 'files': [p.name for p in files], 'size': sum(p.stat().st_size for p in files if p.exists()) or state['bytes_done'] - start,
                                         'at': time.time()}] + state['recent'])[:8]
                except Exception as error:
                    failed += 1
                    state['bytes_total'] -= sum(p.stat().st_size for p in files if p.exists())  # a failed video leaves this run's totals
                    state['bytes_done'] = start
                    with store.db() as db:
                        row = db.execute('SELECT attempts FROM drive_failures WHERE job_id=?', (job['id'],)).fetchone()
                        attempts = (row['attempts'] if row else 0) + 1
                        db.execute('INSERT OR REPLACE INTO drive_failures VALUES(?,?,?,?)', (job['id'], str(error)[:500], attempts, time.time() + min(3600, 60 * 2 ** attempts)))
                state['jobs_done'] += 1
        finally:
            state['result'] = {'uploaded': uploaded, 'failed': failed, 'bytes': state['bytes_done'], 'seconds': round(time.time() - (state['started'] or time.time()))}
            if uploaded or failed:
                names = '; '.join(r['job'] for r in state['recent'][:uploaded][:5])
                emit('drive', f'☁️ Đã đưa {uploaded} video lên Drive ({state["bytes_done"] / 2**30:.1f} GB)'.replace('.', ',')
                     + (f': {names}' if names else '') + (f'\n⚠️ {failed} video chưa đưa lên được, tool sẽ tự thử lại.' if failed else ''))
            state.update(running=False, current=None, phase=None, file=None, speed=0.0, last=time.time())

    def trash_posted():
        """With "Xoá trên Drive sau khi đăng" on: once every post of a video is public, move its Drive copies to the trash."""
        if not drive.setting('delete_after_post', False):
            return 0
        with store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publishing_schedules'").fetchone():
                return 0
            rows = [dict(r) for r in db.execute('''SELECT f.* FROM drive_files f WHERE f.local_deleted=1 AND f.trashed=0
                AND EXISTS(SELECT 1 FROM publishing_schedules s WHERE s.job_id=f.job_id AND s.state='published')
                AND NOT EXISTS(SELECT 1 FROM publishing_schedules s WHERE s.job_id=f.job_id
                               AND s.state NOT IN ('published','cancelled'))''')]
        moved = 0
        for row in rows:
            try:
                drive.trash(row['account'], row['file_id'])
            except Exception:
                continue  # tried again next minute
            with store.db() as db:
                db.execute('UPDATE drive_files SET trashed=1 WHERE job_id=? AND kind=?', (row['job_id'], row['kind']))
            moved += 1
        if moved:
            emit('drive', f'🗑 Đã chuyển {moved} tệp video đã đăng vào thùng rác Drive.')
        return moved
    drive.trash_posted = trash_posted

    def loop():
        while not (stop_event and stop_event.is_set()):
            try:
                tidy_layout()
            except Exception:
                pass
            try:
                sync_once()
            except Exception:
                pass
            try:
                trash_posted()
            except Exception:
                pass
            time.sleep(60)

    if background:
        threading.Thread(target=loop, name='drive-sync', daemon=True).start()
    return drive
