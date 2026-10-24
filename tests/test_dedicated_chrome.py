import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from videostudio.chrome_browser import BrowserConfig, DedicatedChrome


class DedicatedChromeTests(unittest.TestCase):
    def test_launcher_uses_own_profile_ephemeral_loopback_port(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = BrowserConfig(profile=Path(t)/'chrome-profile', executable=Path('chrome.exe'))
            args = cfg.arguments()
            self.assertIn('--remote-debugging-port=0', args)
            self.assertIn('--remote-debugging-address=127.0.0.1', args)
            self.assertIn('--user-data-dir='+str(cfg.profile.resolve()), args)
            self.assertFalse(any('remote-allow-origins' in a or '--headless' in a for a in args))

    def test_refuse_default_personal_profile(self):
        with patch.dict('os.environ', {'LOCALAPPDATA':'D:/user/local'}):
            with self.assertRaisesRegex(ValueError, 'personal'):
                BrowserConfig(profile=Path('D:/user/local/Google/Chrome/User Data')).arguments()

    def test_endpoint_comes_only_from_own_profile_and_requires_matching_token(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=BrowserConfig(profile=Path(t)/'profile')
            cfg.profile.mkdir()
            b=DedicatedChrome(cfg)
            self.assertIsNone(b.discover())
            (cfg.profile/'DevToolsActivePort').write_text('19999\n/devtools/browser/own-token')
            response={'webSocketDebuggerUrl':'ws://127.0.0.1:19999/devtools/browser/own-token'}
            with patch('videostudio.chrome_browser.httpx.get') as get:
                get.return_value.json.return_value=response
                self.assertEqual(b.discover(),response['webSocketDebuggerUrl'])
                response['webSocketDebuggerUrl']='ws://remote.invalid:19999/devtools/browser/own-token'
                self.assertIsNone(b.discover())

    def test_reuse_does_not_spawn_another_chrome(self):
        b=DedicatedChrome(BrowserConfig())
        with patch.object(b,'discover',return_value='ws://127.0.0.1:9999/devtools/browser/a'),patch('subprocess.Popen') as spawn:
            self.assertIn('127.0.0.1',b.ensure_started())
            spawn.assert_not_called()

if __name__=='__main__':unittest.main()
