"""Restart only an absent Comfy service through its pre-authorized launcher.
Does not kill/restart a live process, unload models or submit generation work.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path('D:/Projects/storyforge/.runtime/comfyui-launcher.json')
AUTHORIZED_SHA256 = '590a95b06f12165dc60de6aaf8119a9b7ee8a5d246a56d034c8074a6f1cf64b6'


def require_absent_service():
    # A connect timeout is not evidence of a dead service. Refuse a duplicate
    # process even when an existing Comfy is still booting or unresponsive.
    probe = subprocess.run(
        ['powershell', '-NoProfile', '-File', str(ROOT / 'scripts/comfy_host_state.ps1')],
        capture_output=True, text=True, timeout=20, check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    state = json.loads(probe.stdout)
    if (state.get('listening') is not False
            or not isinstance(state.get('comfy_process_ids'), list)
            or state['comfy_process_ids']):
        raise RuntimeError('Comfy listener/process present or state unknown; refusing duplicate start')


def main(expected_url=None):
    config = json.loads(CONFIG.read_text())
    launcher = Path(config['launcher'])
    if (config['sha256'] != AUTHORIZED_SHA256
            or hashlib.sha256(launcher.read_bytes()).hexdigest() != AUTHORIZED_SHA256):
        raise RuntimeError('Launcher changed; not executing')
    if expected_url is not None and expected_url.rstrip('/') != config['url'].rstrip('/'):
        raise RuntimeError('Requested Comfy URL does not match the authorized launcher')
    if os.name != 'nt':
        raise RuntimeError('This launcher is for Windows host only')
    require_absent_service()
    logdir = ROOT / 'data/comfy-recovery'
    logdir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HOME='D:/Projects/storyforge/.runtime/media/model-cache')
    breakaway = getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0x01000000)
    with (logdir / 'startup.log').open('ab') as log:
        process = subprocess.Popen(
            ['cmd.exe', '/c', str(launcher)], cwd=launcher.parent, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | breakaway,
        )
    print(json.dumps({'launcher_pid': process.pid, 'generation_submitted': False}), flush=True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(config['url'].rstrip('/') + '/system_stats', timeout=3) as response:
                data = json.load(response)
            record = {
                'launcher_pid': process.pid, 'launcher': str(launcher), 'ready': True,
                'generation_submitted': False,
                'devices': [{'name': device['name'], 'vram_free': device['vram_free']} for device in data['devices']],
            }
            (logdir / 'service.json').write_text(json.dumps(record, indent=2))
            print(json.dumps(record), flush=True)
            return record
        except (OSError, ValueError):
            if process.poll() is not None:
                raise RuntimeError('Launcher exited; inspect data/comfy-recovery/startup.log')
            time.sleep(2)
    raise TimeoutError('Comfy startup budget exhausted; generation not submitted')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-url')
    main(parser.parse_args().expected_url)
