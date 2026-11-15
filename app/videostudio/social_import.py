"""Tạo video từ bài Facebook: paste a post link, the tool does the rest.

1. The dedicated Chrome opens the post (cdp_social) and returns its text, its pictures and a few frames of its video.
2. The pictures are downloaded into DATA_ROOT/social-posts/<id>/ (the video itself never is).
3. ChatGPT reads the text with up to 4 of those pictures attached, says what the pictures show, checks the claims on
   the web and writes the idea for a video.
4. ChatGPT also finds real photos about the story on the web; the ones that download as real pictures, plus the post's
   own pictures, become the video's picture pool (image_pool.py), so the video shows real photos, not drawn ones.
   With fewer than 3 usable pictures the video draws its scenes as usual.
5. That idea goes into Hàng đợi as an ordinary "Phát triển ý tưởng" video with the Tạo video page's settings (voice,
   engine); the user can replace any scene's picture afterwards in the video's page.

Imports run one at a time in a background thread and survive a restart (they resume from the step they were on;
the browser read is repeated, the ChatGPT request is journaled by the daemon and never sent twice).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, Request  # module level: FastAPI reads these annotations by name

from .cdp_social import valid_post_url
from .image_pool import MIN_POOL, add_picture, save_pool
from .paths import DATA_ROOT

DAEMON = 'http://127.0.0.1:8879'
ROOT = DATA_ROOT / 'social-posts'
IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
MAX_DOWNLOADS = 6
MAX_IMAGE = 20 * 1024 * 1024
ACTIVE = ('queued', 'reading', 'analysing')
STEPS = {'queued': 'Chờ lượt', 'reading': 'Đang mở bài trong Chrome riêng',
         'analysing': 'ChatGPT đang phân tích bài và ảnh (chờ lượt nếu ChatGPT đang bận)',
         'done': 'Đã đưa vào hàng đợi', 'failed': 'Không làm được'}

PROMPT = """Bạn là biên tập viên nội dung video tiếng Việt. Dưới đây là một bài đăng Facebook{pictures}.

Việc cần làm:
1. Xem kỹ từng ảnh đính kèm (theo thứ tự): ảnh cho thấy gì, có ai, ở đâu, có chữ gì trong ảnh. Khung hình video chỉ để hiểu nội dung, không mô tả kỹ thuật.
2. Tìm trên web để kiểm chứng các thông tin chính trong bài và bổ sung bối cảnh, ghi kết quả vào "kiem_chung" (phần này chỉ để người làm video tham khảo, không đọc trong video). Không dùng cụm "được cho là", "bị cho là".
3. Viết ý tưởng cho một video TIN NÓNG có kịch tính để người xem không lướt qua: mở bằng câu móc gây tò mò, rồi xung đột, cái giá, những cú lật, nhịp nhanh. Không bịa thêm chi tiết. Lời đồn thì gán cho người nói MỘT lần ("theo bài đăng đang lan truyền") rồi kể tiếp; cả video chỉ được nhắc tối đa MỘT câu rằng thông tin chưa được xác nhận, tuyệt đối không rào đón lặp đi lặp lại.
4. Tìm trên web 10–15 ẢNH THẬT liên quan để làm hình cho video: người, địa điểm, sự kiện, sản phẩm được nhắc tới. Lấy từ NHIỀU trang khác nhau (báo chí, trang chính thức của công ty/tổ chức), mỗi trang tối đa 3 ảnh; KHÔNG dùng Wikimedia/Wikipedia; không lấy ảnh có logo, watermark, chữ chèn lớn; không lấy lại ảnh của chính bài đăng này. Mỗi ảnh cho link TRỰC TIẾP tới tệp ảnh (mở link là thấy ảnh, đuôi .jpg/.jpeg/.png/.webp), không phải link trang web.

Bài đăng (tác giả: {author}; link: {url}):
\"\"\"
{text}
\"\"\"

