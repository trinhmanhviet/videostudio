import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock, AsyncMock
from videostudio.chrome_browser import BrowserConfig, DedicatedChrome


class DedicatedChromeTests(unittest.TestCase):
    def test_launcher_uses_own_profile_fixed_loopback_port_without_automation(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = BrowserConfig(profile=Path(t)/'chrome-profile', executable=Path('chrome.exe'))
            args = cfg.arguments()
            self.assertIn('--remote-debugging-port=19223', args)
            self.assertIn('--remote-debugging-address=127.0.0.1', args)
            self.assertIn('--user-data-dir='+str(cfg.profile.resolve()), args)
            self.assertNotIn('--enable-automation', args)
            self.assertFalse(any('remote-allow-origins' in a or '--headless' in a for a in args))

    def test_refuse_default_personal_profile(self):
        with patch.dict('os.environ', {'LOCALAPPDATA':'D:/user/local'}):
            with self.assertRaisesRegex(ValueError, 'personal'):
                BrowserConfig(profile=Path('D:/user/local/Google/Chrome/User Data')).arguments()

    def owned(self, **changes):
        return {'pid':123,'created':'owned-created','mode':'debug','debug_port':19223,
                'cdp_port':19223,'cdp_listener_owned':True,**changes}

    def test_endpoint_requires_attested_process_and_local_listener_without_port_file(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=BrowserConfig(profile=Path(t)/'profile')
            cfg.profile.mkdir()
            b=DedicatedChrome(cfg)
            response={'webSocketDebuggerUrl':'ws://127.0.0.1:19223/devtools/browser/own-token'}
            with patch.object(b,'host_state',return_value={'processes':[self.owned()]}),patch('videostudio.chrome_browser.httpx.get') as get:
                get.return_value.json.return_value=response
                self.assertEqual(b.discover(),response['webSocketDebuggerUrl'])
                response['webSocketDebuggerUrl']='ws://remote.invalid:19223/devtools/browser/own-token'
                self.assertIsNone(b.discover())

    def test_legacy_port_file_cannot_attach_without_process_listener_ownership(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=BrowserConfig(profile=Path(t))
            (cfg.profile/'DevToolsActivePort').write_text('19999\n/devtools/browser/old-token')
            b=DedicatedChrome(cfg)
            for processes in ([],[self.owned(cdp_listener_owned=False)],
                              [self.owned(),self.owned(pid=456)], [self.owned(mode='clean')]):
                with self.subTest(processes=processes),patch.object(b,'host_state',return_value={'processes':processes}),patch('videostudio.chrome_browser.httpx.get') as get:
                    get.return_value.json.return_value={'webSocketDebuggerUrl':'ws://127.0.0.1:19999/devtools/browser/old-token'}
                    self.assertIsNone(b.discover())
                    get.assert_not_called()

    def test_legacy_running_browser_still_requires_matching_port_file_token(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=BrowserConfig(profile=Path(t))
            (cfg.profile/'DevToolsActivePort').write_text('19999\n/devtools/browser/old-token')
            b=DedicatedChrome(cfg)
            with patch.object(b,'host_state',return_value={'processes':[self.owned(debug_port=0,cdp_port=19999)]}),patch('videostudio.chrome_browser.httpx.get') as get:
                get.return_value.json.return_value={'webSocketDebuggerUrl':'ws://127.0.0.1:19999/devtools/browser/old-token'}
                self.assertIsNotNone(b.discover())
                get.return_value.json.return_value={'webSocketDebuggerUrl':'ws://127.0.0.1:19999/devtools/browser/changed-token'}
                self.assertIsNone(b.discover())

    def test_fixed_endpoint_ignores_stale_port_file_and_rejects_malformed_urls(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=BrowserConfig(profile=Path(t))
            (cfg.profile/'DevToolsActivePort').write_text('19999\n/devtools/browser/stale')
            b=DedicatedChrome(cfg)
            with patch.object(b,'host_state',return_value={'processes':[self.owned()]}),patch('videostudio.chrome_browser.httpx.get') as get:
                for url in ('ws://127.0.0.1:19999/devtools/browser/old',
                            'ws://127.0.0.1:19223/devtools/page/wrong',
                            'ws://127.0.0.1:19223/devtools/browser/a?unexpected=true',
                            'ws://user@127.0.0.1:19223/devtools/browser/a'):
                    with self.subTest(url=url):
                        get.return_value.json.return_value={'webSocketDebuggerUrl':url}
                        self.assertIsNone(b.discover())
                get.return_value.json.return_value={'webSocketDebuggerUrl':'ws://127.0.0.1:19223/devtools/browser/current'}
                self.assertIsNotNone(b.discover())

    def test_endpoint_is_rechecked_against_process_replacement(self):
        b=DedicatedChrome()
        endpoint='ws://127.0.0.1:19223/devtools/browser/current'
        with patch.object(b,'host_state',side_effect=[{'processes':[self.owned()]},{'processes':[self.owned(pid=456,created='replacement')]}]),patch('videostudio.chrome_browser.httpx.get') as get:
            get.return_value.json.return_value={'webSocketDebuggerUrl':endpoint}
            self.assertEqual(b.discover(),endpoint)
            with self.assertRaisesRegex(RuntimeError,'profile|process|endpoint'):
                b.attest_endpoint(endpoint)

    def test_foreign_listener_prevents_launch_without_stopping_any_process(self):
        with tempfile.TemporaryDirectory() as t:
            exe=Path(t)/'chrome.exe';exe.touch()
            b=DedicatedChrome(BrowserConfig(profile=Path(t)/'profile',executable=exe))
            with patch.object(b,'host_state',return_value={'processes':[],'port_in_use':True}),patch('subprocess.Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError,'port|Port'):
                    b.start_profile('debug')
                spawn.assert_not_called()

    def test_configurable_port_rejects_zero_and_invalid_values(self):
        for port in (0,True,80,65536,'19223'):
            with self.subTest(port=port),self.assertRaises(ValueError):
                BrowserConfig(debug_port=port).arguments()
        self.assertIn('--remote-debugging-port=19224',BrowserConfig(debug_port=19224).arguments())

    def test_reuse_does_not_spawn_another_chrome(self):
        b=DedicatedChrome(BrowserConfig())
        with patch.object(b,'discover',return_value='ws://127.0.0.1:9999/devtools/browser/a'),patch('subprocess.Popen') as spawn:
            self.assertIn('127.0.0.1',b.ensure_started())
            spawn.assert_not_called()

class BridgeProfileAttestationTests(unittest.IsolatedAsyncioTestCase):
    async def bridge(self, failure=None):
        import asyncio
        from videostudio.cdp_daemon import ChromeChatGPTBridge
        bridge=ChromeChatGPTBridge.__new__(ChromeChatGPTBridge)
        bridge.connect_lock=asyncio.Lock()
        bridge.launcher=Mock()
        bridge.launcher.ensure_started.return_value='ws://127.0.0.1:19223/devtools/browser/owned'
        bridge.launcher.attest_endpoint.side_effect=failure
        bridge.cdp=Mock(connected=False)
        bridge.cdp.connect=AsyncMock()
        bridge.cdp.command=AsyncMock()
        bridge.cdp.close=AsyncMock()
        return bridge

    async def test_connection_rechecks_native_profile_without_command_line_rpc(self):
        bridge=await self.bridge()
        await bridge.connect()
        bridge.launcher.attest_endpoint.assert_called_once_with(bridge.launcher.ensure_started.return_value)
        bridge.cdp.command.assert_awaited_once_with('Target.setDiscoverTargets',{'discover':True})

    async def test_changed_profile_closes_connection_before_any_cdp_command(self):
        bridge=await self.bridge(RuntimeError('owned process changed'))
        with self.assertRaisesRegex(RuntimeError,'changed'):
            await bridge.connect()
        bridge.cdp.command.assert_not_called()
        bridge.cdp.close.assert_awaited_once()


if __name__=='__main__':unittest.main()
