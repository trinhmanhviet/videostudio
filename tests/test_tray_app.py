"""Tray launcher logic (platform independent; the ctypes window itself is Windows-only)."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import tray_app  # noqa: E402
import windows_integration  # noqa: E402
from windows_tray import flatten_menu  # noqa: E402

READY = {'server': {'service': 'videostudio'}, 'flow': {'service': 'videostudio-dedicated-cdp', 'connected': True},
         'comfy': {'system': {}, 'devices': []}}
DOWN = {'server': None, 'flow': None, 'comfy': None}


class FakeTray:
    def __init__(self, app, icons):
        self.icon_paths = icons
        self.notes = []
        self.calls = []
        self.stopped = False

    def notify(self, title, text, action=None, warning=False):
        self.notes.append((title, text, action, warning))

    def call(self, fn):
        self.calls.append(fn)
        fn()

    def stop(self):
        self.stopped = True


def fake_integration(**overrides):
    module = Mock()
    module.resource_dir.return_value = SCRIPTS / 'assets'
    module.startup_enabled.return_value = False
    module.shortcuts_installed.return_value = False
    module.set_shortcuts.return_value = True
    module.launch_command.side_effect = lambda *args: ['VideoStudio.exe', *args]
    for key, value in overrides.items():
        setattr(module, key, value)
    return module


class TrayAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.launcher = Mock()
        self.launcher.read_status.return_value = DOWN
        self.launcher.run_action.return_value = 0
        self.integration = fake_integration()
        self.app = tray_app.TrayApp(self.root, self.launcher, FakeTray, self.integration)
        # Run worker threads inline so the test sees their effects.
        patcher = patch.object(tray_app.threading, 'Thread', side_effect=lambda target, daemon=True: Mock(start=target))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def labels(self, entries=None):
        result = {}
        for entry in entries if entries is not None else self.app.menu():
            if entry[0] == 'item':
                result[entry[1]] = entry[3]
            elif entry[0] == 'submenu':
                result.update(self.labels(entry[2]))
        return result

    def test_icon_and_tooltip_follow_service_state(self):
        self.assertEqual(self.app.tray_state()[0], 'stopped')
        self.app.status = READY
        key, tip = self.app.tray_state()
        self.assertEqual(key, 'ready')
        self.assertIn('Studio ✓ · Flow ✓ · Comfy ✓', tip)
        self.assertLessEqual(len(tip), 127)
        self.app.busy = 'restart'
        self.assertEqual(self.app.tray_state(), ('busy', self.app.tray_state()[1]))
        self.assertIn('khởi động lại', self.app.tray_state()[1])

    def test_menu_greys_actions_that_do_not_apply(self):
        stopped = self.labels()
        self.assertFalse(stopped['Mở hệ thống'].get('grayed'))
        self.assertTrue(stopped['Dừng hệ thống'].get('grayed'))
        self.assertTrue(stopped['Vào Studio'].get('default'))
        self.app.status = READY
        running = self.labels()
        self.assertTrue(running['Mở hệ thống'].get('grayed'))
        self.assertFalse(running['Dừng hệ thống'].get('grayed'))
        commands, _ = flatten_menu(self.app.menu())
        self.assertEqual(len(commands), 11)

    def test_click_when_stopped_starts_system_then_opens_studio_once(self):
        def start(root, action, emit):
            self.launcher.read_status.return_value = DOWN  # health may lag: must not loop into another start
            return 0
        self.launcher.run_action.side_effect = start
        self.app.on_left_click()
        self.launcher.run_action.assert_called_once()
        self.assertEqual(self.launcher.run_action.call_args.args[1], 'start')
        self.launcher.open_studio.assert_called_once()
        self.assertIsNone(self.app.busy)

    def test_click_when_running_opens_studio_without_actions(self):
        self.app.status = READY
        self.app.on_left_click()
        self.launcher.open_studio.assert_called_once()
        self.launcher.run_action.assert_not_called()

    def test_failed_stop_reports_guard_message_from_log(self):
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'launcher.log').write_text('Dang kiem tra...\nCo 1 tac vu video dang chay! Neu muon cuong che dung, hay chay voi tham so -Force.\n', encoding='utf-8')
        self.launcher.run_action.return_value = 1
        self.app.start_action('stop')
        title, text, action, warning = self.app.tray.notes[-1]
        self.assertTrue(warning)
        self.assertIn('dừng hệ thống', title)
        self.assertIn('tac vu video dang chay', text)

    def test_only_one_action_at_a_time(self):
        self.app.busy = 'start'
        self.assertFalse(self.app.start_action('restart'))
        self.launcher.run_action.assert_not_called()

    def test_settings_persist(self):
        self.app.toggle_notify()
        saved = json.loads((self.root / 'data' / 'tray.json').read_text(encoding='utf-8'))
        self.assertFalse(saved['notify'])
        again = tray_app.TrayApp(self.root, self.launcher, FakeTray, self.integration)
        self.assertFalse(again.settings['notify'])

    def test_first_run_creates_shortcuts_once(self):
        self.app.first_run()
        self.integration.set_shortcuts.assert_called_once_with(True, self.root)
        self.app.first_run()
        self.assertEqual(self.integration.set_shortcuts.call_count, 1)  # not installed any more → left alone
        self.integration.refresh_startup.assert_called()

    def test_panel_opens_as_separate_process(self):
        with patch.object(tray_app.subprocess, 'Popen') as popen:
            self.app.open_panel()
        self.assertEqual(popen.call_args.args[0], ['VideoStudio.exe', '--panel'])

    def test_quit_never_stops_services(self):
        self.app.quit()
        self.assertTrue(self.app.tray.stopped)
        self.launcher.run_action.assert_not_called()


class JobWatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'jobs.sqlite3'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE jobs(id TEXT, state TEXT, stage TEXT, output TEXT, request TEXT)')
            c.execute("INSERT INTO jobs VALUES('old','completed','verify','E:/Videos/a/data/old','{}')")
            c.execute("INSERT INTO jobs VALUES('j1','running','images','E:/Videos/phong-xa/data/j1',?)",
                      (json.dumps({'project': 'Phóng xạ', 'idea': 'Lịch sử phát hiện phóng xạ'}),))
            c.execute("INSERT INTO jobs VALUES('j2','running','music','E:/Videos/b/data/j2','{}')")

    def tearDown(self):
        self.temp.cleanup()

    def set_state(self, ident, state):
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE jobs SET state=? WHERE id=?', (state, ident))

    def test_first_poll_is_silent_then_reports_finished_and_failed_jobs(self):
        watcher = tray_app.JobWatcher(self.db)
        self.assertEqual(watcher.poll(), [])
        self.assertEqual(watcher.active, 2)
        self.set_state('j1', 'completed'); self.set_state('j2', 'failed')
        events = {e['id']: e for e in watcher.poll()}
        self.assertEqual(events['j1']['title'], 'Phóng xạ: Lịch sử phát hiện phóng xạ')
        self.assertEqual(events['j2']['state'], 'failed')
        self.assertEqual(watcher.active, 0)
        self.assertEqual(watcher.poll(), [])

    def test_cancelled_jobs_are_not_announced(self):
        watcher = tray_app.JobWatcher(self.db)
        watcher.poll()
        self.set_state('j1', 'cancelled')
        self.assertEqual(watcher.poll(), [])

    def test_video_folder_is_the_project_folder(self):
        self.assertEqual(tray_app.video_folder('E:/Videos/phong-xa/data/j1'), Path('E:/Videos/phong-xa'))
        self.assertEqual(tray_app.video_folder('E:/Videos/legacy-job'), Path('E:/Videos/legacy-job'))

    def test_missing_database_is_quiet(self):
        self.assertEqual(tray_app.JobWatcher(Path(self.temp.name) / 'none.sqlite3').poll(), [])


class IntegrationTests(unittest.TestCase):
    def test_source_launch_command_targets_the_launcher_script(self):
        command = windows_integration.launch_command('--panel')
        self.assertEqual(Path(command[1]).name, 'windows_launcher.py')
        self.assertEqual(command[-1], '--panel')

    def test_frozen_launch_command_uses_the_exe(self):
        with patch.object(windows_integration.sys, 'frozen', True, create=True), \
             patch.object(windows_integration.sys, 'executable', str(Path('D:/Projects/videostudio/VideoStudio.exe'))):
            self.assertEqual(windows_integration.launch_command('--autostart')[1:], ['--autostart'])
            self.assertTrue(windows_integration.launch_command()[0].endswith('VideoStudio.exe'))

    def test_icons_are_shipped(self):
        for name in ('videostudio', 'videostudio-ready', 'videostudio-busy', 'videostudio-stopped'):
            data = (SCRIPTS / 'assets' / (name + '.ico')).read_bytes()
            self.assertEqual(data[:4], b'\0\0\1\0')

    def test_flatten_menu_assigns_unique_ids(self):
        hits = []
        commands, entries = flatten_menu([('item', 'A', lambda: hits.append('a')), ('separator',),
                                          ('submenu', 'S', [('item', 'B', lambda: hits.append('b'), {'checked': True})])])
        self.assertEqual(sorted(commands), [1001, 1002])
        commands[1002]()
        self.assertEqual(hits, ['b'])
        self.assertEqual(entries[2][2][0][3], {'checked': True})


if __name__ == '__main__':
    unittest.main()
