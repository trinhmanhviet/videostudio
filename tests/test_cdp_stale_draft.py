import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from videostudio.cdp_daemon import ChromeChatGPTBridge
from videostudio.cdp_requests import RequestJournal


class StaleDraftTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = ChromeChatGPTBridge(journal=RequestJournal(Path(self.tmp.name) / 'journal.db'))
        self.bridge.cdp = MagicMock()
        self.bridge.cdp.command = AsyncMock(return_value={})

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_only_an_answered_copy_of_our_own_prompt_is_stale(self):
        done = self.bridge.journal.prepare('job', 'old prompt')
        self.bridge.journal.complete(done['id'], {'ok': True})
        pending = self.bridge.journal.prepare('job', 'pending prompt')
        self.assertTrue(self.bridge.stale_own_draft(f"[VideoStudio request {done['id']}]\nold prompt"))
        self.assertTrue(self.bridge.stale_own_draft(f"  [VideoStudio image request {done['id']}] apple"))
        # Not yet answered, unknown to the journal, or the owner's own text: never cleared.
        self.assertFalse(self.bridge.stale_own_draft(f"[VideoStudio request {pending['id']}]\npending prompt"))
        self.assertFalse(self.bridge.stale_own_draft('[VideoStudio request ' + 'a' * 64 + ']'))
        self.assertFalse(self.bridge.stale_own_draft('Ghi chú của tôi [VideoStudio request ' + done['id'] + ']'))
        self.assertFalse(self.bridge.stale_own_draft(''))

    async def test_clear_composer_selects_all_and_deletes_with_trusted_keys(self):
        self.bridge.evaluate = AsyncMock(return_value=True)
        await self.bridge.clear_composer('session')
        keys = [(c.args[1]['key'], c.args[1].get('modifiers', 0)) for c in self.bridge.cdp.command.call_args_list
                if c.args[0] == 'Input.dispatchKeyEvent' and c.args[1]['type'] == 'keyDown']
        self.assertEqual(keys, [('a', 2), ('Backspace', 0)])

    async def test_clear_composer_refuses_without_a_composer(self):
        self.bridge.evaluate = AsyncMock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, 'Composer unavailable'):
            await self.bridge.clear_composer('session')
        self.assertEqual(self.bridge.cdp.command.await_count, 0)


if __name__ == '__main__':
    unittest.main()
