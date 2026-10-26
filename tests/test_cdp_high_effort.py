import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from videostudio.cdp_daemon import ChromeChatGPTBridge
from videostudio.cdp_requests import RequestJournal


class HighEffortTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = ChromeChatGPTBridge(journal=RequestJournal(Path(self.tmp.name) / 'journal.db'))
        self.bridge.cdp = MagicMock()
        self.bridge.cdp.command = AsyncMock(return_value={})

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_sets_slider_to_max_and_verifies_high_before_send(self):
        self.bridge.evaluate = AsyncMock(side_effect=[
            {'high': False, 'button': {'x': 10, 'y': 20}},
            {'slider': {'track': {'x': 100, 'y': 30, 'width': 80}, 'value': 0, 'max': 2}},
            {'high': True, 'value': 2, 'max': 2},
        ])
        await self.bridge.ensure_high_effort('session')
        clicks = [c.args[1] for c in self.bridge.cdp.command.call_args_list
                  if c.args[0] == 'Input.dispatchMouseEvent']
        self.assertEqual(len(clicks), 4)
        self.assertEqual({(c['x'], c['y']) for c in clicks}, {(10, 20), (178, 30)})
        self.assertEqual(self.bridge.evaluate.await_count, 3)

    async def test_refuses_when_high_cannot_be_verified(self):
        self.bridge.evaluate = AsyncMock(side_effect=[
            {'high': False, 'button': {'x': 10, 'y': 20}},
            {'slider': {'track': {'x': 100, 'y': 30, 'width': 80}, 'value': 0, 'max': 2}},
            {'high': False, 'value': 1, 'max': 2},
        ])
        with self.assertRaisesRegex(RuntimeError, 'High'):
            await self.bridge.ensure_high_effort('session')
        self.assertEqual(self.bridge.evaluate.await_count, 3)


if __name__ == '__main__':
    unittest.main()
