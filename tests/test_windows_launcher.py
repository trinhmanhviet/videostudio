import base64
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('windows_launcher',Path(__file__).resolve().parents[1]/'scripts/windows_launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class WindowsLauncherTests(unittest.TestCase):
    def test_actions_use_existing_guarded_scripts_without_force(self):
        for action in ('start','stop','restart'):
            args=launcher.command(Path("D:/Project's folder/Studio"),action)
            script=base64.b64decode(args[-1]).decode('utf-16le')
            self.assertIn("Project''s folder",script)
            self.assertIn(action+'_system.ps1',script)
            self.assertNotIn('-Force',script)
            self.assertEqual(args[0],'powershell.exe')

    def test_launch_reads_exit_code_without_inherited_pipes(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[]
            def spawn(args,**kwargs):
                self.assertNotEqual(kwargs['stdout'],subprocess.PIPE)
                kwargs['stdout'].write(b'fixture startup ready\n');kwargs['stdout'].flush()
                class Process:
                    def poll(self):return 0
                return Process()
            with patch.object(launcher.subprocess,'Popen',side_effect=spawn):
                self.assertEqual(launcher.run_action(Path(folder),'start',events.append),0)
            self.assertIn('fixture startup ready',''.join(value for kind,value in events if kind=='log'))

    def test_missing_services_do_not_crash_status_panel(self):
        with patch.object(launcher.urllib.request,'build_opener') as build:
            build.return_value.open.side_effect=OSError('offline')
            self.assertEqual(launcher.read_status(),{'server':None,'flow':None,'comfy':None})

    def test_source_launcher_locates_this_workspace(self):
        self.assertTrue((launcher.workspace_root()/'scripts/start_system.ps1').is_file())
