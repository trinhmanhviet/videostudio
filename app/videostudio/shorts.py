"""Bản ngắn: a 45–88 second vertical cut of a finished video, posted as a Facebook Reel and a YouTube Short.

Why (2026-11-18): on the owner's channels only short videos travelled (a 88 s Short: 1 022 views; long videos 0–34),
and Facebook spreads an API-posted Reel only when it is 3–90 seconds long. The full video stays the main post; the
short points to it.

How a short is made:
- the video's own subtitles (with their times) go to ChatGPT, which picks the most gripping stretch that starts at a
  sentence and stops on an open question, plus a short title; a bad or missing answer falls back to the opening;
- the vertical copy (here or on Drive) is cut with FFmpeg on the GPU, and the last seconds carry "Xem bản đầy đủ…";
- the result is kept in DATA_ROOT/shorts/<job>/ (short.mp4 + short.json) and reused.

ShortMaker runs in the background: it makes the shorts a posting plan asks for and schedules them, and once an hour
it looks at how posted shorts do. A short well above the channel's usual views is flagged "Nên tự đăng Reel bản đầy
đủ" (shown in Số liệu kênh) and sent once to Telegram."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .paths import DATA_ROOT

ROOT = DATA_ROOT / 'shorts'
SHORT_MIN, SHORT_MAX = 45.0, 88.0      # Facebook spreads API Reels of 3–90 s; keep a margin
FALLBACK = 75.0
END_CARD = 3.0                           # seconds of "Xem bản đầy đủ…" at the end
AFTER_FULL = 3 * 3600                    # a planned short goes out three hours after its full video
FLAG_RATIO = 1.5                         # views over 1.5 x the channel's median, a day after posting
FLAG_AGE = 24 * 3600
FONT = 'C:/Windows/Fonts/arialbd.ttf'
_JOB = re.compile(r'^[0-9a-f-]{36}$')


def _folder(job_id, root=None):
    if not _JOB.match(str(job_id)):
        raise ValueError('Mã video không hợp lệ')
    return Path(root or ROOT) / job_id


def load(job_id, root=None):
    """The kept short of a video, or None (also None when its file is gone)."""
    folder = _folder(job_id, root)  # a bad id is refused, not read as "no short"
    try:
        record = json.loads((folder / 'short.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    path = folder / 'short.mp4'
    return {**record, 'path': str(path)} if path.is_file() else None


# --- subtitles -------------------------------------------------------------------------------------------------
_TIME = re.compile(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)')


def parse_srt(text):
    cues = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip()):
        lines = block.strip().split('\n')
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                h1, m1, s1, f1, h2, m2, s2, f2 = m.groups()
                start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(f1) / 10 ** len(f1)
                end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(f2) / 10 ** len(f2)
                words = ' '.join(x.strip() for x in lines[i + 1:] if x.strip())
                words = re.sub(r'<[^>]+>|\{[^}]*\}', '', words).strip()
                if words and end > start:
                    cues.append((round(start, 2), round(end, 2), words))
                break
    return cues


def subtitle_file(job):
    """The vertical video's subtitles: story videos keep story-doc.srt, the others subtitles.srt."""
    out = Path(job['output'])
    sub = (job.get('checkpoints') or {}).get('subtitles') or {}
    for candidate in (out / 'story-doc.srt', Path(sub['srt_path']) if sub.get('srt_path') else None, out / 'subtitles.srt'):
        if candidate and candidate.is_file():
            return candidate
    return None


# --- choosing the moment -----------------------------------------------------------------------------------------
PROMPT = """Bạn là biên tập viên video ngắn (Facebook Reels, YouTube Shorts). Dưới đây là phụ đề có đánh số và mốc giây của một video "{title}".
Hãy chọn MỘT đoạn liền mạch dài từ {lo:.0f} đến {hi:.0f} giây để cắt thành video ngắn, sao cho:
- câu đầu tiên của đoạn tự nó đã gây tò mò, người chưa xem phần trước vẫn hiểu;
- đoạn bắt đầu ở đầu một câu và kết thúc ở cuối một câu;
- đoạn dừng đúng chỗ còn bỏ ngỏ (một câu hỏi, một tình tiết chưa có lời giải) để người xem muốn xem bản đầy đủ;
- không lấy phần kết, không tiết lộ lời giải hay hung thủ.
Đặt một tiêu đề ngắn cho video ngắn (tối đa 80 ký tự, kịch tính, không viết hoa toàn bộ, không dùng từ ngữ câu view lố).
Chỉ trả lời JSON: {{"tu": <số thứ tự câu đầu>, "den": <số thứ tự câu cuối>, "tieu_de": "..."}}

{lines}"""