Trả về đúng một đối tượng JSON:
{{"tieu_de": "tiêu đề video ngắn, rõ, tiếng Việt",
 "y_tuong": "ý tưởng video 150–400 từ, kể như tin nóng: câu móc mở đầu, xung đột, diễn biến và cú lật, cái giá, dữ kiện đắt giá nhất; không câu rào đón nào",
 "anh": ["mỗi ảnh một dòng: ảnh cho thấy gì"],
 "kiem_chung": [{{"thong_tin": "một thông tin trong bài", "ket_qua": "đúng | sai | chưa kiểm chứng", "nguon": "link nguồn"}}],
 "nguon": ["các link đã dùng"],
 "anh_tim_duoc": [{{"url": "link trực tiếp tới tệp ảnh", "mo_ta": "ảnh cho thấy gì", "trang": "trang web chứa ảnh"}}]}}"""


class SocialImports:
    def __init__(self, store, factory, daemon=DAEMON, root=ROOT, http=None):
        self.store, self.factory, self.daemon, self.root = store, factory, daemon, Path(root)
        self.http = http
        self.lock = threading.Lock()
        self.worker = None
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS social_imports(id TEXT PRIMARY KEY, url TEXT NOT NULL, state TEXT NOT NULL,
                template TEXT NOT NULL, scope TEXT, title TEXT, result TEXT, batch_id TEXT, error TEXT,
                created REAL NOT NULL, updated REAL NOT NULL)''')

    # --- requests -----------------------------------------------------------------------------------------
    def start(self, url, template, scope=None):
        url = valid_post_url(url)
        if not isinstance(template, dict) or not isinstance(template.get('defaults'), dict):
            raise ValueError('Thiếu thiết lập video (giọng đọc, độ dài…)')
        if set(template) - {'project', 'style', 'defaults', 'auto_name'}:
            raise ValueError('Thiết lập video không hợp lệ')
        identifier, now = uuid.uuid4().hex, time.time()
        with self.store.db() as db:
            db.execute('INSERT INTO social_imports(id,url,state,template,scope,created,updated) VALUES(?,?,?,?,?,?,?)',
                       (identifier, url, 'queued', json.dumps(template, ensure_ascii=False), scope, now, now))
        self.kick()
        return self.get(identifier)

    def get(self, identifier):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM social_imports WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise KeyError('Không có lượt này')
        return self._public(row)

    def items(self, limit=20):
        with self.store.db() as db:
            rows = db.execute('SELECT * FROM social_imports ORDER BY created DESC LIMIT ?', (limit,)).fetchall()
        return {'items': [self._public(r) for r in rows]}

    def _public(self, row):
        result = json.loads(row['result']) if row['result'] else {}
        return {'id': row['id'], 'url': row['url'], 'state': row['state'], 'step': STEPS.get(row['state'], row['state']),
                'title': row['title'], 'error': row['error'], 'batch_id': row['batch_id'], 'created': row['created'],
                'updated': row['updated'], 'author': result.get('author'), 'pictures': result.get('pictures', 0),
                'frames': result.get('frames', 0), 'characters': result.get('characters', 0), 'real_pictures': result.get('real_pictures')}

    def _set(self, identifier, **values):
        values['updated'] = time.time()
        with self.store.db() as db:
            db.execute(f'UPDATE social_imports SET {",".join(k + "=?" for k in values)} WHERE id=?', (*values.values(), identifier))

    # --- worker -------------------------------------------------------------------------------------------
    def kick(self):
        """Start the background worker if it is not running (also called at start-up to resume)."""
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.worker = threading.Thread(target=self._run, name='social-imports', daemon=True)
            self.worker.start()

    def _run(self):
        while True:
            with self.store.db() as db:
                row = db.execute(f'SELECT * FROM social_imports WHERE state IN ({",".join("?" * len(ACTIVE))}) ORDER BY created LIMIT 1',
                                 ACTIVE).fetchone()
            if not row:
                return
            try:
                self.process(row['id'])
            except Exception as error:  # the next import still runs
                self._set(row['id'], state='failed', error=str(error)[:500])

    def _post(self, route, payload, timeout):
        import httpx
        client = self.http or httpx
        response = client.post(self.daemon + route, json=payload, headers={'X-VS-Client': 'videostudio'}, timeout=timeout, trust_env=False)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200 or not data.get('ok'):
            if data.get('code') == 'authentication_required':
                raise RuntimeError('Chrome riêng cần đăng nhập ChatGPT. Vào Cài đặt → Kết nối tạo video → Mở Chrome riêng.')
            raise RuntimeError(str(data.get('error') or f'Chrome riêng không trả lời (mã {response.status_code}). Kiểm tra Chrome riêng trong Cài đặt.')[:300])
        return data['data']

    def _chat(self, payload, attempts=8, pause=15):
        """ChatGPT has one tab and answers one request at a time, so this may wait behind a story chapter being
        edited. Waiting again is safe: the daemon journals the request by job and prompt and never sends it twice."""
        import httpx
        for attempt in range(attempts):
            try:
                return self._post('/api/chat', payload, 1100)
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == attempts - 1:
                    raise RuntimeError('ChatGPT bận quá lâu (đang làm việc khác trong Chrome riêng). Bấm thử lại sau.')
            except RuntimeError as error:
                # The daemon says nothing was sent (page not ready yet, control not drawn, turn held): try again.
                if not any(sign in str(error) for sign in ('nothing sent', 'no request sent', 'no prompt sent', 'asked again')) \
                        or attempt == attempts - 1:
                    raise
            time.sleep(pause)

    def process(self, identifier):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM social_imports WHERE id=?', (identifier,)).fetchone()
        folder = self.root / identifier
        folder.mkdir(parents=True, exist_ok=True)

        self._set(identifier, state='reading', error=None)
        post = self._post('/api/social/read', {'task_id': identifier, 'url': row['url']}, 180)
        text = (post.get('text') or post.get('summary') or '').strip()
        if not text:
            raise RuntimeError('Không đọc được nội dung bài. Nếu bài ở trang cá nhân hoặc trong nhóm, đăng nhập Facebook trong Chrome riêng rồi thử lại.')
        pictures = self._download(post.get('images') or ([post['og_image']] if post.get('og_image') else []), folder)
        frames = [f for f in post.get('frames') or [] if Path(f).is_file()]
        attachments = (frames[:2] + pictures)[:4] if frames else pictures[:4]
        self._set(identifier, title=(post.get('title') or '')[:200],
                  result=json.dumps({'author': post.get('author'), 'pictures': len(pictures), 'frames': len(frames), 'characters': len(text),
                                     'post_url': post.get('url')}, ensure_ascii=False))

        self._set(identifier, state='analysing')
        prompt = PROMPT.format(pictures=(f', kèm {len(attachments)} ảnh' + (' (gồm khung hình trích từ video trong bài)' if frames else '')) if attachments else '',
                               author=post.get('author') or 'không rõ', url=row['url'], text=text[:30000])
        answer = self._chat({'prompt': prompt, 'job_id': 'social-' + identifier, 'timeout_seconds': 900,
                             **({'attachments': attachments} if attachments else {})})
        answer = _unwrap(answer)
        idea = compose_idea(answer, post, row['url'])
        title = str(answer.get('tieu_de') or post.get('title') or 'Video từ bài Facebook').strip()[:120]

        found = self._picture_pool(identifier, answer, pictures)
        template = json.loads(row['template'])
        template.pop('auto_name', None)  # the video is named after ChatGPT's title
        if found >= MIN_POOL:
            # Real pictures instead of drawn ones (with fewer, the page's own image setting draws the scenes).
            defaults = {k: v for k, v in template['defaults'].items() if k not in ('meta_batch_size',)}
            template['defaults'] = {**defaults, 'image_provider': 'pool', 'image_pool': identifier, 'flow_batch_size': 1}
        payload = {**template, 'project': title[:80], 'style': template.get('style') or 'news', 'input_mode': 'idea',
                   'items': [{'text': idea, 'title': title}]}
        batch = self.factory.create_batch(payload, 'social-' + identifier, row['scope'])
        result = json.loads(self.get_raw(identifier)['result'] or '{}')
        result['analysis'] = answer
        result['real_pictures'] = found
        self._set(identifier, state='done', title=title, batch_id=batch.get('id') if isinstance(batch, dict) else None,
                  result=json.dumps(result, ensure_ascii=False))

    def _picture_pool(self, identifier, answer, post_pictures):
        """Download the photos ChatGPT found and keep the real ones, then the post's own pictures; returns how many."""
        import httpx
        client = self.http or httpx
        items, number = [], 0
        refused = []
        for found in (answer.get('anh_tim_duoc') or [])[:20]:
            url = str(found.get('url') or '') if isinstance(found, dict) else ''
            if not url.startswith(('https://', 'http://')):
                continue
            try:
                response = client.get(url, timeout=30, follow_redirects=True, headers={'User-Agent': 'VideoStudio/1.0 (picture for a personal video)'})
                kind = response.headers.get('content-type', '').split(';')[0].strip().lower()
                ok = response.status_code == 200 and kind.startswith('image/') and len(response.content) <= MAX_IMAGE
            except Exception:
                ok = False
            if not ok:
                refused.append(found)   # some sites only serve pictures to a real browser
                continue
            number += 1
            entry = add_picture(identifier, response.content, found.get('mo_ta'), found.get('trang') or url, 'web', number, root=self.root)
            if entry:
                items.append(entry)
        if refused:
            # One background tab in the dedicated Chrome opens each refused picture in turn and is closed at the end.
            try:
                fetched = self._post('/api/social/fetch-images', {'task_id': identifier, 'urls': [f['url'] for f in refused]}, 600)
            except Exception:
                fetched = []
            by_url = {f['url']: f for f in refused}
            for got in fetched or []:
                found = by_url.get(got.get('url'))
                try:
                    raw = Path(got['path']).read_bytes() if found and got.get('path') else None
                except OSError:
                    raw = None
                if raw:
                    number += 1
                    entry = add_picture(identifier, raw, found.get('mo_ta'), found.get('trang') or found['url'], 'web', number, root=self.root)
                    if entry:
                        items.append(entry)
        for index, path in enumerate(post_pictures, 1):
            try:
                entry = add_picture(identifier, Path(path).read_bytes(), 'Ảnh trong bài đăng gốc', 'bài Facebook', 'post', index, root=self.root)
            except OSError:
                entry = None
            if entry:
                items.append(entry)
        save_pool(identifier, items, root=self.root)
        return len(items)

    def get_raw(self, identifier):
        with self.store.db() as db:
            return dict(db.execute('SELECT * FROM social_imports WHERE id=?', (identifier,)).fetchone())

    def _download(self, urls, folder):
        import httpx
        client = self.http or httpx
        saved = []
        for number, url in enumerate(urls[:MAX_DOWNLOADS], 1):
            try:
                response = client.get(url, timeout=30, follow_redirects=True)
                kind = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if response.status_code != 200 or kind not in IMAGE_TYPES or not 0 < len(response.content) <= MAX_IMAGE:
                    continue
                path = folder / f'image-{number}{IMAGE_TYPES[kind]}'
                path.write_bytes(response.content)
                saved.append(str(path))
            except Exception:
                continue
        return saved


