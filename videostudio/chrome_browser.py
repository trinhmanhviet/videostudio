"""Only the VideoStudio-owned Chrome profile. Never attach to personal Chrome."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
import httpx

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class BrowserConfig:
    profile: Path = field(default_factory=lambda: Path(os.getenv('VS_CHROME_PROFILE', str(ROOT/'data'/'chrome-profile'))))
    executable: Path = field(default_factory=lambda: Path(os.getenv('VS_CHROME_EXE', 'C:/Program Files/Google/Chrome/Application/chrome.exe')))

    def arguments(self):
        profile = self.profile.resolve()
        personal = (Path(os.getenv('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'Google/Chrome/User Data').resolve()
        if profile == personal or personal in profile.parents:
            raise ValueError('Refusing personal Chrome profile; choose a separate directory')
        return [str(self.executable), '--user-data-dir='+str(profile),
                '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                '--no-first-run', '--no-default-browser-check', 'about:blank']


class DedicatedChrome:
    def __init__(self, config=None):
        self.config = config or BrowserConfig()
        self.process = None

    def discover(self):
        """Ignore stale files and endpoints which do not match our own port/token."""
        try:
            self.config.arguments()  # validate even when reusing
            lines = (self.config.profile/'DevToolsActivePort').read_text().splitlines()
            port = int(lines[0]); token = lines[1].strip()
            if not 0 < port < 65536 or not token.startswith('/devtools/browser/'):
                return None
            response = httpx.get(f'http://127.0.0.1:{port}/json/version', timeout=1, trust_env=False)
            response.raise_for_status()
            url = response.json()['webSocketDebuggerUrl']
            parsed = urlparse(url)
            if parsed.scheme != 'ws' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.port != port or parsed.path != token:
                return None
            return url
        except (OSError, ValueError, KeyError, IndexError, httpx.HTTPError):
            return None

    def ensure_started(self, timeout=20):
        existing = self.discover()
        if existing:
            return existing
        args = self.config.arguments()
        if not self.config.executable.is_file():
            raise RuntimeError('Chrome executable not found; set VS_CHROME_EXE')
        self.config.profile.mkdir(parents=True, exist_ok=True)
        # A living owned process with no endpoint must not cause a spawn loop.
        if self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, close_fds=True)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            endpoint = self.discover()
            if endpoint:
                return endpoint
            time.sleep(.2)
        raise TimeoutError('Owned Chrome endpoint not ready; profile may be locked. Personal Chrome was not modified.')
