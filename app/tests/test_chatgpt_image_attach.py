"""Reference attachments for ChatGPT image requests (pose sheets): validation, upload wait, receipts."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from videostudio import cdp_images
from videostudio.cdp_images import ChatGPTImages, image_prompt, valid_attachments

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'memestudio/assets/rig/poses/sheets/ao_ba_lo_trang.png'


class AttachmentValidationTests(unittest.TestCase):
    def test_only_existing_images_inside_the_asset_folders(self):
        self.assertEqual(valid_attachments(None), [])
        self.assertEqual(valid_attachments([str(REF)]), [REF.resolve()])
        with tempfile.TemporaryDirectory() as folder:
            outside = Path(folder) / 'x.png'
            outside.write_bytes(REF.read_bytes())
            for bad in ([str(outside)], [str(REF.with_suffix('.txt'))], ['missing.png'], [], [str(REF)] * 5, 'one.png', [3]):
                with self.assertRaises(ValueError, msg=bad):
                    valid_attachments(bad)

    def test_sheet_prompt_is_landscape_and_keeps_the_marker(self):
        text = image_prompt('draw', 'abc', 'sheet')
        self.assertIn('landscape', text)
        self.assertIn('[VideoStudio image request abc]', text)
        self.assertIn('portrait 9:16', image_prompt('draw', 'abc'))
        with self.assertRaises(KeyError):
            image_prompt('draw', 'abc', 'square')


class AttachUploadTests(unittest.IsolatedAsyncioTestCase):
    def images(self, states):
        bridge = SimpleNamespace(evaluate=AsyncMock(side_effect=states),
                                 cdp=SimpleNamespace(command=AsyncMock(side_effect=self.command)))
        self.sent = []
        return ChatGPTImages(bridge, '.')

    async def command(self, method, params=None, session=None):
        self.sent.append(method)
        if method == 'Runtime.evaluate':
            return {'result': {'subtype': 'node', 'objectId': 'input-1'}}
        return {}

    async def test_waits_until_every_reference_is_uploaded(self):
        images = self.images([{'ready': True, 'count': 0, 'busy': False},
                              {'ready': True, 'count': 2, 'busy': True},
                              {'ready': True, 'count': 2, 'busy': False}])
        with patch('videostudio.cdp_images.asyncio.sleep', new=AsyncMock()):
            await images._attach('session', [REF, REF])
        self.assertEqual(self.sent, ['Runtime.evaluate', 'DOM.setFileInputFiles'])

    async def test_refuses_a_composer_that_already_holds_attachments(self):
        images = self.images([{'ready': True, 'count': 1, 'busy': False}])
        with self.assertRaisesRegex(RuntimeError, 'already holds'):
            await images._attach('session', [REF])
        self.assertEqual(self.sent, [])

    async def test_upload_that_never_finishes_sends_nothing(self):
        images = self.images([{'ready': True, 'count': 0, 'busy': False}] + [{'ready': True, 'count': 1, 'busy': True}] * 200)
        clock = iter(range(0, 10000, 5))
        with patch('videostudio.cdp_images.asyncio.sleep', new=AsyncMock()), \
                patch('videostudio.cdp_images.time.monotonic', side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(RuntimeError, 'nothing sent'):
                await images._attach('session', [REF])


class Captured(Exception):
    pass


class ReceiptIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_different_references_are_a_different_request(self):
        def prepare(job, text):
            raise Captured(text)
        images = ChatGPTImages(SimpleNamespace(journal=SimpleNamespace(prepare=prepare)), '.')
        seen = []
        for files in ([str(REF)], None):
            with self.assertRaises(Captured) as caught:
                await images.generate('00000000-0000-4000-8000-000000000000', 'same prompt', attachments=files, layout='sheet')
            seen.append(caught.exception.args[0])
        self.assertNotEqual(seen[0], seen[1])
        self.assertIn(cdp_images.digest(REF), seen[0])


if __name__ == '__main__':
    unittest.main()
