"""Local, durable publishing. A schedule pins approved bytes, never 'latest'.

Network credentials and upload receipts stay in the ignored local database.
Unknown remote outcomes stop for reconciliation instead of creating duplicates.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import uuid
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from .core import digest



def _tags(value):
    """YouTube tags: up to 30, each up to 100 characters, about 500 characters in total; '#' and commas removed."""
    if value in (None, '', []):
        return []
    if isinstance(value, str):
        value = value.split(',')
    if not isinstance(value, list):
        raise ValueError('Tag phải là danh sách')
    tags, total = [], 0
    for item in value:
        tag = re.sub(r'[<>,#]', ' ', str(item)).strip()
        tag = re.sub(r'\s+', ' ', tag)[:100]
        if not tag or tag.casefold() in (t.casefold() for t in tags):
            continue
        cost = len(tag) + (2 if ' ' in tag else 0) + (1 if tags else 0)
        if total + cost > 480 or len(tags) >= 30:
            break
        tags.append(tag)
        total += cost
    return tags

class PublishBlocked(Exception):
    pass


class PublishUncertain(Exception):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace('+00:00', 'Z')


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('Chọn ngày giờ đăng có múi giờ')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Ngày giờ đăng phải kèm múi giờ')
    return dt.timestamp()


def _text(value, maximum, label):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label}: nhập 1–{maximum} ký tự')
    return value.strip()


class Publishing:
    def __init__(self, store, versions, clock=time.time, client=None):
        self.store, self.versions, self.clock = store, versions, clock
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
        self.adapters = {'youtube': self.upload_youtube, 'facebook': self.upload_facebook}
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS publishing_channels(
                    id TEXT PRIMARY KEY, platform TEXT NOT NULL, name TEXT NOT NULL,
                    credentials TEXT NOT NULL, connected INTEGER NOT NULL DEFAULT 1,
                    error TEXT, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS publishing_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS publishing_oauth(state TEXT PRIMARY KEY, expires REAL NOT NULL, redirect_uri TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS publishing_schedules(
                    id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    job_id TEXT NOT NULL, version_id TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
                    channel_id TEXT NOT NULL, platform TEXT NOT NULL, title TEXT NOT NULL, caption TEXT NOT NULL,
                    publish_at REAL NOT NULL, state TEXT NOT NULL, phase TEXT,
                    remote_id TEXT, remote_url TEXT, upload_url TEXT, error TEXT,
                    lease_until REAL NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL);
            ''')
            if 'tags' not in {r[1] for r in db.execute('PRAGMA table_info(publishing_schedules)')}:
                db.execute("ALTER TABLE publishing_schedules ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
            # ai_label: the video was made with AI (voice, pictures), declared to the platform when it allows it
            if 'ai_label' not in {r[1] for r in db.execute('PRAGMA table_info(publishing_schedules)')}:
                db.execute('ALTER TABLE publishing_schedules ADD COLUMN ai_label INTEGER NOT NULL DEFAULT 1')

    def save_channel(self, identifier, platform, name, credentials):
        if platform not in self.adapters:
            raise ValueError('Nền tảng chưa hỗ trợ')
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO publishing_channels VALUES(?,?,?,?,1,NULL,?)',
                       (identifier, platform, name, _json(credentials), self.clock()))
        return next(row for row in self.channels()['items'] if row['id'] == identifier)

    def channels(self):
        with self.store.db() as db:
            rows = db.execute('SELECT id,platform,name,connected,error FROM publishing_channels ORDER BY platform,name').fetchall()
            configured = db.execute("SELECT 1 FROM publishing_settings WHERE key='youtube_client'").fetchone() is not None
        configured = configured or self._drive_client() is not None
        items = [dict(row, connected=bool(row['connected']), setup_required=not bool(row['connected'])) for row in rows]
        for platform, name in [('youtube', 'YouTube'), ('facebook', 'Facebook Page')]:
            if not any(row['platform'] == platform for row in items):
                items.append(dict(id=platform, platform=platform, name=name, connected=False, setup_required=True))
        return {'items': items, 'youtube_configured': configured, 'defaults': self.default_channels()}

    # --- which channel each kind of video goes to (vụ án → kênh A, kể truyện → kênh B) ---------------------
    STYLES = ('case', 'story', 'news', 'meme')

    def default_channels(self):
        """{kind of video: {platform: channel id}}: one YouTube channel and one Facebook Page per kind."""
        with self.store.db() as db:
            row = db.execute("SELECT value FROM publishing_settings WHERE key='default_channels'").fetchone()
            known = {r['id']: r['platform'] for r in db.execute('SELECT id,platform FROM publishing_channels WHERE connected=1')}
        saved = json.loads(row['value']) if row else {}
        result = {}
        for style, value in saved.items():
            if style not in self.STYLES:
                continue
            picks = value if isinstance(value, dict) else {known.get(value, ''): value}  # older setting: one channel per kind
            picks = {platform: channel for platform, channel in picks.items() if known.get(channel) == platform}
            if picks:
                result[style] = picks
        return result

    def set_default_channels(self, data):
        if not isinstance(data, dict):
            raise ValueError('Chọn kênh cho từng loại video')
        with self.store.db() as db:
            known = {r['id']: r['platform'] for r in db.execute('SELECT id,platform FROM publishing_channels WHERE connected=1')}
        result = {}
        for style, picks in data.items():
            if style not in self.STYLES:
                raise ValueError('Loại video không hợp lệ')
            if not isinstance(picks, dict):
                raise ValueError('Chọn kênh theo từng nền tảng')
            for platform, channel in picks.items():
                if platform not in self.adapters:
                    raise ValueError('Nền tảng không hợp lệ')
                if channel in (None, ''):
                    continue
                if known.get(channel) != platform:
                    raise ValueError('Kênh chưa kết nối hoặc không thuộc nền tảng này')
                result.setdefault(style, {})[platform] = channel
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO publishing_settings VALUES('default_channels',?)", (_json(result),))
        return {'defaults': self.default_channels()}

    # --- Facebook Page: how the Reels are doing ------------------------------------------------------------
    REEL_FIELDS = ('id,description,created_time,length,permalink_url,views,post_views,picture,'
                   'status{video_status,publishing_phase,copyright_check_status},'
                   'comments.summary(true).limit(0),likes.summary(true).limit(0)')
    # video_insights metrics shown when the token has read_insights (other metrics are ignored)
    REEL_INSIGHTS = {'post_impressions_unique': 'reach', 'blue_reels_play_count': 'plays', 'fb_reels_total_plays': 'total_plays',
                     'fb_reels_replay_count': 'replays', 'post_video_avg_time_watched': 'avg_watch_ms',
                     'post_video_view_time': 'watch_ms', 'post_video_followers': 'new_followers',
                     'post_video_social_actions': 'social_actions'}
    _reels_cache = {}

    def facebook_reels(self, channel_id, refresh=False, limit=30):
        """Recent Reels of a connected Page: views, comments, likes, copyright check, the caption check and,
        with read_insights, reach and watch time. Monetisation status is not offered by the Graph API."""
        from .facebook_safety import check
        channel = self.channel(channel_id)
        if channel['platform'] != 'facebook':
            raise ValueError('Chọn một Facebook Page')
        cached = self._reels_cache.get(channel_id)
        if cached and not refresh and self.clock() - cached['checked_at'] < 600:
            return cached
        credentials = channel['credentials']
        base = 'https://graph.facebook.com/' + credentials.get('api_version', 'v24.0')
        headers = {'Authorization': 'Bearer ' + credentials['access_token']}
        page = self.client.get(f"{base}/{credentials['page_id']}", params={'fields': 'name,followers_count'}, headers=headers)
        reels = self.client.get(f"{base}/{credentials['page_id']}/video_reels", params={'fields': self.REEL_FIELDS, 'limit': limit}, headers=headers)
        if reels.status_code in (401, 403) or page.status_code in (401, 403):
            raise PublishBlocked('Token Trang hết hạn hoặc thiếu quyền; kết nối lại Facebook Page')
        if reels.status_code >= 400:
            raise PublishBlocked(f'Facebook chưa cho đọc danh sách Reels (HTTP {reels.status_code})')
        with self.store.db() as db:
            ours = {r['remote_id']: dict(r) for r in db.execute(
                "SELECT remote_id,job_id,title,state FROM publishing_schedules WHERE platform='facebook' AND remote_id IS NOT NULL")}
        items, insights_ok = [], None
        for video in reels.json().get('data', []):
            insights = {}
            if insights_ok is not False:
                answer = self.client.get(f"{base}/{video['id']}/video_insights", headers=headers)
                if answer.status_code == 200:
                    insights_ok = True
                    for metric in answer.json().get('data', []):
                        key = self.REEL_INSIGHTS.get(metric.get('name'))
                        value = (metric.get('values') or [{}])[0].get('value')
                        if key and isinstance(value, (int, float)):
                            insights[key] = value
                else:
                    insights_ok = False  # no read_insights: one refusal is enough, skip the rest
            status = video.get('status') or {}
            copyright_check = status.get('copyright_check_status') or {}
            caption = video.get('description') or ''
            caption_check = check(caption)
            items.append({
                'id': video['id'], 'caption': caption, 'created': video.get('created_time'), 'length': video.get('length'),
                'url': 'https://www.facebook.com' + video['permalink_url'] if str(video.get('permalink_url', '')).startswith('/') else video.get('permalink_url'),
                'picture': video.get('picture'), 'views': video.get('views'), 'post_views': video.get('post_views'),
                'comments': ((video.get('comments') or {}).get('summary') or {}).get('total_count'),
                'likes': ((video.get('likes') or {}).get('summary') or {}).get('total_count'),
                'published': (status.get('publishing_phase') or {}).get('publish_status') == 'published',
                'video_status': status.get('video_status'),
                'copyright': 'match' if copyright_check.get('matches_found') else ('clear' if copyright_check.get('status') == 'complete' else 'pending'),
                'check': {'verdict': caption_check['verdict'], 'issues': caption_check['issues'][:20]},
                'insights': insights, 'tool': ours.get(video['id']),
            })
        # A Reel well under the Page's usual views (once a day old) is worth a look in Professional Dashboard.
        now = datetime.now(timezone.utc)

        def age(item):
            try:
                return (now - datetime.strptime(item['created'], '%Y-%m-%dT%H:%M:%S%z')).total_seconds()
            except (TypeError, ValueError):
                return 0
        settled = sorted(i['views'] for i in items if isinstance(i['views'], int) and age(i) > 86400)
        median = settled[len(settled) // 2] if len(settled) >= 4 else None
        for item in items:
            item['low'] = bool(median and isinstance(item['views'], int) and age(item) > 86400 and item['views'] < 0.4 * median)
        info = page.json() if page.status_code == 200 else {}
        result = {'channel_id': channel_id, 'page': {'name': info.get('name') or channel['name'], 'followers': info.get('followers_count')},
                  'items': items, 'median_views': median, 'insights': insights_ok is True, 'checked_at': self.clock()}
        self._reels_cache[channel_id] = result
        return result

    def youtube_videos(self, channel_id, refresh=False, limit=30):
        """Latest uploads of a connected YouTube channel with views, likes, comments and visibility (youtube.readonly)."""
        channel = self.channel(channel_id)
        if channel['platform'] != 'youtube':
            raise ValueError('Chọn một kênh YouTube')
        cached = self._reels_cache.get(channel_id)
        if cached and not refresh and self.clock() - cached['checked_at'] < 600:
            return cached
        headers = self._yt_headers(channel)
        api = 'https://www.googleapis.com/youtube/v3/'
        info = (self._request('GET', api + 'channels', params={'part': 'contentDetails,statistics,snippet', 'mine': 'true'},
                              headers=headers).json().get('items') or [{}])[0]
        uploads = ((info.get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads')
        ids = []
        if uploads:
            listing = self._request('GET', api + 'playlistItems', params={'part': 'contentDetails', 'playlistId': uploads, 'maxResults': limit},
                                    headers=headers).json()
            ids = [i['contentDetails']['videoId'] for i in listing.get('items', []) if (i.get('contentDetails') or {}).get('videoId')]
        videos = self._request('GET', api + 'videos', params={'part': 'snippet,statistics,status,contentDetails', 'id': ','.join(ids)},
                               headers=headers).json().get('items', []) if ids else []
        with self.store.db() as db:
            ours = {r['remote_id']: dict(r) for r in db.execute(
                "SELECT remote_id,job_id,title,state FROM publishing_schedules WHERE platform='youtube' AND remote_id IS NOT NULL")}

        def seconds(value):
            match = re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', value or '')
            if not match:
                return None
            d, h, m, s = (int(x or 0) for x in match.groups())
            return d * 86400 + h * 3600 + m * 60 + s
        items = []
        for video in videos:
            stats, snippet, status = video.get('statistics') or {}, video.get('snippet') or {}, video.get('status') or {}
            number = lambda key: int(stats[key]) if str(stats.get(key, '')).isdigit() else None
            thumbs = snippet.get('thumbnails') or {}
            items.append({'id': video['id'], 'title': snippet.get('title') or '', 'created': snippet.get('publishedAt'),
                          'length': seconds((video.get('contentDetails') or {}).get('duration')),
                          'url': 'https://www.youtube.com/watch?v=' + video['id'], 'picture': (thumbs.get('medium') or thumbs.get('default') or {}).get('url'),
                          'views': number('viewCount'), 'likes': number('likeCount'), 'comments': number('commentCount'),
                          'privacy': status.get('privacyStatus'), 'publish_at': status.get('publishAt'), 'tool': ours.get(video['id'])})
        settled = sorted(i['views'] for i in items if isinstance(i['views'], int) and i['privacy'] == 'public')
        median = settled[len(settled) // 2] if len(settled) >= 4 else None
        now = datetime.now(timezone.utc)
        for item in items:
            try:
                old = (now - datetime.fromisoformat(item['created'].replace('Z', '+00:00'))).total_seconds() > 86400
            except (AttributeError, ValueError):
                old = False
            item['low'] = bool(median and old and item['privacy'] == 'public' and isinstance(item['views'], int) and item['views'] < 0.4 * median)
        stats = info.get('statistics') or {}
        result = {'channel_id': channel_id, 'platform': 'youtube',
                  'page': {'name': (info.get('snippet') or {}).get('title') or channel['name'],
                           'followers': int(stats['subscriberCount']) if str(stats.get('subscriberCount', '')).isdigit() else None,
                           'views': int(stats['viewCount']) if str(stats.get('viewCount', '')).isdigit() else None,
                           'videos': int(stats['videoCount']) if str(stats.get('videoCount', '')).isdigit() else None},
                  'items': items, 'median_views': median, 'checked_at': self.clock()}
        self._reels_cache[channel_id] = result
        return result

    def remove_channel(self, identifier):
        """Forget a connected channel in this tool (nothing is deleted on YouTube/Facebook)."""
        with self.store.db() as db:
            if db.execute('SELECT 1 FROM publishing_channels WHERE id=?', (identifier,)).fetchone() is None:
                raise KeyError(identifier)
            busy = db.execute("""SELECT COUNT(*) FROM publishing_schedules WHERE channel_id=?
                AND state NOT IN ('published','cancelled')""", (identifier,)).fetchone()[0]
            if busy:
                raise ValueError(f'Kênh còn {busy} lịch đăng chưa xong; huỷ hoặc chờ đăng xong rồi gỡ')
            db.execute('DELETE FROM publishing_channels WHERE id=?', (identifier,))
        return {'removed': identifier, 'defaults': self.default_channels()}

    def channel(self, identifier):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM publishing_channels WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Kết nối kênh trước khi lên lịch')
        result = dict(row)
        result['credentials'] = json.loads(result['credentials'])
        return result

    def disconnect(self, identifier):
        with self.store.db() as db:
            # Keep remote receipts; disconnecting is never a remote delete.
            db.execute("UPDATE publishing_channels SET connected=0,credentials='{}',updated=? WHERE id=?", (self.clock(), identifier))
        return {'ok': True}

    def configure_youtube(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('Chọn tệp JSON OAuth client của Google Cloud')
        client = raw.get('web') or raw.get('installed') or raw
        if not isinstance(client, dict):
            raise ValueError('OAuth client JSON không hợp lệ')
        config = {key: _text(client.get(key), 1000, key) for key in ('client_id', 'client_secret')}
        if not config['client_id'].endswith('.apps.googleusercontent.com'):
            raise ValueError('Cần OAuth client ID Google, không dùng API key')
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO publishing_settings VALUES('youtube_client',?)", (_json(config),))
        return {'configured': True}

    def youtube_config(self):
        with self.store.db() as db:
            row = db.execute("SELECT value FROM publishing_settings WHERE key='youtube_client'").fetchone()
        if row is None:
            client = self._drive_client()  # one Google OAuth client serves Drive and YouTube
            if client is None:
                raise ValueError('Tải tệp OAuth client JSON trước')
            return client
        return json.loads(row['value'])

    def _drive_client(self):
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drive_settings'").fetchone():
                return None
            row = db.execute("SELECT value FROM drive_settings WHERE key='client'").fetchone()
        client = json.loads(row['value']) if row else None
        return client if isinstance(client, dict) and client.get('client_id') and client.get('client_secret') else None

    def oauth_start(self, callback):
        client = self.youtube_config()
        parsed = urlparse(callback)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('OAuth callback phải thuộc VideoStudio trên máy này')
        state = secrets.token_urlsafe(32)
        with self.store.db() as db:
            db.execute('DELETE FROM publishing_oauth WHERE expires<?', (self.clock(),))
            db.execute('INSERT INTO publishing_oauth VALUES(?,?,?)', (state, self.clock()+600, callback))
        return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(dict(
            client_id=client['client_id'], redirect_uri=callback, response_type='code', state=state,
            scope='https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
            access_type='offline', prompt='select_account consent'))}

    def oauth_finish(self, state, code):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM publishing_oauth WHERE state=? AND expires>?', (state, self.clock())).fetchone()
            if row is None:
                raise ValueError('Phiên kết nối hết hạn hoặc đã được dùng; bấm Kết nối lại')
            db.execute('DELETE FROM publishing_oauth WHERE state=?', (state,))
        client = self.youtube_config()
        tokens = self._request('POST', 'https://oauth2.googleapis.com/token', data=dict(
            **client, code=code, redirect_uri=row['redirect_uri'], grant_type='authorization_code')).json()
        if not tokens.get('refresh_token') or not tokens.get('access_token'):
            raise PublishBlocked('Google chưa cấp quyền chạy nền; kết nối lại và đồng ý quyền upload')
        profile = self._request('GET', 'https://www.googleapis.com/youtube/v3/channels',
                                params={'part':'snippet', 'mine':'true'}, headers={'Authorization':'Bearer '+tokens['access_token']}).json()
        items = profile.get('items', [])
        if not items:
            raise PublishBlocked('Tài khoản chưa có kênh YouTube')
        item = items[0]
        handle = item['snippet'].get('customUrl') or ''
        return self.save_channel('youtube:'+item['id'], 'youtube', item['snippet']['title'] + (' · ' + handle if handle else ''),
                                 {'refresh_token':tokens['refresh_token'], 'channel_id':item['id']})

    def connect_facebook(self, data):
        page_id = _text(data.get('page_id'), 100, 'Page ID')
        if not page_id.isdigit():
            raise ValueError('Page ID phải là số')
        token = _text(data.get('access_token'), 5000, 'Page access token')
        version = data.get('api_version', 'v24.0')
        if not isinstance(version, str) or not re.fullmatch(r'v\d{2}\.0', version):
            raise ValueError('Graph API version không hợp lệ')
        credentials = {'page_id':page_id, 'access_token':token, 'api_version':version}
        # A Page token identifies the Page at /me; a user token is not substituted.
        profile = self._request('GET', f'https://graph.facebook.com/{version}/me',
                                params={'fields':'id,name,category'}, headers={'Authorization':'Bearer '+token}).json()
        if profile.get('id') != page_id or not profile.get('category'):
            raise PublishBlocked('Token phải thuộc đúng Facebook Page; không dùng token trang cá nhân')
        return self.save_channel('facebook:'+page_id, 'facebook', profile['name'], credentials)

    def create_schedule(self, data, key):
        key = _text(key, 200, 'Idempotency-Key')
        if not isinstance(data, dict):
            raise ValueError('Lịch đăng phải là một đối tượng')
        title = _text(data.get('title'), 100, 'Tiêu đề')
        caption = data.get('caption', '')
        if not isinstance(caption, str) or len(caption) > 5000:
            raise ValueError('Nội dung đăng tối đa 5000 ký tự')
        at = _stamp(data.get('publish_at'))
        normalized = {k:data.get(k) for k in ('job_id','version_id','channel_id')}
        if any(not isinstance(v, str) or not v or len(v)>200 for v in normalized.values()):
            raise ValueError('Chọn video, phiên bản và kênh')
        tags = _tags(data.get('tags'))
        ai_label = data.get('ai_label', True)
        if type(ai_label) is not bool:
            raise ValueError('Nhãn AI phải là bật/tắt')
        normalized.update(title=title, caption=caption, publish_at=at)
        if tags:
            normalized['tags'] = tags
        if not ai_label:
            normalized['ai_label'] = False
        fingerprint = hashlib.sha256(_json(normalized).encode()).hexdigest()
        with self.store.db() as db:
            prior = db.execute('SELECT id,fingerprint FROM publishing_schedules WHERE idem=?', (key,)).fetchone()
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise ValueError('Idempotency-Key already used cho lịch khác')
            return self.get_schedule(prior['id'])
        if at < self.clock()+300:
            raise ValueError('Chọn giờ đăng ít nhất 5 phút từ bây giờ')
        channel = self.channel(normalized['channel_id'])
        if not channel['connected']:
            raise ValueError('Kênh đã ngắt kết nối')
        approved = self.versions.approved_version(normalized['job_id'])
        if not approved or approved['version_id'] != normalized['version_id']:
            raise ValueError('Duyệt đúng phiên bản video trước khi lên lịch')
        if str(approved['version_id']).startswith('drive-'):
            # The video now lives on Google Drive: post from there (downloaded just before the upload, checked by MD5).
            path, sha = self._drive_source(normalized['job_id'], channel['platform'] == 'youtube')
        else:
            path = Path(approved['path'])
            if not path.is_file() or digest(path) != approved['sha256']:
                raise ValueError('Video đã thay đổi; cần duyệt lại')
            sha = approved['sha256']
            try:
                render = self.store.get(normalized['job_id'])['checkpoints'].get('render', {})
            except KeyError:
                render = {}
            wide = (render.get('story_outputs') or {}).get('ngang')
            if channel['platform'] == 'youtube' and wide and Path(wide).is_file():
                path, sha = Path(wide), digest(wide)
        identifier, now = str(uuid.uuid4()), self.clock()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id,fingerprint FROM publishing_schedules WHERE idem=?', (key,)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise ValueError('Idempotency-Key already used cho lịch khác')
                identifier = prior['id']
            else:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_history'").fetchone():
                    if db.execute('SELECT 1 FROM publication_history WHERE job_id=?',(normalized['job_id'],)).fetchone() or not db.execute('SELECT 1 FROM jobs WHERE id=?',(normalized['job_id'],)).fetchone():
                        raise ValueError('Video đã được dọn hoặc không còn tồn tại; không tạo lịch đăng mới')
                duplicate = db.execute("SELECT 1 FROM publishing_schedules WHERE channel_id=? AND sha256=? AND state!='cancelled'", (channel['id'],sha)).fetchone()
                if duplicate:
                    raise ValueError('Bản video này đã có lịch hoặc đã đăng trên kênh; không tạo trùng')
                db.execute('''INSERT INTO publishing_schedules
                    (id,idem,fingerprint,job_id,version_id,path,sha256,channel_id,platform,title,caption,publish_at,state,created,updated,tags,ai_label)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (identifier,key,fingerprint,normalized['job_id'],normalized['version_id'],str(path),sha,
                     channel['id'],channel['platform'],title,caption,at,'scheduled',now,now,_json(tags),int(ai_label)))
        return self.get_schedule(identifier)

    def _drive_source(self, job_id, youtube):
        with self.store.db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM drive_files WHERE job_id=? AND local_deleted=1 AND trashed=0 AND name LIKE '%.mp4'", (job_id,))]
        pick = (next((r for r in rows if r['name'].endswith('_ngang.mp4')), None) if youtube else None) \
            or next((r for r in rows if r['name'].endswith('_doc.mp4')), None) or (rows[0] if rows else None)
        if pick is None:
            raise ValueError('Không còn bản video trên Drive để đăng')
        return 'drive:' + job_id + '/' + pick['name'], pick['md5']

    @contextmanager
    def _drive_download(self, row, save=None):
        """Fetch the Drive copy to a temporary file, check its MD5 against the scheduled one, and remove it afterwards."""
        from .drive_storage import DriveStorage, local_md5
        job_id, name = row['path'][len('drive:'):].split('/', 1)
        with self.store.db() as db:
            record = db.execute('SELECT * FROM drive_files WHERE job_id=? AND name=?', (job_id, name)).fetchone()
        if record is None or record['trashed']:
            raise PublishBlocked('Bản video trên Drive không còn; không đăng được')
        folder = Path(tempfile.mkdtemp(prefix='vs-post-'))
        target = folder / name
        renewed = [self.clock()]

        def keep_lease():
            if save and self.clock() - renewed[0] >= 60:
                save(phase='download')
                renewed[0] = self.clock()
        try:
            try:
                DriveStorage(self.store).download(record['file_id'], target, check=keep_lease, account=record['account'])
            except Exception as error:
                raise PublishBlocked('Chưa tải được video từ Drive về để đăng: ' + str(error)[:160])
            if local_md5(target) != row['sha256']:
                raise PublishBlocked('Bản tải từ Drive không khớp mã kiểm tra; không đăng')
            with open(target, 'rb') as handle:
                yield handle, target.stat().st_size
        finally:
            target.unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass

    def _raw_schedule(self, identifier):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM publishing_schedules WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return dict(row)

    def get_schedule(self, identifier):
        raw = self._raw_schedule(identifier)
        return {key:(_iso(value) if key=='publish_at' else value) for key,value in raw.items()
                if key not in ('path','upload_url','fingerprint','idem','lease_until')}

    def schedules(self, job_id=None):
        with self.store.db() as db:
            rows = db.execute('SELECT id FROM publishing_schedules'+(' WHERE job_id=?' if job_id else '')+' ORDER BY publish_at DESC',
                              (job_id,) if job_id else ()).fetchall()
        return {'items':[self.get_schedule(row['id']) for row in rows]}

    def channel_states(self, job_id):
        return [dict(channel=row['channel_id'], status=row['state'], **row) for row in self.schedules(job_id)['items']]

    def _save(self, identifier, **changes):
        allowed = {'state','phase','remote_id','remote_url','upload_url','error','lease_until','next_at'}
        if not changes or not set(changes).issubset(allowed):
            raise ValueError('Invalid publishing update')
        changes['updated'] = self.clock()
        with self.store.db() as db:
            db.execute('UPDATE publishing_schedules SET '+','.join(k+'=?' for k in changes)+' WHERE id=?', (*changes.values(),identifier))

    def cancel(self, identifier):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM publishing_schedules WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            if row['state'] not in ('scheduled','blocked') or row['remote_id'] or row['upload_url']:
                raise ValueError('Video đã bắt đầu gửi; mở bài trên nền tảng để điều chỉnh hoặc gỡ lịch')
            db.execute("UPDATE publishing_schedules SET state='cancelled',updated=? WHERE id=?", (self.clock(),identifier))
        return self.get_schedule(identifier)

    def retry(self, identifier):
        row = self._raw_schedule(identifier)
        resumable = row['platform']=='youtube' and row['upload_url'] and not row['remote_id']
        if row['state'] not in (('blocked','needs_attention') if resumable else ('blocked',)) or row['remote_id']:
            raise ValueError('Cần đối soát kết quả trên nền tảng; không upload lại video chưa rõ kết quả')
        if row['publish_at'] < self.clock()+300:
            raise ValueError('Giờ đăng đã qua; hủy lịch chưa gửi và chọn giờ mới')
        self._save(identifier, state='scheduled', error=None, next_at=0)
        return self.get_schedule(identifier)

    def reconcile(self, identifier):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM publishing_schedules WHERE id=?',(identifier,)).fetchone()
            if row is None:raise KeyError(identifier)
            row=dict(row)
            if row['lease_until']>self.clock():raise ValueError('Bài đang được đối soát; chờ lượt hiện tại hoàn tất')
            if not row['remote_id']:raise ValueError('Chưa có ID bài trên nền tảng; giữ receipt, không tạo upload thay thế')
            if row['state'] in ('cancelled','published'):raise ValueError('Bài đã kết thúc')
            db.execute('UPDATE publishing_schedules SET lease_until=? WHERE id=?',(self.clock()+300,identifier))
        try:
            channel=self.channel(row['channel_id'])
            if not channel['connected']:raise PublishBlocked('Kết nối lại kênh trước khi đối soát')
            changes=self.poll_remote(row,channel)
            self._save(identifier,**changes,error=None,next_at=self.clock()+60)
            return self.get_schedule(identifier)
        except Exception:
            self._save(identifier,state='needs_attention',error='Chưa xác nhận được kết quả; giữ nguyên receipt và kiểm tra lại')
            raise
        finally:self._save(identifier,lease_until=0)

    def tick(self):
        now = self.clock()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # An expired uploader might have completed remotely. Never allocate again.
            db.execute("UPDATE publishing_schedules SET state='needs_attention',error=?,updated=? WHERE state='uploading' AND lease_until<?",
                       ('Tiến trình gửi đã ngắt; cần đối soát receipt trên nền tảng trước khi tiếp tục',now,now))
            row = db.execute("""SELECT * FROM publishing_schedules WHERE next_at<=? AND lease_until<=? AND
                ((state='scheduled' AND (platform='youtube' OR publish_at<=?)) OR state IN ('processing','scheduled_remote'))
                ORDER BY publish_at LIMIT 1""", (now,now,now)).fetchone()
            if row is None:
                return False
            row = dict(row)
            uploading = row['state']=='scheduled'
            db.execute('UPDATE publishing_schedules SET state=?,lease_until=?,updated=? WHERE id=?',
                       ('uploading' if uploading else row['state'],now+300,now,row['id']))
        identifier = row['id']
        try:
            channel = self.channel(row['channel_id'])
            if not channel['connected']:
                raise PublishBlocked('Kênh đã ngắt kết nối; kết nối lại để tiếp tục')
            if uploading:
                path = Path(row['path'])
                if not str(row['path']).startswith('drive:') and (not path.is_file() or digest(path) != row['sha256']):
                    raise PublishBlocked('Tệp video đã thay đổi; duyệt lại trước khi đăng')
                if (row['platform']=='youtube' and row['publish_at'] < now+120) or (row['platform']=='facebook' and row['publish_at'] < now-1800):
                    raise PublishBlocked('Giờ đăng đã qua hoặc quá sát; chọn lịch mới để tránh đăng ngoài ý muốn')
                def save(**changes):
                    self._save(identifier, **changes, lease_until=self.clock()+300)
                result = self.adapters[row['platform']](row, channel, save)
            else:
                result = self.poll_remote(row, channel)
            self._save(identifier, **result, error=None, lease_until=0, next_at=self.clock()+60)
        except PublishBlocked as error:
            self._save(identifier, state='blocked', error=str(error), lease_until=0)
        except Exception as error:
            message = str(error) if isinstance(error, PublishUncertain) else 'Mất kết nối khi gửi/kiểm tra bài. Đối soát receipt trước khi tiếp tục.'
            current=self._raw_schedule(identifier)
            if not current['remote_id'] and not current['upload_url']:
                self._save(identifier,state='blocked',error='Chưa gửi video: không kết nối được nền tảng. Có thể thử lại sau.',lease_until=0)
            elif not uploading and isinstance(error,httpx.RequestError) and current['phase']!='finishing':
                self._save(identifier,error='Mất kết nối; sẽ tự kiểm tra lại bài đã gửi',lease_until=0,next_at=self.clock()+60)
            else:self._save(identifier, state='needs_attention', error=message, lease_until=0)
        return True

    def _request(self, method, url, **kwargs):
        response = self.client.request(method, url, **kwargs)
        if response.status_code in (401,403):
            raise PublishBlocked('Quyền đăng đã hết hạn hoặc chưa được cấp; kết nối lại tài khoản và kiểm tra quyền ứng dụng')
        if response.status_code>=400:
            raise PublishBlocked(f'Nền tảng từ chối yêu cầu (HTTP {response.status_code}); kiểm tra tài khoản và cấu hình API')
        return response

    def _yt_headers(self, channel):
        config = self.youtube_config()
        token = self._request('POST','https://oauth2.googleapis.com/token',data=dict(
            **config, grant_type='refresh_token', refresh_token=channel['credentials'].get('refresh_token',''))).json().get('access_token')
        if not token:
            raise PublishBlocked('Không thể làm mới quyền YouTube; kết nối lại')
        return {'Authorization':'Bearer '+token}

    @staticmethod
    def _upload_url(url, hosts):
        parsed = urlparse(url or '')
        if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password:
            raise PublishUncertain('Nền tảng trả địa chỉ upload không hợp lệ; giữ receipt để đối soát')
        return url

    @contextmanager
    def upload_source(self,row,save=None):
        # Validate the exact bytes that will be sent before authentication/network.
        # Spooling keeps large videos off RAM and isolates a concurrent re-export.
        if str(row['path']).startswith('drive:'):
            with self._drive_download(row, save) as source:
                yield source
            return
        with tempfile.SpooledTemporaryFile(max_size=8*1024*1024,mode='w+b') as snapshot:
            sha=hashlib.sha256();size=0
            with open(row['path'],'rb') as source:
                for block in iter(lambda:source.read(1024*1024),b''):
                    snapshot.write(block);sha.update(block);size+=len(block)
            if sha.hexdigest()!=row['sha256']:raise PublishBlocked('Tệp video đã thay đổi; duyệt lại trước khi đăng')
            snapshot.seek(0)
            yield snapshot,size

    def upload_youtube(self,row,channel,save):
        with self.upload_source(row,save) as (source,size):
            return self._upload_youtube(row,channel,save,source,size)

    def _upload_youtube(self, row, channel, save, source, size):
        headers = self._yt_headers(channel)
        url = row.get('upload_url')
        offset = 0
        if url:
            self._upload_url(url, {'www.googleapis.com','youtube.googleapis.com'})
            status = self._request('PUT',url,headers={**headers,'Content-Length':'0','Content-Range':f'bytes */{size}'},content=b'')
            if status.status_code in (200,201):
                identifier = status.json()['id']
                return dict(state='scheduled_remote',remote_id=identifier,remote_url='https://www.youtube.com/watch?v='+identifier)
            received=status.headers.get('Range')
            offset=int(received.split('-')[-1])+1 if received else 0
        else:
            metadata = {'snippet':{'title':row['title'],'description':row['caption'],'categoryId':'22',
                                   **({'tags':json.loads(row.get('tags') or '[]')} if json.loads(row.get('tags') or '[]') else {})},
                        'status':{'privacyStatus':'private','publishAt':_iso(row['publish_at']), 'selfDeclaredMadeForKids':False,
                                  'containsSyntheticMedia':bool(row.get('ai_label', 1))}}
            response = self._request('POST','https://www.googleapis.com/upload/youtube/v3/videos',
                                     params={'uploadType':'resumable','part':'snippet,status'},json=metadata,
                                     headers={**headers,'X-Upload-Content-Length':str(size),'X-Upload-Content-Type':'video/mp4'})
            url = self._upload_url(response.headers.get('Location'), {'www.googleapis.com','youtube.googleapis.com'})
            save(upload_url=url,phase='upload')
        source.seek(offset)
        while offset<size:
                block = source.read(8*1024*1024)
                end = offset+len(block)-1
                response = self._request('PUT',url,content=block,headers={**headers,'Content-Type':'video/mp4',
                    'Content-Length':str(len(block)),'Content-Range':f'bytes {offset}-{end}/{size}'})
                save(phase='upload')
                if response.status_code in (200,201):
                    identifier = response.json().get('id')
                    if not identifier:
                        raise PublishUncertain('YouTube đã nhận upload nhưng thiếu ID video; cần đối soát')
                    save(remote_id=identifier,phase='uploaded')
                    return dict(state='scheduled_remote',remote_id=identifier,remote_url='https://www.youtube.com/watch?v='+identifier)
                if response.status_code!=308:
                    raise PublishUncertain('Chưa xác nhận upload YouTube; giữ nguyên phiên upload')
                received = response.headers.get('Range')
                if not received:
                    raise PublishUncertain('YouTube chưa xác nhận số byte đã nhận')
                next_offset=int(received.split('-')[-1])+1
                if not offset<next_offset<=size:raise PublishUncertain('YouTube chưa xác nhận tiến độ upload hợp lệ')
                offset = next_offset
                source.seek(offset)
        raise PublishUncertain('YouTube chưa xác nhận hoàn tất; giữ receipt, không upload bản khác')

    def upload_facebook(self,row,channel,save):
        with self.upload_source(row,save) as (source,size):
            return self._upload_facebook(row,channel,save,source,size)

    def _upload_facebook(self, row, channel, save, source, size):
        credentials = channel['credentials']
        base = 'https://graph.facebook.com/'+credentials.get('api_version','v24.0')
        headers = {'Authorization':'Bearer '+credentials['access_token']}
        session = self._request('POST',base+'/'+credentials['page_id']+'/video_reels',data={'upload_phase':'start'},headers=headers).json()
        identifier = str(session.get('video_id') or '')
        if not identifier.isdigit():
            raise PublishUncertain('Facebook chưa xác nhận ID video upload')
        url = self._upload_url(session.get('upload_url'), {'rupload.facebook.com'})
        save(remote_id=identifier,upload_url=url,phase='created')
        def chunks():
            renewed=self.clock()
            for block in iter(lambda:source.read(1024*1024),b''):
                if self.clock()-renewed>=60:save(phase='created');renewed=self.clock()
                yield block
        self._request('POST',url,headers={'Authorization':'OAuth '+credentials['access_token'],
                'offset':'0','file_size':str(size),'Content-Length':str(size),'Content-Type':'application/octet-stream'},
                content=chunks())
        save(phase='uploaded')
        return dict(state='processing',phase='uploaded',remote_id=identifier,remote_url='https://www.facebook.com/reel/'+identifier)

    def poll_remote(self, row, channel):
        if not row.get('remote_id'):
            raise PublishUncertain('Thiếu ID bài đã gửi; cần đối soát trên nền tảng')
        if row['platform']=='youtube':
            response = self._request('GET','https://www.googleapis.com/youtube/v3/videos',
                params={'part':'status,processingDetails','id':row['remote_id']},headers=self._yt_headers(channel)).json()
            items = response.get('items',[])
            if not items:
                raise PublishUncertain('Không tìm thấy ID video YouTube đã gửi; không tạo lại')
            status = items[0].get('status',{})
            if status.get('uploadStatus') in ('failed','rejected','deleted'):
                raise PublishBlocked('YouTube từ chối hoặc đã xóa video; mở YouTube Studio để kiểm tra')
            if status.get('privacyStatus')=='public':
                return {'state':'published'}
            if self.clock()>row['publish_at']+600 and not status.get('publishAt'):
                raise PublishBlocked('YouTube giữ video riêng tư; kiểm tra quyền ứng dụng/upload trong YouTube Studio')
            return {'state':'scheduled_remote'}
        credentials = channel['credentials']
        base = 'https://graph.facebook.com/'+credentials.get('api_version','v24.0')
        headers = {'Authorization':'Bearer '+credentials['access_token']}
        status = self._request('GET',base+'/'+row['remote_id'],params={'fields':'status'},headers=headers).json().get('status',{})
        phase = status.get('publishing_phase',{})
        if phase.get('publish_status')=='published' or phase.get('status')=='complete':
            return {'state':'published','phase':'published'}
        if status.get('video_status')=='error' or any(isinstance(v,dict) and v.get('status')=='error' for v in status.values()):
            raise PublishBlocked('Facebook báo lỗi xử lý video; kiểm tra Page / Meta Business Suite')
        # Facebook only starts processing a Reel after the "finish" call, so the upload being complete is enough to send it.
        uploaded = (status.get('video_status') in ('ready','upload_complete') or status.get('uploading_phase',{}).get('status')=='complete'
                    or status.get('processing_phase',{}).get('status')=='complete')
        if row.get('phase') in ('created','uploaded') and self.clock()>=row['publish_at'] and uploaded:
            # Persist before the effect. A lost finish reply must never trigger a second finish.
            with self.store.db() as db:
                changed=db.execute("UPDATE publishing_schedules SET phase='finishing',updated=? WHERE id=? AND phase IN ('created','uploaded')",
                                   (self.clock(),row['id'])).rowcount
            if not changed:raise PublishUncertain('Lệnh đăng đã được gửi; đang đối soát kết quả')
            self._request('POST',base+'/'+credentials['page_id']+'/video_reels',headers=headers,
                          data={'upload_phase':'finish','video_id':row['remote_id'],'video_state':'PUBLISHED',
                                'title':row['title'],'description':row['caption']})
            return {'state':'processing','phase':'finished'}
        if row.get('phase')=='finishing':
            raise PublishUncertain('Đã gửi lệnh đăng Facebook; chưa xác nhận kết quả. Mở Page để đối soát, không đăng lại')
        return {'state':'processing'}
