"""Сквозной тест без человека: точка в модели -> курсор -> расстановка ЛСК.

Создаёт видимый временный документ с параллелепипедом 100×50×20 мм и 3D-точкой
на верхней грани, ставит настоящий курсор в экранную позицию этой точки, затем
вызывает тот же код, что и горячая клавиша (`Placer.place_under_cursor`), и
проверяет координаты созданных ЛСК.

    python tools/check_e2e.py
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import config as config_mod  # noqa: E402
from lsk import geometry, kompas, picking, win32cursor  # noqa: E402
from lsk.model import PartModel  # noqa: E402
from lsk.session import Placer  # noqa: E402

MM = 1.0  # единицы API КОМПАСа — миллиметры
POINT = (10.0 * MM, 5.0 * MM, 20.0 * MM)  # точка на верхней грани блока
OFFSET = 10.0
NAME = "E2E_ЛСК"

user32 = ctypes.WinDLL("user32", use_last_error=True)
FAILS: list[str] = []


def check(name, condition, detail=""):
    if not condition:
        FAILS.append(f"{name}: {detail}")
    print(f"[{'ok ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def iface(env, app, cls_name, obj):
    try:
        res = getattr(env.ksapi, cls_name)(obj, app)
    except Exception as exc:
        print("   ! cast:", exc, flush=True)
        return None
    return res if res else None


def near(a, b, eps=1e-6):
    return all(abs(x - y) <= eps for x, y in zip(a, b))


def main() -> int:
    env = kompas.load()
    app = env.app()
    if app is None:
        print("КОМПАС не запущен")
        return 2

    doc = app.GetDocuments().AddWithDefaultSettings(env.constants.ksDocumentPart, True)
    try:
        doc.SetActive()
        # новый документ должен стать активным, иначе Placer возьмёт чужой
        for _ in range(30):
            active = app.GetActiveDocument()
            if active and active.GetFullPath() == doc.GetFullPath():
                break
            doc.SetActive()
            import time as _t

            _t.sleep(0.1)
        else:
            check("временный документ активен", False, "КОМПАС не переключился на новый документ")
            return 1

        doc3d = env.ksapi.IKompasDocument3D(doc, app)
        part = doc3d.GetTopPart()
        container = part.GetModelContainer()

        block = iface(env, app, "IBlockBySizes", container.AddObject(env.constants3d.o3d_BlockBySizes))
        block.SetLength(100 * MM)
        block.SetWidth(50 * MM)
        block.SetHeight(1, 20 * MM)
        block.Update()

        pt = container.GetPoints3D().Add()
        pt.SetName("Тест_точка")
        pt.SetX(POINT[0])
        pt.SetY(POINT[1])
        pt.SetZ(POINT[2])
        pt.Update()
        part.RebuildModel(True)

        frame = doc.GetDocumentFrame()
        frame.SetActive()
        frame.ZoomPrevNextOrAll(env.constants.ksZoomAll)
        frame.RefreshWindow()

        # ZoomPrevNextOrAll в v25 анимирован: ждём, пока вид перестанет ехать
        import time as _time

        model_wait = PartModel(env, app).attach(doc)
        last = None
        for _ in range(50):
            current = picking.point_to_pixel(env, model_wait, POINT)
            if current is not None and current == last:
                break
            last = current
            _time.sleep(0.1)

        hwnd = frame.GetWindowHandle()
        width, height = win32cursor.client_size(hwnd)

        model_for_ray = PartModel(env, app).attach(doc)
        found = picking.point_to_pixel(env, model_for_ray, POINT)
        check("пиксель точки найден", found is not None, str(found))
        if found is None:
            return 1
        wx, wy = found
        check("пиксель внутри окна", 0 <= wx < width and 0 <= wy < height,
              f"({wx}, {wy}) при окне {width}x{height}")

        points_now = model_for_ray.points()
        snap = picking.snap_to_point(env, model_for_ray, points_now, (wx, wy), 10.0)
        check("привязка находит точку по пикселю", snap is not None,
              f"точек {len(points_now)}, расстояние {snap.distance_px:.1f} px" if snap else "нет")
        scale = picking.mm_per_pixel(env, model_for_ray, POINT)
        check("масштаб вида разумен", 0.001 < scale < 5.0, f"{scale:.3f} мм/px")

        screen = win32cursor.client_to_screen(hwnd, wx, wy)
        user32.SetCursorPos(screen[0], screen[1])
        check("курсор поставлен в точку", True, f"экран {screen}")

        # куда тянуть: пиксель точки, смещённой на 10 мм по +Y
        drag_to = picking.point_to_pixel(env, model_for_ray, (POINT[0], POINT[1] + 10 * MM, POINT[2]))
        check("пиксель направления +Y найден", drag_to is not None, str(drag_to))

        cfg = config_mod.Config(
            presets=[config_mod.Preset(NAME, last_axis="+Y")],
            offset_mm=OFFSET,
            snap_tol_mm=3.0,
            snap_tol_px=10.0,
            show_name=True,
            active=0,
        )
        logs: list[str] = []
        placer = Placer(
            env,
            app,
            cfg,
            log=lambda t: (logs.append(t), print("   >", t, flush=True)),
            confirm_duplicates=lambda names: True,
        )
        # все шесть направлений должны распознаваться протяжкой
        base_px = picking.point_to_pixel(env, model_for_ray, POINT)
        wrong = []
        for name, vec in picking.AXIS_VECTORS.items():
            target_px = picking.point_to_pixel(
                env, model_for_ray,
                (POINT[0] + vec[0] * 10, POINT[1] + vec[1] * 10, POINT[2] + vec[2] * 10),
            )
            if target_px is None:
                wrong.append(f"{name}: нет пикселя")
                continue
            guess = picking.axis_from_drag(env, model_for_ray, POINT, base_px, target_px)
            if guess is None or guess[0] != name:
                wrong.append(f"{name} -> {guess[0] if guess else None}")
        check("все 6 направлений распознаются", not wrong, ", ".join(wrong) or "ок")

        placer.on_press()                      # «зажал клавишу» в точке
        drag_screen = win32cursor.client_to_screen(hwnd, *drag_to)
        user32.SetCursorPos(drag_screen[0], drag_screen[1])
        check("курсор перетащен в сторону +Y", True, f"экран {drag_screen}")
        placer.on_release()                    # «отпустил клавишу»
        result = bool(logs) and "мм;" in logs[-1]
        check("place выполнился", result, " | ".join(logs[-2:]))
        if not result:
            return 1

        model = PartModel(env, app).attach(doc)
        names = model.list_lcs()
        check("тройка создана", all(n in names for n in (NAME, NAME + "_V", NAME + "_R")), str(names))

        base = model.lcs_by_name(NAME)
        vec = model.lcs_by_name(NAME + "_V")
        rot = model.lcs_by_name(NAME + "_R")
        check(
            "базовая в точке",
            near((base.GetX(), base.GetY(), base.GetZ()), POINT),
            str([round(v / MM, 3) for v in (base.GetX(), base.GetY(), base.GetZ())]),
        )
        check(
            "векторная +10 мм по Y",
            near((vec.GetX(), vec.GetY(), vec.GetZ()), (POINT[0], POINT[1] + OFFSET * MM, POINT[2])),
            str([round(v / MM, 3) for v in (vec.GetX(), vec.GetY(), vec.GetZ())]),
        )
        check(
            "_R перпендикулярна _V (+X при _V по +Y)",
            near((rot.GetX(), rot.GetY(), rot.GetZ()), (POINT[0] + OFFSET * MM, POINT[1], POINT[2])),
            str([round(v / MM, 3) for v in (rot.GetX(), rot.GetY(), rot.GetZ())]),
        )

        # ориентация «без проворота»: оси ЛСК = оси детали
        ok_vec = base.GetVector(env.constants3d.o3d_axisOX, 0.0, 0.0, 0.0)
        check("ось X базовой ЛСК = (1,0,0)", ok_vec[0] and near(ok_vec[1:], (1.0, 0.0, 0.0), 1e-6), str(ok_vec))

        # штатный Ctrl+Z КОМПАСа должен убрать всю тройку одним шагом
        app.ExecuteKompasCommand(57643, False)  # ksCMEditUndo
        import time as _time

        _time.sleep(0.6)
        check("Ctrl+Z убирает всю тройку", model.list_lcs() == [], str(model.list_lcs()))
    finally:
        doc.Close(0)

    print()
    if FAILS:
        print("ПРОВАЛЫ:")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("Сквозной сценарий работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
