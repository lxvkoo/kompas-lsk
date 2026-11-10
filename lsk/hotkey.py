"""Глобальная горячая клавиша через Win32 RegisterHotKey (без внешних зависимостей).

Работает, даже когда фокус в окне КОМПАСа: система присылает WM_HOTKEY в нашу
скрытую очередь, а отдельный поток пересылает событие в Tkinter.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostThreadMessageW.restype = wintypes.BOOL

_NAMED_KEYS = {
    "SPACE": 0x20, "ESC": 0x1B, "ESCAPE": 0x1B, "ENTER": 0x0D, "TAB": 0x09,
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
}


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+L' -> (modifiers, virtual_key)."""
    parts = [p.strip().upper() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    mods = MOD_NOREPEAT
    vk = None
    for part in parts:
        if part in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif part == "ALT":
            mods |= MOD_ALT
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part in ("WIN", "WINDOWS"):
            mods |= MOD_WIN
        elif len(part) == 1 and (part.isalnum() or part in "`-=[]\\;',./"):
            vk = ord(part)
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
        elif part.startswith("F") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])  # VK_F1 = 0x70
        else:
            return None
    return (mods, vk) if vk else None


class HotkeyListener:
    """Слушает одну глобальную горячую клавишу в фоновом потоке."""

    def __init__(self, spec: str, callback, hotkey_id: int = 0xB105):
        self.spec = spec
        self.callback = callback
        self.hotkey_id = hotkey_id
        self.error: str = ""
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()

    def start(self) -> bool:
        parsed = parse_hotkey(self.spec)
        if not parsed:
            self.error = f"не разобрал сочетание «{self.spec}»"
            return False
        self._thread = threading.Thread(target=self._run, args=(parsed,), daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return not self.error

    def _run(self, parsed):
        mods, vk = parsed
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self.hotkey_id, mods, vk):
            self.error = (
                f"не удалось занять «{self.spec}» (занято другой программой?) "
                f"код {ctypes.get_last_error()}"
            )
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    try:
                        self.callback()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread_id = None
