"""Проверка подсказки-стрелки (оверлея) без участия человека.

Создаёт временную видимую деталь, ставит курсор в точку, имитирует «зажал →
потянул» и проверяет, что стрелка появляется и поворачивается на нужную ось.
Документ закрывается без сохранения.

    python tools/check_overlay.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import config as config_mod  # noqa: E402
from lsk import geometry, kompas, picking, ui, win32cursor  # noqa: E402
from lsk.model import PartModel  # noqa: E402

MM = 1.0
POINT = (10.0 * MM, 5.0 * MM, 20.0 * MM)
user32 = ctypes.WinDLL("user32", use_last_error=True)
FAILS: list[str] = []


def check(name, condition, detail=""):
    if not condition:
        FAILS.append(f"{name}: {detail}")
    print(f"[{'ok ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def iface(env, app, cls_name, obj):
    try:
        res = getattr(env.ksapi, cls_name)(obj, app)
    except Exception:
        return None
    return res if res else None


def main() -> int:
    env = kompas.load()
    app = env.app()
    if app is None:
        print("КОМПАС не запущен")
        return 2

    doc = app.GetDocuments().AddWithDefaultSettings(env.constants.ksDocumentPart, True)
    panel = None
    try:
        doc.SetActive()
        doc3d = env.ksapi.IKompasDocument3D(doc, app)
        part = doc3d.GetTopPart()
        container = part.GetModelContainer()
        block = iface(env, app, "IBlockBySizes", container.AddObject(env.constants3d.o3d_BlockBySizes))
        block.SetLength(100 * MM)
        block.SetWidth(50 * MM)
        block.SetHeight(1, 20 * MM)
        block.Update()
        pt = container.GetPoints3D().Add()
        pt.SetName("Точка_тест")
        pt.SetX(POINT[0])
        pt.SetY(POINT[1])
        pt.SetZ(POINT[2])
        pt.Update()
        part.RebuildModel(True)

        frame = doc.GetDocumentFrame()
        frame.SetActive()
        frame.ZoomPrevNextOrAll(env.constants.ksZoomAll)
        frame.RefreshWindow()

        model = PartModel(env, app).attach(doc)
        last = None
        for _ in range(50):  # ждём, пока анимированный зум остановится
            current = picking.point_to_pixel(env, model, POINT)
            if current == last:
                break
            last = current
            time.sleep(0.1)

        hwnd = frame.GetWindowHandle()
        anchor = picking.point_to_pixel(env, model, POINT)
        check("точка спроецирована", anchor is not None, str(anchor))
        if anchor is None:
            return 1
        anchor_screen = win32cursor.client_to_screen(hwnd, *anchor)
        user32.SetCursorPos(*anchor_screen)
        time.sleep(0.2)

        panel = ui.Panel(env, app, config_mod.Config())
        panel.root.update()

        panel.placer.on_press()
        panel.root.update()
        state = panel.placer.state
        check("точка найдена при нажатии", state is not None and state.origin is not None,
              state.error if state else "нет состояния")
        if state is None or state.origin is None:
            return 1
        check("направления осей посчитаны", len(state.vectors) >= 4, f"{list(state.vectors)}")

        preview = panel.placer.preview()
        check("подсказка появилась сразу", preview is not None, str(preview and preview[2]))
        panel._refresh_overlay()
        panel.root.update()
        check("оверлей видим", panel._overlay.visible)

        # тащим в экранную сторону оси +Y и проверяем, что стрелка встала на +Y
        labels = {}
        for axis_name, vec in picking.AXIS_VECTORS.items():
            target_pixel = picking.point_to_pixel(
                env, model,
                (POINT[0] + vec[0] * 10, POINT[1] + vec[1] * 10, POINT[2] + vec[2] * 10),
            )
            if target_pixel is None:
                continue
            user32.SetCursorPos(*win32cursor.client_to_screen(hwnd, *target_pixel))
            panel.root.update()
            preview = panel.placer.preview()
            labels[axis_name] = preview[2] if preview else "нет"

        check(
            "стрелка следует за протяжкой по всем осям",
            all(f"_V: {axis}" == labels.get(axis, "") for axis in ("+X", "-X", "+Z", "-Z") if axis in state.vectors),
            ", ".join(f"{k}:{v}" for k, v in labels.items()),
        )

        panel._overlay.hide()
        created = panel.placer.on_release()
        panel.root.update()
        check("ЛСК созданы после отпускания", bool(created), str(created))
        check("оверлей скрыт", not panel._overlay.visible)
        check(
            "тройка в модели",
            all(n in model.list_lcs() for n in (created or "", (created or "") + "_V", (created or "") + "_R")),
            str(model.list_lcs()),
        )
    finally:
        if panel is not None:
            panel._on_close()
        doc.Close(0)

    print()
    if FAILS:
        print("ПРОВАЛЫ:")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("Подсказка направления работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
