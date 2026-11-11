import asyncio, json, tempfile, time, unittest, uuid
from pathlib import Path
from unittest import mock

from PIL import Image

from videostudio.cdp_meta import MetaImages, conversation_id, valid_image_url, valid_meta_url
from videostudio.cdp_requests import IndeterminateRequest
from videostudio.core import digest


class FakeBridge:
    def __init__(self):
        self.connected = 0

    async def connect(self):
        self.connected += 1
        raise AssertionError('browser must not be touched')


class MetaImagesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.bridge = FakeBridge()
        self.meta = MetaImages(self.bridge, self.root)
        self.task = str(uuid.uuid4())

    def tearDown(self):
        self.folder.cleanup()

    def test_urls_are_checked(self):
        self.assertTrue(valid_meta_url('https://meta.ai/prompt/abc'))
        self.assertTrue(valid_meta_url('https://www.meta.ai/'))
        self.assertFalse(valid_meta_url('https://evil.example/meta.ai'))
        self.assertTrue(valid_image_url('https://scontent.xx.fbcdn.net/v/t39/x.webp?a=1'))
        self.assertFalse(valid_image_url('https://static.xx.fbcdn.net/rsrc.php/yd/r/x.webp'))
        self.assertFalse(valid_image_url('http://scontent.xx.fbcdn.net/x.webp'))
        self.assertFalse(valid_image_url('https://fbcdn.net.evil.com/x.webp'))
        self.assertEqual(conversation_id('https://meta.ai/prompt/ffb4dd86-03b4'), 'ffb4dd86-03b4')
        self.assertEqual(conversation_id('https://meta.ai/'), '')

    def test_finished_task_is_returned_without_sending_again(self):
        out = self.root / (self.task + '.png')
        Image.new('RGB', (600, 900), 'red').save(out)
        receipt = {'task_id': self.task, 'sha256': digest(out), 'file_path': str(out)}
        (self.root / (self.task + '.json')).write_text(json.dumps(receipt), encoding='utf8')
        self.assertEqual(asyncio.run(self.meta.generate(self.task, 'a cat')), receipt)
        self.assertEqual(self.bridge.connected, 0)

    def test_sent_prompt_without_conversation_is_never_resent(self):
        class Bridge(FakeBridge):
            async def connect(self):
                self.connected += 1
        self.meta.bridge = bridge = Bridge()
        self.meta._tab = mock.AsyncMock(return_value='tab')
        bridge.session = mock.AsyncMock(return_value='s')
        bridge.cdp = mock.Mock(command=mock.AsyncMock(return_value={}))
        (self.root / (self.task + '.sent.json')).write_text(json.dumps({'url': ''}), encoding='utf8')
        with self.assertRaises(IndeterminateRequest):
            asyncio.run(self.meta.generate(self.task, 'a cat'))

    def test_sends_are_at_least_twenty_seconds_apart(self):
        self.assertEqual(self.meta.interval, 20.0)
        self.meta.stamp.write_text(str(time.time() - 5))
        with mock.patch('videostudio.cdp_meta.asyncio.sleep', new=mock.AsyncMock()) as sleep:
            asyncio.run(self.meta._wait_turn())
        self.assertAlmostEqual(sleep.call_args[0][0], 15, delta=1)
        self.meta.stamp.write_text(str(time.time() - 60))
        with mock.patch('videostudio.cdp_meta.asyncio.sleep', new=mock.AsyncMock()) as sleep:
            asyncio.run(self.meta._wait_turn())
        sleep.assert_not_called()

    def test_bad_inputs_are_refused(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.meta.generate('not-a-uuid', 'a cat'))
        with self.assertRaises(ValueError):
            asyncio.run(self.meta.generate(self.task, '  '))


class MetaProviderRoutingTests(unittest.TestCase):
    def test_meta_is_an_accepted_image_provider(self):
        from videostudio.core import validate_request as validate
        try:
            request = validate({'idea': 'Một chủ đề thử', 'voice_id': 'x', 'duration_seconds': 45, 'image_provider': 'meta'})
        except ValueError as error:
            self.assertNotIn('image_provider', str(error))
        else:
            self.assertEqual(request['image_provider'], 'meta')


if __name__ == '__main__':
    unittest.main()
