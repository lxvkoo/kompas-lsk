"""Разбор падения КОМПАСа на перехвате клика.

Шаги:
  0 — просто открыть документ и кликнуть по нему НАСТОЯЩИМ кликом (SendInput),
      без подписки на события: понять, не убивает ли КОМПАС сам клик;
  1 — подписаться на MouseDown, кликнуть, посмотреть, вызвался ли обработчик;
  2 — проверить альтернативу: позиция курсора -> ScreenToClient -> GetPickRay.

Каждый шаг печатается с flush: если КОМПАС умрёт, будет видно, где.

    python tools/check_click2.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import kompas  # noqa: E402

MM = 1.0  # единицы API КОМПАСа — миллиметры

user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def step(text):
    print(text, flush=True)


def real_click(screen_x, screen_y):
    user32.SetCursorPos(int(screen_x), int(screen_y))
    time.sleep(0.15)
    for flag in (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
        inp = INPUT(type=0, u=INPUT._U(mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.08)


def client_to_screen(hwnd, x, y):
    pt = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def iface(env, app, cls_name, obj):
    try:
        res = getattr(env.ksapi, cls_name)(obj, app)
    except Exception as exc:
        step(f"   ! cast {cls_name}: {exc}")
        return None
    return res if res else None


def main() -> int:
    env = kompas.load()
    app = env.app()
    if app is None:
        step("КОМПАС не запущен")
        return 2

    doc = app.GetDocuments().AddWithDefaultSettings(env.constants.ksDocumentPart, True)
    doc3d = env.ksapi.IKompasDocument3D(doc, app)
    part = doc3d.GetTopPart()
    block = iface(env, app, "IBlockBySizes", part.GetModelContainer().AddObject(env.constants3d.o3d_BlockBySizes))
    if block:
        block.SetLength(100 * MM)
        block.SetWidth(50 * MM)
        block.SetHeight(1, 20 * MM)
        block.Update()
    part.RebuildModel(True)

    frame = doc.GetDocumentFrame()
    frame.SetActive()
    frame.ZoomPrevNextOrAll(env.constants.ksZoomAll)
    frame.RefreshWindow()
    left, top, right, bottom = frame.GetWorkAreaRect(0, 0, 0, 0)
    cx, cy = (left + right) // 2, (top + bottom) // 2
    hwnd = frame.GetWindowHandle()
    sx, sy = client_to_screen(hwnd, cx, cy)
    step(f"hwnd={hwnd} клиентские=({cx},{cy}) экранные=({sx},{sy})")

    def alive(tag):
        try:
            part.GetName()
            step(f"   связь жива ({tag})")
            return True
        except Exception as exc:
            step(f"   !!! СВЯЗЬ ПОТЕРЯНА ({tag}): {exc}")
            return False

    step("=== шаг 0: настоящий клик БЕЗ подписки на события ===")
    alive("до клика")
    real_click(sx, sy)
    time.sleep(0.8)
    if not alive("после клика без подписки"):
        step("ВЫВОД: КОМПАС падает от самого клика (синтетика не подходит)")
        return 1

    step("=== шаг 1: подписка на MouseDown + настоящий клик ===")
    events = frame.Events()
    fired: list = []
    cb = env.ksapi.IDocumentFrameEvents_OnMouseDownHandler(
        lambda keys, x, y: fired.append((x, y)) or False
    )
    events.AddMouseDownHandler("check_click2", cb)
    alive("после подписки")
    real_click(sx, sy)
    time.sleep(0.8)
    step(f"   срабатываний обработчика: {len(fired)} {fired[:3]}")
    if not alive("после клика с подпиской"):
        step("ВЫВОД: подписка на MouseDown роняет КОМПАС")
        return 1
    events.RemoveAllHandlers("check_click2")
    alive("после отписки")

    step("=== шаг 2: позиция курсора -> GetPickRay (без событий) ===")
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    user32.ScreenToClient(hwnd, ctypes.byref(point))
    step(f"   курсор в клиентских координатах: ({point.x},{point.y})")
    ok, px, py, pz, dx, dy, dz = frame.GetPickRay(point.x, point.y, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    step(f"   GetPickRay ok={ok} точка=({px / MM:.2f},{py / MM:.2f},{pz / MM:.2f}) мм")
    if ok:
        objects = doc3d.PickModelObjects([px, py, pz, dx, dy, dz], None)
        step(f"   объектов по лучу: {len(objects or [])}")
    alive("после GetPickRay")

    step("закрываю документ")
    doc.Close(0)
    step("ГОТОВО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
