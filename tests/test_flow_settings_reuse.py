import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from videostudio.cdp_flow import FlowImages

class FlowSettingsReuseTests(unittest.IsolatedAsyncioTestCase):
    def flow(self):
        flow=FlowImages(object(),Path('unused'))
        flow._click_named=AsyncMock();flow._click_expr=AsyncMock()
        return flow
    def state(self,**extra):
        return {'agentOn':False,'settingsOpen':False,'settingsText':'Nano Banana 2.1 crop_9_16 x1','creditLines':[],**extra}
    async def test_saved_settings_are_reused_without_opening_or_selecting_controls(self):
        flow=self.flow();state=self.state();flow._snapshot=AsyncMock(return_value=state)
        self.assertEqual(await flow._ensure_agent_and_settings('session','prompt'),state)
        flow._click_named.assert_not_awaited();flow._click_expr.assert_not_awaited()
    async def test_settings_are_checked_from_the_current_project_not_a_global_flag(self):
        flow=self.flow();flow._snapshot=AsyncMock(side_effect=[self.state(),self.state(settingsText='other model'),self.state(settingsOpen=True),self.state(settingsOpen=True)])
        await flow._ensure_agent_and_settings('session','first prompt')
        flow._click_named.assert_not_awaited()
        flow._wait_page=AsyncMock(return_value=self.state(settingsOpen=True,settingsText='other model'))
        await flow._ensure_agent_and_settings('session','new project prompt')
        self.assertIn('9:16',[call.args[1] for call in flow._click_named.await_args_list])
    async def test_agent_on_is_corrected_before_reusing_saved_settings(self):
        flow=self.flow();flow._snapshot=AsyncMock(return_value=self.state(agentOn=True))
        flow._wait_page=AsyncMock(return_value=self.state())
        await flow._ensure_agent_and_settings('session','prompt')
        flow._click_named.assert_not_awaited();self.assertEqual(flow._click_expr.await_count,1)
    async def test_zero_credit_check_can_open_panel_without_reselecting_settings(self):
        flow=self.flow();flow._snapshot=AsyncMock(return_value=self.state())
        flow._wait_page=AsyncMock(return_value=self.state(settingsOpen=True,creditLines=['Generation will cost 0 credits']))
        state=await flow._ensure_agent_and_settings('session','prompt',require_zero_credit=True)
        self.assertEqual(state['creditLines'],['Generation will cost 0 credits'])
        flow._click_named.assert_not_awaited();self.assertEqual(flow._click_expr.await_count,1)

if __name__=='__main__':unittest.main()
