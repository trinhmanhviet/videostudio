"""Stop, start and restart the local ComfyUI service, from the tool's Cài đặt and from the tray app.

ComfyUI can end up alive but stuck (2026-11-16: up for 8 days, its HTTP server no longer answering and its VRAM figure
wrong), so "restart" kills its process tree, waits until the process is really gone and port 8188 is free (a process
that held GPU memory can take minutes to exit), then starts it again through the tool's own launcher
(scripts/start_comfy_recovery.py), which never starts a second copy.

Stopping is refused while a video or image job is running, unless forced: ComfyUI may be drawing or making music for it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .paths import DATA_ROOT

ROOT = Path(__file__).resolve().parents[1]
URL = os.getenv('VS_COMFY_URL', 'http://127.0.0.1:8188')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


class Busy(ValueError):
    pass


def host_state():
    """{'listening': bool, 'comfy_process_ids': [int]} from scripts/comfy_host_state.ps1."""
    probe = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'scripts' / 'comfy_host_state.ps1')],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    if probe.returncode:
        raise RuntimeError('Không đọc được trạng thái ComfyUI: ' + probe.stderr[-200:])
    state = json.loads(probe.stdout)
    state['comfy_process_ids'] = [int(p) for p in (state.get('comfy_process_ids') or [])]
    return state


def responding(timeout=5):
    try:
        with urllib.request.urlopen(URL.rstrip('/') + '/system_stats', timeout=timeout) as response:
            return response.status == 200
    except OSError:
        return False


def status(state=None):
    state = state or host_state()
    running = bool(state['comfy_process_ids'])
    answers = responding() if state.get('listening') else False
    label = ('Đang chạy' if answers else 'Không trả lời (có thể đang khởi động hoặc bị treo)') if running else 'Đã tắt'
    return {'running': running, 'listening': bool(state.get('listening')), 'responding': answers, 'pids': state['comfy_process_ids'], 'label': label}


def active_jobs():
    """Video jobs and scene-image tasks that may be using ComfyUI right now."""
    database = Path(os.getenv('VS_DATABASE', str(DATA_ROOT / 'jobs.sqlite3')))
    if not database.exists():
        return 0
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        count = connection.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('running','retrying')").fetchone()[0]
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scene_image_tasks'").fetchone():
            count += connection.execute("SELECT COUNT(*) FROM scene_image_tasks WHERE state IN ('queued','running')").fetchone()[0]
    return count


def stop(force=False, wait=240, jobs=active_jobs, state=host_state, kill=None, sleep=time.sleep):
    """Kill ComfyUI's process tree and wait until it is gone and port 8188 is free."""
    if not force and jobs():
        raise Busy('Đang có video hoặc ảnh chạy, ComfyUI có thể đang làm cho nó. Chờ xong, hoặc chọn vẫn tắt.')
    kill = kill or (lambda pid: subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True, creationflags=NO_WINDOW))
    current = state()
    for pid in current['comfy_process_ids']:
        kill(pid)
    deadline = time.monotonic() + wait
    while True:
        current = state()
        if not current['comfy_process_ids'] and not current.get('listening'):
            return {'stopped': True, 'message': 'Đã tắt ComfyUI.'}
        if time.monotonic() >= deadline:
            return {'stopped': False, 'message': 'ComfyUI đã nhận lệnh tắt nhưng vẫn đang thoát (đang trả bộ nhớ GPU). Chờ thêm rồi bấm Bật.'}
        sleep(3)


def start(state=host_state, launch=None):
    """Start ComfyUI through the tool's launcher (never a second copy) and wait until it answers."""
    current = state()
    if current['comfy_process_ids'] or current.get('listening'):
        return {'started': False, 'message': 'ComfyUI đang chạy hoặc chưa thoát hẳn; không mở thêm bản trùng.'}
    launch = launch or (lambda: subprocess.run([sys.executable, str(ROOT / 'scripts' / 'start_comfy_recovery.py'), '--expected-url', URL],
                                               capture_output=True, text=True, cwd=str(ROOT), timeout=420, creationflags=NO_WINDOW))
    result = launch()
    if result.returncode:
        return {'started': False, 'message': 'Chưa bật được ComfyUI: ' + (result.stderr or result.stdout or '')[-300:]}
    return {'started': True, 'message': 'Đã bật ComfyUI.'}


def restart(force=False, **options):
    stopped = stop(force, **{k: v for k, v in options.items() if k in ('wait', 'jobs', 'state', 'kill', 'sleep')})
    if not stopped['stopped']:
        return {**stopped, 'started': False}
    started = start(**{k: v for k, v in options.items() if k in ('state', 'launch')})
    return {**started, 'stopped': True, 'message': 'Đã khởi động lại ComfyUI.' if started['started'] else started['message']}


if __name__ == '__main__':
    import argparse
    sys.stdout.reconfigure(encoding='utf8')
    parser = argparse.ArgumentParser(description='Stop / start / restart the local ComfyUI service.')
    parser.add_argument('action', choices=['status', 'stop', 'start', 'restart'])
    parser.add_argument('--force', action='store_true', help='also while a video is running')
    args = parser.parse_args()
    try:
        if args.action == 'status':
            result, ok = status(), True
        elif args.action == 'stop':
            result = stop(args.force)
            ok = result['stopped']
        elif args.action == 'start':
            result = start()
            ok = result['started'] or 'đang chạy' in result['message']
        else:
            result = restart(args.force)
            ok = result['started']
        print(result.get('message') or result.get('label'))
        raise SystemExit(0 if ok else 1)
    except (Busy, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(error)
        raise SystemExit(1)
