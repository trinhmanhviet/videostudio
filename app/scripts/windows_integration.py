"""Per-user Windows integration for the VideoStudio tray: start with Windows and shortcuts.

Only writes HKEY_CURRENT_USER and the user's own Start Menu / Desktop folders.
"""
import os
from pathlib import Path
import subprocess
import sys

IS_WIN = sys.platform == 'win32'
NO_WINDOW = 0x08000000
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'VideoStudio'
LINK_NAME = 'VideoStudio.lnk'

if IS_WIN:
    import winreg


def resource_dir():
    """Bundled assets (PyInstaller) or scripts/assets in a source checkout."""
    base = getattr(sys, '_MEIPASS', None)
    return Path(base) / 'assets' if base else Path(__file__).resolve().parent / 'assets'


def launch_command(*args):
    """Command that starts this launcher again (frozen exe or pythonw + script)."""
    if getattr(sys, 'frozen', False):
        return [str(Path(sys.executable).resolve()), *args]
    python = Path(sys.executable)
    windowless = python.with_name('pythonw.exe')
    return [str(windowless if windowless.is_file() else python), str(Path(__file__).resolve().with_name('windows_launcher.py')), *args]


def quote(parts):
    return subprocess.list2cmdline([str(p) for p in parts])


def startup_enabled():
    if not IS_WIN:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_startup(on):
    if not IS_WIN:
        return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, quote(launch_command('--autostart')))
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    return True


def refresh_startup():
    """Keep the Run entry pointing at the current exe/script after the folder moves or is rebuilt."""
    if startup_enabled():
        set_startup(True)


# Parameters go through environment variables to avoid quoting/Unicode problems in PowerShell.
_LINK_PS = (
    "$p = if ($env:VS_FOLDER) { Join-Path ([Environment]::GetFolderPath($env:VS_FOLDER)) $env:VS_NAME } else { $env:VS_LINK };"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
    "$s.TargetPath=$env:VS_TARGET;$s.Arguments=$env:VS_ARGS;$s.WorkingDirectory=$env:VS_DIR;"
    "$s.IconLocation=$env:VS_ICON;$s.Description=$env:VS_DESC;$s.Save()"
)
_REMOVE_DESKTOP_PS = "Remove-Item -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('Desktop')) $env:VS_NAME)"


def _powershell(script, **env):
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
                                env={**os.environ, **{k: str(v) for k, v in env.items()}},
                                capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def start_menu_link():
    return Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / LINK_NAME


def shortcuts_installed():
    if not IS_WIN:
        return None
    return start_menu_link().is_file()


def set_shortcuts(on, workspace):
    if not IS_WIN:
        return False
    if on:
        command = launch_command()
        icon = command[0] if getattr(sys, 'frozen', False) else str(resource_dir() / 'videostudio.ico')
        common = dict(VS_TARGET=command[0], VS_ARGS=quote(command[1:]), VS_DIR=str(workspace), VS_ICON=icon,
                      VS_DESC='VideoStudio - tạo video tự động', VS_NAME=LINK_NAME)
        menu = _powershell(_LINK_PS, VS_FOLDER='', VS_LINK=str(start_menu_link()), **common)
        desktop = _powershell(_LINK_PS, VS_FOLDER='Desktop', VS_LINK='', **common)
        return menu and desktop
    try:
        start_menu_link().unlink()
    except OSError:
        pass
    _powershell(_REMOVE_DESKTOP_PS, VS_NAME=LINK_NAME)
    return True
