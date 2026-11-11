"""Интеграционный самотест без кликов: создаёт временную деталь в запущенном
КОМПАСе, ставит точки и ЛСК, проверяет координаты, удаляет и закрывает документ
без сохранения. Ничего не меняет в твоих моделях.

    python selftest.py
"""

from __future__ import annotations

import sys

from lsk import geometry, kompas
from lsk.model import PartModel

MM = 1.0  # единицы API КОМПАСа — миллиметры
FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        FAILS.append(f"{name}: {detail}")
    print(f"[{'ok ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=== 1. Геометрия (без КОМПАСа) ===")
    axes = geometry.frame_from_normal((0.0, 0.0, 1.0))
    check("базис из нормали +Z", axes[1] == (0.0, 0.0, 1.0), f"Y={axes[1]}")
    check("базис ортонормирован", abs(geometry.dot(axes[0], axes[1])) < 1e-12)
    check("правый базис", _near(geometry.cross(axes[0], axes[1]), axes[2]), str(geometry.cross(axes[0], axes[1])))
    mtr = geometry.matrix_from_frame((1.0, 2.0, 3.0), axes)
    check("матрица: 16 чисел", len(mtr) == 16 and mtr[15] == 1.0)
    check("матрица: начало координат", mtr[12:15] == [1.0, 2.0, 3.0])
    check("мм -> единицы API", geometry.mm(10) == 10.0 * geometry.UNITS_PER_MM)
    check("обратно в мм", geometry.to_mm(geometry.mm(10)) == 10.0)
    dist, _t = geometry.distance_to_ray((0.0, 0.0, 0.5), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    check("расстояние до луча", dist < 1e-12, f"{dist}")

    print("\n=== 2. Живой КОМПАС ===")
    env = kompas.load()
    app = env.app()
    if app is None:
        print("КОМПАС не запущен — интеграционную часть пропускаю.")
        return 1 if FAILS else 0
    ok, major, minor, release, _build = app.GetSystemVersion(0, 0, 0, 0)
    env.features.version = (major, minor, release)
    print(env.features.as_text())
    doc = app.GetDocuments().AddWithDefaultSettings(env.constants.ksDocumentPart, False)
    try:
        model = PartModel(env, app).attach(doc)
        check("коллекция ЛСК получена", model.has_collection)

        points = model.part.GetModelContainer().GetPoints3D()
        for i, coords in enumerate([(0.0, 0.0, 0.0), (20 * MM, 30 * MM, 5 * MM)]):
            pt = points.Add()
            pt.SetName(f"Самотест_{i}")
            pt.SetX(coords[0])
            pt.SetY(coords[1])
            pt.SetZ(coords[2])
            pt.Update()
        model.rebuild()

        read_points = model.points()
        check("точки модели читаются", len(read_points) == 2, f"{[p.name for p in read_points]}")
        check("координаты точек верные", read_points[1].coords == (20 * MM, 30 * MM, 5 * MM))

        base = "Самотест_ЛСК"
        rect = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        model.create_triplet(base, (0.0, 0.0, 0.0), rect, 10 * MM, 1, "+X", show_name=True)

        names = model.list_lcs()
        check("созданы три ЛСК", all(f"{base}{s}" in names for s in ("", "_V", "_R")), f"{names}")
        check("дубликаты видны", model.existing([base, base + "_V"]) == [base, base + "_V"])

        lcs_v = model.lcs_by_name(base + "_V")
        lcs_r = model.lcs_by_name(base + "_R")
        lcs_b = model.lcs_by_name(base)
        check("базовая в (0,0,0)", (lcs_b.GetX(), lcs_b.GetY(), lcs_b.GetZ()) == (0.0, 0.0, 0.0))
        check(
            "векторная в (0, 10, 0) мм",
            _near((lcs_v.GetX(), lcs_v.GetY(), lcs_v.GetZ()), (0.0, 10 * MM, 0.0)),
            str((lcs_v.GetX() / MM, lcs_v.GetY() / MM, lcs_v.GetZ() / MM)),
        )
        check(
            "поворотная в (10, 0, 0) мм",
            _near((lcs_r.GetX(), lcs_r.GetY(), lcs_r.GetZ()), (10 * MM, 0.0, 0.0)),
            str((lcs_r.GetX() / MM, lcs_r.GetY() / MM, lcs_r.GetZ() / MM)),
        )

        # повёрнутая система: нормаль +Z (деталь «стоит» на торце)
        rotated = geometry.frame_from_normal((0.0, 0.0, 1.0))
        model.create_triplet("Самотест_поворот", (0.0, 0.0, 0.0), rotated, 10 * MM, 1, "+Z")
        lcs_v2 = model.lcs_by_name("Самотест_поворот_V")
        check(
            "векторная при нормали +Z -> (0, 0, 10) мм",
            _near((lcs_v2.GetX(), lcs_v2.GetY(), lcs_v2.GetZ()), (0.0, 0.0, 10 * MM)),
            str((lcs_v2.GetX() / MM, lcs_v2.GetY() / MM, lcs_v2.GetZ() / MM)),
        )

        removed = model.undo_triplet(base)
        check("тройка удаляется", removed == 3, f"удалено {removed}")
        removed2 = model.undo_triplet("Самотест_поворот")
        check("вторая тройка удаляется", removed2 == 3, f"удалено {removed2}")
        check("ЛСК не осталось", model.list_lcs() == [], f"{model.list_lcs()}")

    finally:
        doc.Close(0)  # kdDoNotSaveChanges — без запроса на сохранение

    print()
    if FAILS:
        print("ПРОВАЛЫ:")
        for fail in FAILS:
            print("  - " + fail)
        return 1
    print("Все проверки пройдены.")
    return 0


def _near(a, b, eps: float = 1e-9) -> bool:
    return all(abs(x - y) <= eps for x, y in zip(a, b))


if __name__ == "__main__":
    sys.exit(main())