def _clock(seconds):
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


def choose(cues, title, ask):
    """(start, end, title, how): ChatGPT's pick when it is a valid stretch, else the opening."""
    if not cues:
        raise ValueError('Video chưa có phụ đề để chọn đoạn ngắn')
    lines = '\n'.join(f'[{i}] {_clock(a)}–{_clock(b)} {text}' for i, (a, b, text) in enumerate(cues))
    try:
        answer = ask(PROMPT.format(title=title, lo=SHORT_MIN, hi=SHORT_MAX, lines=lines[:60000])) or {}
        first, last = int(answer['tu']), int(answer['den'])
        if 0 <= first <= last < len(cues):
            start, end = cues[first][0], cues[last][1]
            if SHORT_MIN - 5 <= end - start <= SHORT_MAX + 2:
                name = str(answer.get('tieu_de') or '').strip()[:90] or title
                return max(0.0, start - 0.15), min(end + 0.35, start + SHORT_MAX), name, 'chatgpt'
    except Exception:
        pass
    end = cues[0][0]
    for a, b, _ in cues:  # the opening, cut at the end of a line
        if b - cues[0][0] > FALLBACK:
            break
        end = b
    return max(0.0, cues[0][0] - 0.15), max(end, cues[0][0] + SHORT_MIN), title, 'opening'


# --- cutting -----------------------------------------------------------------------------------------------------
def _escape(text):
    return text.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\u2019").replace('%', '\\%')


