import json
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image

from videostudio.core import Store
from videostudio.publishing import Publishing
from videostudio import story_promo
from videostudio.story_promo import StoryPromo, youtube_title, keywords, set_branding


SHEET = {'the_loai': 'Trọng Sinh', 'phong_cach': 'Modern manhua illustration, soft light.',
         'nhan_vat': [{'ten': 'Bạch Thù Văn', 'vai': 'nữ chính', 'ngoai_hinh': 'young woman, long black hair'},
                      {'ten': 'Lăng Ương', 'vai': 'nam chính', 'ngoai_hinh': 'tall young man, short dark hair'}]}
EPISODE = {'tieu_de': 'Sống lại năm 2011, cô quyết cứu người đàn ông từng chết vì mình', 'chu_anh': 'Sống lại để cứu anh',
           'canh': 'Bach Thu Van grabs Lang Uong by the wrist in a rainy street.', 'nhan_vat_trong_anh': ['Bạch Thù Văn', 'lăng ương', 'Ai đó'],
           'nhan_vat_moi': [], 'ngoai_hinh_chuong': {}}


class FakeChatGPT:
    def __init__(self):
        self.asked, self.answers = [], []

    def ask(self, key, prompt):
        self.asked.append((key, prompt))
        if 'bảng nhân vật' in prompt:
            return SHEET
        return self.answers.pop(0) if self.answers else EPISODE


class FakeComfy:
    def __init__(self, fail=0):
        self.fail, self.drawn, self.freed = fail, [], 0

    def draw(self, prompt, seed, target, size, references=()):
        self.drawn.append({'prompt': prompt, 'seed': seed, 'target': Path(target), 'size': size, 'references': [Path(r) for r in references]})
        if self.fail:
            self.fail -= 1
            raise RuntimeError('comfy down')
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (size[0], size[1]), (90, 40 + len(self.drawn) * 20 % 200, 40)).save(target)
        return Path(target)

    def free(self):
        self.freed += 1


class FakeYouTube:
    """Just enough of the YouTube Data API: videos, thumbnails, playlists, playlist items."""

    def __init__(self):
        self.videos = {}
        self.thumbs, self.playlists, self.items, self.calls = {}, {}, [], []

    def __call__(self, request):
        url, method = str(request.url), request.method
        self.calls.append((method, request.url.path))
        params = dict(request.url.params)
        if 'oauth2' in url:
            return httpx.Response(200, json={'access_token': 't', 'scope': 'https://www.googleapis.com/auth/youtube'})
        if request.url.path.endswith('/thumbnails/set'):
            self.thumbs[params['videoId']] = request.content
            return httpx.Response(200, json={'items': [{'default': {'url': 'x'}}]})
        if request.url.path.endswith('/videos') and method == 'GET':
            return httpx.Response(200, json={'items': [{'id': params['id'], 'snippet': dict(self.videos[params['id']], thumbnails={'a': 1})}]})
        if request.url.path.endswith('/videos') and method == 'PUT':
            body = json.loads(request.content)
            assert 'thumbnails' not in body['snippet']
            self.videos[body['id']] = body['snippet']
            return httpx.Response(200, json={'id': body['id'], 'snippet': body['snippet']})
        if request.url.path.endswith('/playlists') and method == 'GET':
            return httpx.Response(200, json={'items': [{'id': k, 'snippet': {'title': v}} for k, v in self.playlists.items()]})
        if request.url.path.endswith('/playlists') and method == 'POST':
            identifier = f'PL{len(self.playlists)}'
            self.playlists[identifier] = json.loads(request.content)['snippet']['title']
            return httpx.Response(200, json={'id': identifier})
        if request.url.path.endswith('/playlistItems') and method == 'GET':
            found = [i for i in self.items if i['playlist'] == params['playlistId'] and i['video'] == params['videoId']]
            return httpx.Response(200, json={'items': [{'id': i['id']} for i in found]})
        if request.url.path.endswith('/playlistItems') and method == 'POST':
            snippet = json.loads(request.content)['snippet']
            item = {'id': f'item{len(self.items)}', 'playlist': snippet['playlistId'], 'video': snippet['resourceId']['videoId']}
            mine = [i for i in self.items if i['playlist'] == item['playlist']]
            position = snippet.get('position', len(mine))
            self.items.insert(self.items.index(mine[position]) if position < len(mine) else len(self.items), item)
            return httpx.Response(200, json={'id': item['id']})
        if request.url.path.endswith('/channels') and method == 'GET':
            return httpx.Response(200, json={'items': [{'brandingSettings': {'channel': {'title': 'Tôi Đọc Truyện', 'defaultLanguage': 'vi'},
                                                                             'watch': {'textColor': '#fff'}}}]})
        if request.url.path.endswith('/channels') and method == 'PUT':
            body = json.loads(request.content)
            self.branding = body
            return httpx.Response(200, json=body)
        raise AssertionError(f'unexpected {method} {url}')

    def order(self, playlist):
        return [i['video'] for i in self.items if i['playlist'] == playlist]


class StoryPromoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'jobs.sqlite3', self.root / 'out')
        self.now = 1800000000.0
        self.youtube = FakeYouTube()
        self.publishing = Publishing(self.store, None, clock=lambda: self.now, client=httpx.Client(transport=httpx.MockTransport(self.youtube)))
        self.publishing.save_channel('youtube:UC1', 'youtube', 'Tôi Đọc Truyện', {'refresh_token': 'r'})
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO publishing_settings VALUES('youtube_client',?)",
                       (json.dumps({'client_id': 'x.apps.googleusercontent.com', 'client_secret': 's'}),))
        self.chatgpt, self.comfy = FakeChatGPT(), FakeComfy()
        self.promo = StoryPromo(self.store, self.publishing, chatgpt=self.chatgpt, clock=lambda: self.now, root=self.root / 'promo',
                                library=self.root / 'missing.sqlite3', comfy=self.comfy)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, number, mode='story_narration'):
        identifier = f'00000000-0000-0000-0000-00000000000{number}'
        output = self.root / 'out' / identifier
        output.mkdir(parents=True)
        (output / 'story-snapshot.json').write_text(json.dumps({
            'book': {'id': 'book1', 'title': 'Trọng Sinh: Công Lược Khẩn Cấp'},
            'chapters': [{'id': f'c{number}', 'number': number, 'order': number, 'title': f'Chương {number}', 'text': f'Nội dung chương {number}.'}]},
            ensure_ascii=False), encoding='utf-8')
        (output / 'social.json').write_text(json.dumps({'state': 'ready', 'youtube': {'title': f'Trọng Sinh · Chương {number}', 'description': 'd'}},
                                                       ensure_ascii=False), encoding='utf-8')
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,idem,request,state,output,created,updated) VALUES(?,?,?,?,?,?,?)',
                       (identifier, identifier, json.dumps({'workflow_mode': mode, 'project': 'Trọng Sinh: Công Lược Khẩn Cấp'}),
                        'completed', str(output), self.now, self.now))
        return identifier

    def uploaded(self, job_id, video_id, created, state='scheduled_remote'):
        self.youtube.videos[video_id] = {'title': 'old', 'description': 'keep me', 'tags': ['a'], 'categoryId': '22', 'defaultLanguage': 'vi'}
        with self.store.db() as db:
            db.execute('''INSERT INTO publishing_schedules(id,idem,fingerprint,job_id,version_id,path,sha256,channel_id,platform,title,caption,
                          publish_at,state,remote_id,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       ('s-' + video_id, 'k-' + video_id, 'f', job_id, 'v', 'p', 'h', 'youtube:UC1', 'youtube', 't', 'c',
                        self.now + 3600, state, video_id, created, created))

    def test_title_keeps_the_episode_label_within_100_characters(self):
        self.assertEqual(youtube_title('Sống lại năm 2011, cô quyết cứu người đàn ông từng chết vì mình', 'trọng sinh', '1'),
                         'Sống lại năm 2011, cô quyết cứu người đàn ông từng chết vì mình | Truyện audio trọng sinh – Tập 1')
        long = youtube_title('chữ ' * 40, 'trọng sinh', '12–13')
        self.assertLessEqual(len(long), 100)
        self.assertTrue(long.endswith('| Truyện audio trọng sinh – Tập 12–13'))

    def test_prepare_makes_one_sheet_per_book_and_a_consistent_thumbnail_per_episode(self):
        first, second = self.job(1), self.job(2)
        for job_id in (first, second):
            record = self.promo.prepare(story_promo.episode(self.store.get(job_id)))
            self.assertEqual(record['state'], 'ready', record.get('error'))
        sheet_asks = [k for k, p in self.chatgpt.asked if 'bảng nhân vật' in p]
        self.assertEqual(len(sheet_asks), 1)  # the sheet is made once for the book
        portraits = [d for d in self.comfy.drawn if d['size'] == story_promo.PORTRAIT]
        scenes = [d for d in self.comfy.drawn if d['size'] == story_promo.SCENE]
        self.assertEqual([p['target'].parent.name for p in portraits], ['cast', 'cast'])   # one portrait per character, drawn once
        self.assertEqual(len(scenes), 2)
        for scene in scenes:   # every chapter picture carries the same two portraits, in order, and the fixed style
            self.assertEqual(scene['references'], [p['target'] for p in portraits])
            self.assertIn('Reference image 1: Bạch Thù Văn. Reference image 2: Lăng Ương.', scene['prompt'])
            self.assertIn('Modern manhua illustration', scene['prompt'])
            self.assertIn('long black hair', scene['prompt'])
        self.assertNotEqual(portraits[0]['seed'], portraits[1]['seed'])
        self.assertEqual(record['people'], ['Bạch Thù Văn', 'Lăng Ương'])
        self.assertEqual(record['title'], 'Sống lại năm 2011, cô quyết cứu người đàn ông từng chết vì mình | Truyện audio trọng sinh – Tập 2')
        with Image.open(next((self.root / 'promo' / 'book1').glob('*/thumb.jpg'))) as picture:
            self.assertEqual(picture.size, (1280, 720))
        social = json.loads((self.root / 'out' / second / 'social.json').read_text(encoding='utf-8'))
        self.assertEqual(social['youtube']['title'], record['title'])
        self.assertEqual(social['youtube']['plain_title'], 'Trọng Sinh · Chương 2')

    def test_cast_grows_with_important_characters_and_keeps_their_portraits(self):
        newcomer = dict(EPISODE, nhan_vat_trong_anh=['Đường Trưng', 'Bạch Thù Văn'],
                        nhan_vat_moi=[{'ten': 'Đường Trưng', 'vai': 'bạn thân của nam chính', 'ngoai_hinh': 'boy with red hair, black hoodie'},
                                      {'ten': 'Người qua đường', 'vai': 'phụ', 'ngoai_hinh': 'old man'}],   # not in the scene list: ignored
                        ngoai_hinh_chuong={'bạch thù văn': 'wears a white wedding dress', 'Lăng Ương': 'not in the scene'})
        self.chatgpt.answers = [newcomer, dict(EPISODE, nhan_vat_trong_anh=['Đường Trưng'])]
        five = self.promo.prepare(story_promo.episode(self.store.get(self.job(5))))
        self.assertEqual(five['people'], ['Đường Trưng', 'Bạch Thù Văn'])
        self.assertEqual(five['looks_now'], {'Bạch Thù Văn': 'wears a white wedding dress'})
        cast = self.promo.cast('book1')['characters']
        self.assertEqual([c['name'] for c in cast], ['Bạch Thù Văn', 'Lăng Ương', 'Đường Trưng'])
        self.assertTrue(cast[2]['portrait'])
        scene = self.comfy.drawn[-1]
        self.assertIn('Reference image 1: Đường Trưng. Reference image 2: Bạch Thù Văn.', scene['prompt'])
        self.assertIn('In this chapter Bạch Thù Văn: wears a white wedding dress.', scene['prompt'])
        self.assertIn('boy with red hair', scene['prompt'])
        # the next chapter knows him: his portrait is reused, not drawn again
        drawn = len(self.comfy.drawn)
        self.promo.prepare(story_promo.episode(self.store.get(self.job(6))))
        self.assertEqual(len(self.comfy.drawn), drawn + 1)
        self.assertEqual(self.comfy.drawn[-1]['references'], [self.promo.portrait_path('book1', 'Đường Trưng')])
        self.assertIn('Nhân vật đã biết: Bạch Thù Văn (nữ chính), Lăng Ương (nam chính), Đường Trưng (bạn thân của nam chính)', self.chatgpt.asked[-1][1])

    def test_repaint_draws_a_new_picture_with_the_same_title(self):
        job_id = self.job(1)
        info = story_promo.episode(self.store.get(job_id))
        first = self.promo.prepare(info)
        with self.assertRaises(ValueError):
            self.promo.repaint(self.job(2))   # no title yet: nothing to repaint
        self.promo.repaint(job_id)
        self.assertEqual([i['key'] for i in self.promo.wanted()], [info['key']])   # the background round picks it up
        self.assertTrue(self.promo.prepare_next())
        again = self.promo.promo(info)
        self.assertEqual((again['title'], again.get('repaint')), (first['title'], None))
        scenes = [d['seed'] for d in self.comfy.drawn if d['size'] == story_promo.SCENE]
        self.assertEqual(len(set(scenes)), 2)   # another seed: another picture
        self.assertNotEqual(again['thumb_sha'], first['thumb_sha'])

    def test_idle_rounds_draw_the_missing_portraits_of_the_cast(self):
        self.promo.prepare(story_promo.episode(self.store.get(self.job(1))))
        self.promo.add_cast('book1', [{'name': 'Nữ sinh sao đỏ', 'role': 'tình địch', 'look': 'girl with a red armband'}])
        self.assertFalse(self.promo.cast('book1')['characters'][2]['portrait'])
        self.assertTrue(self.promo.prepare_next())
        self.assertTrue(self.promo.cast('book1')['characters'][2]['portrait'])
        self.assertFalse(self.promo.prepare_next())   # nothing left

    def test_books_list_one_card_per_book(self):
        self.promo.prepare(story_promo.episode(self.store.get(self.job(1))))
        self.job(2)
        books = self.promo.books()
        self.assertEqual(books['total'], 1)
        book = books['items'][0]
        self.assertEqual((book['title'], book['videos'], book['book_id'], book['characters']), ('Trọng Sinh: Công Lược Khẩn Cấp', 2, 'book1', 2))
        self.assertTrue(book['cover'].startswith('/api/story-promo/thumb/'))
        with self.assertRaises(ValueError):
            self.promo.books(page_size=13)

    def test_a_portrait_leaves_out_other_characters(self):
        sheet = {'style': 'Manhua. Keep faces.', 'characters': [{'name': 'Bạch Thù Văn', 'look': 'girl'},
                 {'name': 'Mèo trắng', 'look': 'Small white cat with golden eyes. Often sits on Bạch Thù Văn\'s shoulder. Fluffy tail.'}]}
        prompt = story_promo.portrait_prompt(sheet, sheet['characters'][1])
        self.assertIn('Small white cat with golden eyes. Fluffy tail.', prompt)
        self.assertNotIn('shoulder', prompt)
        self.assertIn('no people', prompt)
        self.assertIn('exactly one person', story_promo.portrait_prompt(sheet, sheet['characters'][0]))

    def test_a_picture_that_keeps_failing_gets_words_on_plain_and_a_later_try(self):
        info = story_promo.episode(self.store.get(self.job(1)))
        sheet = self.promo.make_sheet(info)
        for person in sheet['characters']:
            self.promo.portrait('book1', sheet, person)
        self.comfy.fail = 99
        for attempt in range(story_promo.ART_TRIES):
            record = self.promo.prepare(info)
        self.assertEqual((record['state'], record['art']), ('ready', 'plain'))
        scenes = [d['seed'] for d in self.comfy.drawn if d['size'] == story_promo.SCENE]
        self.assertEqual(len(set(scenes)), story_promo.ART_TRIES)  # each try is a new picture
        self.assertEqual(self.promo.prepare(info)['art'], 'plain')   # not again at once
        self.now += story_promo.REDRAW_AFTER
        self.comfy.fail = 0
        redrawn = self.promo.prepare(info)   # hours later the picture is tried again; the title stays
        self.assertEqual((redrawn['art'], redrawn['title']), ('comfy', record['title']))
        self.assertNotEqual(redrawn['thumb_sha'], record['thumb_sha'])

    def test_new_uploads_get_title_category_thumbnail_and_playlist_in_chapter_order(self):
        jobs = [self.job(n) for n in (1, 2, 3)]
        for job_id in jobs:
            self.promo.prepare(story_promo.episode(self.store.get(job_id)))
        # uploaded after the feature started, out of order
        self.uploaded(jobs[2], 'v3', self.now + 10)
        self.uploaded(jobs[0], 'v1', self.now + 20)
        self.uploaded(jobs[1], 'v2', self.now + 30)
        self.assertEqual(self.promo.apply_all(), 3)
        self.assertEqual(self.youtube.videos['v1']['categoryId'], '24')
        self.assertTrue(self.youtube.videos['v1']['title'].endswith('– Tập 1'))
        self.assertEqual((self.youtube.videos['v1']['description'], self.youtube.videos['v1']['tags']), ('keep me', ['a']))
        self.assertEqual(set(self.youtube.thumbs), {'v1', 'v2', 'v3'})
        self.assertEqual(list(self.youtube.playlists.values()), ['Trọng Sinh: Công Lược Khẩn Cấp'])
        self.assertEqual(self.youtube.order('PL0'), ['v1', 'v2', 'v3'])
        calls = len(self.youtube.calls)
        self.assertEqual(self.promo.apply_all(), 0)  # nothing twice
        self.assertEqual(len(self.youtube.calls), calls)

    def test_a_playlist_deleted_on_youtube_is_made_again_but_a_new_one_is_waited_for(self):
        job_id = self.job(1)
        self.promo.prepare(story_promo.episode(self.store.get(job_id)))
        self.uploaded(job_id, 'v1', self.now + 5)
        missing = {'on': True}
        original = self.youtube.__call__

        def youtube(request):
            if missing['on'] and request.url.path.endswith('/playlistItems'):
                return httpx.Response(404, json={'error': {'errors': [{'reason': 'playlistNotFound'}], 'message': 'not found'}})
            return original(request)
        self.publishing.client = httpx.Client(transport=httpx.MockTransport(youtube))
        self.promo.apply_all()
        self.assertIn('playlistNotFound', self.promo._rows()[0]['error'])
        self.assertEqual(len(self.youtube.playlists), 1)   # just made: kept, the next round tries again
        self.now += 3 * 3600
        self.promo.apply_all()                             # still missing hours later: forgotten here...
        missing['on'] = False
        self.youtube.playlists.clear()                     # ...because it is gone on YouTube
        self.now += story_promo.APPLY_RETRY + 1
        self.promo.apply_all()                             # made again, the video added
        self.assertEqual(len(self.youtube.playlists), 1)
        self.assertEqual(self.youtube.order(next(iter(self.youtube.playlists))), ['v1'])

    def test_videos_from_before_the_feature_wait_for_the_owner(self):
        old = self.job(1)
        self.promo.prepare(story_promo.episode(self.store.get(old)))
        self.uploaded(old, 'v1', self.now - 86400, state='published')
        self.uploaded(self.job(2, mode='case'), 'case', self.now + 10)   # not a story: never touched
        self.assertEqual(self.promo.apply_all(), 0)
        self.assertEqual(self.youtube.videos['v1']['title'], 'old')
        self.assertEqual(self.promo.approve_backfill('youtube:UC1', ['playlist', 'category', 'nonsense']), {'videos': 1, 'parts': ['category', 'playlist']})
        self.assertEqual(self.promo.apply_all(), 1)
        self.assertEqual((self.youtube.videos['v1']['title'], self.youtube.videos['v1']['categoryId']), ('old', '24'))
        self.assertEqual(self.youtube.thumbs, {})
        self.assertEqual(self.youtube.order('PL0'), ['v1'])
        self.assertEqual(self.youtube.videos['case']['categoryId'], '22')

    def test_title_is_written_while_a_video_runs_and_the_picture_waits_for_the_gpu(self):
        job_id = self.job(1)
        self.uploaded(job_id, 'v1', self.now + 5)
        self.promo._discover()
        other = self.job(2)   # any video being made holds the GPU, a story one too
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (other,))
        info = story_promo.episode(self.store.get(job_id))
        self.assertTrue(self.promo.prepare_next())      # the title, without the GPU
        self.assertEqual((self.promo.promo(info)['state'], self.comfy.drawn, self.comfy.freed), ('titled', [], 0))
        self.assertFalse(self.promo.prepare_next())     # the picture waits
        self.promo.apply_all()                          # the title already goes up
        self.assertTrue(self.youtube.videos['v1']['title'].endswith('– Tập 1'))
        self.assertNotIn('v1', self.youtube.thumbs)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='completed' WHERE id=?", (other,))
        self.assertTrue(self.promo.prepare_next())
        self.assertTrue(self.promo.ready(info))
        self.assertEqual(self.comfy.freed, 1)           # the GPU is given back after the episode
        self.promo.apply_all()
        self.assertIn('v1', self.youtube.thumbs)

    def test_story_uploads_use_the_entertainment_category(self):
        story, case = self.job(1), self.job(2, mode='case')
        self.assertEqual(self.publishing._category({'job_id': story}), '24')
        self.assertEqual(self.publishing._category({'job_id': case}), '22')
        self.assertEqual(self.publishing._category({'job_id': 'gone'}), '22')

    def test_channel_branding_keeps_other_settings(self):
        self.assertEqual(keywords(['truyện audio', 'trọng sinh', 'ngontinh']), '"truyện audio" "trọng sinh" ngontinh')
        got = set_branding(self.publishing, 'youtube:UC1', 'Mô tả kênh', ['truyện audio'])
        self.assertEqual(got['description'], 'Mô tả kênh')
        sent = self.youtube.branding['brandingSettings']
        self.assertEqual((sent['channel']['title'], sent['channel']['country'], sent['watch']), ('Tôi Đọc Truyện', 'VN', {'textColor': '#fff'}))


if __name__ == '__main__':
    unittest.main()
