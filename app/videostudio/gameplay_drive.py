"""Gameplay folder on Google Drive: the user drops gameplay videos into one folder; the tool fetches the new ones into
the gameplay library by itself, and once a video has played a clip to its end the clip is moved into "Used" inside that
folder. With "Dùng lại clip đã dùng" on, used clips stay in the playlists (and clips already in Used are fetched too).

State lives in the story library (gameplay_settings, and drive_folder/used/moved on each clip). The move on Drive may
fail (no permission yet, network): the clip is still counted as used, and the move is retried on the next sync.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from pathlib import Path

from .drive_storage import CACHE, DriveError, DriveStorage, cache_trim, folder_id_from_link
from .notify import emit

VIDEO_TYPES = {'.mp4', '.mkv', '.mov', '.webm'}
SYNC_EVERY = 15 * 60
REPORTED = {}  # the last sync problem sent to Telegram
USED = 'Used'


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class GameplayFolder:
    def __init__(self, store, library, drive=None):
        self.store, self.library = store, library
        self.drive = drive or DriveStorage(store)
        self.lock = threading.Lock()
        self.task = {'state': 'idle', 'done': 0, 'total': 0, 'current': '', 'received': 0, 'size': 0, 'added': 0, 'error': None}
        self.on_new_clips = None  # called after a sync that added clips (Làm dần cả truyện goes on when enough)

    def source(self):
        return self.library.gameplay_setting('folder')

    def status(self):
        source = self.source()
        counts = self.library.folder_counts(source['id']) if source else {'new': 0, 'used': 0, 'to_move': 0}
        return {'folder': source, 'reuse': self.library.gameplay_setting('reuse', False), **counts, 'task': dict(self.task)}

    def browse(self, account=None, parent='root'):
        """For the folder picker: connected accounts, the sub-folders of parent and how many videos parent holds."""
        accounts = [a['id'] for a in self.drive.accounts() if not a.get('disabled')]
        if not accounts:
            raise ValueError('Chưa kết nối tài khoản Google Drive. Vào Cài đặt → Google Drive để thêm tài khoản.')
        account = account if account in accounts else accounts[0]
        parent = str(parent or 'root')
        if parent not in ('root', 'shared') and not re.fullmatch(r'[A-Za-z0-9_-]{10,}', parent):
            raise ValueError('Thư mục không hợp lệ')
        folders = self.drive.list_folders(account, parent)
        videos = 0 if parent in ('root', 'shared') else len(self.drive.list_videos(account, parent))
        return {'accounts': accounts, 'account': account, 'parent': parent, 'folders': folders, 'videos': videos}

    def configure(self, data):
        """data: {link? (a link or a folder id), account?, reuse?, clear?}. A new folder is checked on Drive before it is saved."""
        if data.get('clear'):
            self.library.set_gameplay_setting('folder', None)
        elif data.get('link'):
            folder_id = folder_id_from_link(data['link'])
            account, meta = self.drive.find_folder(folder_id, data.get('account'))
            self.library.set_gameplay_setting('folder', {'id': folder_id, 'name': meta.get('name') or folder_id, 'account': account,
                                                          'used_id': None, 'last_sync': None, 'error': None})
        if 'reuse' in data:
            if type(data['reuse']) is not bool:
                raise ValueError('reuse phải là bật/tắt')
            self.library.set_reuse(data['reuse'])
        return self.status()

    def _save(self, **changes):
        source = self.source()
        if source:
            self.library.set_gameplay_setting('folder', {**source, **changes})

    def _used_folder(self, source, create=True):
        if source.get('used_id'):
            return source['used_id']
        used = self.drive.child_folder(source['account'], source['id'], USED, create=create)
        if used:
            self._save(used_id=used)
        return used

    # --- sync --------------------------------------------------------------------------------------------------
    def start_sync(self):
        if not self.source():
            raise ValueError('Chưa chọn thư mục gameplay trên Drive')
        if self.task['state'] == 'running':
            return self.status()
        self.task.update(state='running', error=None)
        threading.Thread(target=self.sync, name='gameplay-drive-sync', daemon=True).start()
        return self.status()

    def tick(self):
        """Called about once a minute by the app: fetch new clips every SYNC_EVERY seconds."""
        source = self.source()
        if source and self.task['state'] != 'running' and time.time() - (source.get('last_sync') or 0) >= SYNC_EVERY:
            self.task['state'] = 'running'
            self.sync()

    def sync(self):
        if not self.lock.acquire(blocking=False):
            return self.status()
        try:
            source = self.source()
            if not source:
                self.task.update(state='idle')
                return self.status()
            self.task.update(state='running', done=0, total=0, current='', received=0, size=0, added=0, error=None)
            known = self.library.drive_clip_ids() | set(self.library.gameplay_setting('duplicate_ids', []))
            wanted = [(f, False) for f in self.drive.list_videos(source['account'], source['id'])]
            if self.library.gameplay_setting('reuse', False):
                used_folder = self._used_folder(source, create=False)
                if used_folder:
                    wanted += [(f, True) for f in self.drive.list_videos(source['account'], used_folder)]
            wanted = [(f, used) for f, used in wanted if f['id'] not in known and Path(f.get('name', '')).suffix.lower() in VIDEO_TYPES]
            self.task.update(total=len(wanted))
            problems = []
            for meta, used in wanted:
                name = meta.get('name') or meta['id'] + '.mp4'
                self.task.update(current=name, received=0, size=int(meta.get('size') or 0))
                target = CACHE / f'{meta["id"]}{Path(name).suffix.lower()}'
                try:
                    size = int(meta.get('size') or 0)
                    if size and target.is_file() and target.stat().st_size == size:
                        sha = file_sha256(target)  # already here from an earlier sync: no second download
                    else:
                        sha, _ = self.drive.download(meta['id'], target, account=source['account'], progress=lambda n: self.task.update(received=n))
                    if self._skip_duplicate(meta['id'], sha, target):
                        self.task['done'] += 1
                        continue
                    self.library.add_gameplay_cached(target, name, sha, meta['id'], f'https://drive.google.com/file/d/{meta["id"]}/view',
                                                     folder=source['id'], used=used)
                    cache_trim(keep=[target])
                    self.task['added'] += 1
                except Exception as error:  # one bad file must not stop the others
                    problems.append(f'{name}: {str(error)[:120]}')
                self.task['done'] += 1
            try:
                self.move_used()
            except DriveError as error:
                problems.append(str(error))
            error = '; '.join(problems)[:600] or None
            self._save(last_sync=time.time(), error=error)
            self.task.update(state='done', current='', error=error)
            if self.task['added']:
                emit('drive', f'🎮 Đã lấy {self.task["added"]} clip gameplay mới từ Drive.')
                if self.on_new_clips:
                    try:
                        self.on_new_clips()
                    except Exception:  # noqa: BLE001 - its own check runs again shortly
                        pass
            if error and error != REPORTED.get('error'):
                emit('drive', f'⚠️ Lấy clip gameplay từ Drive có lỗi, tool sẽ thử lại lần sau:\n{error[:300]}')
        except Exception as error:
            self._save(last_sync=time.time(), error=str(error)[:300])
            self.task.update(state='failed', current='', error=str(error)[:300])
            if str(error)[:300] != REPORTED.get('error'):
                emit('drive', f'⚠️ Đồng bộ thư mục gameplay trên Drive lỗi, tool sẽ thử lại lần sau:\n{str(error)[:300]}')
        finally:
            REPORTED['error'] = self.task.get('error')  # the same problem is reported once, not every sync
            self.lock.release()
        return self.status()

    def _skip_duplicate(self, file_id, sha, target):
        """A Drive file with the same picture as a clip already fetched (a video uploaded twice) or one the owner
        deleted: never a second clip. Its Drive id is remembered, so later syncs do not download it again, and the
        downloaded copy leaves the cache."""
        with self.library.db() as db:
            row = db.execute('SELECT * FROM gameplay WHERE sha256=?', (sha,)).fetchone()
        if not row or (not row['deleted'] and not row['drive_file_id']):
            return False  # new, or a clip added from this computer that this Drive file now backs (kept as before)
        ids = self.library.gameplay_setting('duplicate_ids', [])
        if file_id not in ids:
            self.library.set_gameplay_setting('duplicate_ids', ids + [file_id])
        if Path(target).resolve() != Path(row['path']).resolve():
            Path(target).unlink(missing_ok=True)
        return True

    # --- one clip: play it, delete it everywhere -----------------------------------------------------------------
    def _row(self, clip_id):
        with self.library.db() as db:
            row = db.execute('SELECT * FROM gameplay WHERE id=? AND deleted=0', (clip_id,)).fetchone()
        if not row:
            raise KeyError('Không tìm thấy clip')
        return dict(row)

    def _account_for(self, row):
        """The Drive account that can reach a clip: its gameplay folder's account, else the first one that sees it."""
        source = self.source()
        if source and row.get('drive_folder') == source['id']:
            return source['account']
        account, _ = self.drive.metadata(row['drive_file_id'])
        return account

    def playback(self, clip_id):
        """Where the clip can be played from: ('file', path) when it is on this computer, else ('drive', account, file id)."""
        row = self._row(clip_id)
        if Path(row['path']).is_file():
            return 'file', Path(row['path'])
        if row.get('drive_file_id'):
            return 'drive', self._account_for(row), row['drive_file_id']
        raise KeyError('Không thấy tệp của clip này trên máy')

    def delete_clip(self, clip_id, in_use):
        """The owner deleted the clip (confirmed on its thumbnail): it leaves every book, its file and preview leave this
        computer, and its Drive file goes to Drive's trash (Google keeps it 30 days). A clip a queued video still uses
        is refused. The library keeps the Drive id, so the folder sync never fetches the clip again."""
        row = self._row(clip_id)
        self.library.remove_gameplay(clip_id, in_use)
        path = Path(row['path'])
        roots = [Path(self.library.gameplay_root).resolve(), CACHE.resolve()]
        local = False
        if path.is_file() and any(path.resolve().is_relative_to(root) for root in roots):
            path.unlink(missing_ok=True)
            local = True
        (Path(self.library.root) / 'previews' / f'thumb-{row["sha256"][:16]}.jpg').unlink(missing_ok=True)
        drive, problem = 'none', None
        if row.get('drive_file_id'):
            try:
                drive = 'trashed' if self.drive.trash(self._account_for(row), row['drive_file_id']) else 'gone'
            except Exception as error:  # the clip is gone here either way; say why Drive kept its file
                drive, problem = 'failed', str(error)[:300]
        emit('drive', f'🗑 Đã xoá clip gameplay: {row.get("name") or Path(row["path"]).name}'
             + {'trashed': ' (bản trên Drive vào thùng rác)', 'failed': f'\n⚠️ Drive chưa xoá được: {problem}'}.get(drive, ''))
        return {'deleted': True, 'local': local, 'drive': drive, 'error': problem}

    # --- used clips --------------------------------------------------------------------------------------------
    def move_used(self):
        """Move every used clip of the folder into Used on Drive. Raises DriveError (with how to fix it) if Drive refuses."""
        source = self.source()
        if not source:
            return 0
        pending = self.library.clips_to_move(source['id'])
        if not pending:
            return 0
        used = self._used_folder(source)
        moved = 0
        for clip in pending:
            self.drive.move(source['account'], clip['drive_file_id'], source['id'], used)
            self.library.set_moved(clip['id'])
            moved += 1
        return moved

    def after_plan(self, segments, clips, log=lambda message: None):
        """A new gameplay plan was made: clips it played to their end are used. Never fails the video."""
        ends = {c['id']: c['end'] for c in clips}
        finished = {s['id'] for s in segments if s['id'] in ends and s['start'] + s['length'] >= ends[s['id']] - .5}
        newly = self.library.mark_used(finished)
        if not newly:
            return []
        try:
            self.move_used()
            log(f'Đã chuyển {len(newly)} clip gameplay đã dùng vào thư mục {USED} trên Drive.')
            emit('drive', f'🎮 Đã chuyển {len(newly)} clip gameplay đã dùng vào thư mục {USED} trên Drive.')
        except Exception as error:
            self._save(error=str(error)[:300])
            log(f'{len(newly)} clip gameplay đã dùng; chưa chuyển được vào {USED} trên Drive ({str(error)[:160]}). Tool sẽ thử lại khi lấy clip mới.')
        return newly
