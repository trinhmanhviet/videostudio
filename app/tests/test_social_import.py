import json
import tempfile
import unittest
from pathlib import Path

from videostudio.cdp_social import valid_post_url
from videostudio.core import Store
from videostudio.social_import import SocialImports, compose_idea

POST = 'https://www.facebook.com/share/p/18uZ5VUDB3/'
FOUND = [{'url': f'https://upload.wikimedia.org/photo-{i}.jpg', 'mo_ta': f'ảnh thật {i}', 'trang': f'https://example.com/{i}'} for i in range(3)]


def jpeg(color=(30, 120, 200)):
    import io
    from PIL import Image
    data = io.BytesIO()
    picture = Image.new('RGB', (800, 600), color)
    picture.paste((10, 10, 10), (0, 0, 200, 600))
    picture.save(data, format='JPEG')
    return data.getvalue()


class Response:
    def __init__(self, status, data=None, content=b'', kind='application/json'):
        self.status_code, self._data, self.content, self.headers = status, data, content, {'content-type': kind}

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data


class FakeHttp:
    """The daemon (read + chat) and the picture CDN."""
    def __init__(self, folder):
        self.folder, self.calls, self.answer = Path(folder), [], None

    def post(self, url, json=None, **kwargs):
        self.calls.append((url, json))
        if url.endswith('/api/social/read'):
            frame = self.folder / 'frame-1.jpg'
            frame.write_bytes(b'jpg')
            return Response(200, {'ok': True, 'data': {
                'text': 'Thuyết âm mưu về Jensen Huang…', 'title': 'Tinhte.vn - Thuyết âm mưu', 'author': 'Tinhte.vn', 'url': POST,
                'images': ['https://scontent.fbcdn.net/a.jpg', 'https://scontent.fbcdn.net/b.gif'], 'frames': [str(frame)]}})
        if url.endswith('/api/chat'):
            return Response(200, {'ok': True, 'data': self.answer or {'your_response': {
                'tieu_de': 'Jensen Huang và thuyết âm mưu', 'y_tuong': 'Kể lại vì sao CEO NVIDIA mất ghế.',
                'anh': ['Ảnh Jensen Huang trên sân khấu'], 'kiem_chung': [{'thong_tin': 'Mất ghế CEO', 'ket_qua': 'chưa kiểm chứng'}],
                'nguon': ['https://example.com/tin'], 'anh_tim_duoc': FOUND + [{'url': 'https://example.com/page.html'}]}}})
        return Response(404, {})

    def get(self, url, **kwargs):
        if url.endswith('.gif'):
            return Response(200, content=b'GIF', kind='image/gif')
        if url.endswith('.html'):
            return Response(200, content=b'<html>', kind='text/html')
        return Response(200, content=jpeg(), kind='image/jpeg')


class FakeFactory:
    def __init__(self):
        self.batches = []

    def create_batch(self, data, key, scope=None):
        self.batches.append((data, key, scope))
        return {'id': 'batch-1'}


class SocialImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(Path(self.tmp, 'jobs.db'), Path(self.tmp, 'out'))
        self.http, self.factory = FakeHttp(self.tmp), FakeFactory()
        self.imports = SocialImports(self.store, self.factory, root=Path(self.tmp, 'posts'), http=self.http)
        self.imports.kick = lambda: None  # run the steps by hand

    def test_only_facebook_links(self):
        self.assertEqual(valid_post_url(POST + ' '), POST)
        for bad in ('http://www.facebook.com/x', 'https://evil.com/facebook.com', 'https://facebook.com.evil.com/p', 12):
            with self.assertRaises(ValueError):
                valid_post_url(bad)
        with self.assertRaises(ValueError):
            self.imports.start(POST, {'defaults': {}, 'items': []})  # the items come from the post, not the page

    def test_post_becomes_an_idea_video_in_the_queue(self):
        item = self.imports.start(POST, {'project': 'x', 'style': 'case', 'defaults': {'voice_id': 'v', 'duration_seconds': 180}, 'auto_name': True})
        self.assertEqual(item['state'], 'queued')
        self.imports.process(item['id'])
        done = self.imports.get(item['id'])
        self.assertEqual((done['state'], done['pictures'], done['frames'], done['author']), ('done', 1, 1, 'Tinhte.vn'))  # the GIF is skipped
        chat = next(body for url, body in self.http.calls if url.endswith('/api/chat'))
        self.assertEqual(len(chat['attachments']), 2)  # one video frame first, then the picture
        self.assertTrue(chat['attachments'][0].endswith('frame-1.jpg'))
        self.assertIn('Thuyết âm mưu về Jensen Huang', chat['prompt'])
        data, key, scope = self.factory.batches[0]
        self.assertEqual((data['input_mode'], data['style'], data['project'], key), ('idea', 'case', 'Jensen Huang và thuyết âm mưu', 'social-' + item['id']))
        self.assertNotIn('auto_name', data)
        # real pictures instead of drawn ones: 3 found on the web + the post's own picture
        self.assertEqual((data['defaults']['image_provider'], data['defaults']['image_pool'], data['defaults']['flow_batch_size']), ('pool', item['id'], 1))
        self.assertEqual(done['state'], 'done')
        self.assertEqual(self.imports.get(item['id'])['real_pictures'], 4)
        from videostudio.image_pool import load_pool
        pool = load_pool(item['id'], root=Path(self.tmp, 'posts'))
        self.assertEqual([p['kind'] for p in pool], ['web', 'web', 'web', 'post'])
        self.assertEqual(pool[0]['nguon'], 'https://example.com/0')
        idea = data['items'][0]['text']
        for part in ('Kể lại vì sao CEO NVIDIA mất ghế.', 'Ảnh Jensen Huang trên sân khấu', 'tin nóng có kịch tính', POST):
            self.assertIn(part, idea)
        # the fact-check list is for the user only: handed to the script writer it became a disclaimer every few lines
        self.assertNotIn('chưa kiểm chứng', idea)
        self.assertNotIn('Kiểm chứng:', idea)

    def test_with_too_few_real_pictures_the_video_draws_its_scenes(self):
        self.http.answer = {'your_response': {'tieu_de': 'T', 'y_tuong': 'Ý tưởng', 'anh_tim_duoc': FOUND[:1]}}
        item = self.imports.start(POST, {'defaults': {'voice_id': 'v', 'image_provider': 'meta', 'meta_batch_size': 8}})
        self.imports.process(item['id'])
        defaults = self.factory.batches[0][0]['defaults']
        self.assertEqual((defaults['image_provider'], defaults.get('meta_batch_size')), ('meta', 8))   # the page's own setting
        self.assertNotIn('image_pool', defaults)
        self.assertEqual(self.imports.get(item['id'])['real_pictures'], 2)

    def test_a_picture_refused_to_the_plain_download_is_fetched_through_chrome(self):
        refused = 'https://site.example/blocked.jpg'
        self.http.answer = {'your_response': {'tieu_de': 'T', 'y_tuong': 'Ý tưởng', 'anh_tim_duoc': FOUND[:2] + [{'url': refused, 'mo_ta': 'ảnh bị chặn'}]}}
        original_get, original_post = self.http.get, self.http.post

        def get(url, **kwargs):
            return Response(403, content=b'', kind='text/plain') if url == refused else original_get(url, **kwargs)

        def post(url, json=None, **kwargs):
            if url.endswith('/api/social/fetch-images'):
                self.http.calls.append((url, json))
                path = Path(self.tmp, 'fetched.jpg')
                path.write_bytes(jpeg((200, 30, 30)))
                return Response(200, {'ok': True, 'data': [{'url': refused, 'path': str(path)}]})
            return original_post(url, json=json, **kwargs)
        self.http.get, self.http.post = get, post
        item = self.imports.start(POST, {'defaults': {'voice_id': 'v'}})
        self.imports.process(item['id'])
        fetch = [body for url, body in self.http.calls if url.endswith('/api/social/fetch-images')]
        self.assertEqual(fetch, [{'task_id': item['id'], 'urls': [refused]}])   # only the refused one, in one call
        from videostudio.image_pool import load_pool
        self.assertIn('ảnh bị chặn', [p['mo_ta'] for p in load_pool(item['id'], root=Path(self.tmp, 'posts'))])
        self.assertEqual(self.imports.get(item['id'])['real_pictures'], 4)   # 2 direct + 1 through Chrome + the post's own

    def test_a_missing_answer_fails_with_a_reason_and_the_next_import_still_runs(self):
        self.http.answer = {'your_response': {'tieu_de': 'x'}}
        first = self.imports.start(POST, {'defaults': {}})
        second = self.imports.start(POST, {'defaults': {}})
        self.imports._run()
        self.assertEqual(self.imports.get(first['id'])['state'], 'failed')
        self.assertIn('ChatGPT', self.imports.get(first['id'])['error'])
        self.assertEqual(self.imports.get(second['id'])['state'], 'failed')  # processed, not stuck behind the first
        self.assertEqual(self.factory.batches, [])

    def test_a_busy_chatgpt_is_waited_for_not_reported_as_an_error(self):
        import httpx
        calls = []

        def busy_then_answer(route, payload, timeout):
            calls.append(route)
            if len(calls) < 3:
                raise httpx.ReadTimeout('busy with a story chapter')
            return {'your_response': {'y_tuong': 'ok'}}
        self.imports._post = busy_then_answer
        self.assertEqual(self.imports._chat({'prompt': 'p'}, pause=0), {'your_response': {'y_tuong': 'ok'}})
        self.assertEqual(len(calls), 3)

        def always_busy(route, payload, timeout):
            raise httpx.ReadTimeout('busy')
        self.imports._post = always_busy
        with self.assertRaisesRegex(RuntimeError, 'ChatGPT bận'):
            self.imports._chat({'prompt': 'p'}, attempts=2, pause=0)

    def test_a_page_not_ready_yet_is_retried_because_nothing_was_sent(self):
        calls = []

        def not_ready_then_answer(route, payload, timeout):
            calls.append(route)
            if len(calls) == 1:
                raise RuntimeError('ChatGPT High reasoning control unavailable; no request sent')
            return {'your_response': {'y_tuong': 'ok'}}
        self.imports._post = not_ready_then_answer
        self.assertEqual(self.imports._chat({'prompt': 'p'}, pause=0), {'your_response': {'y_tuong': 'ok'}})

        def other_error(route, payload, timeout):
            calls.append('other')
            raise RuntimeError('Chrome riêng cần đăng nhập ChatGPT.')
        calls.clear()
        self.imports._post = other_error
        with self.assertRaisesRegex(RuntimeError, 'đăng nhập'):
            self.imports._chat({'prompt': 'p'}, pause=0)
        self.assertEqual(calls, ['other'])   # not retried

    def test_author_without_the_badge_text(self):
        from videostudio.cdp_social import clean_author
        self.assertEqual(clean_author('Tinhte.vn Verified account'), 'Tinhte.vn')
        self.assertEqual(clean_author('Báo Mới\nTài khoản đã xác minh'), 'Báo Mới')
        self.assertEqual(clean_author(None), '')

    def test_compose_idea_keeps_it_readable(self):
        idea = compose_idea({'tieu_de': 'T', 'y_tuong': 'Ý', 'nguon': ['a', '']}, {'author': ''}, POST)
        self.assertEqual(idea.splitlines()[0], 'T')
        self.assertIn('một câu ngắn', idea)   # unconfirmed claims: said once, not repeated
        self.assertTrue(idea.endswith(POST))


if __name__ == '__main__':
    unittest.main()


class RouteTests(unittest.TestCase):
    def test_the_page_can_start_an_import_and_list_it(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from videostudio.social_import import register_social_routes
        tmp = tempfile.mkdtemp()
        store = Store(Path(tmp, 'jobs.db'), Path(tmp, 'out'))
        app = FastAPI()
        imports = register_social_routes(app, store, FakeFactory(), lambda request: None)
        imports.kick = lambda: None
        client = TestClient(app)
        started = client.post('/api/social/imports', json={'url': POST, 'batch': {'style': 'news', 'defaults': {'voice_id': 'v'}}})
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()['state'], 'queued')
        self.assertEqual(client.post('/api/social/imports', json={'url': 'https://evil.com/x', 'batch': {'defaults': {}}}).status_code, 422)
        self.assertEqual([i['id'] for i in client.get('/api/social/imports').json()['items']], [started.json()['id']])
