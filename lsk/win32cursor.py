"""Win32-мелочи, которые нужны инструменту (без pywin32).

Зачем: события мыши из API КОМПАСа в Python не доставляются (проверено на v25 —
обработчик не вызывается ни при настоящем клике, ни при синтетическом), поэтому
точку берём по позиции курсора в момент нажатия горячей клавиши.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
user32.ScreenToClient.restype = wintypes.BOOL
user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.GetClientRect.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))


def cursor_client_pos(hwnd: int) -> tuple[int, int]:
    """Позиция курсора в клиентских координатах окна (-1, -1 при ошибке)."""
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return (-1, -1)
    if not user32.ScreenToClient(wintypes.HWND(hwnd), ctypes.byref(point)):
        return (-1, -1)
    return (point.x, point.y)


def client_size(hwnd: int) -> tuple[int, int]:
    """Размер клиентской области окна (в ней же работают оконные координаты КОМПАСа)."""
    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return (0, 0)
    return (rect.right - rect.left, rect.bottom - rect.top)


def cursor_screen_pos() -> tuple[int, int] | None:
    """Позиция курсора в экранных координатах."""
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return None
    return (point.x, point.y)


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(x, y)
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
    return (point.x, point.y)


def process_id_of_window(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def foreground_process_id() -> int:
    hwnd = user32.GetForegroundWindow()
    return process_id_of_window(hwnd) if hwnd else 0


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)
