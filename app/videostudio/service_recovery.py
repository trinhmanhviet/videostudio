"""Bounded recovery of an absent local Flow daemon; never kill a live browser."""
from .paths import DATA_ROOT
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
import httpx


def ensure_flow_service(base_url,check):
    parsed=urlparse(base_url)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.port!=8879:
        raise RuntimeError('Automatic Flow recovery requires the local daemon on port 8879')
    root=Path(__file__).resolve().parents[1];check()
    try:
        response=httpx.get('http://127.0.0.1:8879/api/status',timeout=2,trust_env=False)
    except (httpx.ConnectError,httpx.ConnectTimeout):response=None
    if response is not None:
        response.raise_for_status()
        if response.json().get('service')!='videostudio-dedicated-cdp':raise RuntimeError('Port 8879 is not the VideoStudio Flow service')
        return
    log_path=DATA_ROOT/'logs'/'flow-recovery.log';log_path.parent.mkdir(parents=True,exist_ok=True)
    with log_path.open('ab') as log:
        process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'scripts'/'start_browser.ps1')],
            cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
        deadline=time.monotonic()+60
        try:
            while process.poll() is None:
                check()
                if time.monotonic()>deadline:raise TimeoutError('Flow recovery timed out; see data/logs/flow-recovery.log')
                time.sleep(.2)
            check()
            if process.returncode:raise RuntimeError('Flow recovery failed; see data/logs/flow-recovery.log')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    response=httpx.get('http://127.0.0.1:8879/api/status',timeout=3,trust_env=False);response.raise_for_status()
    if response.json().get('service')!='videostudio-dedicated-cdp' or not response.json().get('connected'):
        raise RuntimeError('Flow service started but Chrome is not connected')
