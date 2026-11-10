"""Проверка перехвата клика БЕЗ участия человека: клик посылается в окно КОМПАСа
через PostMessage. Так можно понять, что именно роняет КОМПАС.

Варианты обработчика:
  A — только Python-код, возвращает False;
  B — внутри вызывается API (IPressedKeys), возвращает False;
  C — только Python-код, возвращает True (клик «съедается»).

После каждого варианта вызывается безобидный метод API, чтобы проверить,
жива ли связь с КОМПАСом.

    python tools/check_click.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import kompas  # noqa: E402

MM = 0.001
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL


def step(text):
    print(text, flush=True)


def click(hwnd, x, y):
    lparam = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


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
    step(f"окно: hwnd={hwnd} центр=({cx},{cy})")

    events = frame.Events()
    fired: list = []

    def alive(tag):
        try:
            name = part.GetName()
            step(f"   связь жива после {tag} (part.GetName -> {name!r})")
            return True
        except Exception as exc:
            step(f"   !!! СВЯЗЬ ПОТЕРЯНА после {tag}: {exc}")
            return False

    # ---------- A: чистый Python, возвращает False ----------
    step("--- A: обработчик без вызовов API, return False ---")
    cb_a = env.ksapi.IDocumentFrameEvents_OnMouseDownHandler(
        lambda keys, x, y: fired.append(("A", x, y)) or False
    )
    events.AddMouseDownHandler("check_a", cb_a)
    click(hwnd, cx, cy)
    time.sleep(0.6)
    step(f"   срабатываний: {len(fired)}")
    alive("A")
    events.RemoveAllHandlers("check_a")

    # ---------- B: внутри обработчика вызов API ----------
    step("--- B: внутри обработчика IPressedKeys ---")
    result_b: list = []

    def handler_b(keys_ref, x, y):
        try:
            keys = env.ksapi.IPressedKeys(keys_ref, app)
            result_b.append(bool(keys) and keys.IsMouseLeftButton())
        except Exception as exc:
            result_b.append(f"ошибка: {exc}")
        return False

    cb_b = env.ksapi.IDocumentFrameEvents_OnMouseDownHandler(handler_b)
    events.AddMouseDownHandler("check_b", cb_b)
    click(hwnd, cx, cy)
    time.sleep(0.6)
    step(f"   результат: {result_b}")
    alive("B")
    events.RemoveAllHandlers("check_b")

    # ---------- C: чистый Python, возвращает True ----------
    step("--- C: обработчик без API, return True ---")
    fired_c: list = []
    cb_c = env.ksapi.IDocumentFrameEvents_OnMouseDownHandler(
        lambda keys, x, y: fired_c.append((x, y)) or True
    )
    events.AddMouseDownHandler("check_c", cb_c)
    click(hwnd, cx, cy)
    time.sleep(0.6)
    step(f"   срабатываний: {len(fired_c)}")
    alive("C")
    events.RemoveAllHandlers("check_c")

    step("--- D: работа с моделью сразу после клика (как в place()) ---")
    try:
        ok, px, py, pz, dx, dy, dz = frame.GetPickRay(cx, cy, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        step(f"   GetPickRay ok={ok}")
        objects = doc3d.PickModelObjects([px, py, pz, dx, dy, dz], None)
        step(f"   объектов: {len(objects or [])}")
        alive("D")
    except Exception as exc:
        step(f"   !!! ошибка на D: {exc}")

    step("закрываю документ")
    doc.Close(0)  # kdDoNotSaveChanges
    step("ГОТОВО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
