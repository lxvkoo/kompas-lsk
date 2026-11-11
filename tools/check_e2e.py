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

        hwnd = frame.GetWindowHandle()
        width, height = win32cursor.client_size(hwnd)

        model_for_ray = PartModel(env, app).attach(doc)
        found = picking.pixel_for_point(env, model_for_ray, POINT)
        check("пиксель точки найден", found is not None, str(found))
        if found is None:
            return 1
        wx, wy = found
        check("пиксель внутри окна", 0 <= wx < width and 0 <= wy < height,
              f"({wx}, {wy}) при окне {width}x{height}")
        ray = picking.ray_at(env, model_for_ray, wx, wy)
        if ray is None:
            check("луч взгляда получен", False, f"пиксель ({wx}, {wy})")
            return 1
        dist, _t = geometry.distance_to_ray(POINT, ray.origin, ray.direction)
        check("луч проходит через точку", dist < 1.0, f"расстояние {dist:.4f} мм")

        screen = win32cursor.client_to_screen(hwnd, wx, wy)
        user32.SetCursorPos(screen[0], screen[1])
        check("курсор поставлен в точку", True, f"экран {screen}")

        cfg = config_mod.Config(
            presets=[config_mod.Preset(NAME, r_axis="+X", v_sign=1)],
            offset_mm=OFFSET,
            snap_tol_mm=3.0,
            snap_tol_px=10.0,
            show_name=True,
            orientation="global",  # без проворота
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
        result = placer.place_under_cursor()
        check("place_under_cursor выполнился", result, " | ".join(logs[-2:]))
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
            "поворотная +10 мм по X",
            near((rot.GetX(), rot.GetY(), rot.GetZ()), (POINT[0] + OFFSET * MM, POINT[1], POINT[2])),
            str([round(v / MM, 3) for v in (rot.GetX(), rot.GetY(), rot.GetZ())]),
        )

        # ориентация «без проворота»: оси ЛСК = оси детали
        ok_vec = base.GetVector(env.constants3d.o3d_axisOX, 0.0, 0.0, 0.0)
        check("ось X базовой ЛСК = (1,0,0)", ok_vec[0] and near(ok_vec[1:], (1.0, 0.0, 0.0), 1e-6), str(ok_vec))

        placer.undo_last()
        check("тройка удалена", model.list_lcs() == [], str(model.list_lcs()))
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
