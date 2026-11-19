"""Truyện trên YouTube dễ tìm, dễ bấm: tiêu đề có tình tiết, ảnh bìa vẽ riêng từng tập, một danh sách phát mỗi bộ.

Why (2026-11-19): the story channel "Tôi Đọc Truyện" was new (0 subscribers, 0 views); its videos had gameplay
frames with small text as thumbnails, all alike, and titles that only said "<book> · Chương N: <name>".

Per book, kept in DATA_ROOT/story-promo/<book id>/:
- sheet.json: ChatGPT reads the opening chapters once and fixes the genre ("trọng sinh"), ONE art style and the look
  of the main characters (female and male lead first). The cast grows as the story goes: a chapter's important new
  character (a lead, or someone close to the leads; never a passer-by) joins it with their look.
- cast/<id>.png: each character's portrait, drawn once by ComfyUI (fixed seed). Every chapter picture takes the
  portraits of the (up to two) most important characters in its moment as identity references, so faces stay the same
  across the book (the owner's choice of ComfyUI over ChatGPT pictures, 2026-11-19).
Per episode, in <book id>/<episode key>/:
- promo.json: ChatGPT's title (the chapter's hook), the few words printed on the picture, the moment to draw, who is
  in it and how they look different in this chapter (clothes, injury, age), if they do;
- art.png (ComfyUI's picture) and thumb.jpg (1280x720, the words and "TẬP N" on it).
The YouTube title is "<hook> | Truyện audio <genre> – Tập N"; it is also written into the video's social.json, so a
post made after it is ready already carries it.

On YouTube (StoryPromo.apply, after a story video is uploaded): the title above, category 24 (Entertainment), the
thumbnail (thumbnails.set) and the book's playlist (made once per book and channel, chapters kept in order).
Videos uploaded before this feature started are left alone until the owner approves (approve_backfill), part by part.

Work runs in its own background thread, one episode at a time. Titles are written at any time; pictures are drawn
only while no video or scene-image task runs (the GPU is theirs), and ComfyUI's memory is freed after each episode.
Failing to make a picture never blocks a post: after three failed tries the thumbnail is the words on a plain
background, and the picture is tried again six hours later."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from .paths import DATA_ROOT

ROOT = DATA_ROOT / 'story-promo'
API = 'https://www.googleapis.com/youtube/v3/'
STORY_CATEGORY = '24'                    # Entertainment (stories were uploaded as 22, People & Blogs)
PARTS = ('title', 'category', 'thumbnail', 'playlist')
ART_TRIES = 3                            # failed ChatGPT pictures before the thumbnail is made without one
RETRY = 30 * 60
REDRAW_AFTER, REDRAWS = 6 * 3600, 2      # a thumbnail without ChatGPT's picture is tried again later (image limit)
APPLY_RETRY = 20 * 60
FONTS = ('C:/Windows/Fonts/seguibl.ttf', 'C:/Windows/Fonts/arialbd.ttf')   # Segoe UI Black has every Vietnamese letter; Arial Black does not
_ID = re.compile(r'^[0-9A-Za-z_-]{1,80}$')


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
    part.replace(path)
    return value


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _clean(text, limit):
    text = re.sub(r'[<>|]', ' ', str(text or ''))
    text = re.sub(r'\s+', ' ', text).strip().strip('"“”\'')
    return text[:limit].strip()


# --- what a story video tells ------------------------------------------------------------------------------------
def episode(job):
    """The book and chapters a story video tells, or None for other videos."""
    if (job.get('request') or {}).get('workflow_mode') != 'story_narration':
        return None
    snapshot = _read(Path(job['output']) / 'story-snapshot.json')
    if not snapshot or not snapshot.get('chapters') or not (snapshot.get('book') or {}).get('id'):
        return None
    book = snapshot['book']
    if not _ID.match(str(book['id'])):
        return None
    chapters = snapshot['chapters']
    numbers = [c.get('number') or c.get('order') for c in chapters]
    label = str(numbers[0]) if len(numbers) == 1 or numbers[0] == numbers[-1] else f'{numbers[0]}–{numbers[-1]}'
    key = hashlib.sha1('+'.join(sorted(str(c['id']) for c in chapters)).encode()).hexdigest()[:16]
    return {'book_id': str(book['id']), 'book': book.get('title') or '', 'key': key, 'number': label,
            'order': float(chapters[0].get('order') or chapters[0].get('number') or 0),
            'chapters': [{'id': c['id'], 'title': c.get('title') or '', 'number': c.get('number') or c.get('order')} for c in chapters],
            'text': '\n\n'.join(str(c.get('text') or '') for c in chapters), 'job_id': job['id'], 'output': job['output']}


def book_sample(book_id, limit=24000, library=None):
    """The opening chapters of a book from the story library (read only), for the character sheet."""
    from .story_library import STORY_ROOT
    path = Path(library or Path(STORY_ROOT) / 'library.sqlite3')
    if not path.is_file():
        return ''
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            rows = db.execute('SELECT title, text FROM chapters WHERE book_id=? AND deleted=0 ORDER BY position LIMIT 4', (book_id,)).fetchall()
    except sqlite3.Error:
        return ''
    return '\n\n'.join(f'{title}\n{text}' for title, text in rows)[:limit]


# --- what ChatGPT is asked ---------------------------------------------------------------------------------------
SHEET_PROMPT = """Bạn là họa sĩ chính của một kênh YouTube truyện audio. Dưới đây là phần mở đầu bộ truyện "{book}".
Hãy lập bảng nhân vật để vẽ ảnh bìa cho TẤT CẢ các tập của bộ truyện, sao cho nhân vật và nét vẽ giống hệt nhau ở mọi tập.
Chỉ trả lời JSON: {{"the_loai": "...", "phong_cach": "...", "nhan_vat": [{{"ten": "...", "vai": "...", "ngoai_hinh": "..."}}]}}
- the_loai: thể loại chính của truyện, 1–3 từ tiếng Việt viết thường, đúng từ người nghe hay tìm (ví dụ "trọng sinh", "xuyên không", "ngôn tình", "tu tiên", "hệ thống", "đô thị").
- phong_cach: MỘT phong cách vẽ cố định cho mọi ảnh bìa, viết bằng tiếng Anh, 1–2 câu (ví dụ "Modern Chinese manhua digital illustration, clean line art, soft cinematic lighting, rich saturated colours"). Chọn phong cách hợp thể loại và bối cảnh (cổ đại hay hiện đại).
- nhan_vat: 2–4 nhân vật chính, nữ chính và nam chính đứng đầu. ten: đúng tên trong truyện. vai: "nữ chính", "nam chính" hoặc một vai ngắn gọn khác. ngoai_hinh: tiếng Anh, cụ thể và cố định: giới tính, tuổi, khuôn mặt, kiểu tóc và màu tóc, màu mắt, dáng người, trang phục thường mặc và màu sắc. Truyện không tả thì tự chọn cho hợp vai, không mâu thuẫn với truyện.

