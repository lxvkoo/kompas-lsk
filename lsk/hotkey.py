"""Горячая клавиша с отслеживанием нажатия И отпускания (Win32, без зависимостей).

`RegisterHotKey` умеет сообщать только о нажатии, а нам нужен жест
«зажал клавишу → потянул мышью → отпустил». Поэтому состояние клавиши
опрашивается через `GetAsyncKeyState`; дополнительно клавиша регистрируется
глобально, чтобы КОМПАС её не получал.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL

_NAMED_KEYS = {
    "SPACE": 0x20, "ESC": 0x1B, "ESCAPE": 0x1B, "ENTER": 0x0D, "TAB": 0x09,
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
}


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """'Ctrl+1' -> (модификаторы, виртуальный код клавиши)."""
    parts = [p.strip().upper() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
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
            vk = 0x6F + int(part[1:])
        else:
            return None
    return (mods, vk) if vk is not None else None


def _pressed(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class KeyWatcher:
    """Следит за комбинацией: сообщает о нажатии и об отпускании."""

    def __init__(self, spec: str, on_press, on_release, interval: float = 0.02,
                 hotkey_id: int = 0xB10C):
        self.spec = spec
        self.on_press = on_press
        self.on_release = on_release
        self.interval = interval
        self.hotkey_id = hotkey_id
        self.error: str = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._parsed = parse_hotkey(spec)
        self._registered = False

    # ------------------------------------------------------------------
    def start(self) -> bool:
        if not self._parsed:
            self.error = f"не разобрал сочетание «{self.spec}»"
            return False
        mods, vk = self._parsed
        # пробуем «забрать» клавишу у КОМПАСа (не критично, если не выйдет)
        self._registered = bool(user32.RegisterHotKey(None, self.hotkey_id, mods | MOD_NOREPEAT, vk))
        if not self._registered:
            self.error = "клавиша занята другой программой (всё равно слежу за ней)"
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _combo_down(self) -> bool:
        mods, vk = self._parsed
        if mods & MOD_CONTROL and not _pressed(VK_CONTROL):
            return False
        if mods & MOD_ALT and not _pressed(VK_MENU):
            return False
        if mods & MOD_SHIFT and not _pressed(VK_SHIFT):
            return False
        if mods & MOD_WIN and not (_pressed(VK_LWIN) or _pressed(VK_RWIN)):
            return False
        return _pressed(vk)

    def _run(self) -> None:
        previous = False
        while not self._stop.is_set():
            try:
                down = self._combo_down()
            except Exception:
                down = False
            if down and not previous:
                try:
                    self.on_press()
                except Exception:
                    pass
            elif previous and not down:
                try:
                    self.on_release()
                except Exception:
                    pass
            previous = down
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._registered:
            user32.UnregisterHotKey(None, self.hotkey_id)
            self._registered = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
