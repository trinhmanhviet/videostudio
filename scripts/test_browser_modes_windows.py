"""Exercise real Windows process ownership with an isolated headless test profile."""
import json,uuid
from pathlib import Path
from videostudio.chrome_browser import BrowserConfig,DedicatedChrome
from videostudio.browser_manager import BrowserManager

ROOT=Path(__file__).resolve().parents[1]
class FixtureConfig(BrowserConfig):
    def arguments(self,mode='debug'):
        args=super().arguments(mode)
        return args[:-1]+['--headless=new','--disable-gpu','about:blank']

def main():
    actual=DedicatedChrome();before=actual.host_state()['processes']
    profile=ROOT/'data/browser-control-tests'/str(uuid.uuid4())
    manager=BrowserManager(launcher=DedicatedChrome(FixtureConfig(profile=profile)))
    try:
        clean=manager.open('clean');assert clean['mode']=='clean' and clean['running']
        assert not manager.launcher.discover();print('PASS clean process has no debug endpoint',flush=True)
        try:manager.launcher.ensure_started()
        except RuntimeError as error:assert 'Mở debug' in str(error)
        else:raise AssertionError('Automatic Flow startup must not hijack clean login mode')
        print('PASS clean login cannot be silently reused as debug',flush=True)
        debug=manager.open('debug');assert debug['mode']=='debug' and debug['debug_ready']
        assert debug['profile']==clean['profile'];print('PASS switch uses the same profile and creates an attested debug endpoint',flush=True)
        closed=manager.stop();assert closed['mode']=='closed' and not closed['running']
        print('PASS exact test-profile process is stopped',flush=True)
        assert actual.host_state()['processes']==before;print('PASS real VideoStudio login browser unchanged',flush=True)
    finally:
        if manager.status()['running']:manager.stop()
    print(json.dumps({'passed':True,'test_profile':str(profile),'production_browser_untouched':True}),flush=True)

if __name__=='__main__':main()
