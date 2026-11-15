"""Runs the WikiCV downloader (wikicv_auto_v3_2_mixed_titles/crawl_wikicv.py) from the Kể truyện page.

The downloader is used exactly as it is when run by hand: robots.txt check, 2–4 s between chapters, stop on
403/429/Cloudflare. This module only starts it in the background, reads the lines it prints to show progress, and lets
the person stop it. Chapters land in du_lieu_truyen/<truyện>/, where the "Truyện nguồn" panel already lists them for the
ChatGPT edit and the import into the library."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

_LINES = [
    ('title', re.compile(r'^Tên truyện\s*:\s*(.+)$')),
    ('folder', re.compile(r'^Đầu ra\s*:\s*(.+)$')),
    ('resume', re.compile(r'^Tiếp tục từ\s*:\s*mục (\d+)')),
    ('saved', re.compile(r'^\[Lưu\] Mục (\d+): (.+?) — ([\d.,]+) ký tự')),
    ('known', re.compile(r'^\[Đã có\] Mục (\d+): (.+)$')),
    ('limit', re.compile(r'^\[Tạm dừng\] (.+)$')),
    ('latest', re.compile(r'^\[Xong\] (.+)$')),
    ('total', re.compile(r'^Tổng đã lưu: (\d+) chương \| Mới tải: (\d+)')),
    ('complete', re.compile(r'^Hoàn tất đến chương mới nhất: (CÓ|CHƯA)')),
    ('error', re.compile(r'^\[LỖI\] (.+)$')),
]


def valid_url(url):
    parsed = urlparse(str(url or '').strip())
    if parsed.scheme != 'https' or parsed.hostname not in ('wikicv.org', 'www.wikicv.org') or not parsed.path.startswith('/truyen/'):
        raise ValueError('Dán link trang giới thiệu truyện trên wikicv.org (dạng https://wikicv.org/truyen/…)')
    return parsed.geturl()


class Crawler:
    def __init__(self, script, output, on_finish=None):
        self.script, self.output, self.on_finish = Path(script), Path(output), on_finish
        self.lock = threading.Lock()
        self.process = None
        self.state = {'running': False}

    def status(self):
        with self.lock:
            return dict(self.state, log=list(self.state.get('log') or [])[-40:])

    def start(self, url, max_chapters=0):
        url = valid_url(url)
        if type(max_chapters) is not int or not 0 <= max_chapters <= 5000:
            raise ValueError('Số chương tối đa 0–5000 (0 = đến chương mới nhất)')
        if not self.script.is_file():
            raise ValueError('Không thấy công cụ tải truyện: ' + str(self.script))
        with self.lock:
            if self.state.get('running'):
                raise ValueError('Đang tải một truyện. Chờ xong hoặc bấm Dừng.')
            self.state = {'running': True, 'url': url, 'title': None, 'folder': None, 'saved': 0, 'known': 0, 'position': 0,
                          'last': None, 'complete': None, 'error': None, 'stopped': False, 'log': [], 'started': time.time(), 'finished': None}
        command = [sys.executable, '-X', 'utf8', '-u', str(self.script), '--url', url, '--output', str(self.output),
                   '--max-chapters', str(max_chapters)]
        env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
        self.output.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(command, cwd=str(self.script.parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', env=env,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._follow, args=(self.process,), name='story-crawl', daemon=True).start()
        return self.status()

    def stop(self):
        with self.lock:
            running = self.state.get('running')
            self.state['stopped'] = bool(running)
        if running and self.process and self.process.poll() is None:
            self.process.terminate()  # chapters already saved stay; running again continues from there
        return self.status()

    def _read(self, line):
        line = line.rstrip()
        if not line:
            return
        with self.lock:
            state = self.state
            state['log'] = (state.get('log') or [])[-40:] + [line]
            for kind, pattern in _LINES:
                match = pattern.match(line.strip())
                if not match:
                    continue
                if kind == 'title':
                    state['title'] = match.group(1).strip()
                elif kind == 'folder':
                    state['folder'] = Path(match.group(1).strip()).name
                elif kind == 'resume':
                    state['position'] = int(match.group(1))
                elif kind == 'saved':
                    state['saved'] += 1
                    state['position'] = int(match.group(1))
                    state['last'] = match.group(2).strip()
                elif kind == 'known':
                    state['known'] += 1
                    state['position'] = int(match.group(1))
                elif kind == 'total':
                    state['total'] = int(match.group(1))
                elif kind == 'complete':
                    state['complete'] = match.group(1) == 'CÓ'
                elif kind == 'error':
                    state['error'] = match.group(1).strip()
                break

    def _follow(self, process):
        for line in process.stdout:
            self._read(line)
        process.stdout.close()
        code = process.wait()
        with self.lock:
            self.state['running'] = False
            self.state['finished'] = time.time()
            self.state['code'] = code
            if code and not self.state.get('error') and not self.state.get('stopped'):
                self.state['error'] = f'Công cụ tải dừng với mã {code}; xem nhật ký bên dưới.'
            result = dict(self.state)
        if self.on_finish:
            try:
                self.on_finish(result)
            except Exception:
                pass