Truyện:
{text}"""

EPISODE_PROMPT = """Bạn viết tiêu đề YouTube và chọn cảnh vẽ ảnh bìa cho một tập truyện audio.
Bộ truyện: "{book}" (thể loại {genre}). Tập {number}. Nhân vật đã biết: {people}.
Chỉ trả lời JSON: {{"tieu_de": "...", "chu_anh": "...", "canh": "...", "nhan_vat_trong_anh": ["..."], "nhan_vat_moi": [{{"ten": "...", "vai": "...", "ngoai_hinh": "..."}}], "ngoai_hinh_chuong": {{"<tên>": "..."}}}}
- tieu_de: tiếng Việt, 40–65 ký tự, kể tình tiết đáng tò mò nhất của TẬP NÀY (ai, làm gì, mâu thuẫn gì) để người lướt YouTube muốn bấm xem, ví dụ "Sống lại năm 2011, cô quyết cứu người đàn ông từng chết vì mình". Đúng nội dung tập, không bịa, không lộ cái kết của tập, không viết hoa toàn bộ, không emoji, không ghi số tập hay tên bộ truyện, không dùng dấu |.
- chu_anh: 2–5 từ tiếng Việt in to trên ảnh bìa, tối đa 28 ký tự, gây tò mò (ví dụ "SỐNG LẠI ĐỂ CỨU ANH").
- canh: tiếng Anh, 2–4 câu tả MỘT khoảnh khắc then chốt của tập này để vẽ: nhân vật nào (gọi đúng tên), nét mặt, hành động, bối cảnh, ánh sáng, cảm xúc. Không có chữ trong ảnh, không máu me, không gợi dục.
- nhan_vat_trong_anh: tên các nhân vật có mặt trong cảnh đó theo đúng nội dung tập này (1–3 nhân vật, người quan trọng nhất trước), viết đúng tên như trong truyện. Chỉ ghi nhân vật chính hoặc người gắn bó mật thiết với nhân vật chính (người yêu, gia đình, đối thủ chính, bạn thân, người xuất hiện nhiều). Nhân vật quá phụ (người qua đường, xuất hiện một lần) thì không ghi tên ở đây; nếu họ có trong cảnh thì chỉ tả trong canh.
- nhan_vat_moi: những nhân vật trong nhan_vat_trong_anh CHƯA có trong danh sách nhân vật đã biết ở trên. ten: đúng tên trong truyện. vai: vai ngắn gọn, nói rõ quan hệ với nhân vật chính. ngoai_hinh: tiếng Anh, cụ thể và cố định (giới tính, tuổi, khuôn mặt, kiểu tóc và màu tóc, màu mắt, dáng người, trang phục thường mặc và màu sắc), theo truyện, không mâu thuẫn với truyện. Không có ai mới thì để [].
- ngoai_hinh_chuong: chỉ cho nhân vật trong cảnh mà ở tập này trông KHÁC thường lệ (trang phục khác, bị thương, già hơn hay trẻ hơn, kiểu tóc khác): tên → một câu tiếng Anh tả điểm khác. Giữ nguyên gương mặt. Không ai khác thì để {{}}.

Nội dung tập:
{text}"""


CAST_LIMIT = 16                          # characters kept per book (each with its own portrait)


def _people(items):
    people = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and _clean(item.get('ten'), 60) and _clean(item.get('ngoai_hinh'), 1200):
            people.append({'name': _clean(item['ten'], 60), 'role': _clean(item.get('vai'), 40), 'look': _clean(item['ngoai_hinh'], 1200)})
    return people


def check_sheet(data):
    if not isinstance(data, dict):
        raise ValueError('ChatGPT không trả bảng nhân vật')
    genre = _clean(data.get('the_loai'), 30).lower()
    style = _clean(data.get('phong_cach'), 400)
    people = _people(data.get('nhan_vat'))
    if not genre or not style or not people:
        raise ValueError('Bảng nhân vật thiếu thể loại, phong cách hoặc nhân vật')
    return {'genre': genre, 'style': style, 'characters': people[:4]}


def check_copy(data, sheet):
    """The episode's title and moment. Characters of the chapter not yet in the book's sheet come back in 'new' (with
    their look) and are added to the sheet by the caller, so they keep one face in every later chapter too."""
    if not isinstance(data, dict):
        raise ValueError('ChatGPT không trả tiêu đề')
    title = _clean(data.get('tieu_de'), 70)
    hook = _clean(data.get('chu_anh'), 32)
    scene = _clean(data.get('canh'), 900)
    if len(title) < 10 or not hook or not scene:
        raise ValueError('Tiêu đề, chữ trên ảnh hoặc cảnh vẽ còn thiếu')
    return {'hook_title': title, 'hook': hook, 'scene': scene, **check_people(data, sheet)}


def check_people(data, sheet):
    """Who is in a moment (known names only, new important characters with their look) and how they look different."""
    known = {c['name'].casefold(): c['name'] for c in sheet['characters']}
    new = [p for p in _people(data.get('nhan_vat_moi')) if p['name'].casefold() not in known]
    for person in new:
        known.setdefault(person['name'].casefold(), person['name'])
    people = list(dict.fromkeys(known[n.strip().casefold()] for n in (data.get('nhan_vat_trong_anh') or [])
                                if isinstance(n, str) and n.strip().casefold() in known))[:3] or [sheet['characters'][0]['name']]
    changes = data.get('ngoai_hinh_chuong') if isinstance(data.get('ngoai_hinh_chuong'), dict) else {}
    looks_now = {known[k.strip().casefold()]: _clean(v, 300) for k, v in changes.items()
                 if isinstance(k, str) and k.strip().casefold() in known and known[k.strip().casefold()] in people and _clean(v, 300)}
    return {'people': people, 'looks_now': looks_now, 'new': [p for p in new if p['name'] in people]}


def youtube_title(hook_title, genre, number):
    suffix = f' | Truyện audio {genre} – Tập {number}'
    room = 100 - len(suffix)
    head = hook_title if len(hook_title) <= room else hook_title[:room - 1].rsplit(' ', 1)[0].rstrip(',;:') + '…'
    return head + suffix


def _style(sheet):
    """The leading look of the style only: the rest (e.g. "keep the same faces in every episode") would be drawn as a collage."""
    return sheet['style'].split('.')[0].strip()[:200]


def _alone(sheet, person):
    """The look without the sentences that name another character: the cat's "sits on Bạch Thù Văn's shoulder" drew a
    person into its portrait (2026-11-19)."""
    others = [c['name'] for c in sheet['characters'] if c['name'] != person['name']]
    sentences = re.split(r'(?<=[.!?])\s+', person['look'])
    kept = [s for s in sentences if not any(name.casefold() in s.casefold() for name in others)]
    return ' '.join(kept) or person['look']


def portrait_prompt(sheet, person):
    one = ('exactly one animal, no people, no humans' if re.search(r'\b(cat|dog|fox|bird|animal)\b', person['look'][:80], re.I)
           else 'exactly one person')
    return (f'{_style(sheet)}. Character reference portrait of {person["name"]}: {_alone(sheet, person)} Knee-up portrait, three-quarter view, '
            f'relaxed natural posture, face clearly visible with a calm natural expression, plain light gray studio background, soft light, '
            f'sharp focus, {one}, no text.')


FRAMING = {
    'thumbnail': 'Characters large and close to the camera, strong clear emotions on their faces',
    # Video background (story_art.py): the gameplay window covers the lower-left quarter of the landscape frame.
    'background': ('Wide cinematic composition: every character stands in the right half of the frame, faces clearly visible; the '
                   'left half, above all its lower part, is open background scenery with no people and no important details'),
}


def scene_prompt(sheet, copy, names, framing='thumbnail'):
    """The episode's moment; names are the characters whose portraits go with it, in order (reference image 1, 2)."""
    now = copy.get('looks_now') or {}
    looks = ' '.join(f'{c["name"]}: {c["look"]}' for c in sheet['characters'] if c['name'] in copy['people'])
    changes = ' '.join(f'In this chapter {name}: {note}' + ('' if note.endswith('.') else '.') for name, note in now.items())
    lead = ('Use the supplied images only for each character\'s identity: face, hair, body build and usual clothing; never copy their '
            'pose, expression, background or framing. ' + ' '.join(f'Reference image {k}: {name}.' for k, name in enumerate(names, 1)) + ' '
            if names else '')
    # Qwen sometimes drew a referenced character twice (chapters 7 and 8, 2026-11-19).
    return (lead + f'Render one full-frame scene, not a collage. {_style(sheet)}. Scene: {copy["scene"]} {looks} {changes} '
            f'Each named character appears exactly once, never duplicated. {FRAMING[framing]}, cinematic lighting, vivid colours. '
            'No text, letters, logos or watermarks.').replace('  ', ' ')


