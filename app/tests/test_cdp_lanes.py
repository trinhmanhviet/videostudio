"""ChatGPT lanes: the video, every story being edited and Facebook analyses each have their own tab and run side by side."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from videostudio.cdp_daemon import ChromeChatGPTBridge, lane_of
from videostudio.cdp_requests import RequestJournal


class LaneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = ChromeChatGPTBridge(launcher=MagicMock(), journal=RequestJournal(Path(self.tmp.name) / 'db'))

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_lane_of(self):
        self.assertEqual(lane_of('story-5e01b022c6-chapter-038-0'), 'story-5e01b022c6')
        self.assertEqual(lane_of('story-77aa-fix-002-1'), 'story-77aa')
        self.assertEqual(lane_of('social-9f3c'), 'social')
        for job in ('3f2a6c1e-0000-4000-8000-000000000000', '__login__', '__acceptance__', 'story-not-hex'):
            self.assertEqual(lane_of(job), 'video')
        self.assertIs(self.bridge.lock_for('video'), self.bridge.job_lock)
        self.assertIs(self.bridge.lock_for('social'), self.bridge.lock_for('social'))
        self.assertIsNot(self.bridge.lock_for('social'), self.bridge.job_lock)

    async def test_a_side_lane_opens_its_own_background_tab_and_leaves_a_busy_lane_tab_open(self):
        self.bridge.lane_targets['video'] = 'video-tab'
        self.bridge.lane_used['video'] = time.time()          # used a moment ago: still needed
        self.bridge.journal.own_target('video-tab', 'text')
        self.bridge.journal.set_conversation('video-job', 'https://chatgpt.com/', 'video-tab')
        self.bridge.cdp = MagicMock()
        self.bridge.cdp.command = AsyncMock(side_effect=[
            {'targetInfos': [{'targetId': 'video-tab', 'url': 'https://chatgpt.com/', 'type': 'page'},
                             {'targetId': 'idle-tab', 'url': 'https://chatgpt.com/c/old', 'type': 'page'}]},
            {'targetId': 'story-tab'}, {}])
        self.assertEqual(await self.bridge.ensure_tab('story-abc123-chapter-001-0'), 'story-tab')
        create = next(c for c in self.bridge.cdp.command.call_args_list if c.args[0] == 'Target.createTarget')
        self.assertTrue(create.args[1]['background'])
        closed = [c.args[1]['targetId'] for c in self.bridge.cdp.command.call_args_list if c.args[0] == 'Target.closeTarget']
        self.assertEqual(closed, ['idle-tab'])                  # never the video lane's tab
        self.assertEqual(self.bridge.lane_targets['story-abc123'], 'story-tab')

    def fake_cdp(self, tabs, created='new-tab'):
        """A CDP connection answering by method; records every call."""
        calls = []

        async def command(method, params=None, session=None):
            calls.append((method, params or {}))
            if method == 'Target.getTargets':
                return {'targetInfos': [{'targetId': t, 'url': u, 'type': 'page'} for t, u in tabs.items()]}
            if method == 'Target.attachToTarget':
                return {'sessionId': 'session-' + params['targetId']}
            if method == 'Target.createTarget':
                return {'targetId': created}
            if method == 'Runtime.evaluate':   # the new chat page has loaded
                return {'result': {'value': {'path': '/', 'ready': 'complete', 'composer': True, 'draft': 0}}}
            return {}
        self.bridge.cdp = MagicMock()
        self.bridge.cdp.command = command
        return calls

    async def test_each_chapter_starts_a_new_chat_in_its_story_tab(self):
        self.bridge.lane_targets['story-abc'] = 'story-tab'
        calls = self.fake_cdp({'story-tab': 'https://chatgpt.com/c/chapter-41'})
        self.assertEqual(await self.bridge.ensure_tab('story-abc-chapter-042-0'), 'story-tab')
        self.assertIn(('Page.navigate', {'url': 'https://chatgpt.com/'}), calls)
        self.assertEqual(self.bridge.journal.conversation('story-abc-chapter-042-0')['url'], 'https://chatgpt.com/')
        self.assertFalse(any(m == 'Target.createTarget' for m, _ in calls))

    async def test_the_new_chat_page_is_awaited_not_the_old_one_read(self):
        pages = iter([{'path': '/c/chapter-41', 'ready': 'complete', 'composer': True},   # still the old page
                      {'path': '/', 'ready': 'loading', 'composer': False},
                      {'path': '/', 'ready': 'complete', 'composer': True}])
        seen = []

        async def evaluate(session, expression):
            value = next(pages)
            seen.append(value['path'])
            return value
        self.bridge.evaluate = evaluate
        self.assertTrue(await self.bridge.settle_new_chat('session', timeout=10))
        self.assertEqual(seen, ['/c/chapter-41', '/', '/'])
        self.bridge.evaluate = AsyncMock(return_value={'path': '/c/old', 'ready': 'complete', 'composer': True})
        self.assertFalse(await self.bridge.settle_new_chat('session', timeout=1.2))

    async def test_a_tab_waiting_for_an_unknown_conversation_is_never_navigated_away(self):
        record = self.bridge.journal.prepare('story-abc-chapter-041-0', 'prompt')
        with self.bridge.journal.db() as c:
            c.execute("UPDATE requests SET state='sending' WHERE id=?", (record['id'],))
        self.bridge.journal.set_conversation('story-abc-chapter-041-0', 'https://chatgpt.com/', 'story-tab')
        self.bridge.lane_targets['story-abc'] = 'story-tab'
        calls = self.fake_cdp({'story-tab': 'https://chatgpt.com/'}, created='second-tab')
        self.assertEqual(await self.bridge.ensure_tab('story-abc-fix-041-0'), 'second-tab')
        self.assertFalse(any(m == 'Page.navigate' for m, _ in calls))
        self.assertFalse(any(m == 'Target.closeTarget' and p.get('targetId') == 'story-tab' for m, p in calls))

    async def test_a_retried_chapter_goes_back_to_its_own_conversation(self):
        record = self.bridge.journal.prepare('story-abc-chapter-041-0', 'prompt')
        self.bridge.journal.claim_send(record['id'])                               # it was sent
        self.bridge.journal.set_conversation('story-abc-chapter-041-0', 'https://chatgpt.com/c/chapter-41', 'story-tab')
        self.bridge.lane_targets['story-abc'] = 'story-tab'
        calls = self.fake_cdp({'story-tab': 'https://chatgpt.com/c/chapter-41'})
        self.assertEqual(await self.bridge.ensure_tab('story-abc-chapter-041-0'), 'story-tab')
        self.assertFalse(any(m in ('Page.navigate', 'Target.createTarget') for m, _ in calls))

    async def test_a_chapter_noted_but_never_sent_starts_a_new_chat(self):
        self.bridge.journal.prepare('story-abc-chapter-073-0', 'prompt')          # prepared, not sent
        self.bridge.journal.set_conversation('story-abc-chapter-073-0', 'https://chatgpt.com/c/chapter-72', 'story-tab')
        self.bridge.lane_targets['story-abc'] = 'story-tab'
        calls = self.fake_cdp({'story-tab': 'https://chatgpt.com/c/chapter-72'})
        self.assertEqual(await self.bridge.ensure_tab('story-abc-chapter-073-0'), 'story-tab')
        self.assertIn(('Page.navigate', {'url': 'https://chatgpt.com/'}), calls)

    async def test_the_video_lane_keeps_its_conversation(self):
        self.bridge.journal.own_target('video-tab', 'text')
        self.bridge.journal.set_conversation('earlier', 'https://chatgpt.com/c/video', 'video-tab')
        calls = self.fake_cdp({'video-tab': 'https://chatgpt.com/c/video'})
        self.assertEqual(await self.bridge.ensure_tab('3f2a6c1e-0000-4000-8000-000000000000'), 'video-tab')
        self.assertFalse(any(m == 'Page.navigate' for m, _ in calls))

    async def test_an_idle_lane_tab_is_closed_after_a_while(self):
        self.bridge.lane_targets['social'] = 'social-tab'
        self.bridge.lane_used['social'] = time.time() - 3600
        self.assertNotIn('social-tab', self.bridge.busy_targets())
        self.bridge.lane_used['social'] = time.time()
        self.assertIn('social-tab', self.bridge.busy_targets())
        self.bridge.on_event({'method': 'Target.targetDestroyed', 'params': {'targetId': 'social-tab'}})
        self.assertNotIn('social', self.bridge.lane_targets)

    async def test_lanes_run_side_by_side_but_one_request_at_a_time_inside_a_lane(self):
        running, overlap = set(), []

        async def fake(job, prompt, timeout, files):
            lane = lane_of(job)
            overlap.append(set(running))
            running.add(lane)
            await asyncio.sleep(0.05)
            running.discard(lane)
            return {'job': job}
        self.bridge._ask_in_lane = fake
        await asyncio.gather(self.bridge.ask_chatgpt('story-aa-chapter-001-0', 'p1'), self.bridge.ask_chatgpt('social-1', 'p2'),
                             self.bridge.ask_chatgpt('video-job', 'p3'))
        self.assertTrue(any(seen for seen in overlap))          # different lanes were running at the same time
        running.clear(); overlap.clear()
        await asyncio.gather(self.bridge.ask_chatgpt('story-aa-chapter-001-0', 'p1'), self.bridge.ask_chatgpt('story-aa-chapter-002-0', 'p2'))
        self.assertTrue(all('story-aa' not in seen for seen in overlap))   # the same story: one chapter after the other

    async def test_a_typing_turn_held_too_long_fails_clearly_without_sending(self):
        from videostudio import cdp_daemon
        self.bridge.connect = AsyncMock()
        self.bridge._send_prompt = AsyncMock()
        await self.bridge.compose_lock.acquire()          # another tab is stuck in its typing turn
        original = cdp_daemon.COMPOSE_WAIT
        cdp_daemon.COMPOSE_WAIT = 0.05
        try:
            with self.assertRaisesRegex(RuntimeError, 'nothing sent'):
                await self.bridge.ask_chatgpt('story-ab-chapter-001-0', 'prompt')
        finally:
            cdp_daemon.COMPOSE_WAIT = original
            self.bridge.compose_lock.release()
        self.bridge._send_prompt.assert_not_awaited()
        self.assertFalse(self.bridge.lock_for('story-ab').locked())   # the lane is free again for the retry
        record = self.bridge.journal.prepare('story-ab-chapter-001-0', 'prompt')
        self.assertEqual(record['state'], 'prepared')     # never marked as sent: asking again may send it

    async def empty_answer(self, job):
        """A sent request whose finished turn stays empty, also after the page reload."""
        from videostudio import cdp_daemon
        record = self.bridge.journal.prepare(job, 'prompt')
        self.bridge.journal.claim_send(record['id'])
        self.bridge.journal.set_conversation(job, 'https://chatgpt.com/c/empty', 'tab')
        self.bridge.connect = AsyncMock()
        self.bridge.ensure_tab = AsyncMock(return_value='tab')
        self.bridge.session = AsyncMock(return_value='session')
        self.bridge.cdp = MagicMock()
        self.bridge.cdp.command = AsyncMock(return_value={})
        marker = '[VideoStudio request ' + record['id'] + ']'
        self.bridge.evaluate = AsyncMock(return_value={'url': 'https://chatgpt.com/c/empty', 'matched': False, 'turns': [
            {'user': marker + ' prompt', 'assistant': '', 'state': 'complete', 'id': 'm1'}]})
        # only the daemon's own waits are shortened; time and asyncio stay real for every other test
        patches = [mock.patch.object(cdp_daemon, 'EMPTY_WAIT', 0.05), mock.patch.object(cdp_daemon, 'EMPTY_RELOAD_PAUSE', 0)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return record

    async def test_an_empty_story_answer_is_reloaded_once_then_asked_again_in_a_new_chat(self):
        record = await self.empty_answer('story-ab-chapter-077-0')
        with self.assertRaisesRegex(RuntimeError, 'asked again'):
            await self.bridge.ask_chatgpt('story-ab-chapter-077-0', 'prompt', timeout_seconds=600)
        reloads = [c for c in self.bridge.cdp.command.call_args_list if c.args[0] == 'Page.reload']
        self.assertEqual(len(reloads), 1)
        self.assertEqual(self.bridge.journal.get(record['id'])['state'], 'prepared')   # the retry sends it again
        self.assertIsNone(self.bridge.journal.conversation('story-ab-chapter-077-0'))   # ...in a new chat

    async def test_an_empty_video_answer_is_never_resent(self):
        from videostudio.cdp_requests import IndeterminateRequest
        record = await self.empty_answer('3f2a6c1e-0000-4000-8000-000000000000')
        with self.assertRaises(IndeterminateRequest):
            await self.bridge.ask_chatgpt('3f2a6c1e-0000-4000-8000-000000000000', 'prompt', timeout_seconds=600)
        self.assertEqual(self.bridge.journal.get(record['id'])['state'], 'sending')

    async def test_side_lanes_are_capped(self):
        from videostudio import cdp_daemon
        peak, now = [0], [0]

        async def fake(job, prompt, timeout, files):
            now[0] += 1; peak[0] = max(peak[0], now[0])
            await asyncio.sleep(0.03)
            now[0] -= 1
        self.bridge._ask_in_lane = fake
        await asyncio.gather(*(self.bridge.ask_chatgpt(f'story-{i:02x}-chapter-001-0', 'p') for i in range(cdp_daemon.SIDE_LANES + 3)))
        self.assertEqual(peak[0], cdp_daemon.SIDE_LANES)


class ParallelEditTests(unittest.TestCase):
    def test_two_stories_may_be_edited_at_once(self):
        from videostudio import story_api
        self.assertEqual(story_api.PARALLEL_EDITS, 2)

    def test_dedicated_chrome_keeps_background_tabs_running(self):
        from videostudio.chrome_browser import BrowserConfig
        debug = BrowserConfig(profile=Path('data/test-profile')).arguments('debug')
        for flag in ('--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'):
            self.assertIn(flag, debug)
        self.assertNotIn('--disable-renderer-backgrounding', BrowserConfig(profile=Path('data/test-profile')).arguments('clean'))


if __name__ == '__main__':
    unittest.main()


class ReplyParsingTests(unittest.TestCase):
    def test_a_plain_text_reply_with_real_line_breaks_in_a_chapter_is_accepted(self):
        from videostudio.exchanges import parse_reply
        reply = '{\n  "request_id": "x",\n  "result": {"your_response": {"noi_dung": "Sáng sớm hôm sau.\n\nBiệt thự nhà họ Hoắc."}}\n}'
        self.assertEqual(parse_reply(reply)['result']['your_response']['noi_dung'], 'Sáng sớm hôm sau.\n\nBiệt thự nhà họ Hoắc.')
