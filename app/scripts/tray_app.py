"""VideoStudio tray app: the launcher lives in the Windows notification area (like vTransfer).

Left click opens Studio (starting the system first when needed); right click shows the menu.
Closing the tray never stops services or videos; Stop/Restart keep their active-job guards.
"""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import threading

import windows_integration as integration
from windows_tray import Tray, message_box, single_instance

ACTIVE = ('queued', 'running', 'retrying')
ACTION_LABELS = {'start': 'mở hệ thống', 'stop': 'dừng hệ thống', 'restart': 'khởi động lại'}
DEFAULT_SETTINGS = {'setup_done': False, 'notify': True, 'autostart_services': True}
# ChatGPT text channel; start_system.ps1 reads the same data/text_transport.txt.
TEXT_TRANSPORTS = {'cdp': 'Chrome riêng (CDP)', 'extension': 'Chrome thường (extension)'}


def read_text_transport(root):
    try:
        value = (Path(root).parent / 'data' / 'text_transport.txt').read_text(encoding='utf-8').strip().lower()
    except OSError:
        return 'extension'
    return value if value in TEXT_TRANSPORTS else 'extension'


def write_text_transport(root, value):
    if value not in TEXT_TRANSPORTS:
        raise ValueError(value)
    path = Path(root).parent / 'data' / 'text_transport.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(value, encoding='utf-8')
    temporary.replace(path)


def server_ready(status):
    server = (status or {}).get('server')
    return bool(server and server.get('service') == 'videostudio')


def flow_ready(status):
    flow = (status or {}).get('flow')
    return bool(flow and flow.get('service') == 'videostudio-dedicated-cdp' and flow.get('connected'))


def comfy_ready(status):
    comfy = (status or {}).get('comfy')
    return bool(comfy and 'system' in comfy and 'devices' in comfy)


def job_title(request_text):
    try:
        request = json.loads(request_text or '{}')
    except ValueError:
        request = {}
    idea = ' '.join(str(request.get('idea', '')).split())
    project = str(request.get('project') or '').strip()
    title = idea[:60] + ('…' if len(idea) > 60 else '')
    return (project + ': ' + title) if project and title else (title or project or 'Video')


def video_folder(output):
    """Job data lives in <project>/data/<job id>; the published MP4 sits in <project>."""
    path = Path(output)
    return path.parent.parent if path.parent.name == 'data' else path


class JobWatcher:
    """Reads job states read-only from SQLite and reports transitions (no API load, no writes)."""

    def __init__(self, database):
        self.database = Path(database)
        self.states = None
        self.active = 0

    def poll(self):
        if not self.database.is_file():
            return []
        try:
            with closing(sqlite3.connect('file:' + self.database.as_posix() + '?mode=ro', uri=True, timeout=2)) as db:
                rows = db.execute('SELECT id,state,stage,output,request FROM jobs').fetchall()
        except sqlite3.Error:
            return []
        current = {row[0]: row for row in rows}
        self.active = sum(1 for row in rows if row[1] in ACTIVE)
        if self.states is None:  # first look: remember, never announce old results
            self.states = {ident: row[1] for ident, row in current.items()}
            return []
        events = []
        for ident, (_, state, stage, output, request) in current.items():
            before = self.states.get(ident)
            if before in ACTIVE and state in ('completed', 'failed'):
                events.append({'id': ident, 'state': state, 'stage': stage, 'output': output, 'title': job_title(request)})
        self.states = {ident: row[1] for ident, row in current.items()}
        return events


