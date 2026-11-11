"""Only the VideoStudio-owned Chrome profile. Never attach to personal Chrome."""
from .paths import DATA_ROOT
from dataclasses import dataclass, field
import os,json,re
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
import httpx

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class BrowserConfig:
    profile: Path = field(default_factory=lambda: Path(os.getenv('VS_CHROME_PROFILE', str(DATA_ROOT/'chrome-profile'))))
    executable: Path = field(default_factory=lambda: Path(os.getenv('VS_CHROME_EXE', 'C:/Program Files/Google/Chrome/Application/chrome.exe')))
    debug_port: int = field(default_factory=lambda: int(os.getenv('VS_CHROME_DEBUG_PORT', '19223')))

    def arguments(self, mode='debug'):
        if mode not in ('clean','debug'):raise ValueError('Unknown dedicated browser mode')
        if type(self.debug_port) is not int or not 1024<=self.debug_port<=65535:
            raise ValueError('VS_CHROME_DEBUG_PORT must be an integer from 1024 to 65535')
        profile = self.profile.resolve()
        personal = (Path(os.getenv('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'Google/Chrome/User Data').resolve()
        if profile == personal or personal in profile.parents:
            raise ValueError('Refusing personal Chrome profile; choose a separate directory')
        args=[str(self.executable),'--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check']
        if mode=='debug':args+=['--remote-debugging-address=127.0.0.1',f'--remote-debugging-port={self.debug_port}']
        return args+['https://accounts.google.com/AddSession' if mode=='clean' else 'https://flow.google.com/']


class DedicatedChrome:
    def __init__(self, config=None):
        self.config = config or BrowserConfig()
        self.process = None
        self._endpoint_receipt = None

    def host_state(self, action='inspect', process=None):
        self.config.arguments()  # Validate the profile before any host operation.
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/chrome_profile_state.ps1'),'-ProfilePath',str(self.config.profile.resolve()),'-ChromeExe',str(self.config.executable.resolve()),'-DebugPort',str(self.config.debug_port),'-Action',action]
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
        if mode=='debug':
            state=self.host_state()
            if state.get('port_in_use') is not False:
                raise RuntimeError(f'CDP port {self.config.debug_port} is busy or unavailable; no browser launched')
            if state['processes']:raise RuntimeError('Dedicated Chrome profile is already running; no duplicate launched')
        self.config.profile.mkdir(parents=True,exist_ok=True)
        self.process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
        return self.process

    def discover(self):
        """Use the exact owned process and its local listener; never trust a port alone."""
        try:
            self.config.arguments()  # validate even when reusing
            processes=self.host_state()['processes']
            if len(processes)!=1:return None
            owned=processes[0]
            if owned.get('mode')!='debug' or owned.get('cdp_listener_owned') is not True:return None
            pid=owned.get('pid');created=owned.get('created');port=owned.get('cdp_port');declared=owned.get('debug_port')
            if type(pid) is not int or pid<=0 or not isinstance(created,str) or not created:return None
            if type(port) is not int or not 0<port<65536 or type(declared) is not int:return None
            token=None
            if declared==0:  # Preserve an already running legacy browser until explicitly reopened.
                lines=(self.config.profile/'DevToolsActivePort').read_text().splitlines()
                if int(lines[0])!=port:return None
                token=lines[1].strip()
            elif declared!=port:return None
            response = httpx.get(f'http://127.0.0.1:{port}/json/version', timeout=1, trust_env=False)
            response.raise_for_status()
            url = response.json()['webSocketDebuggerUrl']
            parsed = urlparse(url)
            if (parsed.scheme!='ws' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.port!=port
                    or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                    or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]+',parsed.path)
                    or (token is not None and parsed.path!=token)):
                return None
            self._endpoint_receipt=(url,pid,created,port)
            return url
        except (OSError, RuntimeError, TypeError, ValueError, KeyError, IndexError, httpx.HTTPError):
            return None

    def attest_endpoint(self, endpoint):
        """Recheck ownership after WebSocket connection, before issuing any command."""
        previous=self._endpoint_receipt
        if not previous or previous[0]!=endpoint or self.discover()!=endpoint or self._endpoint_receipt!=previous:
            raise RuntimeError('CDP endpoint or owned profile process changed; connection refused')
        return True

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
