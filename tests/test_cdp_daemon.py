import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from aiohttp.test_utils import TestClient, TestServer
from videostudio.cdp_daemon import ChromeChatGPTBridge, create_app
from videostudio.cdp_requests import RequestJournal


class DaemonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.launcher=MagicMock()
        self.bridge=ChromeChatGPTBridge(launcher=self.launcher,journal=RequestJournal(Path(self.tmp.name)/'db'))
        self.client=TestClient(TestServer(await create_app(self.bridge)))
        await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()
    async def test_status_poll_is_passive_and_never_launches_or_connects(self):
        for _ in range(3):
            r=await self.client.get('/api/status')
            d=await r.json();self.assertFalse(d['connected']);self.assertFalse(d['ready'])
        self.launcher.ensure_started.assert_not_called()
    async def test_cross_origin_and_missing_client_header_cannot_control_browser(self):
        for headers in ({},{'Origin':'https://evil.example','X-VS-Client':'videostudio'}):
            r=await self.client.post('/api/browser/start',json={},headers=headers)
            self.assertEqual(r.status,403)
        self.launcher.ensure_started.assert_not_called()
    async def test_cached_receipt_does_not_need_browser_or_resubmit(self):
        r=self.bridge.journal.prepare('job','prompt');self.bridge.journal.complete(r['id'],{'done':True})
        self.assertEqual(await self.bridge.ask_chatgpt('job','prompt'),{'done':True})
        self.launcher.ensure_started.assert_not_called()
    async def test_owned_tab_recreated_when_closed_does_not_take_foreign_tab(self):
        self.bridge.journal.set_conversation('job','https://chatgpt.com/c/owned','gone')
        self.bridge.cdp=MagicMock()
        self.bridge.cdp.close=AsyncMock()
        self.bridge.cdp.command=AsyncMock(side_effect=[{'targetInfos':[{'targetId':'foreign','url':'https://chatgpt.com/c/personal','type':'page'}]}, {'targetId':'new'}])
        tid=await self.bridge.ensure_tab('job')
        self.assertEqual(tid,'new')
        self.assertEqual(self.bridge.cdp.command.call_args_list[1].args[0],'Target.createTarget')
        self.assertEqual(self.bridge.cdp.command.call_args_list[1].args[1]['url'],'https://chatgpt.com/c/owned')
    async def test_target_destroyed_invalidates_session(self):
        self.bridge.sessions['a']='session'
        self.bridge.on_event({'method':'Target.targetDestroyed','params':{'targetId':'a'}})
        self.assertNotIn('a',self.bridge.sessions)
    async def test_chat_requires_job_and_never_accepts_unscoped_old_api(self):
        r=await self.client.post('/api/chat',json={'prompt':'hello'},headers={'X-VS-Client':'videostudio'})
        self.assertEqual(r.status,400)

if __name__=='__main__':unittest.main()
