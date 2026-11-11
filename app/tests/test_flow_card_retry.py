import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from videostudio.cdp_flow import FlowImages, FlowTaskError

TASK = '11111111-2222-3333-4444-555555555555'


async def instant(_):
    return None


class FakeFlow(FlowImages):
    """A Flow page scripted frame by frame: each poll reads one (images, failed card, notice) step."""

    def __init__(self, folder, steps):
        super().__init__(type('Bridge', (), {})(), Path(folder))
        self.steps, self.k, self.clicks = steps, 0, 0
        self.RETRY_SETTLE_SECONDS = 0.0

    async def _snapshot(self, session, prompt=''):
        step = self.steps[min(self.k, len(self.steps) - 1)]
        return {'largeImages': step.get('images', [])}

    async def _eval(self, session, expression, timeout=8):
        step = self.steps[min(self.k, len(self.steps) - 1)]
        if 'flow-grid-tile-container' in expression:
            self.k += 1
            return step.get('failed')
        return step.get('notice', '')

    async def _click_point(self, session, point):
        self.clicks += 1


RETRY = {'x': 5, 'y': 6, 'tile': 't9', 'text': 'Không tạo được', 'retry': True}


class FailedCardTests(unittest.IsolatedAsyncioTestCase):
    async def wait(self, flow, receipt=None, timeout=30):
        with patch('videostudio.cdp_flow.asyncio.sleep', instant):
            return await flow._wait_new_media('s', TASK, receipt if receipt is not None else {'baseline_tile_ids': ['old']}, ['old-media'], timeout, 'p')

    async def test_blocked_card_is_retried_once_and_the_new_picture_is_taken(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = FakeFlow(folder, [{'failed': RETRY}, {'failed': None}, {'images': [{'media_id': 'new'}]}])
            receipt = {'task_id': TASK, 'baseline_tile_ids': ['old']}
            state = await self.wait(flow, receipt)
            self.assertEqual(state['largeImages'], [{'media_id': 'new'}])
            self.assertEqual(flow.clicks, 1)
            self.assertEqual([r['tile'] for r in receipt['card_retries']], ['t9'])

    async def test_a_second_failure_after_the_retry_is_blocked_at_once(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = FakeFlow(folder, [{'failed': RETRY}, {'failed': None}, {'failed': RETRY}])
            receipt = {'task_id': TASK, 'baseline_tile_ids': ['old']}
            with self.assertRaises(FlowTaskError) as caught:
                await self.wait(flow, receipt)
            self.assertEqual(caught.exception.code, 'flow_blocked')
            self.assertEqual(flow.clicks, 1)  # never a second retry
            self.assertEqual((receipt['stage'], receipt['blocked_confirmed']), ('blocked', True))
            self.assertEqual(flow._read_receipt(TASK)['stage'], 'blocked')

    async def test_a_failed_card_without_a_retry_button_is_blocked_without_clicking(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = FakeFlow(folder, [{'failed': {'x': None, 'y': None, 'tile': 't', 'text': 'Vi phạm chính sách', 'retry': False}}])
            with self.assertRaises(FlowTaskError) as caught:
                await self.wait(flow)
            self.assertEqual(caught.exception.code, 'flow_blocked')
            self.assertEqual(flow.clicks, 0)

    async def test_a_retry_already_pressed_by_an_earlier_call_is_not_pressed_again(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = FakeFlow(folder, [{'failed': RETRY}])
            with self.assertRaises(FlowTaskError):
                await self.wait(flow, {'baseline_tile_ids': [], 'card_retries': [{'tile': 't9'}]})
            self.assertEqual(flow.clicks, 0)

    async def test_rate_limit_notice_and_timeout_are_reported_as_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = FakeFlow(folder, [{'notice': 'You are requesting too quickly'}])
            with self.assertRaises(FlowTaskError) as caught:
                await self.wait(flow)
            self.assertEqual(caught.exception.code, 'flow_blocked')
        with tempfile.TemporaryDirectory() as folder:
            flow = FakeFlow(folder, [{}])
            with self.assertRaises(FlowTaskError) as caught:
                await self.wait(flow, timeout=0.0)
            self.assertEqual(caught.exception.code, 'flow_blocked')
            self.assertIn('chưa có ảnh', str(caught.exception))



class FailedCardBaselineTests(unittest.TestCase):
    def test_failed_cards_already_on_the_grid_are_counted_not_mistaken_for_the_new_scene(self):
        tiles = [{'media_id': None, 'text': 'warning Không thành công Chúng tôi nhận thấy có hoạt động bất thường'},
                 {'media_id': 'm1', 'text': ''}, {'media_id': None, 'text': 'trial_lan accessibility_new'}]
        self.assertEqual(FlowImages._failed_card_count(tiles), 1)
        self.assertIn('BASELINE', FlowImages.FAILED_CARD)


class CharacterPortraitTests(unittest.IsolatedAsyncioTestCase):
    """The Character page shows the same "Không thành công" panel; it gets one retry, then it is reported blocked."""

    def flow(self, folder, steps):
        flow = FlowImages(type('Bridge', (), {})(), Path(folder))
        flow.RETRY_SETTLE_SECONDS = 0.0
        flow.clicks = 0
        state = {'k': 0}

        async def evaluate(session, expression, timeout=8):
            step = steps[min(state['k'], len(steps) - 1)]
            if expression is FlowImages.CHARACTER_FAILED:
                state['k'] += 1
                return step.get('failed')
            return {'complete': step.get('done', False), 'hasImg': step.get('done', False)}

        async def click(session, point):
            flow.clicks += 1
        flow._eval = evaluate
        flow._click_point = click
        return flow

    async def wait(self, flow, receipt):
        with patch('videostudio.cdp_flow.asyncio.sleep', instant):
            return await flow._wait_character_complete('s', 30, task_id=TASK, receipt=receipt)

    async def test_failed_portrait_is_retried_once_and_then_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = self.flow(folder, [{'failed': RETRY}, {}, {'done': True}])
            receipt = {'task_id': TASK}
            self.assertTrue(await self.wait(flow, receipt))
            self.assertEqual((flow.clicks, len(receipt['card_retries'])), (1, 1))

    async def test_failing_again_reports_blocked_instead_of_waiting_fifteen_minutes(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = self.flow(folder, [{'failed': RETRY}, {}, {'failed': RETRY}])
            receipt = {'task_id': TASK}
            with self.assertRaises(FlowTaskError) as caught:
                await self.wait(flow, receipt)
            self.assertEqual(caught.exception.code, 'flow_blocked')
            self.assertEqual(flow.clicks, 1)
            self.assertTrue(receipt['blocked_confirmed'])

if __name__ == '__main__':
    unittest.main()
