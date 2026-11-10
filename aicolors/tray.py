"""Iconița AI Colors din bara de lângă ceas (Windows), fără pachete externe.

Click: deschide fereastra. Click dreapta: meniu (Deschide, Pauză lumini, Pornește cu
Windows, Ieșire). Tooltip cu starea; notificare la baterie slabă la mouse/căști.
Rulează pe firul principal; restul aplicației (server, motor) e pe alte fire.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("bara de lângă ceas există doar pe Windows")

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 1

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO, NIIF_WARNING = 0x01, 0x02
MF_STRING, MF_CHECKED, MF_SEPARATOR, MF_GRAYED = 0x0000, 0x0008, 0x0800, 0x0001
TPM_RIGHTBUTTON, TPM_BOTTOMALIGN, TPM_RETURNCMD = 0x0002, 0x0020, 0x0100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
IDI_APPLICATION = 32512


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", POINT)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.LPVOID]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadIconW.restype = wintypes.HICON
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

# (id, text) – None = separator; textul poate fi o funcție (pentru bife)
MenuItem = Tuple[int, str, bool, bool]  # id, text, bifat, activ


class Tray:
    TIMER_ID = 1

    def __init__(self, icon_path: Path, tooltip: Callable[[], str],
                 menu: Callable[[], List[Optional[MenuItem]]], on_command: Callable[[int], None],
                 on_click: Callable[[], None], on_timer: Optional[Callable[["Tray"], None]] = None,
                 on_shutdown: Optional[Callable[[], None]] = None,
                 timer_ms: int = 5000):
        self.tooltip = tooltip
        self.menu = menu
        self.on_command = on_command
        self.on_click = on_click
        self.on_timer = on_timer
        self.on_shutdown = on_shutdown
        self.timer_ms = timer_ms
        self._proc = WNDPROC(self._wndproc)  # referință păstrată, altfel callback-ul dispare
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "AIColorsTray"
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "AIColorsTray", "AI Colors", 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise OSError(f"nu pot crea fereastra pentru bară: {ctypes.WinError(ctypes.get_last_error())}")
        self.hicon = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE) or \
            user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._add()
        user32.SetTimer(self.hwnd, self.TIMER_ID, self.timer_ms, None)

    # ------------------------------------------------------------ iconiță

    def _nid(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = (self.tooltip() or "AI Colors")[:127]
        return nid

    def _add(self) -> None:
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)))

    def refresh(self) -> None:
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid(NIF_TIP | NIF_ICON)))

    def notify(self, title: str, text: str, warning: bool = False) -> None:
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # ------------------------------------------------------------ evenimente

    def _show_menu(self) -> None:
        hmenu = user32.CreatePopupMenu()
        try:
            for item in self.menu():
                if item is None:
                    user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                    continue
                cmd_id, text, checked, enabled = item
                flags = MF_STRING | (MF_CHECKED if checked else 0) | (0 if enabled else MF_GRAYED)
                user32.AppendMenuW(hmenu, flags, cmd_id, text)
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self.hwnd)  # altfel meniul nu se închide la click în altă parte
            cmd = user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                                        pt.x, pt.y, 0, self.hwnd, None)
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(hmenu)
        if cmd:
            self._safe(self.on_command, cmd)

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("bara de lângă ceas")

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            result = self._handle(hwnd, msg, wparam, lparam)
        except Exception:
            log.exception("bara de lângă ceas: mesaj %#x", msg)
            result = None
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam) if result is None else result

    def _handle(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._safe(self.on_click)
            elif event == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_TIMER and wparam == self.TIMER_ID:
            self._safe(self.refresh)
            if self.on_timer:
                self._safe(self.on_timer, self)
            return 0
        if msg == self.taskbar_created:  # Explorer a repornit: iconița trebuie adăugată din nou
            self._add()
            return 0
        if msg == WM_QUERYENDSESSION:  # Windows se oprește / repornește / deloghează
            return 1
        if msg == WM_ENDSESSION:
            if wparam and self.on_shutdown:
                self._safe(self.on_shutdown)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.KillTimer(hwnd, self.TIMER_ID)
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
            user32.PostQuitMessage(0)
            return 0
        return None

    def run(self) -> None:
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self) -> None:
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


# ---------------------------------------------------------------------- legătura cu aplicația

OPEN, PAUSE, AUTOSTART, EXIT = 1, 2, 3, 9


def run_tray(app, open_window: Callable[[str], None], icon_path: Path, quiet: bool = False) -> None:
    from . import autostart
    from .peripherals.logitech import battery_warnings

    warned: Dict[str, bool] = {}

    def tooltip() -> str:
        if app.engine.paused:
            return "AI Colors - în pauză"
        st = app.api_state()
        ok = sum(1 for d in st["devices"] if d["connected"])
        cs2 = "CS2 conectat" if st["game"].get("connected") else "aștept CS2"
        return f"AI Colors - {cs2}, {ok}/{len(st['devices'])} dispozitive"

    def menu():
        return [
            (OPEN, "Deschide AI Colors", False, True),
            (PAUSE, "Pauză lumini", app.engine.paused, True),
            None,
            (AUTOSTART, "Pornește odată cu Windows", autostart.is_enabled(), True),
            None,
            (EXIT, "Ieșire", False, True),
        ]

    def on_command(cmd: int) -> None:
        if cmd == OPEN:
            open_window(app.ui_url)
        elif cmd == PAUSE:
            app.engine.set_paused(not app.engine.paused)
        elif cmd == AUTOSTART:
            autostart.set_enabled(not autostart.is_enabled(), app.cfg.path)
        elif cmd == EXIT:
            tray.close()

    def on_timer(t: Tray) -> None:
        if not (app._engine_thread and app._engine_thread.is_alive()):  # oprit din interfață
            t.close()
            return
        if app.peripherals:
            for msg in battery_warnings(app.peripherals.snapshot(), warned):
                t.notify("Baterie slabă", msg, warning=True)

    def on_shutdown() -> None:
        if app.cfg.lights_off_on_shutdown:
            app.engine.blackout()
        app.stop()  # tastatura: efectul și culorile tale înapoi

    tray = Tray(icon_path, tooltip, menu, on_command, lambda: open_window(app.ui_url), on_timer, on_shutdown)
    if not quiet:
        tray.notify("AI Colors", "Rulează lângă ceas. Click pe iconiță pentru setări.")
    tray.run()
