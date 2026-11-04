"""Windows notification-area (tray) icon written with ctypes only (same approach as vTransfer).

The app object supplies:
  tray_state()      -> (icon_key, tooltip)     called every second on the tray thread; must not block
  menu()            -> list of entries          ('item', text, callback, {'checked','grayed','default'}),
                                                ('separator',), ('submenu', text, [entries])
  on_left_click()                               called on a single left click
Other threads talk to the tray only through call() / notify() / stop().
"""
import queue
import sys
import time
import traceback

IS_WIN = sys.platform == 'win32'

if IS_WIN:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [('cbSize', wt.UINT), ('style', wt.UINT), ('lpfnWndProc', WNDPROC),
                    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int), ('hInstance', wt.HINSTANCE),
                    ('hIcon', wt.HICON), ('hCursor', wt.HANDLE), ('hbrBackground', wt.HBRUSH),
                    ('lpszMenuName', wt.LPCWSTR), ('lpszClassName', wt.LPCWSTR), ('hIconSm', wt.HICON)]

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wt.DWORD), ('Data2', wt.WORD), ('Data3', wt.WORD), ('Data4', ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT), ('uFlags', wt.UINT),
                    ('uCallbackMessage', wt.UINT), ('hIcon', wt.HICON), ('szTip', wt.WCHAR * 128),
                    ('dwState', wt.DWORD), ('dwStateMask', wt.DWORD), ('szInfo', wt.WCHAR * 256),
                    ('uVersion', wt.UINT), ('szInfoTitle', wt.WCHAR * 64), ('dwInfoFlags', wt.DWORD),
                    ('guidItem', GUID), ('hBalloonIcon', wt.HICON)]

    def _sig(fn, args, res=None):
        fn.argtypes = args
        if res is not None:
            fn.restype = res

    _sig(user32.DefWindowProcW, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM], LRESULT)
    _sig(user32.RegisterClassExW, [ctypes.POINTER(WNDCLASSEXW)], wt.ATOM)
    _sig(user32.CreateWindowExW, [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID], wt.HWND)
    _sig(user32.DestroyWindow, [wt.HWND], wt.BOOL)
    _sig(user32.LoadImageW, [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT], wt.HANDLE)
    _sig(user32.DestroyIcon, [wt.HICON], wt.BOOL)
    _sig(user32.CreatePopupMenu, [], wt.HMENU)
    _sig(user32.AppendMenuW, [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR], wt.BOOL)
    _sig(user32.SetMenuDefaultItem, [wt.HMENU, wt.UINT, wt.UINT], wt.BOOL)
    _sig(user32.TrackPopupMenu, [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p], ctypes.c_int)
    _sig(user32.DestroyMenu, [wt.HMENU], wt.BOOL)
    _sig(user32.GetCursorPos, [ctypes.POINTER(wt.POINT)], wt.BOOL)
    _sig(user32.SetForegroundWindow, [wt.HWND], wt.BOOL)
    _sig(user32.PostMessageW, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL)
    _sig(user32.RegisterWindowMessageW, [wt.LPCWSTR], wt.UINT)
    _sig(user32.SetTimer, [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p], ctypes.c_size_t)
    _sig(user32.GetMessageW, [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT], wt.BOOL)
    _sig(user32.TranslateMessage, [ctypes.POINTER(wt.MSG)], wt.BOOL)
    _sig(user32.DispatchMessageW, [ctypes.POINTER(wt.MSG)], LRESULT)
    _sig(user32.PostQuitMessage, [ctypes.c_int])
    _sig(user32.GetSystemMetrics, [ctypes.c_int], ctypes.c_int)
    _sig(user32.MessageBoxW, [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT], ctypes.c_int)
    _sig(shell32.Shell_NotifyIconW, [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)], wt.BOOL)
    _sig(kernel32.GetModuleHandleW, [wt.LPCWSTR], wt.HMODULE)
    _sig(kernel32.CreateMutexW, [wt.LPVOID, wt.BOOL, wt.LPCWSTR], wt.HANDLE)

WM_NULL, WM_DESTROY, WM_CLOSE, WM_TIMER = 0x0000, 0x0002, 0x0010, 0x0113
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_APP = 0x8000
WM_TRAY, WM_WAKE = WM_APP + 1, WM_APP + 2
NIN_BALLOONUSERCLICK = 0x0405
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO, NIIF_WARNING = 0x01, 0x02
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x0002, 0x0080, 0x0100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON = 49
ERROR_ALREADY_EXISTS = 183
FIRST_COMMAND = 1001


def message_box(text, title='VideoStudio', error=False):
    if IS_WIN:
        user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    else:
        print(title + ': ' + text, file=sys.stderr)