def cut(source, start, end, target, ffmpeg=None, run=None):
    """The stretch of the vertical video, re-encoded on the GPU (CPU when NVENC is missing), the end card on top."""
    import subprocess
    from .story_pipeline import video_codec
    ffmpeg = ffmpeg or os.getenv('VS_FFMPEG', 'ffmpeg')
    seconds = round(end - start, 2)
    card = (f"drawbox=x=0:y=ih*0.42:w=iw:h=ih*0.14:color=black@0.62:t=fill:enable='gte(t,{seconds - END_CARD})',"
            f"drawtext=fontfile='{_escape(FONT)}':text='{_escape('Xem bản đầy đủ trên kênh')}':fontcolor=white:fontsize=h*0.032:"
            f"x=(w-text_w)/2:y=h*0.47:enable='gte(t,{seconds - END_CARD})'")
    temp = Path(target).with_suffix('.part.mp4')

    def build(codec):
        return [ffmpeg, '-v', 'error', '-y', '-ss', f'{start:.2f}', '-i', str(source), '-t', f'{seconds:.2f}',
                '-vf', card, '-af', f'afade=t=out:st={max(0, seconds - 0.6):.2f}:d=0.6', *codec,
                '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(temp)]
    runner = run or (lambda args: subprocess.run(args, check=True, capture_output=True, timeout=900))
    try:
        runner(build(video_codec(ffmpeg)))
    except Exception:
        runner(build(['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21']))
    temp.replace(target)
    return seconds


def _vertical(store, job):
    """(path, cleanup): the vertical copy here, or downloaded from Drive into a temporary folder."""
    render = (job.get('checkpoints') or {}).get('render') or {}
    for candidate in ((render.get('story_outputs') or {}).get('doc'), render.get('video')):
        if candidate and Path(candidate).is_file():
            return Path(candidate), None
    with store.db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM drive_files WHERE job_id=? AND trashed=0 AND name LIKE '%.mp4'", (job['id'],))]
    pick = next((r for r in rows if r['name'].endswith('_doc.mp4')), None) or next((r for r in rows if 'ngang' not in r['name']), None)
    if pick is None:
        raise ValueError('Không còn bản video dọc (trên máy hoặc Drive) để cắt bản ngắn')
    from .drive_storage import DriveStorage
    folder = Path(tempfile.mkdtemp(prefix='vs-short-'))
    target = folder / pick['name']
    DriveStorage(store).download(pick['file_id'], target, account=pick['account'])
    return target, folder


def make(store, job_id, ask=None, root=None, cutter=cut):
    """The short of a finished video, made once and kept (short.mp4 + short.json)."""
    kept = load(job_id, root)
    if kept:
        return kept
    job = store.get(job_id)
    if job['state'] != 'completed':
        raise ValueError('Video chưa làm xong')
    srt = subtitle_file(job)
    cues = parse_srt(srt.read_text(encoding='utf-8-sig')) if srt else []
    title = _title(store, job)
    if ask is None:
        from .story_editor import ask_chatgpt
        ask = lambda prompt: ask_chatgpt(f'short-{job_id}', prompt)
    start, end, name, how = choose(cues, title, ask)
    folder = _folder(job_id, root)
    folder.mkdir(parents=True, exist_ok=True)
    source, temporary = _vertical(store, job)
    try:
        seconds = cutter(source, start, end, folder / 'short.mp4')
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)
    from .core import digest
    record = {'job_id': job_id, 'start': round(start, 2), 'end': round(end, 2), 'seconds': seconds, 'title': name,
              'full_title': title, 'chosen_by': how, 'sha256': digest(folder / 'short.mp4'), 'made': time.time()}
    (folder / 'short.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**record, 'path': str(folder / 'short.mp4')}


def _title(store, job):
    with store.db() as db:
        row = db.execute('SELECT title FROM factory_items WHERE job_id=?', (job['id'],)).fetchone() \
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='factory_items'").fetchone() else None
    social = {}
    try:
        from . import social_copy
        social = social_copy.read(job) or {}
    except Exception:
        pass
    return ((social.get('youtube') or {}).get('title') or (row[0] if row else '') or job['request'].get('idea', '').splitlines()[0])[:100]


# --- posting ------------------------------------------------------------------------------------------------------
def captions(record, full_url=None):
    """(title, caption) of a short: its own title, and a pointer to the full video."""
    pointer = f'Xem bản đầy đủ: {full_url}' if full_url else 'Bản đầy đủ có trên kênh.'
    return record['title'][:90], f'{record["title"]}\n\n{pointer}'


def schedule(store, publishing, versions, job_id, channels, at, record=None, ask=None, root=None, key=None):
    """Schedule the short on each channel (made first when needed). Returns [schedule ids], [problems]."""
    record = record or make(store, job_id, ask=ask, root=root)
    version = versions.approved_version(job_id)
    if not version:
        raise ValueError('Duyệt video trước khi đăng bản ngắn')
    with store.db() as db:
        full = {r['channel_id']: r['remote_url'] for r in db.execute(
            "SELECT channel_id, remote_url FROM publishing_schedules WHERE job_id=? AND cut='' AND remote_url IS NOT NULL", (job_id,))}
    made, problems = [], []
    for channel_id in channels:
        youtube = channel_id.startswith('youtube:')
        title, caption = captions(record, full.get(channel_id))
        body = {'job_id': job_id, 'version_id': version['version_id'], 'channel_id': channel_id, 'cut': 'short',
                'title': (title + ' #shorts')[:100] if youtube else title, 'caption': caption,
                'publish_at': datetime.fromtimestamp(at, timezone.utc).isoformat(), 'tags': [], 'ai_label': True}
        try:
            made.append(publishing.create_schedule(body, (key or f'short:{job_id}:{int(at)}') + ':' + channel_id)['id'])
        except Exception as error:
            problems.append(f'{channel_id}: {error}')
    return made, problems


# --- background work ----------------------------------------------------------------------------------------------
class ShortMaker:
    """Makes and schedules the shorts that posting plans ask for, one at a time, and flags shorts that do well."""

    def __init__(self, store, publishing, versions, ask=None, notify=None, clock=time.time, root=None):
        self.store, self.publishing, self.versions, self.ask, self.clock, self.root = store, publishing, versions, ask, clock, root
        self.notify = notify
        self.last_check = 0
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS short_requests(
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, channels TEXT NOT NULL, publish_at REAL NOT NULL,
                    state TEXT NOT NULL, note TEXT, schedule_ids TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS short_flags(
                    schedule_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, views INTEGER, median REAL, flagged REAL NOT NULL);''')

    def request(self, job_id, channels, at):
        """Ask for the short of a video, posted at `at` (once per video and time)."""
        with self.store.db() as db:
            if db.execute('SELECT 1 FROM short_requests WHERE job_id=? AND publish_at=?', (job_id, at)).fetchone():
                return
            db.execute('INSERT INTO short_requests VALUES(?,?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), job_id, json.dumps(channels), at, 'waiting', None, None, self.clock(), self.clock()))

    def tick(self):
        """One waiting request (oldest first); the hourly look at posted shorts. True when something was done."""
        did = False
        with self.store.db() as db:
            row = db.execute("SELECT * FROM short_requests WHERE state='waiting' ORDER BY publish_at LIMIT 1").fetchone()
            # The GPU does one thing at a time: a short is cut only while no video is being made.
            if row and db.execute("SELECT 1 FROM jobs WHERE state IN ('running','retrying') LIMIT 1").fetchone():
                row = None
        if row:
            did = True
            row = dict(row)
            at = max(row['publish_at'], self.clock() + 900)  # never too close: the upload needs time
            try:
                ids, problems = schedule(self.store, self.publishing, self.versions, row['job_id'], json.loads(row['channels']), at,
                                         ask=self.ask, root=self.root, key=f'short:{row["id"]}')
                state, note = ('done' if ids else 'failed'), ('; '.join(problems)[:500] or None)
            except Exception as error:
                ids, state, note = [], 'failed', str(error)[:500]
            with self.store.db() as db:
                db.execute('UPDATE short_requests SET state=?,note=?,schedule_ids=?,updated=? WHERE id=?',
                           (state, note, json.dumps(ids), self.clock(), row['id']))
        if self.clock() - self.last_check >= 3600:
            self.last_check = self.clock()
            try:
                did = bool(self.check()) or did
            except Exception:
                pass
        return did

    def check(self):
        """Shorts a day or more old with views over FLAG_RATIO x the channel's median: flagged once, sent to Telegram."""
        with self.store.db() as db:
            posted = [dict(r) for r in db.execute(
                "SELECT id, job_id, channel_id, platform, remote_id, title, updated FROM publishing_schedules "
                "WHERE cut='short' AND state='published' AND id NOT IN (SELECT schedule_id FROM short_flags)")]
        flagged = []
        stats = {}
        for row in posted:
            if self.clock() - row['updated'] < FLAG_AGE:
                continue
            channel = row['channel_id']
            if channel not in stats:
                try:
                    data = self.publishing.facebook_reels(channel) if row['platform'] == 'facebook' else self.publishing.youtube_videos(channel)
                except Exception:
                    data = None
                stats[channel] = data
            data = stats[channel]
            if not data:
                continue
            item = next((i for i in data.get('items', []) if str(i.get('id')) == str(row['remote_id'])), None)
            median = data.get('median_views') or 0
            if not item or not median:
                continue
            views = item.get('views') or 0
            if views >= FLAG_RATIO * median:
                with self.store.db() as db:
                    db.execute('INSERT OR IGNORE INTO short_flags VALUES(?,?,?,?,?)', (row['id'], row['job_id'], views, median, self.clock()))
                flagged.append(row)
                text = (f'Bản ngắn "{row["title"]}" đang hút: {views} lượt xem, gấp {views / median:.1f} lần mức thường của kênh. '
                        'Nên tự đăng Reel bản đầy đủ (Kho video → video này → Tải video).')
                (self.notify or _emit)(text)
        return flagged

    def flags(self):
        """Flagged shorts, keyed by the post's id on its platform (Số liệu kênh marks those rows)."""
        with self.store.db() as db:
            return {r['remote_id']: dict(r) for r in db.execute(
                'SELECT f.*, s.remote_id, s.channel_id, s.title FROM short_flags f JOIN publishing_schedules s ON s.id=f.schedule_id')}

    def requests(self, job_id=None):
        with self.store.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM short_requests' + (' WHERE job_id=?' if job_id else '') + ' ORDER BY publish_at DESC LIMIT 50',
                                                (job_id,) if job_id else ())]


def _emit(text):
    try:
        from . import notify
        notify.emit('publish', text)
    except Exception:
        pass