class TrayApp:
    def __init__(self, root, launcher, tray_factory=Tray, integration_module=integration):
        self.root = Path(root)
        self.launcher = launcher
        self.integration = integration_module
        self.settings_path = self.root.parent / 'data' / 'tray.json'
        self.settings = self._load_settings()
        self.status = None
        self.busy = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        database = os.environ.get('VS_DATABASE') or str(self.root.parent / 'data' / 'jobs.sqlite3')
        self.jobs = JobWatcher(database)
        assets = self.integration.resource_dir()
        self.tray = tray_factory(self, {key: assets / f'videostudio-{key}.ico' for key in ('ready', 'busy', 'stopped')})

    # ── settings ──
    def _load_settings(self):
        try:
            saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        return {**DEFAULT_SETTINGS, **{k: v for k, v in saved.items() if k in DEFAULT_SETTINGS}}

    def _save_settings(self, **changes):
        self.settings.update(changes)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.settings_path)

    # ── state shown by the tray (called on the tray thread; no blocking I/O) ──
    def tray_state(self):
        status = self.status
        if self.busy:
            key, head = 'busy', 'VideoStudio — đang ' + ACTION_LABELS[self.busy] + '…'
        elif server_ready(status):
            key, head = 'ready', 'VideoStudio — đang chạy'
        else:
            key, head = 'stopped', 'VideoStudio — chưa mở hệ thống'
        lines = [head]
        if status is not None:
            lines.append('Studio {} · Flow {} · Comfy {}'.format(
                *('✓' if ok else '✗' for ok in (server_ready(status), flow_ready(status), comfy_ready(status)))))
        if self.jobs.active:
            lines.append(f'{self.jobs.active} video đang xử lý')
        lines.append('Bấm: vào Studio · chuột phải: menu')
        return key, '\n'.join(lines)[:127]

    def menu(self):
        ready = server_ready(self.status)
        busy = self.busy is not None
        startup = self.integration.startup_enabled()
        shortcuts = self.integration.shortcuts_installed()
        transport = read_text_transport(self.root)
        return [
            ('item', 'Vào Studio', self.open_studio, {'default': True}),
            ('separator',),
            ('item', 'Mở hệ thống', lambda: self.start_action('start'), {'grayed': busy or ready}),
            ('item', 'Khởi động lại', lambda: self.start_action('restart'), {'grayed': busy}),
            ('item', 'Dừng hệ thống', lambda: self.start_action('stop'), {'grayed': busy or not ready}),
            ('separator',),
            ('item', 'Bảng điều khiển && nhật ký', self.open_panel, {}),
            ('item', 'Mở thư mục video', self.open_output, {}),
            ('submenu', 'Kết nối ChatGPT (tạo chữ)', [
                ('item', label, lambda value=value: self.set_text_transport(value),
                 {'checked': transport == value, 'grayed': busy})
                for value, label in TEXT_TRANSPORTS.items()
            ]),
            ('submenu', 'Cài đặt', [
                ('item', 'Khởi động cùng Windows', self.toggle_startup, {'checked': bool(startup), 'grayed': startup is None}),
                ('item', 'Tự mở hệ thống khi khởi động cùng Windows', self.toggle_autostart, {'checked': self.settings['autostart_services']}),
                ('item', 'Thông báo khi video xong hoặc lỗi', self.toggle_notify, {'checked': self.settings['notify']}),
                ('item', 'Shortcut trên Desktop và Start Menu', self.toggle_shortcuts, {'checked': bool(shortcuts), 'grayed': shortcuts is None}),
            ]),
            ('separator',),
            ('item', 'Thoát khay (video vẫn chạy)', self.quit, {}),
        ]

    # ── actions ──
    def on_left_click(self):
        self.open_studio()

    def _open_studio_now(self):
        try:
            self.launcher.open_studio()
        except Exception as error:
            self.tray.notify('Không mở được Studio', str(error), warning=True)

    def open_studio(self):
        if server_ready(self.status):
            self._open_studio_now()
        elif self.busy:
            self.tray.notify('VideoStudio', 'Đang ' + ACTION_LABELS[self.busy] + ', chờ một chút rồi bấm lại.')
        else:
            self.tray.notify('VideoStudio', 'Đang mở hệ thống, Studio sẽ tự mở khi sẵn sàng.')
            self.start_action('start', open_after=True)

    def start_action(self, action, open_after=False):
        with self.lock:
            if self.busy:
                return False
            self.busy = action

        def work():
            try:
                code = self.launcher.run_action(self.root, action, lambda event: None)
            except Exception as error:
                code, detail = 1, str(error)
            else:
                detail = self._last_log_line()
            self.status = self.launcher.read_status()
            with self.lock:
                self.busy = None
            if code == 0:
                if action == 'stop':
                    self.tray.notify('Đã dừng VideoStudio', 'Bấm vào biểu tượng để mở lại hệ thống.')
                elif open_after:
                    # Open directly: retrying through open_studio() could loop into another start.
                    self.tray.call(self._open_studio_now)
                else:
                    self.tray.notify('VideoStudio đã sẵn sàng', 'Bấm vào thông báo để vào Studio.', self.open_studio)
            else:
                self.tray.notify('Chưa ' + ACTION_LABELS[action] + ' được', detail or 'Xem Bảng điều khiển & nhật ký.', self.open_panel, warning=True)
        threading.Thread(target=work, daemon=True).start()
        return True

    def _last_log_line(self):
        try:
            lines = (self.root.parent / 'data' / 'logs' / 'launcher.log').read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return ''
        meaningful = [line.strip() for line in lines if line.strip() and not line.strip().startswith(('At ', '+ ', '~'))]
        return meaningful[-1][:200] if meaningful else ''

    def open_panel(self):
        try:
            subprocess.Popen(self.integration.launch_command('--panel'), cwd=self.root, close_fds=True)
        except OSError as error:
            self.tray.notify('Không mở được bảng điều khiển', str(error), warning=True)

    def open_folder(self, path):
        path = Path(path)
        if not path.is_dir():
            self.tray.notify('Chưa có thư mục', str(path), warning=True)
            return
        try:
            os.startfile(str(path))  # noqa: S606 - opens Explorer on the user's own folder
        except (OSError, AttributeError) as error:
            self.tray.notify('Không mở được thư mục', str(error), warning=True)

    def open_output(self):
        # The folder chosen in Settings → Nơi lưu video (data/output-root.json), else VS_OUTPUT_DIR, else E:/Videos.
        root = os.environ.get('VS_OUTPUT_DIR') or 'E:/Videos'
        try:
            import json
            saved = json.loads((Path(__file__).resolve().parents[2] / 'data' / 'output-root.json').read_text(encoding='utf-8')).get('root')
            root = saved or root
        except (OSError, ValueError):
            pass
        self.open_folder(root)

    def toggle_startup(self):
        on = not self.integration.startup_enabled()
        self.integration.set_startup(on)
        self.tray.notify('Khởi động cùng Windows', 'Đã bật.' if on else 'Đã tắt.')

    def set_text_transport(self, value):
        if value == read_text_transport(self.root):
            return False
        if self.busy:
            self.tray.notify('VideoStudio', 'Đang ' + ACTION_LABELS[self.busy] + ', đổi kết nối sau.')
            return False
        if self.jobs.active:
            self.tray.notify('Chưa đổi kết nối', 'Có video đang chạy. Đổi sau khi video xong.', warning=True)
            return False
        write_text_transport(self.root, value)
        if server_ready(self.status):
            self.tray.notify('Đổi kết nối ChatGPT', 'Đang khởi động lại để dùng ' + TEXT_TRANSPORTS[value] + '.')
            self.start_action('restart')
        else:
            self.tray.notify('Đổi kết nối ChatGPT', 'Lần mở hệ thống tới sẽ dùng ' + TEXT_TRANSPORTS[value] + '.')
        return True

    def toggle_autostart(self):
        self._save_settings(autostart_services=not self.settings['autostart_services'])

    def toggle_notify(self):
        self._save_settings(notify=not self.settings['notify'])

    def toggle_shortcuts(self):
        on = not self.integration.shortcuts_installed()
        if not self.integration.set_shortcuts(on, self.root):
            self.tray.notify('Chưa tạo được shortcut', 'PowerShell không tạo được file .lnk.', warning=True)

    def quit(self):
        self.stopping.set()
        self.tray.stop()

    # ── background monitoring ──
    def poll_once(self):
        self.status = self.launcher.read_status()
        for event in self.jobs.poll():
            if not self.settings['notify']:
                continue
            if event['state'] == 'completed':
                folder = video_folder(event['output'])
                self.tray.notify('Video đã xong', event['title'], lambda f=folder: self.open_folder(f))
            else:
                self.tray.notify('Video bị lỗi ở bước ' + str(event['stage']), event['title'], self.open_studio, warning=True)

    def monitor(self, interval=4.0):
        while not self.stopping.is_set():
            try:
                self.poll_once()
            except Exception:
                pass
            self.stopping.wait(interval)

    def first_run(self):
        """First launch: add shortcuts like vTransfer. Later: keep paths current after rebuilds/moves."""
        try:
            if not self.settings['setup_done']:
                self.integration.set_shortcuts(True, self.root)
                self._save_settings(setup_done=True)
                self.tray.notify('VideoStudio chạy ở khay hệ thống', 'Bấm biểu tượng để vào Studio, chuột phải để xem menu.')
            elif self.integration.shortcuts_installed():
                self.integration.set_shortcuts(True, self.root)
            self.integration.refresh_startup()
        except Exception:
            pass

    def snapshot(self):
        """Self-check data for --tray-check (no window, no services touched)."""
        from windows_tray import flatten_menu
        commands, entries = flatten_menu(self.menu())
        key, tip = self.tray_state()
        icons = {k: str(p) for k, p in self.tray.icon_paths.items()} if hasattr(self.tray, 'icon_paths') else {}
        return {'ok': True, 'root': str(self.root), 'icon_state': key, 'tooltip': tip, 'menu_commands': len(commands),
                'icons_present': all(Path(p).is_file() for p in icons.values()) if icons else False, 'settings': self.settings}


def tray_main(argv, launcher):
    try:
        root = launcher.workspace_root()
    except RuntimeError as error:
        message_box(str(error), error=True)
        return 1
    if '--tray-check' in argv:
        destination = Path(argv[argv.index('--tray-check') + 1])
        app = TrayApp(root, launcher)
        app.poll_once()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(app.snapshot(), ensure_ascii=False, indent=2), encoding='utf-8')
        return 0
    guard = single_instance()
    if guard is None:
        message_box('VideoStudio đã chạy ở khay hệ thống (góc phải thanh tác vụ). Bấm biểu tượng để vào Studio.')
        return 0
    app = TrayApp(root, launcher)
    app.first_run()
    if '--autostart' in argv and app.settings['autostart_services']:
        app.start_action('start')
    threading.Thread(target=app.monitor, daemon=True).start()
    app.tray.run()
    app.stopping.set()
    return 0