def single_instance(name='Local\\VideoStudioTray'):
    """Return a handle while this is the only tray process, else None. Keep the handle alive."""
    if not IS_WIN:
        return object()
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def flatten_menu(entries, first=FIRST_COMMAND):
    """Assign command IDs to callbacks; returns ({id: callback}, normalized entries). Pure for tests."""
    commands = {}
    next_id = [first]

    def walk(items):
        normalized = []
        for entry in items:
            if entry[0] == 'separator':
                normalized.append(('separator',))
            elif entry[0] == 'submenu':
                normalized.append(('submenu', entry[1], walk(entry[2])))
            else:
                options = entry[3] if len(entry) > 3 else {}
                ident = next_id[0]
                next_id[0] += 1
                commands[ident] = entry[2]
                normalized.append(('item', ident, entry[1], options))
        return normalized
    return commands, walk(entries)


class Tray:
    def __init__(self, app, icons, app_id='VideoStudio'):
        self.app = app
        self.icon_paths = icons
        self.app_id = app_id
        self.hwnd = None
        self.q = queue.Queue()
        self._tip = None
        self._icon_key = None
        self._last_open = 0.0
        self._balloon_action = None
        self.handles = {}
        self.msg_taskbar = 0
        if IS_WIN:
            self._proc = WNDPROC(self._wndproc)  # keep a reference so it is not garbage collected

    # ── thread-safe entry points ──
    def call(self, fn):
        self.q.put(fn)
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_WAKE, 0, 0)

    def notify(self, title, text, action=None, warning=False):
        self.call(lambda: self._balloon(title, text, action, warning))

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ── main loop (main thread) ──
    def run(self):
        try:
            shell32.SetCurrentProcessExplicitAppUserModelID(self.app_id)
        except Exception:
            pass
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(WNDCLASSEXW)
        window_class.lpfnWndProc = self._proc
        window_class.hInstance = instance
        window_class.lpszClassName = 'VideoStudioTrayWindow'
        user32.RegisterClassExW(ctypes.byref(window_class))
        self.hwnd = user32.CreateWindowExW(0, window_class.lpszClassName, 'VideoStudio tray', 0, 0, 0, 0, 0,
                                           None, None, instance, None)
        if not self.hwnd:
            raise OSError('CreateWindowExW failed: %d' % ctypes.get_last_error())
        self.msg_taskbar = user32.RegisterWindowMessageW('TaskbarCreated')
        size = user32.GetSystemMetrics(SM_CXSMICON) or 16
        for key, path in self.icon_paths.items():
            self.handles[key] = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        self._add_icon()
        user32.SetTimer(self.hwnd, 1, 1000, None)
        # Work queued before the window existed (e.g. an early notification).
        user32.PostMessageW(self.hwnd, WM_WAKE, 0, 0)
        message = wt.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        for handle in set(self.handles.values()):
            if handle:
                user32.DestroyIcon(handle)

    # ── icon ──
    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        return nid

    def _handle(self, key):
        return self.handles.get(key) or next((h for h in self.handles.values() if h), None)

    def _add_icon(self):
        key, tip = self.app.tray_state()
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._handle(key)
        nid.szTip = tip[:127]
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._icon_key, self._tip = key, tip

    def _refresh(self):
        key, tip = self.app.tray_state()
        if key != self._icon_key or tip != self._tip:
            nid = self._nid(NIF_ICON | NIF_TIP)
            nid.hIcon = self._handle(key)
            nid.szTip = tip[:127]
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
            self._icon_key, self._tip = key, tip

    def _balloon(self, title, text, action=None, warning=False):
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = (text or ' ')[:255]
        nid.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
        self._balloon_action = action
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _remove_icon(self):
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))

    # ── menu ──
    def _build(self, menu, entries):
        for entry in entries:
            if entry[0] == 'separator':
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            elif entry[0] == 'submenu':
                sub = user32.CreatePopupMenu()
                self._build(sub, entry[2])
                user32.AppendMenuW(menu, MF_POPUP, sub, entry[1])
            else:
                _, ident, text, options = entry
                flags = MF_STRING | (MF_CHECKED if options.get('checked') else 0) | (MF_GRAYED if options.get('grayed') else 0)
                user32.AppendMenuW(menu, flags, ident, text)
                if options.get('default'):
                    user32.SetMenuDefaultItem(menu, ident, 0)

    def _menu(self):
        commands, entries = flatten_menu(self.app.menu())
        menu = user32.CreatePopupMenu()
        self._build(menu, entries)
        point = wt.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD, point.x, point.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)  # also destroys attached submenus
        if chosen in commands:
            commands[chosen]()

    # ── window procedure ──
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event == WM_LBUTTONUP:
                    if time.time() - self._last_open > 1.5:  # a double click must not open twice
                        self._last_open = time.time()
                        self.app.on_left_click()
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                elif event == NIN_BALLOONUSERCLICK:
                    action, self._balloon_action = self._balloon_action, None
                    (action or self.app.on_left_click)()
                return 0
            if msg == WM_WAKE:
                while True:
                    try:
                        fn = self.q.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        fn()
                    except Exception:
                        traceback.print_exc()
                return 0
            if msg == WM_TIMER:
                self._refresh()
                return 0
            if msg == self.msg_taskbar and msg:  # Explorer restarted: add the icon again
                self._add_icon()
                return 0
            if msg == WM_CLOSE:
                self._remove_icon()
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            traceback.print_exc()
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
