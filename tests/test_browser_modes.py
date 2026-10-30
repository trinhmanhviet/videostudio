import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from videostudio.chrome_browser import BrowserConfig,DedicatedChrome

class BrowserModeTests(unittest.TestCase):
    def test_modes_share_profile_but_clean_has_no_debug_or_automation(self):
        cfg=BrowserConfig(profile=Path('data/test-profile'))
        clean=cfg.arguments(mode='clean');debug=cfg.arguments(mode='debug')
        self.assertEqual([s for s in clean if s.startswith('--user-data-dir=')],[s for s in debug if s.startswith('--user-data-dir=')])
        self.assertFalse(any('remote-debugging' in s or s=='--enable-automation' for s in clean))
        self.assertIn('--remote-debugging-port=0',debug);self.assertIn('--enable-automation',debug)
    def manager(self,state,active=0):
        from videostudio.browser_manager import BrowserManager
        launcher=Mock();launcher.config.profile=Path('data/test-profile');launcher.host_state.return_value={'processes':state}
        return BrowserManager(launcher=launcher,active_jobs=lambda:active),launcher
    def test_stop_while_video_active_does_not_touch_browser(self):
        manager,launcher=self.manager([{'pid':123,'mode':'debug','created':'owned'}],active=1)
        with self.assertRaisesRegex(ValueError,'video'):manager.stop()
        launcher.stop_profile.assert_not_called()
    def test_same_mode_reuses_existing_profile_without_restart(self):
        manager,launcher=self.manager([{'pid':123,'mode':'clean','created':'owned'}])
        result=manager.open('clean')
        self.assertEqual(result['mode'],'clean');launcher.start_profile.assert_not_called();launcher.stop_profile.assert_not_called()
    def test_switch_mode_stops_only_attested_profile_then_reopens(self):
        manager,launcher=self.manager([{'pid':123,'mode':'clean','created':'owned'}])
        launcher.host_state.side_effect=[{'processes':[{'pid':123,'mode':'clean','created':'owned'}]},{'processes':[{'pid':456,'mode':'debug','created':'new'}]}]
        launcher.discover.return_value='ws://127.0.0.1:123/devtools/browser/owned'
        result=manager.open('debug')
        launcher.stop_profile.assert_called_once_with({'pid':123,'mode':'clean','created':'owned'})
        launcher.start_profile.assert_called_once_with('debug');self.assertEqual(result['mode'],'debug')
    def test_unknown_mode_is_refused_without_starting_browser(self):
        manager,launcher=self.manager([])
        with self.assertRaises(ValueError):manager.open('anything')
        launcher.start_profile.assert_not_called()

if __name__=='__main__':unittest.main()
