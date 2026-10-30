"""Only the VideoStudio-owned Chrome profile. Never attach to personal Chrome."""
from dataclasses import dataclass, field
import os,json
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

    def arguments(self, mode='debug'):
        if mode not in ('clean','debug'):raise ValueError('Unknown dedicated browser mode')
        profile = self.profile.resolve()
        personal = (Path(os.getenv('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'Google/Chrome/User Data').resolve()
        if profile == personal or personal in profile.parents:
            raise ValueError('Refusing personal Chrome profile; choose a separate directory')
        args=[str(self.executable),'--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check']
        if mode=='debug':args+=['--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--enable-automation']
        return args+['https://accounts.google.com/AddSession' if mode=='clean' else 'https://flow.google.com/']


class DedicatedChrome:
    def __init__(self, config=None):
        self.config = config or BrowserConfig()
        self.process = None

    def host_state(self, action='inspect', process=None):
        self.config.arguments()  # Validate the profile before any host operation.
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/chrome_profile_state.ps1'),'-ProfilePath',str(self.config.profile.resolve()),'-ChromeExe',str(self.config.executable.resolve()),'-Action',action]
        if process:command+=['-ExpectedProcessId',str(process['pid']),'-ExpectedCreated',process['created']]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf8',timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError('Không xác nhận được Chrome riêng; chưa thay đổi trình duyệt. '+result.stderr[-350:])
        state=json.loads(result.stdout)
        if not isinstance(state.get('processes'),list):raise RuntimeError('Chrome profile state unavailable')
        return state

    def stop_profile(self, process):
        self.host_state('stop',process)

    def start_profile(self, mode):
        args=self.config.arguments(mode)
        if not self.config.executable.is_file():raise RuntimeError('Chrome executable not found')
        self.config.profile.mkdir(parents=True,exist_ok=True)
        self.process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
        return self.process

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
        processes=self.host_state()['processes']
        if any(p.get('mode')=='clean' for p in processes):
            raise RuntimeError('Chrome riêng đang mở sạch để đăng nhập. Bấm Mở debug trong Studio trước khi tạo ảnh Flow.')
        if not self.config.executable.is_file():
            raise RuntimeError('Chrome executable not found; set VS_CHROME_EXE')
        self.config.profile.mkdir(parents=True, exist_ok=True)
        # A living owned process with no endpoint must not cause a spawn loop.
        if not processes and (self.process is None or self.process.poll() is not None):
            self.start_profile('debug')
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            endpoint = self.discover()
            if endpoint:
                return endpoint
            time.sleep(.2)
        raise TimeoutError('Owned Chrome endpoint not ready; profile may be locked. Personal Chrome was not modified.')
