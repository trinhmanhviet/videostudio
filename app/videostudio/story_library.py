"""Story library for the "Kể truyện" mode: books, chapters, gameplay clips, backgrounds and frozen episode snapshots.

Shared by every browser of this local instance (SQLite under DATA_ROOT/story-library). Text is stored on the server
with a revision per chapter; a stale save gets a clear conflict instead of overwriting newer text. Episodes are frozen
into immutable snapshot files when queued, so editing a draft later never changes a job that is already waiting or
running. Gameplay sources are kept once, by content hash, in DATA_ROOT/media-library/gameplay (not inside any job).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path

from .paths import DATA_ROOT

STORY_ROOT = Path(os.getenv('VS_STORY_ROOT', str(DATA_ROOT / 'story-library')))
GAMEPLAY_ROOT = Path(os.getenv('VS_GAMEPLAY_ROOT', str(DATA_ROOT / 'media-library' / 'gameplay')))
VIDEO_TYPES = {'.mp4', '.mkv', '.mov', '.webm'}
IMAGE_TYPES = {'.png', '.jpg', '.jpeg', '.webp'}
MAX_CHAPTER_CHARS = 400_000
HEADING = re.compile(r'^\s*(?:Chương|Chuong|Chapter|Hồi|Hoi)\s+(\d+)\s*[.:：\-–—]?\s*(.*?)\s*$', re.I)

DEFAULT_SETTINGS = {'speech_engine': 'vieneu', 'voice_id': 'Thiện Minh', 'speech_rhythm': 'story', 'speech_speed': 1.0,
                    'khanh_steps': 32, 'speech_batch_size': 256}
DEFAULT_LAYOUT = {'channel': '', 'background': 'preset:dem-xanh', 'horizontal': True, 'vertical': True,
                  'burn_subtitles': True, 'export_srt': True, 'export_mp3': True, 'game_audio': False,
                  'continue_gameplay': True, 'game_box': {}, 'video_codec': 'hevc'}
# Built-in backgrounds: gradients rendered by FFmpeg, no image files required.
PRESET_BACKGROUNDS = {
    'preset:dem-xanh': {'name': 'Đêm xanh', 'top': '0x0b1a33', 'bottom': '0x1d3b63'},
    'preset:hoang-hon': {'name': 'Hoàng hôn', 'top': '0x2a1033', 'bottom': '0x7a3b2e'},
    'preset:rung-sau': {'name': 'Rừng sâu', 'top': '0x0c1f17', 'bottom': '0x24513a'},
    'preset:giay-cu': {'name': 'Giấy cũ', 'top': '0x3a2c1c', 'bottom': '0x6b5232'},
}


def slug(text, limit=60):
    value = unicodedata.normalize('NFD', str(text or '')).replace('đ', 'd').replace('Đ', 'D')
    value = ''.join(ch for ch in value if unicodedata.category(ch) != 'Mn').lower()
    value = re.sub(r'[^a-z0-9]+', '-', value).strip('-')
    return value[:limit].strip('-') or 'truyen'


def natural_key(name):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', str(name))]


def words(text):
    return len(re.findall(r'\S+', text or ''))


def sha256_text(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def clean_text(text):
    """Technical normalisation only: line endings, BOM, trailing spaces and runs of blank lines. Words are never touched."""
    text = str(text or '').replace('﻿', '').replace('\r\n', '\n').replace('\r', '\n')
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def split_heading(text):
    """Separate a clear chapter heading on the first line. Anything unclear stays in the body."""
    text = clean_text(text)
    first, _, rest = text.partition('\n')
    match = HEADING.match(first)
    if not match or not rest.strip():
        return None, '', text
    return int(match.group(1)), match.group(2).strip(), rest.strip()


def split_chapters(text):
    """A merged file (several "Chương N" headings) becomes several chapters; the first line before them may be the book title."""
    text = clean_text(text)
    lines = text.split('\n')
    marks = [i for i, line in enumerate(lines) if HEADING.match(line)]
    if len(marks) < 2:
        return None, []
    intro = '\n'.join(lines[:marks[0]]).strip()
    title = intro.split('\n')[0].strip() if intro and len(intro.split('\n')[0]) <= 200 else ''
    chapters = []
    for index, start in enumerate(marks):
        end = marks[index + 1] if index + 1 < len(marks) else len(lines)
        match = HEADING.match(lines[start])
        body = '\n'.join(lines[start + 1:end]).strip()
        if body:
            chapters.append({'number': int(match.group(1)), 'title': match.group(2).strip(), 'text': body})
    return title, chapters


def estimate_seconds(text, rate=4.2, speed=1.0):
    """Rough reading time from Vietnamese syllables; the real length always comes from the WAV."""
    return max(1.0, words(text) / max(.5, rate) / max(.5, float(speed or 1)))


class StoryLibrary:
    def __init__(self, root=None, gameplay_root=None, ffprobe='ffprobe', ffmpeg='ffmpeg'):
        self.root = Path(root or STORY_ROOT)
        self.gameplay_root = Path(gameplay_root or GAMEPLAY_ROOT)
        self.ffprobe, self.ffmpeg = ffprobe, ffmpeg
        for folder in (self.root, self.root / 'snapshots', self.root / 'backgrounds', self.root / 'previews', self.gameplay_root, self.gameplay_root / '.incoming'):
            folder.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'library.sqlite3'
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, title TEXT NOT NULL, settings TEXT NOT NULL, layout TEXT NOT NULL,
                revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, source TEXT);
            CREATE TABLE IF NOT EXISTS chapters(id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id), position REAL NOT NULL,
                number INTEGER, title TEXT NOT NULL, read_title INTEGER NOT NULL DEFAULT 1, text TEXT NOT NULL, sha256 TEXT NOT NULL,
                source_name TEXT, revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS chapters_book ON chapters(book_id, deleted, position);
            CREATE TABLE IF NOT EXISTS gameplay(id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
                duration REAL NOT NULL, width INTEGER, height INTEGER, fps REAL, has_audio INTEGER NOT NULL, size INTEGER NOT NULL,
                created REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS book_gameplay(book_id TEXT NOT NULL, gameplay_id TEXT NOT NULL, position REAL NOT NULL,
                start REAL NOT NULL DEFAULT 0, end REAL, PRIMARY KEY(book_id, gameplay_id));
            CREATE TABLE IF NOT EXISTS gameplay_cursor(book_id TEXT PRIMARY KEY, clip INTEGER NOT NULL, offset REAL NOT NULL,
                job_id TEXT, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, book_id TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
                chapter_ids TEXT NOT NULL, idem TEXT UNIQUE, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS chapter_history(chapter_id TEXT NOT NULL, revision INTEGER NOT NULL, title TEXT NOT NULL,
                text TEXT NOT NULL, sha256 TEXT NOT NULL, saved REAL NOT NULL, reason TEXT NOT NULL);
            ''')
            # source_sha256 = the text as last imported from a file or the ChatGPT edit. When the chapter text differs
            # from it, the user has edited the chapter and a later import must never overwrite it.
            columns = {r['name'] for r in db.execute('PRAGMA table_info(gameplay)')}
            if 'drive_file_id' not in columns:
                db.execute('ALTER TABLE gameplay ADD COLUMN drive_file_id TEXT')
                db.execute('ALTER TABLE gameplay ADD COLUMN source_url TEXT')
            if 'source_sha256' not in {r['name'] for r in db.execute('PRAGMA table_info(chapters)')}:
                db.execute('ALTER TABLE chapters ADD COLUMN source_sha256 TEXT')
                db.execute('UPDATE chapters SET source_sha256=sha256')

    @contextmanager
    def db(self):
        with self.lock:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    # --- books -------------------------------------------------------------------------------------------
    def _book(self, row):
        settings = {**DEFAULT_SETTINGS, **json.loads(row['settings'])}
        layout = {**DEFAULT_LAYOUT, **json.loads(row['layout'])}
        return {'id': row['id'], 'title': row['title'], 'settings': settings, 'layout': layout, 'revision': row['revision'],
                'created': row['created'], 'updated': row['updated'], 'source': row['source']}

    def books(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM books WHERE deleted=0 ORDER BY updated DESC').fetchall()
            counts = {r['book_id']: (r['n'], r['w']) for r in db.execute(
                'SELECT book_id, COUNT(*) n, SUM(LENGTH(text)) w FROM chapters WHERE deleted=0 GROUP BY book_id')}
        return [{**self._book(row), 'chapters': counts.get(row['id'], (0, 0))[0]} for row in rows]

    def book(self, book_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM books WHERE id=? AND deleted=0', (book_id,)).fetchone()
        if not row:
            raise KeyError('Không tìm thấy truyện')
        return self._book(row)

    def create_book(self, title, source=None, settings=None):
        title = str(title or '').strip()[:200]
        if not title:
            raise ValueError('Nhập tên truyện')
        now, identifier = time.time(), uuid.uuid4().hex
        with self.db() as db:
            if source:
                old = db.execute('SELECT id FROM books WHERE source=? AND deleted=0', (source,)).fetchone()
                if old:
                    return self.book(old['id'])
            last = db.execute('SELECT settings FROM books WHERE deleted=0 ORDER BY updated DESC LIMIT 1').fetchone()
            inherited = json.loads(last['settings']) if last else {}
            db.execute('INSERT INTO books VALUES(?,?,?,?,?,?,?,0,?)', (identifier, title, json.dumps({**inherited, **(settings or {})}, ensure_ascii=False),
                       json.dumps({}, ensure_ascii=False), 1, now, now, source))
            # A new book uses every gameplay clip already in the library, in import order.
            for index, clip in enumerate(db.execute('SELECT id FROM gameplay WHERE deleted=0 ORDER BY created').fetchall()):
                db.execute('INSERT OR IGNORE INTO book_gameplay VALUES(?,?,?,0,NULL)', (identifier, clip['id'], index))
        return self.book(identifier)

    def update_book(self, book_id, data):
        allowed = {'title', 'settings', 'layout', 'expected_revision'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError('Trường truyện không hợp lệ')
        with self.db() as db:
            row = db.execute('SELECT * FROM books WHERE id=? AND deleted=0', (book_id,)).fetchone()
            if not row:
                raise KeyError('Không tìm thấy truyện')
            if 'expected_revision' in data and data['expected_revision'] != row['revision']:
                raise ConflictError('Thiết lập truyện vừa được lưu ở cửa sổ khác. Tải lại để xem bản mới.')
            title = str(data.get('title', row['title'])).strip()[:200] or row['title']
            settings = {**json.loads(row['settings']), **validate_settings(data.get('settings', {}))}
            layout = {**json.loads(row['layout']), **validate_layout(data.get('layout', {}))}
            db.execute('UPDATE books SET title=?,settings=?,layout=?,revision=revision+1,updated=? WHERE id=?',
                       (title, json.dumps(settings, ensure_ascii=False), json.dumps(layout, ensure_ascii=False), time.time(), book_id))
        return self.book(book_id)

    def delete_book(self, book_id):
        with self.db() as db:
            if not db.execute('UPDATE books SET deleted=1,updated=? WHERE id=? AND deleted=0', (time.time(), book_id)).rowcount:
                raise KeyError('Không tìm thấy truyện')
        return {'deleted': True}

    # --- chapters ----------------------------------------------------------------------------------------
    def _chapter(self, row, text=False):
        value = {'id': row['id'], 'book_id': row['book_id'], 'position': row['position'], 'number': row['number'], 'title': row['title'],
                 'read_title': bool(row['read_title']), 'sha256': row['sha256'], 'source_name': row['source_name'],
                 'revision': row['revision'], 'words': words(row['text']), 'characters': len(row['text']), 'updated': row['updated']}
        if text:
            value['text'] = row['text']
        return value

    def chapters(self, book_id, q='', page=1, page_size=50):
        self.book(book_id)
        page, page_size = max(1, int(page)), min(200, max(1, int(page_size)))
        with self.db() as db:
            rows = db.execute('SELECT * FROM chapters WHERE book_id=? AND deleted=0 ORDER BY position', (book_id,)).fetchall()
        items = [self._chapter(row) for row in rows]
        for index, item in enumerate(items, 1):
            item['order'] = index
        needle = slug(q, 200).replace('-', ' ') if q else ''
        if needle:
            items = [i for i in items if needle in slug(i['title'], 200).replace('-', ' ') or needle == str(i['order'])]
        total_words = sum(i['words'] for i in items)
        start = (page - 1) * page_size
        return {'items': items[start:start + page_size], 'total': len(items), 'page': page, 'page_size': page_size,
                'total_words': total_words, 'all_ids': [i['id'] for i in items]}

    def chapter(self, chapter_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM chapters WHERE id=? AND deleted=0', (chapter_id,)).fetchone()
        if not row:
            raise KeyError('Không tìm thấy chương')
        return self._chapter(row, text=True)

    def save_chapter(self, chapter_id, data):
        if not isinstance(data, dict) or set(data) - {'title', 'text', 'read_title', 'expected_revision'}:
            raise ValueError('Trường chương không hợp lệ')
        with self.db() as db:
            row = db.execute('SELECT * FROM chapters WHERE id=? AND deleted=0', (chapter_id,)).fetchone()
            if not row:
                raise KeyError('Không tìm thấy chương')
            if 'expected_revision' in data and data['expected_revision'] != row['revision']:
                raise ConflictError('Chương này vừa được lưu ở cửa sổ khác. Tải lại để xem bản mới, phần bạn đang gõ vẫn còn trong bản nháp.')
            text = clean_text(data.get('text', row['text']))
            if not text:
                raise ValueError('Chương chưa có nội dung')
            if len(text) > MAX_CHAPTER_CHARS:
                raise ValueError('Chương quá dài (tối đa 400.000 ký tự); hãy tách thành nhiều chương')
            title = str(data.get('title', row['title'])).strip()[:300]
            read_title = int(bool(data.get('read_title', row['read_title'])))
            changed = (text, title, read_title) != (row['text'], row['title'], row['read_title'])
            if changed:
                self._remember(db, row, 'trước khi lưu')
                db.execute('UPDATE chapters SET title=?,text=?,read_title=?,sha256=?,revision=revision+1,updated=? WHERE id=?',
                           (title, text, read_title, sha256_text(text), time.time(), chapter_id))
                db.execute('UPDATE books SET updated=? WHERE id=?', (time.time(), row['book_id']))
        return self.chapter(chapter_id)

    def rename_chapter(self, chapter_id, title):
        return self.save_chapter(chapter_id, {'title': title})

    def delete_chapters(self, book_id, chapter_ids):
        with self.db() as db:
            count = 0
            for identifier in chapter_ids:
                count += db.execute('UPDATE chapters SET deleted=1,updated=? WHERE id=? AND book_id=? AND deleted=0', (time.time(), identifier, book_id)).rowcount
        return {'deleted': count}

    def reorder(self, book_id, chapter_ids):
        with self.db() as db:
            known = {r['id'] for r in db.execute('SELECT id FROM chapters WHERE book_id=? AND deleted=0', (book_id,))}
            if set(chapter_ids) != known or len(chapter_ids) != len(known):
                raise ConflictError('Danh sách chương đã thay đổi. Tải lại rồi sắp xếp lại.')
            for index, identifier in enumerate(chapter_ids):
                db.execute('UPDATE chapters SET position=? WHERE id=?', (index, identifier))
        return self.chapters(book_id, page_size=200)

    def import_files(self, book_id, files, split=True):
        """files: [{name, text}]. One file = one chapter; a merged file with many "Chương N" headings is split.
        Re-importing the same file skips it; same name with new text becomes a new revision of that chapter."""
        self.book(book_id)
        if not isinstance(files, list) or not 1 <= len(files) <= 200:
            raise ValueError('Mỗi lần nhập 1–200 tệp')
        prepared = []
        for item in sorted(files, key=lambda f: natural_key(f.get('name', '') if isinstance(f, dict) else '')):
            if not isinstance(item, dict) or not isinstance(item.get('text'), str):
                raise ValueError('Tệp nhập không hợp lệ')
            name = str(item.get('name') or 'chuong.txt')[:300]
            book_title, merged = split_chapters(item['text']) if split else (None, [])
            if merged:
                for chapter in merged:
                    prepared.append({'source_name': f'{name}#chuong-{chapter["number"]:05d}', 'number': chapter['number'],
                                     'title': chapter['title'], 'text': chapter['text']})
                continue
            number, title, body = split_heading(item['text'])
            if not body:
                continue
            stem = Path(name).stem
            prepared.append({'source_name': name, 'number': number, 'title': title or stem, 'text': body})
        added, updated, skipped, kept = 0, 0, 0, 0
        now = time.time()
        with self.db() as db:
            position = db.execute('SELECT COALESCE(MAX(position),-1) FROM chapters WHERE book_id=? AND deleted=0', (book_id,)).fetchone()[0]
            for item in prepared:
                if len(item['text']) > MAX_CHAPTER_CHARS:
                    raise ValueError(f'{item["source_name"]}: chương quá dài, hãy tách nhỏ')
                digest = sha256_text(item['text'])
                old = db.execute('SELECT * FROM chapters WHERE book_id=? AND source_name=? AND deleted=0', (book_id, item['source_name'])).fetchone()
                if old and old['sha256'] == digest:
                    if old['source_sha256'] != digest:
                        db.execute('UPDATE chapters SET source_sha256=? WHERE id=?', (digest, old['id']))
                    skipped += 1
                    continue
                if old and old['source_sha256'] and old['sha256'] != old['source_sha256']:
                    kept += 1  # edited by the user since the last import: their text wins
                    continue
                if old:
                    self._remember(db, old, 'trước khi nhập bản mới')
                    db.execute('UPDATE chapters SET text=?,sha256=?,source_sha256=?,revision=revision+1,updated=? WHERE id=?',
                               (item['text'], digest, digest, now, old['id']))
                    updated += 1
                    continue
                if db.execute('SELECT 1 FROM chapters WHERE book_id=? AND sha256=? AND deleted=0', (book_id, digest)).fetchone():
                    skipped += 1
                    continue
                position += 1
                db.execute('INSERT INTO chapters(id,book_id,position,number,title,read_title,text,sha256,source_name,revision,created,updated,deleted,source_sha256) '
                           'VALUES(?,?,?,?,?,1,?,?,?,1,?,?,0,?)', (uuid.uuid4().hex, book_id, position, item['number'],
                           (item['title'] or f'Chương {position + 1}')[:300], item['text'], digest, item['source_name'], now, now, digest))
                added += 1
            db.execute('UPDATE books SET updated=? WHERE id=?', (now, book_id))
        return {'added': added, 'updated': updated, 'skipped': skipped, 'kept': kept}

    @staticmethod
    def _remember(db, row, reason):
        """Every replaced chapter text is kept, so an edit can always be recovered."""
        db.execute('INSERT INTO chapter_history VALUES(?,?,?,?,?,?,?)', (row['id'], row['revision'], row['title'], row['text'], row['sha256'], time.time(), reason))

    def history(self, chapter_id):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT revision,title,sha256,saved,reason,LENGTH(text) characters FROM chapter_history WHERE chapter_id=? ORDER BY saved DESC', (chapter_id,))]

    def restore(self, chapter_id, revision):
        with self.db() as db:
            old = db.execute('SELECT * FROM chapter_history WHERE chapter_id=? AND revision=? ORDER BY saved DESC LIMIT 1', (chapter_id, revision)).fetchone()
        if not old:
            raise KeyError('Không có bản cũ này')
        return self.save_chapter(chapter_id, {'title': old['title'], 'text': old['text']})

    # --- gameplay ----------------------------------------------------------------------------------------
    def probe_video(self, path):
        data = json.loads(subprocess.check_output([self.ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], timeout=60))
        video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
        if not video:
            raise ValueError('Tệp không có hình video')
        duration = float(data.get('format', {}).get('duration') or video.get('duration') or 0)
        if not duration or duration < 1:
            raise ValueError('Không đọc được độ dài video')
        rate = (video.get('avg_frame_rate') or '0/1').split('/')
        fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1] or 0) else 0
        return {'duration': duration, 'width': video.get('width'), 'height': video.get('height'), 'fps': round(fps, 3),
                'has_audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', []))}

    def add_gameplay(self, temporary, name, sha):
        """temporary: a fully written file in .incoming; it is moved (not copied) into the library once."""
        temporary = Path(temporary)
        suffix = Path(name).suffix.lower()
        if suffix not in VIDEO_TYPES:
            temporary.unlink(missing_ok=True)
            raise ValueError('Chỉ nhận MP4, MKV, MOV hoặc WebM')
        with self.db() as db:
            old = db.execute('SELECT * FROM gameplay WHERE sha256=?', (sha,)).fetchone()
        if old and Path(old['path']).is_file():
            temporary.unlink(missing_ok=True)
            if old['deleted']:
                with self.db() as db:
                    db.execute('UPDATE gameplay SET deleted=0 WHERE id=?', (old['id'],))
            return {**self._clip(old), 'duplicate': True}
        try:
            info = self.probe_video(temporary)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise ValueError('FFmpeg không đọc được video này: ' + str(error)[:200])
        target = self.gameplay_root / f'{sha[:16]}{suffix}'
        temporary.replace(target)
        identifier = old['id'] if old else uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO gameplay VALUES(?,?,?,?,?,?,?,?,?,?,?,0)', (identifier, sha, Path(name).name[:200], str(target),
                       info['duration'], info['width'], info['height'], info['fps'], int(info['has_audio']), target.stat().st_size, time.time()))
            # Every book gets the new clip at the end of its playlist.
            for book in db.execute('SELECT id FROM books WHERE deleted=0').fetchall():
                last = db.execute('SELECT COALESCE(MAX(position),-1) FROM book_gameplay WHERE book_id=?', (book['id'],)).fetchone()[0]
                db.execute('INSERT OR IGNORE INTO book_gameplay VALUES(?,?,?,0,NULL)', (book['id'], identifier, last + 1))
            row = db.execute('SELECT * FROM gameplay WHERE id=?', (identifier,)).fetchone()
        return self._clip(row)

    def _clip(self, row):
        path = Path(row['path'])
        drive = row['drive_file_id'] if 'drive_file_id' in row.keys() else None
        # A Drive clip stays usable when its cached copy was trimmed: it is downloaded again when a video needs it.
        return {'id': row['id'], 'sha256': row['sha256'], 'name': row['name'], 'duration': row['duration'], 'width': row['width'],
                'height': row['height'], 'fps': row['fps'], 'has_audio': bool(row['has_audio']), 'size': row['size'],
                'available': path.is_file() or bool(drive), 'cached': path.is_file(), 'drive_file_id': drive,
                'source': 'drive' if drive else 'local', 'thumbnail': f'/api/story/gameplay/{row["id"]}/thumbnail'}

    def add_gameplay_cached(self, path, name, sha, drive_file_id, url):
        """A clip downloaded from a Drive link: the file stays in the cache (it may be trimmed and fetched again)."""
        path = Path(path)
        with self.db() as db:
            old = db.execute('SELECT * FROM gameplay WHERE sha256=?', (sha,)).fetchone()
        if old and not old['deleted']:
            return {**self._clip(old), 'duplicate': True}
        info = self.probe_video(path)
        identifier = old['id'] if old else uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO gameplay(id,sha256,name,path,duration,width,height,fps,has_audio,size,created,deleted,drive_file_id,source_url) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,?)', (identifier, sha, Path(name).name[:200], str(path), info['duration'], info['width'],
                       info['height'], info['fps'], int(info['has_audio']), path.stat().st_size, time.time(), drive_file_id, url[:500]))
            for book in db.execute('SELECT id FROM books WHERE deleted=0').fetchall():
                last = db.execute('SELECT COALESCE(MAX(position),-1) FROM book_gameplay WHERE book_id=?', (book['id'],)).fetchone()[0]
                db.execute('INSERT OR IGNORE INTO book_gameplay VALUES(?,?,?,0,NULL)', (book['id'], identifier, last + 1))
            row = db.execute('SELECT * FROM gameplay WHERE id=?', (identifier,)).fetchone()
        self.thumbnail(identifier)  # made now, while the file is surely on disk
        return self._clip(row)

    def gameplay(self, book_id=None):
        with self.db() as db:
            if book_id:
                rows = db.execute('''SELECT g.*, b.position, b.start, b.end FROM book_gameplay b JOIN gameplay g ON g.id=b.gameplay_id
                    WHERE b.book_id=? AND g.deleted=0 ORDER BY b.position''', (book_id,)).fetchall()
                items = [{**self._clip(r), 'start': r['start'], 'end': r['end'] if r['end'] is not None else r['duration']} for r in rows]
                cursor = db.execute('SELECT * FROM gameplay_cursor WHERE book_id=?', (book_id,)).fetchone()
            else:
                items = [self._clip(r) for r in db.execute('SELECT * FROM gameplay WHERE deleted=0 ORDER BY created').fetchall()]
                cursor = None
        usable = sum(max(0, i.get('end', i['duration']) - i.get('start', 0)) for i in items if i['available'])
        return {'items': items, 'total_seconds': usable, 'cursor': dict(cursor) if cursor else None}

    def set_playlist(self, book_id, clips):
        """clips: [{id, start, end}] in play order. Clips left out are removed from this book only."""
        self.book(book_id)
        if not isinstance(clips, list):
            raise ValueError('Danh sách clip không hợp lệ')
        with self.db() as db:
            known = {r['id']: r for r in db.execute('SELECT * FROM gameplay WHERE deleted=0')}
            db.execute('DELETE FROM book_gameplay WHERE book_id=?', (book_id,))
            for index, clip in enumerate(clips):
                row = known.get(clip.get('id'))
                if not row:
                    raise ValueError('Clip không còn trong thư viện')
                start = max(0.0, float(clip.get('start') or 0))
                end = clip.get('end')
                end = row['duration'] if end in (None, '') else min(row['duration'], float(end))
                if end - start < 1:
                    raise ValueError(f'{row["name"]}: đoạn dùng phải dài ít nhất 1 giây')
                db.execute('INSERT INTO book_gameplay VALUES(?,?,?,?,?)', (book_id, row['id'], index, start, end))
            db.execute('DELETE FROM gameplay_cursor WHERE book_id=?', (book_id,))
        return self.gameplay(book_id)

    def remove_gameplay(self, clip_id, in_use):
        if clip_id in in_use:
            raise ConflictError('Clip đang được một video trong hàng đợi dùng. Chờ video xong rồi xoá.')
        with self.db() as db:
            row = db.execute('SELECT * FROM gameplay WHERE id=? AND deleted=0', (clip_id,)).fetchone()
            if not row:
                raise KeyError('Không tìm thấy clip')
            db.execute('UPDATE gameplay SET deleted=1 WHERE id=?', (clip_id,))
            db.execute('DELETE FROM book_gameplay WHERE gameplay_id=?', (clip_id,))
        return {'deleted': True, 'file_kept': row['path']}

    def thumbnail(self, clip_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM gameplay WHERE id=?', (clip_id,)).fetchone()
        if not row:
            raise KeyError('Không tìm thấy clip')
        target = self.root / 'previews' / f'thumb-{row["sha256"][:16]}.jpg'
        if not target.is_file() and not Path(row['path']).is_file():
            raise KeyError('Không tìm thấy clip')
        if not target.is_file():
            at = min(5.0, row['duration'] / 3)
            subprocess.run([self.ffmpeg, '-v', 'error', '-y', '-ss', f'{at:.2f}', '-i', row['path'], '-frames:v', '1',
                            '-vf', 'scale=480:-2', str(target)], check=True, timeout=60)
        return target

    # --- cursor ------------------------------------------------------------------------------------------
    def cursor(self, book_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM gameplay_cursor WHERE book_id=?', (book_id,)).fetchone()
        return dict(row) if row else {'clip': 0, 'offset': 0.0, 'job_id': None}

    def advance_cursor(self, book_id, clip, offset, job_id):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO gameplay_cursor VALUES(?,?,?,?,?)', (book_id, int(clip), float(offset), job_id, time.time()))

    # --- backgrounds -------------------------------------------------------------------------------------
    def backgrounds(self):
        items = [{'id': key, 'name': value['name'], 'preset': True} for key, value in PRESET_BACKGROUNDS.items()]
        for path in sorted((self.root / 'backgrounds').iterdir(), key=lambda p: p.stat().st_mtime):
            if path.suffix.lower() in IMAGE_TYPES:
                items.append({'id': 'image:' + path.name, 'name': path.stem.split('-', 1)[-1][:60], 'preset': False})
        return items

    def add_background(self, data, name):
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_TYPES:
            raise ValueError('Ảnh nền cần là PNG, JPG hoặc WebP')
        if not data or len(data) > 25 * 1024 * 1024:
            raise ValueError('Ảnh nền tối đa 25 MB')
        digest = hashlib.sha256(data).hexdigest()[:12]
        target = self.root / 'backgrounds' / f'{digest}-{slug(Path(name).stem, 40)}{suffix}'
        if not target.is_file():
            target.write_bytes(data)
        return {'id': 'image:' + target.name, 'name': target.stem.split('-', 1)[-1], 'preset': False}

    def background_path(self, background_id):
        if isinstance(background_id, str) and background_id.startswith('image:'):
            path = (self.root / 'backgrounds' / background_id[6:]).resolve()
            if path.parent == (self.root / 'backgrounds').resolve() and path.is_file():
                return path
        return None

    # --- episodes ----------------------------------------------------------------------------------------
    def freeze(self, book_id, chapter_ids, idem):
        """Immutable snapshot for one queued episode: text revisions, order, voice settings, layout and gameplay playlist."""
        book = self.book(book_id)
        with self.db() as db:
            old = db.execute('SELECT * FROM episodes WHERE idem=?', (idem,)).fetchone()
            if old:
                return self.snapshot(old['snapshot_sha256'])
            rows = {r['id']: r for r in db.execute(f'SELECT * FROM chapters WHERE book_id=? AND deleted=0 AND id IN ({",".join("?" * len(chapter_ids))})',
                                                   (book_id, *chapter_ids))}
            order = {r['id']: i for i, r in enumerate(db.execute('SELECT id FROM chapters WHERE book_id=? AND deleted=0 ORDER BY position', (book_id,)), 1)}
        if len(rows) != len(chapter_ids):
            raise ConflictError('Có chương đã bị xoá hoặc không thuộc truyện này. Tải lại danh sách chương.')
        chapters = [{'id': rows[i]['id'], 'order': order[i], 'number': rows[i]['number'], 'title': rows[i]['title'], 'read_title': bool(rows[i]['read_title']),
                     'text': rows[i]['text'], 'sha256': rows[i]['sha256'], 'revision': rows[i]['revision']} for i in chapter_ids]
        playlist = [c for c in self.gameplay(book_id)['items'] if c['available']]
        snapshot = {'version': 1, 'book': {'id': book['id'], 'title': book['title']}, 'chapters': chapters,
                    'settings': book['settings'], 'layout': book['layout'],
                    'gameplay': [{'id': c['id'], 'sha256': c['sha256'], 'name': c['name'], 'path': self._clip_path(c['id']),
                                  'duration': c['duration'], 'start': c['start'], 'end': c['end'], 'has_audio': c['has_audio'],
                                  'drive_file_id': c.get('drive_file_id'),
                                  'width': c['width'], 'height': c['height']} for c in playlist],
                    'background': self.background_path(book['layout'].get('background')) and str(self.background_path(book['layout']['background'])),
                    'background_preset': PRESET_BACKGROUNDS.get(book['layout'].get('background'), PRESET_BACKGROUNDS['preset:dem-xanh'])}
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        path = self.root / 'snapshots' / f'{digest}.json'
        if not path.is_file():
            part = path.with_suffix('.part')
            part.write_text(raw, encoding='utf-8')
            part.replace(path)
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO episodes VALUES(?,?,?,?,?,?)', (uuid.uuid4().hex, book_id, digest, json.dumps(chapter_ids), idem, time.time()))
        return {**snapshot, 'sha256': digest}

    def _clip_path(self, clip_id):
        with self.db() as db:
            return db.execute('SELECT path FROM gameplay WHERE id=?', (clip_id,)).fetchone()['path']

    def snapshot(self, digest):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest or '')):
            raise ValueError('Mã snapshot không hợp lệ')
        path = self.root / 'snapshots' / f'{digest}.json'
        raw = path.read_text(encoding='utf-8')
        if hashlib.sha256(raw.encode('utf-8')).hexdigest() != digest:
            raise ValueError('Snapshot truyện đã bị thay đổi')
        return {**json.loads(raw), 'sha256': digest}


class ConflictError(ValueError):
    pass


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError('Thiết lập giọng không hợp lệ')
    allowed = {'speech_engine', 'voice_id', 'speech_rhythm', 'speech_speed', 'khanh_steps', 'speech_batch_size', 'speech_reference_text'}
    if set(value) - allowed:
        raise ValueError('Thiết lập giọng có trường lạ')
    result = dict(value)
    if 'speech_engine' in result and result['speech_engine'] not in ('vieneu', 'khanhtts'):
        raise ValueError('Bộ đọc không hợp lệ')
    if 'speech_rhythm' in result and result['speech_rhythm'] not in ('natural', 'story'):
        raise ValueError('Nhịp đọc không hợp lệ')
    if 'speech_speed' in result:
        speed = float(result['speech_speed'])
        if not .5 <= speed <= 2:
            raise ValueError('Tốc độ cần từ 0,5 đến 2')
        result['speech_speed'] = speed
    if 'khanh_steps' in result and int(result['khanh_steps']) not in (16, 32):
        raise ValueError('KhanhTTS chỉ có 16 hoặc 32 bước')
    if 'speech_batch_size' in result and not 1 <= int(result['speech_batch_size']) <= 512:
        raise ValueError('Batch giọng đọc từ 1 đến 512')
    if 'voice_id' in result and (not isinstance(result['voice_id'], str) or not result['voice_id'].strip()):
        raise ValueError('Chọn giọng đọc')
    return result


def validate_layout(value):
    if not isinstance(value, dict):
        raise ValueError('Khung hình không hợp lệ')
    if set(value) - set(DEFAULT_LAYOUT):
        raise ValueError('Khung hình có trường lạ')
    result = dict(value)
    for key in ('horizontal', 'vertical', 'burn_subtitles', 'export_srt', 'export_mp3', 'game_audio', 'continue_gameplay'):
        if key in result and type(result[key]) is not bool:
            raise ValueError(key + ' phải là bật/tắt')
    if 'channel' in result:
        result['channel'] = str(result['channel'] or '').strip()[:80]
    if 'background' in result and not isinstance(result['background'], str):
        raise ValueError('Ảnh nền không hợp lệ')
    if 'game_box' in result:
        result['game_box'] = validate_game_box(result['game_box'])
    if 'video_codec' in result and result['video_codec'] not in ('hevc', 'h264'):
        raise ValueError('Kiểu nén chỉ có HEVC hoặc H.264')
    return result


CANVAS = {'ngang': (1920, 1080), 'doc': (1080, 1920)}


def validate_game_box(value):
    """{'ngang': [x, y, w], 'doc': [x, y, w]} chosen by dragging in the layout preview; height is always w*9/16."""
    if not isinstance(value, dict) or set(value) - set(CANVAS):
        raise ValueError('Khung game không hợp lệ')
    result = {}
    for orientation, box in value.items():
        if box is None:
            continue
        if not isinstance(box, (list, tuple)) or len(box) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box):
            raise ValueError('Khung game không hợp lệ')
        width, height = CANVAS[orientation]
        w = int(round(min(width, max(width * .35, box[2])) / 2) * 2)
        h = int(round(w * 9 / 16 / 2) * 2)
        x = int(min(width - w, max(0, box[0])))
        y = int(min(height - h, max(0, box[1])))
        result[orientation] = [x, y, w]
    return result