# --- the picture -------------------------------------------------------------------------------------------------
def _font(size):
    from PIL import ImageFont
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _lines(text, font, width):
    lines, line = [], ''
    for word in text.split():
        trial = f'{line} {word}'.strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def compose(art, hook, number, target):
    """1280x720 JPEG: the picture, darker on the left, the hook in large yellow/white type and a red "TẬP N" badge."""
    from PIL import Image, ImageDraw, ImageOps
    size = (1280, 720)
    if art and Path(art).is_file():
        with Image.open(art) as picture:
            base = ImageOps.fit(picture.convert('RGB'), size, Image.LANCZOS, centering=(0.5, 0.35))
    else:
        base = Image.new('RGB', size, (24, 30, 58))
    shade = Image.new('L', (size[0], 1))
    shade.putdata([max(0, min(215, int(215 * (1 - x / 760)))) for x in range(size[0])])   # dark on the left, clear from x=760
    shade = shade.resize(size)
    base = Image.composite(Image.new('RGB', size, (8, 10, 22)), base, shade)
    draw = ImageDraw.Draw(base)
    text = ' '.join(str(hook).upper().split())
    for points in range(112, 54, -6):
        font = _font(points)
        lines = _lines(text, font, 640)
        if len(lines) <= 3 and all(font.getlength(line) <= 640 for line in lines):
            break
    step = int(points * 1.12)
    # Bottom left: ChatGPT does not reliably keep the left third empty, and faces sit in the upper half (2026-11-19).
    y = 720 - 46 - step * len(lines)
    for index, line in enumerate(lines):
        draw.text((52, y), line, font=font, fill=(255, 222, 50) if index % 2 == 0 else (255, 255, 255),
                  stroke_width=max(5, points // 13), stroke_fill=(0, 0, 0))
        y += step
    badge = _font(46)
    label = f'TẬP {number}'
    box = draw.textbbox((0, 0), label, font=badge)
    width, height = box[2] - box[0], box[3] - box[1]
    draw.rounded_rectangle((36, 30, 36 + width + 40, 30 + height + 30), radius=12, fill=(214, 28, 38))
    draw.text((56 - box[0], 45 - box[1]), label, font=badge, fill=(255, 255, 255))
    target = Path(target)
    part = target.with_name(target.name + '.part')
    for quality in (90, 82, 72):
        base.save(part, 'JPEG', quality=quality, optimize=True)
        if part.stat().st_size < 1_900_000:
            break
    part.replace(target)
    return target


# --- ChatGPT through the dedicated Chrome ------------------------------------------------------------------------
class ChatGPT:
    """Text through the daemon's chat route (one tab, one request at a time)."""

    def ask(self, key, prompt):
        from .story_editor import ask_chatgpt
        return ask_chatgpt(key, prompt, attempts=3)


# --- ComfyUI on this computer (the owner's choice, 2026-11-19) ------------------------------------------------------
PORTRAIT = (768, 1376)
SCENE = (1376, 768)


class Comfy:
    """Qwen Image 2.1 in the local ComfyUI, the same model and reference conditioning the video scenes use
    (providers.image_graph, comfy_references.reference_graph). Each portrait reference holds one character only:
    a group sheet as reference made Comfy add stray people (trial 2026-11-19)."""

    def __init__(self, url=None):
        from .comfy_control import URL
        self.url = (url or URL).rstrip('/') + '/'

    def _client(self):
        import httpx
        return httpx.Client(base_url=self.url, timeout=60, trust_env=False)

    def _ensure(self):
        from . import comfy_control
        if comfy_control.responding():
            return
        comfy_control.start()
        if not comfy_control.responding(timeout=10):
            raise RuntimeError('ComfyUI chưa chạy và chưa bật lên được')

    def _upload(self, client, path):
        """A reference on the scene's canvas (as upload_references prepares it), named by its content."""
        import io
        from PIL import Image, ImageOps
        board = Image.new('RGB', SCENE, (127, 127, 127))
        with Image.open(path) as picture:
            picture = ImageOps.contain(picture.convert('RGB'), SCENE)
            board.paste(picture, ((SCENE[0] - picture.width) // 2, (SCENE[1] - picture.height) // 2))
        data = io.BytesIO()
        board.save(data, format='PNG')
        name = hashlib.sha256(data.getvalue()).hexdigest() + '.png'
        answer = client.post('upload/image', data={'type': 'input', 'subfolder': 'videostudio/story-promo', 'overwrite': 'true'},
                             files={'image': (name, data.getvalue(), 'image/png')})
        answer.raise_for_status()
        result = answer.json()
        return result['subfolder'] + '/' + result['name']

    def draw(self, prompt, seed, target, size=SCENE, references=(), timeout=900):
        from .providers import image_graph
        from .comfy_references import reference_graph
        from PIL import Image
        self._ensure()
        prefix = 'videostudio/story-promo/' + Path(target).parent.name + '-' + Path(target).stem
        with self._client() as client:
            names = [self._upload(client, p) for p in references]
            graph = reference_graph(prompt, seed, prefix, names, size=size) if names else image_graph(prompt, seed, prefix, size=size)
            answer = client.post('prompt', json={'prompt': graph, 'client_id': 'videostudio-story-promo'})
            answer.raise_for_status()
            prompt_id = answer.json()['prompt_id']
            deadline = time.monotonic() + timeout
            while True:
                history = client.get(f'history/{prompt_id}').json().get(prompt_id) or {}
                if history.get('outputs'):
                    image = next(i for out in history['outputs'].values() for i in out.get('images', []))
                    content = client.get('view', params=image).content
                    break
                if (history.get('status') or {}).get('status_str') == 'error':
                    raise RuntimeError('ComfyUI báo lỗi khi vẽ')
                if time.monotonic() > deadline:
                    raise RuntimeError('ComfyUI vẽ quá lâu')
                time.sleep(1)
        import io
        with Image.open(io.BytesIO(content)) as picture:
            if min(picture.size) < 512:
                raise RuntimeError('ComfyUI trả ảnh quá nhỏ')
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + '.part')
            picture.convert('RGB').save(part, format='PNG')
            part.replace(target)
        return target

    def free(self):
        """Give the GPU back once an episode is drawn (the video pipeline needs all of it)."""
        try:
            with self._client() as client:
                client.post('free', json={'unload_models': True, 'free_memory': True})
        except Exception:
            pass


# --- the background work -----------------------------------------------------------------------------------------
class StoryPromo:
    def __init__(self, store, publishing, chatgpt=None, clock=time.time, root=None, library=None, comfy=None):
        self.store, self.publishing, self.clock = store, publishing, clock
        self.chatgpt = chatgpt or ChatGPT()
        self.comfy = comfy or Comfy()
        self.root = Path(root or ROOT)
        self.library = library
        self.lock = threading.Lock()
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS story_promo_applied(
                    schedule_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, video_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    allowed TEXT NOT NULL, title TEXT, category TEXT, thumb_sha TEXT, playlist_id TEXT,
                    error TEXT, next_at REAL NOT NULL DEFAULT 0, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS story_playlists(
                    channel_id TEXT NOT NULL, book_id TEXT NOT NULL, playlist_id TEXT NOT NULL, title TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(channel_id, book_id));
                CREATE TABLE IF NOT EXISTS story_playlist_items(
                    playlist_id TEXT NOT NULL, video_id TEXT NOT NULL, order_key REAL NOT NULL, item_id TEXT,
                    PRIMARY KEY(playlist_id, video_id));
                CREATE TABLE IF NOT EXISTS publishing_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
            row = db.execute("SELECT value FROM publishing_settings WHERE key='story_promo_since'").fetchone()
            if row is None:
                db.execute("INSERT INTO publishing_settings VALUES('story_promo_since',?)", (str(self.clock()),))
                self.since = self.clock()
            else:
                self.since = float(row[0])

    # --- files ---------------------------------------------------------------------------------------------
    def _book(self, book_id):
        if not _ID.match(str(book_id)):
            raise ValueError('Mã truyện không hợp lệ')
        return self.root / book_id

    def sheet(self, book_id):
        return _read(self._book(book_id) / 'sheet.json')

    def promo(self, info):
        return _read(self._book(info['book_id']) / info['key'] / 'promo.json')

    def ready(self, info):
        promo = self.promo(info)
        folder = self._book(info['book_id']) / info['key']
        return promo if promo and promo.get('state') == 'ready' and (folder / 'thumb.jpg').is_file() else None

    # --- making the sheet, title and picture ---------------------------------------------------------------
    def _round(self):
        """Part of a ChatGPT request key: the daemon answers the same key and prompt from its journal, so a retry in a
        later round (after a bad answer) must be a new request, while a retry in the same round reads the same answer."""
        return int(self.clock() // RETRY)

    def make_sheet(self, info):
        """The book's genre, style and opening cast (ChatGPT, text only, once per book)."""
        sheet = self.sheet(info['book_id'])
        if not sheet or sheet.get('state') != 'ready':
            text = book_sample(info['book_id'], library=self.library) or info['text'][:24000]
            answer = self.chatgpt.ask(f'promo-sheet-{info["book_id"]}-{self._round()}', SHEET_PROMPT.format(book=info['book'], text=text))
            sheet = _write(self._book(info['book_id']) / 'sheet.json', {'state': 'ready', 'book': info['book'], **check_sheet(answer),
                                                                        'updated': self.clock()})
        return sheet

    def add_cast(self, book_id, people):
        """Characters met in a chapter join the book's cast (once, up to CAST_LIMIT)."""
        sheet = self.sheet(book_id)
        known = {c['name'].casefold() for c in sheet['characters']}
        added = [dict(p, since=self.clock()) for p in people if p['name'].casefold() not in known]
        if added:
            sheet['characters'] = (sheet['characters'] + added)[:CAST_LIMIT]
            _write(self._book(book_id) / 'sheet.json', dict(sheet, updated=self.clock()))
        return self.sheet(book_id)

    def write_copy(self, info, sheet):
        """ChatGPT's title, words and moment for the episode; new important characters join the cast."""
        people = ', '.join(f'{c["name"]} ({c["role"]})' for c in sheet['characters'])
        answer = self.chatgpt.ask(f'promo-{info["book_id"]}-{info["key"]}-{self._round()}', EPISODE_PROMPT.format(
            book=info['book'], genre=sheet['genre'], number=info['number'], people=people, text=info['text'][:16000]))
        copy = check_copy(answer, sheet)
        self.add_cast(info['book_id'], copy.pop('new'))
        return copy

    @staticmethod
    def _cast_id(name):
        return hashlib.sha1(name.casefold().encode('utf-8')).hexdigest()[:12]

    def portrait_path(self, book_id, name):
        return self._book(book_id) / 'cast' / (self._cast_id(name) + '.png')

    def portrait(self, book_id, sheet, person):
        """The character's fixed portrait (drawn once by Comfy, same seed): the identity reference of every scene."""
        path = self.portrait_path(book_id, person['name'])
        if not path.is_file():
            seed = int(hashlib.sha1(f'{book_id}:{person["name"].casefold()}'.encode('utf-8')).hexdigest()[:8], 16)
            self.comfy.draw(portrait_prompt(sheet, person), seed, path, PORTRAIT)
        return path

    def draw_scene(self, info, sheet, record, target, framing='thumbnail', salt=''):
        """The moment with the portraits of the (up to two) most important characters in it."""
        by_name = {c['name']: c for c in sheet['characters']}
        names = [n for n in record['people'] if n in by_name][:2]
        references = [self.portrait(info['book_id'], sheet, by_name[n]) for n in names]
        seed = int(hashlib.sha1(f'{info["book_id"]}:{info["key"]}:{salt}{record.get("art_tries", 0)}:{record.get("redraws", 0)}'.encode()).hexdigest()[:8], 16)
        return self.comfy.draw(scene_prompt(sheet, record, names, framing), seed, target, SCENE, references)

    def prepare(self, info, draw=True):
        """Title (always) and thumbnail (when draw: the GPU is free) of one episode. Returns the promo record: state
        'ready', 'titled' (title only, picture waits for the GPU) or 'error' (tried again later)."""
        folder = self._book(info['book_id']) / info['key']
        record = self.promo(info) or {'state': 'new', 'tries': 0}
        if record.get('state') == 'ready' and (folder / 'thumb.jpg').is_file():
            return self._redraw(info, record) if draw and self._redraw_due(record) else record
        try:
            sheet = self.make_sheet(info)
            if not record.get('hook_title'):
                record.update(self.write_copy(info, sheet))
                record.update(title=youtube_title(record['hook_title'], sheet['genre'], info['number']), state='titled', job_id=info['job_id'],
                              number=info['number'], book=info['book'], chapters=info['chapters'], updated=self.clock())
                _write(folder / 'promo.json', record)
                self._into_social(info, record['title'])
                sheet = self.sheet(info['book_id'])
            if not draw:
                return record
            art = folder / 'art.png'
            if not art.is_file() and record.get('art_tries', 0) < ART_TRIES:
                try:
                    self.draw_scene(info, sheet, record, art)
                    record['art'] = 'comfy'
                except Exception as error:
                    record['art_tries'] = record.get('art_tries', 0) + 1
                    record['art_error'] = str(error)[:300]
                    if record['art_tries'] < ART_TRIES:
                        raise
            if not art.is_file():   # Comfy could not draw it: the words on a plain background, drawn again later
                record['art'] = 'plain'
            compose(art if art.is_file() else None, record['hook'], info['number'], folder / 'thumb.jpg')
            record.update(state='ready', error=None, thumb_sha=_sha(folder / 'thumb.jpg'), updated=self.clock())
            _write(folder / 'promo.json', record)
            return record
        except Exception as error:
            tries = record.get('tries', 0) + 1
            record.update(state='error', error=str(error)[:400], tries=tries, next_at=self.clock() + RETRY * min(tries, 8), updated=self.clock())
            _write(folder / 'promo.json', record)
            return record

    def _redraw_due(self, record):
        """A thumbnail made without a picture (Comfy failed three times) gets another try later: after REDRAW_AFTER,
        at most REDRAWS times."""
        if record.get('repaint'):
            return True   # the owner asked for another picture
        return (record.get('art') in ('sheet', 'plain') and record.get('redraws', 0) < REDRAWS
                and self.clock() - record.get('updated', 0) >= REDRAW_AFTER)

    def repaint(self, job_id):
        """Vẽ lại ảnh bìa: another picture (a new seed) for the episode, its title kept; drawn when the GPU is free and
        put on YouTube by the next round. Repainting a character's portrait first: forget_portrait."""
        info = self._info(job_id)
        record = self.promo(info) if info else None
        if not record or not record.get('hook_title'):
            raise ValueError('Tập này chưa có tiêu đề và ảnh bìa để vẽ lại')
        _write(self._book(info['book_id']) / info['key'] / 'promo.json', dict(record, repaint=True, job_id=job_id))
        return {'job_id': job_id, 'episode': info['number']}

    def forget_portrait(self, book_id, name):
        """The character's portrait is drawn again next time it is needed."""
        path = self.portrait_path(book_id, name)
        if path.is_file():
            path.replace(path.with_name(path.stem + f'-old-{int(self.clock())}.png'))

    def _redraw(self, info, record):
        """One more try at the picture for a ready episode; its title stays. On failure the thumbnail stays as it is."""
        folder = self._book(info['book_id']) / info['key']
        record = dict(record, redraws=record.get('redraws', 0) + 1, updated=self.clock())
        record.pop('repaint', None)
        try:
            self.draw_scene(info, self.sheet(info['book_id']), record, folder / 'art.png')
            compose(folder / 'art.png', record['hook'], info['number'], folder / 'thumb.jpg')
            record.update(art='comfy', thumb_sha=_sha(folder / 'thumb.jpg'))
        except Exception as error:
            record['art_error'] = str(error)[:300]
        return _write(folder / 'promo.json', record)

    def books(self, page=1, page_size=12):
        """Kho video → Kể truyện: one small card per book, newest first: finished episodes, how many are posted or
        planned, and a cover (the newest episode thumbnail made here, else none). Light: no video file is opened."""
        if type(page) is not int or page < 1 or page_size not in (12, 24, 48):
            raise ValueError('Mỗi trang 12, 24 hoặc 48 truyện')
        from .project_lifecycle import deleted_job_ids
        with self.store.db() as db:
            hidden = deleted_job_ids(db)
            rows = [dict(r) for r in db.execute(
                """SELECT id, request, output, created FROM jobs WHERE state='completed'
                   AND json_extract(request,'$.workflow_mode')='story_narration' ORDER BY created DESC""") if r['id'] not in hidden]
            states = {}
            for job_id, state in db.execute("SELECT job_id, state FROM publishing_schedules WHERE cut='' AND state!='cancelled'"):
                states.setdefault(job_id, set()).add(state)
        groups = {}
        for row in rows:
            request = json.loads(row['request'])
            groups.setdefault(request.get('project') or 'Truyện', []).append({**row, 'request': request})
        result = []
        for title, jobs in groups.items():
            posted = sum('published' in states.get(j['id'], ()) for j in jobs)
            planned = sum(bool(states.get(j['id'])) and 'published' not in states[j['id']] for j in jobs)
            result.append({'title': title, 'videos': len(jobs), 'posted': posted, 'planned': planned, 'latest': jobs[0]['created'], 'jobs': jobs})
        total = len(result)
        page_items = result[(page - 1) * page_size:page * page_size]
        for book in page_items:
            jobs = book.pop('jobs')
            book['book_id'] = book['cover'] = None
            for job in jobs:
                info = episode(job)
                if not info:
                    continue
                book['book_id'] = book['book_id'] or info['book_id']
                if (self._book(info['book_id']) / info['key'] / 'thumb.jpg').is_file():
                    book['cover'] = f'/api/story-promo/thumb/{job["id"]}'
                    break
            if not book['cover']:   # no thumbnail made here yet: the newest video's own cover still on this computer
                for job in jobs[:10]:
                    name = next((Path(a['path']).name for a in (self.store.get_light(job['id'], ('render',))['checkpoints'].get('render') or {}).get('assets', [])
                                 if Path(a.get('path', '')).parent == Path(job['output']) and Path(a['path']).suffix.lower() in ('.jpg', '.png')
                                 and Path(a['path']).is_file()), None)
                    if name:
                        book['cover'] = f'/api/jobs/{job["id"]}/files/{name}'
                        break
            sheet = self.sheet(book['book_id']) if book['book_id'] else None
            book['characters'] = len((sheet or {}).get('characters') or [])
        return {'items': page_items, 'page': page, 'page_size': page_size, 'total': total,
                'total_pages': max(1, (total + page_size - 1) // page_size)}

    def thumb_file(self, job_id):
        info = self._info(job_id)
        path = self._book(info['book_id']) / info['key'] / 'thumb.jpg' if info else None
        if not path or not path.is_file():
            raise KeyError(job_id)
        return path

    def portrait_file(self, book_id, cast_id):
        sheet = self.sheet(book_id) or {}
        for person in sheet.get('characters') or []:
            if self._cast_id(person['name']) == cast_id and self.portrait_path(book_id, person['name']).is_file():
                return self.portrait_path(book_id, person['name'])
        raise KeyError(cast_id)

    def cast(self, book_id):
        """The book's characters for the library page: name, role, look and whether the portrait is drawn."""
        sheet = self.sheet(book_id) or {}
        return {'book_id': book_id, 'genre': sheet.get('genre'), 'style': sheet.get('style'),
                'characters': [{'id': self._cast_id(c['name']), 'name': c['name'], 'role': c.get('role', ''), 'look': c.get('look', ''),
                                'portrait': self.portrait_path(book_id, c['name']).is_file()} for c in sheet.get('characters') or []]}

    def _into_social(self, info, title):
        """The new title in the video's post copy, so the post form and Đăng tự động use it."""
        from . import social_copy
        job = {'id': info['job_id'], 'output': info['output']}
        social = social_copy.read(job)
        if not social or social.get('state') != 'ready' or not isinstance(social.get('youtube'), dict):
            return
        youtube = social['youtube']
        if youtube.get('title') != title:
            youtube.setdefault('plain_title', youtube.get('title'))
            youtube['title'] = title
            social_copy._write(job, social)

    # --- which videos ----------------------------------------------------------------------------------------
    def _discover(self):
        """Uploaded story videos on YouTube get a row; those uploaded before this feature start with nothing allowed."""
        with self.store.db() as db:
            rows = [dict(r) for r in db.execute(
                """SELECT s.id, s.channel_id, s.remote_id, s.job_id, s.created FROM publishing_schedules s JOIN jobs j ON j.id=s.job_id
                   WHERE s.platform='youtube' AND s.cut='' AND s.remote_id IS NOT NULL
                   AND s.state IN ('scheduled_remote','processing','published')
                   AND json_extract(j.request,'$.workflow_mode')='story_narration'
                   AND s.id NOT IN (SELECT schedule_id FROM story_promo_applied)""")]
            for row in rows:
                allowed = list(PARTS) if row['created'] >= self.since else []
                db.execute('INSERT OR IGNORE INTO story_promo_applied(schedule_id,channel_id,video_id,job_id,allowed,updated) VALUES(?,?,?,?,?,?)',
                           (row['id'], row['channel_id'], row['remote_id'], row['job_id'], json.dumps(allowed), self.clock()))

    def _rows(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute(
                """SELECT a.*, s.state AS schedule_state, s.publish_at FROM story_promo_applied a JOIN publishing_schedules s ON s.id=a.schedule_id
                   WHERE s.state IN ('scheduled_remote','processing','published') ORDER BY s.publish_at""")]

    def _info(self, job_id):
        try:
            return episode(self.store.get(job_id))
        except KeyError:
            return None

    def wanted(self):
        """Episodes that need a title and thumbnail: uploaded ones allowed to get them, then the next two of each
        story posting plan (so the title is ready when the plan schedules them)."""
        found = []
        for path in self.root.glob('*/*/promo.json'):   # "Vẽ lại ảnh bìa" asked by the owner
            record = _read(path) or {}
            if record.get('repaint') and record.get('job_id'):
                info = self._info(record['job_id'])
                if info:
                    found.append(info)
        for row in self._rows():
            allowed = json.loads(row['allowed'])
            if 'title' in allowed or 'thumbnail' in allowed:
                info = self._info(row['job_id'])
                if info:
                    found.append(info)
        plans = getattr(self.publishing, 'plans', None)
        if plans is not None:
            with self.store.db() as db:
                rows = [dict(r) for r in db.execute("SELECT * FROM publishing_plans WHERE enabled=1 AND style='story'")]
            for plan in map(plans._public_light, rows):
                if not any(str(c).startswith('youtube:') for c in plan['channels']):
                    continue
                for job in plans.candidates(plan)[:2]:
                    info = episode(job)
                    if info:
                        found.append(info)
        seen, result = set(), []
        for info in found:
            if (info['book_id'], info['key']) not in seen:
                seen.add((info['book_id'], info['key']))
                result.append(info)
        return result

    def _busy(self):
        """A video or a scene-image task is running: the GPU is theirs, so pictures wait (titles do not)."""
        with self.store.db() as db:
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('running','retrying') LIMIT 1").fetchone():
                return True
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scene_image_tasks'").fetchone():
                return db.execute("SELECT 1 FROM scene_image_tasks WHERE state IN ('queued','running') LIMIT 1").fetchone() is not None
        return False

    def prepare_next(self):
        """One waiting episode: its title at any time, its picture only while the GPU is free. True when work was done."""
        busy = self._busy()
        for info in self.wanted():
            ready = self.ready(info)
            if ready and (busy or not self._redraw_due(ready)):
                continue
            record = self.promo(info) or {}
            if record.get('state') == 'error' and self.clock() < record.get('next_at', 0):
                continue
            if busy and record.get('hook_title'):
                continue  # only the picture is missing: it waits for the GPU
            try:
                self.prepare(info, draw=not busy)
            finally:
                if not busy:
                    self.comfy.free()
            return True
        return False if busy else self._portrait_next()

    def _portrait_next(self):
        """With nothing else to do and the GPU free: one character of a book's cast still without a portrait (so Kho
        video shows the whole cast, and the next chapters do not wait for it)."""
        for path in sorted(self.root.glob('*/sheet.json')):
            sheet = _read(path) or {}
            for person in sheet.get('characters') or []:
                portrait = self.portrait_path(path.parent.name, person['name'])
                tried = path.parent / 'cast' / (portrait.stem + '.failed')
                try:
                    failed_at = float(tried.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    failed_at = None
                if portrait.is_file() or (failed_at is not None and self.clock() - failed_at < REDRAW_AFTER):
                    continue
                try:
                    self.portrait(path.parent.name, sheet, person)
                except Exception:
                    tried.parent.mkdir(parents=True, exist_ok=True)
                    tried.write_text(str(self.clock()), encoding='utf-8')
                finally:
                    self.comfy.free()
                return True
        return False

    # --- YouTube ------------------------------------------------------------------------------------------
    def _headers(self, channel_id):
        from .publishing import YOUTUBE_MANAGE, PublishBlocked
        channel = self.publishing.channel(channel_id)
        if not channel['connected']:
            raise PublishBlocked('Kênh đã ngắt kết nối')
        headers, granted = self.publishing._yt_token(channel)
        if YOUTUBE_MANAGE not in granted:
            raise PublishBlocked('Kênh chưa cấp quyền sửa video; kết nối lại kênh YouTube')
        return headers

    def _call(self, method, url, headers, **kwargs):
        return self.publishing._request(method, url, headers=headers, **kwargs)

    def set_snippet(self, headers, video_id, title=None, category=None):
        """Change the title and/or category and keep the description, tags and languages: videos.update replaces the
        whole snippet with what it is sent."""
        from .publishing import PublishUncertain
        items = self._call('GET', API + 'videos', headers, params={'part': 'snippet', 'id': video_id}).json().get('items') or []
        if not items:
            raise PublishUncertain('Không đọc được video trên YouTube')
        current = items[0].get('snippet') or {}
        body = {k: current[k] for k in ('title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage') if k in current}
        wanted = dict(body, **({'title': title} if title else {}), **({'categoryId': category} if category else {}))
        if wanted == body:
            return current
        answer = self._call('PUT', API + 'videos', headers, params={'part': 'snippet'}, json={'id': video_id, 'snippet': wanted}).json()
        snippet = answer.get('snippet') or {}
        if (title and snippet.get('title') != title) or (category and snippet.get('categoryId') != category):
            raise PublishUncertain('YouTube chưa xác nhận tiêu đề/danh mục mới')
        return snippet

    def set_thumbnail(self, headers, video_id, path):
        data = Path(path).read_bytes()
        answer = self._call('POST', 'https://www.googleapis.com/upload/youtube/v3/thumbnails/set', {**headers, 'Content-Type': 'image/jpeg'},
                            params={'videoId': video_id, 'uploadType': 'media'}, content=data).json()
        if not answer.get('items'):
            from .publishing import PublishUncertain
            raise PublishUncertain('YouTube chưa xác nhận ảnh bìa')
        return answer

    def playlist(self, headers, channel_id, book_id, book):
        """The book's playlist on this channel, made once (an existing playlist with the same name is reused)."""
        with self.store.db() as db:
            row = db.execute('SELECT playlist_id FROM story_playlists WHERE channel_id=? AND book_id=?', (channel_id, book_id)).fetchone()
        if row:
            return row[0]
        title = book[:150]
        found, token = None, None
        while not found:
            listing = self._call('GET', API + 'playlists', headers, params={'part': 'snippet', 'mine': 'true', 'maxResults': 50,
                                                                            **({'pageToken': token} if token else {})}).json()
            found = next((p['id'] for p in listing.get('items', []) if (p.get('snippet') or {}).get('title') == title), None)
            token = listing.get('nextPageToken')
            if not token:
                break
        if not found:
            answer = self._call('POST', API + 'playlists', headers, params={'part': 'snippet,status'}, json={
                'snippet': {'title': title, 'defaultLanguage': 'vi',
                            'description': f'Nghe trọn bộ truyện audio "{book}" theo đúng thứ tự từng tập.'},
                'status': {'privacyStatus': 'public'}}).json()
            found = answer.get('id')
            if not found:
                from .publishing import PublishUncertain
                raise PublishUncertain('YouTube chưa xác nhận danh sách phát mới')
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO story_playlists VALUES(?,?,?,?,?)', (channel_id, book_id, found, title, self.clock()))
        return found

    def add_to_playlist(self, headers, playlist_id, video_id, order):
        """Put the chapter in the playlist at its place in chapter order (once)."""
        from .publishing import PublishBlocked
        there = self._call('GET', API + 'playlistItems', headers, params={'part': 'id', 'playlistId': playlist_id, 'videoId': video_id}).json()
        item = next((i.get('id') for i in there.get('items', [])), None)
        if not item:
            with self.store.db() as db:
                position = db.execute('SELECT COUNT(*) FROM story_playlist_items WHERE playlist_id=? AND order_key<? AND video_id!=?',
                                      (playlist_id, order, video_id)).fetchone()[0]
            body = {'snippet': {'playlistId': playlist_id, 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}, 'position': position}}
            try:
                answer = self._call('POST', API + 'playlistItems', headers, params={'part': 'snippet'}, json=body).json()
            except PublishBlocked as error:
                if 'HTTP 400' not in str(error) and 'manualSort' not in str(error):
                    raise
                del body['snippet']['position']   # a playlist not in manual order takes no position: add at the end
                answer = self._call('POST', API + 'playlistItems', headers, params={'part': 'snippet'}, json=body).json()
            item = answer.get('id')
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO story_playlist_items VALUES(?,?,?,?)', (playlist_id, video_id, order, item))
        return item

    def apply(self, row):
        """Bring one uploaded story video up to date with what is allowed for it. Returns the changes made."""
        allowed = set(json.loads(row['allowed']))
        info = self._info(row['job_id'])
        if not allowed or not info:
            return {}
        promo = self.ready(info)
        written = (self.promo(info) or {}).get('title')   # the title is ready before the picture
        title = written if written and 'title' in allowed and row['title'] != written else None
        category = STORY_CATEGORY if 'category' in allowed and row['category'] != STORY_CATEGORY else None
        thumb = promo and 'thumbnail' in allowed and row['thumb_sha'] != promo['thumb_sha']
        listed = 'playlist' in allowed and not row['playlist_id']
        if not (title or category or thumb or listed):
            return {}
        headers = self._headers(row['channel_id'])
        done = {}
        if title or category:
            self.set_snippet(headers, row['video_id'], title, category)
            done.update(**({'title': title} if title else {}), **({'category': category} if category else {}))
            self._save(row, **done)
        if thumb:
            self.set_thumbnail(headers, row['video_id'], self._book(info['book_id']) / info['key'] / 'thumb.jpg')
            done['thumb_sha'] = promo['thumb_sha']
            self._save(row, thumb_sha=promo['thumb_sha'])
        if listed:
            playlist = self.playlist(headers, row['channel_id'], info['book_id'], info['book'])
            try:
                self.add_to_playlist(headers, playlist, row['video_id'], info['order'])
            except Exception as error:
                # A playlist just made answers "not found" for a while (chapter 7, 2026-11-19 08:03): the next round
                # adds the video. One still missing an hour after it was made was deleted on YouTube: made again.
                if 'playlistNotFound' in str(error):
                    with self.store.db() as db:
                        db.execute('DELETE FROM story_playlists WHERE playlist_id=? AND created<?', (playlist, self.clock() - 3600))
                        db.execute('DELETE FROM story_playlist_items WHERE playlist_id NOT IN (SELECT playlist_id FROM story_playlists)')
                raise
            done['playlist_id'] = playlist
            self._save(row, playlist_id=playlist)
        return done

    def _save(self, row, **changes):
        changes['updated'] = self.clock()
        with self.store.db() as db:
            db.execute('UPDATE story_promo_applied SET ' + ','.join(k + '=?' for k in changes) + ' WHERE schedule_id=?',
                       (*changes.values(), row['schedule_id']))

    def apply_all(self):
        self._discover()
        changed = 0
        for row in self._rows():
            if row['next_at'] > self.clock() or not json.loads(row['allowed']):
                continue
            try:
                if self.apply(row):
                    changed += 1
                self._save(row, error=None, next_at=0)
            except Exception as error:
                self._save(row, error=str(error)[:400], next_at=self.clock() + APPLY_RETRY)
        return changed

    def tick(self):
        """One round: bring uploaded videos up to date, then make one waiting episode. True when work was done."""
        if not self.lock.acquire(blocking=False):
            return False
        try:
            did = bool(self.apply_all())
            did = self.prepare_next() or did
            if did:
                self.apply_all()   # a title/thumbnail just made goes up at once
            return did
        finally:
            self.lock.release()

    # --- the owner's decisions -------------------------------------------------------------------------------
    def approve_backfill(self, channel_id, parts):
        """Allow these parts on story videos uploaded to the channel before this feature started."""
        parts = [p for p in PARTS if p in (parts or [])]
        self._discover()
        with self.store.db() as db:
            ids = [r[0] for r in db.execute(
                'SELECT a.schedule_id FROM story_promo_applied a JOIN publishing_schedules s ON s.id=a.schedule_id WHERE a.channel_id=? AND s.created<?',
                (channel_id, self.since))]
            for identifier in ids:
                db.execute('UPDATE story_promo_applied SET allowed=?,next_at=0,updated=? WHERE schedule_id=?', (json.dumps(parts), self.clock(), identifier))
        return {'videos': len(ids), 'parts': parts}

    def redo(self, job_id):
        """Make the episode's title and thumbnail again (the next round applies them)."""
        info = self._info(job_id)
        if not info:
            raise ValueError('Không phải video kể truyện')
        folder = self._book(info['book_id']) / info['key']
        if folder.is_dir():
            shutil.rmtree(folder)
        return {'job_id': job_id, 'episode': info['key']}

    def status(self):
        rows = []
        for row in self._rows():
            info = self._info(row['job_id'])
            promo = self.promo(info) if info else None
            rows.append({'schedule_id': row['schedule_id'], 'video_id': row['video_id'], 'channel_id': row['channel_id'],
                         'state': row['schedule_state'], 'allowed': json.loads(row['allowed']), 'title_set': row['title'],
                         'category_set': row['category'], 'thumbnail_set': bool(row['thumb_sha']), 'playlist_id': row['playlist_id'],
                         'error': row['error'], 'episode': info and info['number'], 'book': info and info['book'],
                         'promo': {k: promo.get(k) for k in ('state', 'title', 'hook', 'art', 'error')} if promo else None})
        with self.store.db() as db:
            playlists = [dict(r) for r in db.execute('SELECT * FROM story_playlists')]
        return {'since': self.since, 'videos': rows, 'playlists': playlists}


# --- the channel's About text -------------------------------------------------------------------------------------
def keywords(words):
    """YouTube channel keywords: space separated, a phrase with spaces in quotes, at most 500 characters."""
    out = ''
    for word in words:
        word = re.sub(r'["<>]', '', str(word)).strip()
        if not word:
            continue
        token = f'"{word}"' if ' ' in word else word
        if len(out) + len(token) + 1 > 500:
            break
        out = f'{out} {token}'.strip()
    return out


def set_branding(publishing, channel_id, description, words, country='VN'):
    """Channel description, keywords and country, keeping the other branding settings (read, merge, write)."""
    from .publishing import YOUTUBE_MANAGE, PublishBlocked, PublishUncertain
    channel = publishing.channel(channel_id)
    headers, granted = publishing._yt_token(channel)
    if YOUTUBE_MANAGE not in granted:
        raise PublishBlocked('Kênh chưa cấp quyền quản lý; kết nối lại kênh YouTube')
    remote = str(channel_id).split(':', 1)[-1]
    items = publishing._request('GET', API + 'channels', params={'part': 'brandingSettings', 'id': remote}, headers=headers).json().get('items') or []
    if not items:
        raise PublishUncertain('Không đọc được kênh')
    branding = items[0].get('brandingSettings') or {}
    settings = dict(branding.get('channel') or {})
    settings.update(description=str(description)[:1000], keywords=keywords(words), country=country)
    body = {'id': remote, 'brandingSettings': {**{k: v for k, v in branding.items() if k in ('watch',)}, 'channel': settings}}
    answer = publishing._request('PUT', API + 'channels', params={'part': 'brandingSettings'}, headers=headers, json=body).json()
    got = (answer.get('brandingSettings') or {}).get('channel') or {}
    if got.get('description') != settings['description']:
        raise PublishUncertain('YouTube chưa xác nhận mô tả kênh')
    return got
