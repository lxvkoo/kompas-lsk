"""Сквозной тест без человека: точка в модели -> курсор -> расстановка ЛСК.

Создаёт видимый временный документ с параллелепипедом и 3D-точкой на верхней
грани, ставит настоящий курсор в экранную позицию этой точки (через
UnConvertCoordinates), затем вызывает тот же код, что и горячая клавиша
(`Placer.place_under_cursor`), и проверяет координаты созданных ЛСК.

    python tools/check_e2e.py
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import config as config_mod  # noqa: E402
from lsk import kompas  # noqa: E402
from lsk.model import PartModel  # noqa: E402
from lsk.session import Placer  # noqa: E402

MM = 0.001
POINT = (10 * MM, 5 * MM, 20 * MM)  # на верхней грани блока 100x50x20
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


def near(a, b, eps=1e-8):
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

        # Внимание: UnConvertCoordinates (3D -> пиксель) отдаёт Y с обратным знаком
        # относительно GetPickRay, поэтому пиксель ищем численно, по самому лучу.
        left, top, right, bottom = frame.GetWorkAreaRect(0, 0, 0, 0)
        cx, cy = (left + right) // 2, (top + bottom) // 2
        step = 200
        probes = {}
        for dx, dy in ((0, 0), (step, 0), (0, step)):
            ok, px, py, pz, _a, _b, _c = frame.GetPickRay(cx + dx, cy + dy, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            if not ok:
                check("луч для калибровки", False, f"({cx + dx},{cy + dy})")
                return 1
            probes[(dx, dy)] = (px, py)
        a0 = probes[(0, 0)]
        m11 = (probes[(step, 0)][0] - a0[0]) / step
        m21 = (probes[(step, 0)][1] - a0[1]) / step
        m12 = (probes[(0, step)][0] - a0[0]) / step
        m22 = (probes[(0, step)][1] - a0[1]) / step
        det = m11 * m22 - m12 * m21
        if abs(det) < 1e-12:
            check("калибровка вида", False, "вырожденная матрица")
            return 1
        tx, ty = POINT[0] - a0[0], POINT[1] - a0[1]
        pdx = (m22 * tx - m12 * ty) / det
        pdy = (-m21 * tx + m11 * ty) / det
        wx, wy = int(round(cx + pdx)), int(round(cy + pdy))
        check("пиксель точки найден", True, f"({wx}, {wy})")
        screen = wintypes.POINT(wx, wy)
        user32.ClientToScreen(wintypes.HWND(frame.GetWindowHandle()), ctypes.byref(screen))
        user32.SetCursorPos(screen.x, screen.y)
        check("курсор поставлен в точку", True, f"экран ({screen.x}, {screen.y})")

        check("точка внутри рабочей области", left <= wx <= right and top <= wy <= bottom,
              f"окно ({wx},{wy}) в ({left},{top})-({right},{bottom})")

        cfg = config_mod.Config(
            presets=[config_mod.Preset("E2E_ЛСК", r_axis="+X", v_sign=1)],
            offset_mm=10.0,
            snap_tol_mm=3.0,
            show_name=True,
            active=0,
        )
        logs: list[str] = []
        placer = Placer(env, app, cfg, log=lambda t: (logs.append(t), print("   >", t, flush=True)),
                        confirm_duplicates=lambda names: True)
        result = placer.place_under_cursor()
        check("place_under_cursor выполнился", result, "|".join(logs[-2:]))
        if not result:
            return 1

        model = PartModel(env, app).attach(doc)
        names = model.list_lcs()
        check("тройка создана", all(n in names for n in ("E2E_ЛСК", "E2E_ЛСК_V", "E2E_ЛСК_R")), str(names))

        base = model.lcs_by_name("E2E_ЛСК")
        vec = model.lcs_by_name("E2E_ЛСК_V")
        rot = model.lcs_by_name("E2E_ЛСК_R")
        check("базовая в точке", near((base.GetX(), base.GetY(), base.GetZ()), POINT),
              str([round(v / MM, 2) for v in (base.GetX(), base.GetY(), base.GetZ())]))
        check("векторная +10 мм по Z (нормаль верхней грани)",
              near((vec.GetX(), vec.GetY(), vec.GetZ()), (POINT[0], POINT[1], POINT[2] + 10 * MM)),
              str([round(v / MM, 2) for v in (vec.GetX(), vec.GetY(), vec.GetZ())]))
        check("поворотная +10 мм по X",
              near((rot.GetX(), rot.GetY(), rot.GetZ()), (POINT[0] + 10 * MM, POINT[1], POINT[2])),
              str([round(v / MM, 2) for v in (rot.GetX(), rot.GetY(), rot.GetZ())]))

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
