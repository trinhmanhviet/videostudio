"""Đăng tự động: posting plans that schedule the next finished videos by themselves.

A plan names a kind of video (and optionally one book or project), the channels, the posting times and weekdays.
Every few minutes the plan fills each free slot of the next two days with the next finished video that has not been
posted on those channels: story episodes in chapter order, other videos oldest first. The schedule is made exactly as
the post form makes it (title, YouTube description and tags, Facebook caption, the case note, the AI label), so the
normal publisher uploads it: YouTube landscape copy, Facebook Reels vertical copy, straight from Drive when needed."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

VN = timezone(timedelta(hours=7))
HORIZON = 48 * 3600      # slots are filled up to two days ahead
LEAD = 20 * 60           # a slot closer than this is left alone (uploads need time)
EVERY = 300              # seconds between two planning rounds
STYLES = ('story', 'case', 'news', 'meme')
CASE_NOTE = 'Bài đăng thuật lại vụ án, không cổ suý bạo lực. Khán thính giả vui lòng cân nhắc trước khi xem.'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hashtags(tags, text, limit=5):
    seen = []
    for tag in tags or []:
        mark = '#' + ''.join(str(tag).replace('#', '').split())
        if len(mark) > 1 and mark not in text and mark not in seen:
            seen.append(mark)
    return ' '.join(seen[:limit])


def captions(social, style, title):
    """(title, youtube description, youtube tags, facebook caption) like the post form fills them."""
    youtube, facebook = social.get('youtube') or {}, social.get('facebook') or {}
    description = youtube.get('description') or ''
    tags = [t for t in (youtube.get('tags') or []) if isinstance(t, str)]
    youtube_text = '\n\n'.join(x for x in (description, _hashtags(tags, description)) if x)
    caption = facebook.get('caption') or ''
    hashtags = ' '.join(h for h in (facebook.get('hashtags') or []) if isinstance(h, str) and h not in caption)
    parts = [x for x in (caption, CASE_NOTE if style == 'case' else '', hashtags) if x]
    return (youtube.get('title') or title)[:100], youtube_text, tags, '\n\n'.join(parts)


class PostingPlans:
    def __init__(self, store, publishing, factory, clock=time.time):
        self.store, self.publishing, self.factory, self.clock = store, publishing, factory, clock
        self.last_round = 0
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS publishing_plans(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, style TEXT NOT NULL, project TEXT NOT NULL DEFAULT '',
                    channels TEXT NOT NULL, times TEXT NOT NULL, days TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    ai_label INTEGER NOT NULL DEFAULT 1, note TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS publishing_plan_slots(
                    plan_id TEXT NOT NULL, slot_at REAL NOT NULL, job_id TEXT NOT NULL, schedule_ids TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(plan_id, slot_at));
                CREATE TABLE IF NOT EXISTS publishing_plan_skips(
                    plan_id TEXT NOT NULL, job_id TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(plan_id, job_id));
            ''')

    # --- plans ---------------------------------------------------------------------------------------------
    def _validate(self, data):
        if not isinstance(data, dict):
            raise ValueError('Kế hoạch đăng không hợp lệ')
        name = str(data.get('name') or '').strip()[:120]
        style = data.get('style')
        if style not in STYLES:
            raise ValueError('Chọn loại video')
        project = str(data.get('project') or '').strip()[:300]
        channels = data.get('channels')
        known = {c['id']: c for c in self.publishing.channels()['items'] if c.get('connected') and ':' in str(c['id'])}
        if not isinstance(channels, list) or not channels or any(c not in known for c in channels) or len(set(channels)) != len(channels):
            raise ValueError('Tick ít nhất một kênh đã kết nối')
        times = data.get('times')
        if not isinstance(times, list) or not 1 <= len(times) <= 12:
            raise ValueError('Nhập 1–12 giờ đăng mỗi ngày')
        clean = []
        for value in times:
            try:
                hour, minute = (int(x) for x in str(value).strip().split(':'))
            except ValueError:
                raise ValueError(f'Giờ đăng "{value}" phải dạng 19:00')
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError(f'Giờ đăng "{value}" không hợp lệ')
            clean.append(f'{hour:02d}:{minute:02d}')
        days = data.get('days', list(range(7)))
        if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days):
            raise ValueError('Chọn ít nhất một ngày trong tuần')
        for key in ('enabled', 'ai_label'):
            if type(data.get(key, True)) is not bool:
                raise ValueError(key + ' phải là bật/tắt')
        return {'name': name or ('Đăng ' + project if project else 'Đăng tự động'), 'style': style, 'project': project,
                'channels': channels, 'times': sorted(set(clean)), 'days': sorted(set(days)),
                'enabled': data.get('enabled', True), 'ai_label': data.get('ai_label', True)}

    def save(self, data, plan_id=None):
        plan = self._validate(data)
        now = self.clock()
        with self.store.db() as db:
            if plan_id:
                if not db.execute('SELECT 1 FROM publishing_plans WHERE id=?', (plan_id,)).fetchone():
                    raise KeyError(plan_id)
                db.execute('''UPDATE publishing_plans SET name=?,style=?,project=?,channels=?,times=?,days=?,enabled=?,ai_label=?,note=NULL,updated=?
                              WHERE id=?''', (plan['name'], plan['style'], plan['project'], _json(plan['channels']), _json(plan['times']),
                                              _json(plan['days']), int(plan['enabled']), int(plan['ai_label']), now, plan_id))
            else:
                plan_id = uuid.uuid4().hex
                db.execute('INSERT INTO publishing_plans VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?)',
                           (plan_id, plan['name'], plan['style'], plan['project'], _json(plan['channels']), _json(plan['times']),
                            _json(plan['days']), int(plan['enabled']), int(plan['ai_label']), now, now))
        self.last_round = 0  # plan at once
        return self.get(plan_id)

    def delete(self, plan_id):
        """Stop the plan; schedules it already made stay in the calendar (cancel them there if needed)."""
        with self.store.db() as db:
            if not db.execute('DELETE FROM publishing_plans WHERE id=?', (plan_id,)).rowcount:
                raise KeyError(plan_id)
            db.execute('DELETE FROM publishing_plan_skips WHERE plan_id=?', (plan_id,))
        return {'deleted': plan_id}

    def get(self, plan_id):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM publishing_plans WHERE id=?', (plan_id,)).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return self._public(dict(row))

    def _public(self, row):
        plan = {**row, 'channels': json.loads(row['channels']), 'times': json.loads(row['times']), 'days': json.loads(row['days']),
                'enabled': bool(row['enabled']), 'ai_label': bool(row['ai_label'])}
        with self.store.db() as db:
            slots = [dict(r) for r in db.execute('SELECT * FROM publishing_plan_slots WHERE plan_id=? AND slot_at>=? ORDER BY slot_at',
                                                 (plan['id'], self.clock() - 3600))]
            skips = [dict(r) for r in db.execute('SELECT * FROM publishing_plan_skips WHERE plan_id=? ORDER BY created DESC LIMIT 10', (plan['id'],))]
        for slot in slots:
            slot['title'] = self._title(slot['job_id'])
        for skip in skips:
            skip['title'] = self._title(skip['job_id'])
        plan['upcoming'] = slots
        plan['skipped'] = skips
        plan['waiting'] = len(self.candidates(plan))
        return plan

    def items(self):
        with self.store.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM publishing_plans ORDER BY created')]
        return {'items': [self._public(r) for r in rows]}

    def projects(self):
        """Books and projects per kind of video, for the plan form."""
        with self.store.db() as db:
            rows = db.execute('''SELECT b.style, b.project, COUNT(i.job_id) AS videos FROM factory_batches b JOIN factory_items i ON i.batch_id=b.id
                                 JOIN jobs j ON j.id=i.job_id WHERE j.state='completed' GROUP BY b.style, b.project ORDER BY b.project''').fetchall()
        result = {}
        for row in rows:
            result.setdefault(row['style'], []).append({'project': row['project'], 'videos': row['videos']})
        # Books of the story library too, so a plan can be set before their episodes are made.
        try:
            import sqlite3
            from .story_library import STORY_ROOT
            path = Path(STORY_ROOT) / 'library.sqlite3'
            if path.is_file():
                with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
                    titles = [r[0] for r in db.execute('SELECT title FROM books WHERE deleted=0 ORDER BY title')]
                known = {item['project'] for item in result.get('story', [])}
                result.setdefault('story', []).extend({'project': t, 'videos': 0} for t in titles if t not in known)
        except Exception:
            pass
        return result

    # --- candidates ---------------------------------------------------------------------------------------
    def _title(self, job_id):
        with self.store.db() as db:
            row = db.execute('SELECT title FROM factory_items WHERE job_id=?', (job_id,)).fetchone()
        if row:
            return row['title']
        try:
            return self.store.get(job_id)['request'].get('project') or job_id
        except KeyError:
            return job_id

    def _order(self, job):
        """Story episodes go in chapter order; other videos oldest first."""
        try:
            snapshot = json.loads((Path(job['output']) / 'story-snapshot.json').read_text(encoding='utf-8'))
            first = min(c.get('order', 0) for c in snapshot.get('chapters') or [{}])
            return (0, first, job['created'])
        except (OSError, ValueError, KeyError):
            return (1, 0, job['created'])

    def candidates(self, plan):
        from .project_lifecycle import deleted_job_ids
        with self.store.db() as db:
            hidden = deleted_job_ids(db)
            rows = db.execute('''SELECT j.id, b.style, b.project FROM jobs j JOIN factory_items i ON i.job_id=j.id
                                 JOIN factory_batches b ON b.id=i.batch_id WHERE j.state='completed' AND b.style=?''', (plan['style'],)).fetchall()
            marks = ','.join('?' * len(plan['channels']))
            posted = {r[0] for r in db.execute(f"SELECT job_id FROM publishing_schedules WHERE state!='cancelled' AND channel_id IN ({marks})",
                                               plan['channels'])}
            planned = {r[0] for r in db.execute('SELECT job_id FROM publishing_plan_slots')}
            skipped = {r[0] for r in db.execute('SELECT job_id FROM publishing_plan_skips WHERE plan_id=?', (plan['id'],))}
        jobs = []
        for row in rows:
            if row['id'] in hidden or row['id'] in posted or row['id'] in planned or row['id'] in skipped:
                continue
            if plan['project'] and row['project'] != plan['project']:
                continue
            try:
                job = self.store.get(row['id'])
            except KeyError:
                continue
            render = job['checkpoints'].get('render', {})
            if render.get('audio_only') or job['checkpoints'].get('verify', {}).get('verified') is not True:
                continue  # MP3-only narrations and unverified videos are never posted
            jobs.append(job)
        return sorted(jobs, key=self._order)

    # --- planning round ------------------------------------------------------------------------------------
    def slots(self, plan, now):
        start = datetime.fromtimestamp(now, VN).date()
        for offset in range(3):
            day = start + timedelta(days=offset)
            if day.weekday() not in plan['days']:
                continue
            for value in plan['times']:
                hour, minute = (int(x) for x in value.split(':'))
                at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=VN).timestamp()
                if now + LEAD <= at <= now + HORIZON:
                    yield at

    def _schedule(self, plan, job, at):
        from . import social_copy
        social = social_copy.read(job) or {}
        if social.get('state') != 'ready':
            return None, 'Chưa có tiêu đề và lời đăng (đang chờ tool viết xong)'
        version = self.factory.get_video_version(job['id'])
        self.factory.approve(job['id'], version['version_id'], version['sha256'])  # the plan is the approval to post
        title, youtube_text, tags, facebook_text = captions(social, plan['style'], self._title(job['id']))
        channels = {c['id']: c for c in self.publishing.channels()['items']}
        made, problems = [], []
        for channel_id in plan['channels']:
            youtube = (channels.get(channel_id) or {}).get('platform') == 'youtube'
            body = {'job_id': job['id'], 'version_id': version['version_id'], 'channel_id': channel_id, 'title': title,
                    'caption': youtube_text if youtube else facebook_text, 'publish_at': datetime.fromtimestamp(at, timezone.utc).isoformat(),
                    'tags': tags if youtube else [], 'ai_label': plan['ai_label']}
            try:
                made.append(self.publishing.create_schedule(body, f'plan:{plan["id"]}:{int(at)}:{channel_id}')['id'])
            except Exception as error:
                problems.append(f'{(channels.get(channel_id) or {}).get("name", channel_id)}: {error}')
        if not made:
            return None, '; '.join(problems)[:500] or 'Không tạo được lịch đăng'
        return made, '; '.join(problems)[:500] or None

    def tick(self, force=False):
        now = self.clock()
        if not force and now - self.last_round < EVERY:
            return 0
        self.last_round = now
        made = 0
        with self.store.db() as db:
            plans = [self._public_light(dict(r)) for r in db.execute('SELECT * FROM publishing_plans WHERE enabled=1')]
        for plan in plans:
            with self.store.db() as db:
                taken = {r[0] for r in db.execute('SELECT slot_at FROM publishing_plan_slots WHERE plan_id=?', (plan['id'],))}
            free = [at for at in self.slots(plan, now) if at not in taken]
            if not free:
                continue
            queue = self.candidates(plan)
            note = None
            for at in free:
                while queue:
                    job = queue.pop(0)
                    try:
                        ids, problem = self._schedule(plan, job, at)
                    except Exception as error:
                        ids, problem = None, str(error)[:500]
                    if ids:
                        with self.store.db() as db:
                            db.execute('INSERT OR IGNORE INTO publishing_plan_slots VALUES(?,?,?,?,?)', (plan['id'], at, job['id'], _json(ids), now))
                        made += 1
                        note = problem
                        break
                    if problem and 'đang chờ tool viết' not in problem:
                        with self.store.db() as db:  # never retried by this plan; shown in the plan card
                            db.execute('INSERT OR REPLACE INTO publishing_plan_skips VALUES(?,?,?,?)', (plan['id'], job['id'], problem, now))
                else:
                    note = 'Hết video sẵn sàng để đăng: làm thêm video cho kế hoạch này.'
                    break
            with self.store.db() as db:
                db.execute('UPDATE publishing_plans SET note=? WHERE id=?', (note, plan['id']))
        return made

    @staticmethod
    def _public_light(row):
        return {**row, 'channels': json.loads(row['channels']), 'times': json.loads(row['times']), 'days': json.loads(row['days']),
                'enabled': bool(row['enabled']), 'ai_label': bool(row['ai_label'])}
