import unittest
from videostudio.cdp_flow import FlowImages


class FlowToggleClickTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_toggle_remains_open_after_one_action(self):
        flow = FlowImages.__new__(FlowImages)
        opened = False
        actions = []

        async def evaluate(session, expression):
            nonlocal opened
            if '.click()' in expression:
                opened = not opened
                actions.append('synthetic')
            return {'x': 30, 'y': 40}

        async def native_click(session, point):
            nonlocal opened
            opened = not opened
            actions.append('native')

        flow._eval = evaluate
        flow._click_point = native_click
        await flow._click_expr('session', 'settings-locator', 'Cài đặt')
        self.assertTrue(opened, 'A second click must not close settings again')
        self.assertEqual(actions, ['native'])
