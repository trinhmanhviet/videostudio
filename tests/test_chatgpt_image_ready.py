import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from videostudio.cdp_images import ChatGPTImages


class ImageComposerReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_switch_waits_for_ui_hydration_without_clicking_twice(self):
        work={'mode':'work','draft':'','composer':True}
        bridge=SimpleNamespace(evaluate=AsyncMock(side_effect=[work,{'x':12,'y':20},work,work,{'mode':'chat','draft':'','composer':True}]))
        images=ChatGPTImages(bridge,'.');images._click=AsyncMock()
        with patch('videostudio.cdp_images.asyncio.sleep',new=AsyncMock()):
            result=await images._ready('session','marker')
        self.assertEqual(result['mode'],'chat');images._click.assert_awaited_once()

    async def test_only_the_exact_owned_image_draft_can_switch_modes(self):
        work={'mode':'work','draft':'Owned image\n prompt','composer':True}
        bridge=SimpleNamespace(evaluate=AsyncMock(side_effect=[work,{'x':12,'y':20},{'mode':'chat','draft':'','composer':True}]))
        images=ChatGPTImages(bridge,'.');images._click=AsyncMock()
        with patch('videostudio.cdp_images.asyncio.sleep',new=AsyncMock()):
            await images._ready('session','marker','Owned image prompt')
        images._click.assert_awaited_once()

    async def test_foreign_draft_is_never_discarded_to_change_modes(self):
        bridge=SimpleNamespace(evaluate=AsyncMock(return_value={'mode':'work','draft':'My personal draft','composer':True}))
        images=ChatGPTImages(bridge,'.');images._click=AsyncMock()
        with self.assertRaisesRegex(RuntimeError,'draft'):
            await images._ready('session','marker','Owned image prompt')
        images._click.assert_not_awaited()

    async def test_missing_mode_switch_control_waits_without_clicking_null(self):
        work={'mode':'work','draft':'','composer':True}
        bridge=SimpleNamespace(evaluate=AsyncMock(side_effect=[work,None,work,{'x':12,'y':20},{'mode':'chat','draft':'','composer':True}]))
        images=ChatGPTImages(bridge,'.');images._click=AsyncMock()
        with patch('videostudio.cdp_images.asyncio.sleep',new=AsyncMock()):
            await images._ready('session','marker')
        images._click.assert_awaited_once_with('session',{'x':12,'y':20})
