"""Проверка гипотезы: события приходят только пока крутится ksapi.RunLoop().

  1. открыть документ с параллелепипедом, подписаться на MouseDown;
  2. запустить ksapi.RunLoop() в отдельном потоке;
  3. кликнуть настоящим кликом (SendInput) дважды;
  4. посмотреть, вызвался ли обработчик, и жива ли связь;
  5. остановить цикл.

    python tools/check_click3.py
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import kompas  # noqa: E402

MM = 1.0  # единицы API КОМПАСа — миллиметры

user32 = ctypes.WinDLL("user32", use_last_error=True)
ULONG_PTR = ctypes.c_ulonglong


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


def step(text):
    print(text, flush=True)


def real_click(sx, sy):
    user32.SetCursorPos(int(sx), int(sy))
    time.sleep(0.15)
    for flag in (0x0002, 0x0004):
        inp = INPUT(type=0, u=INPUT._U(mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.1)


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
    pt = wintypes.POINT(cx, cy)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    step(f"hwnd={hwnd} экранные=({pt.x},{pt.y})")

    fired: list = []
    cb = env.ksapi.IDocumentFrameEvents_OnMouseDownHandler(
        lambda keys, x, y: fired.append((x, y)) or False
    )
    frame.Events().AddMouseDownHandler("check_click3", cb)
    step("подписка оформлена")

    loop_thread = threading.Thread(target=env.ksapi.RunLoop, daemon=True)
    loop_thread.start()
    step("RunLoop запущен в отдельном потоке")
    time.sleep(0.5)

    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    step("клик 1")
    real_click(pt.x, pt.y)
    time.sleep(0.7)
    step(f"   срабатываний: {len(fired)}")
    step("клик 2")
    real_click(pt.x, pt.y)
    time.sleep(0.7)
    step(f"   срабатываний всего: {len(fired)} {fired[:5]}")

    try:
        part.GetName()
        step("   связь с КОМПАСом жива")
    except Exception as exc:
        step(f"   !!! связь потеряна: {exc}")
        return 1

    env.ksapi.StopLoop()
    step("StopLoop вызван")
    frame.Events().RemoveAllHandlers("check_click3")
    doc.Close(0)
    step("ГОТОВО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