def _unwrap(value):
    inner = value.get('your_response') if isinstance(value, dict) and len(value) == 1 else None
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            inner = None
    value = inner if isinstance(inner, dict) else value
    if not isinstance(value, dict) or not str(value.get('y_tuong') or '').strip():
        raise RuntimeError('ChatGPT chưa trả về ý tưởng video; thử lại.')
    return value


def compose_idea(answer, post, url):
    """The idea text the video pipeline gets: title, idea, what the pictures show, checked facts, and the post's link."""
    lines = [str(answer.get('tieu_de') or '').strip(), '', str(answer['y_tuong']).strip()]
    pictures = [str(p).strip() for p in answer.get('anh') or [] if str(p).strip()]
    if pictures:
        lines += ['', 'Ảnh trong bài cho thấy:'] + [f'- {p}' for p in pictures[:8]]
    # The fact-check list stays in the import record for the user; it is NOT handed to the script writer, which
    # otherwise turns every unconfirmed point into a disclaimer (owner feedback 2026-11-16).
    lines += ['', 'Cách kể: tin nóng có kịch tính, nhịp nhanh: câu móc, xung đột, cú lật, cái giá. Lời đồn gán cho người nói một lần '
                  'rồi kể tiếp; cả video chỉ một câu ngắn nhắc thông tin chưa được xác nhận, không rào đón lặp lại.']
    lines += ['', f'Bài gốc trên Facebook: {post.get("author") or ""} — {url}'.replace(':  —', ': —')]
    return '\n'.join(lines).strip()


def register_social_routes(app, store, factory, same_origin):
    imports = SocialImports(store, factory)
    app.state.social_imports = imports
    with store.db() as db:
        pending = db.execute(f'SELECT 1 FROM social_imports WHERE state IN ({",".join("?" * len(ACTIVE))}) LIMIT 1', ACTIVE).fetchone()
    if pending:
        imports.kick()  # resume after a restart

    @app.post('/api/social/imports')
    def start(data: dict, request: Request):
        same_origin(request)
        try:
            return imports.start(data.get('url'), data.get('batch'), request.headers.get('x-connector-scope'))
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/social/imports')
    def listing():
        return imports.items()

    return imports
