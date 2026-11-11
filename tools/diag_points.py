"""Диагностика: где API держит точки активной детали.

Ничего не меняет в модели — только читает. Запускать при открытой детали,
в которой проставлены точки (любым инструментом КОМПАСа).

    python tools/diag_points.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import kompas  # noqa: E402

MM = 1.0  # единицы API КОМПАСа — миллиметры


def cast(env, app, cls_name, obj):
    try:
        res = getattr(env.ksapi, cls_name)(obj, app)
    except Exception as exc:
        return None
    return res if res else None


def describe(env, app, obj, label=""):
    """Что это за объект: тип, имя, координаты (если точка)."""
    name = "?"
    try:
        name = obj.GetName()
    except Exception:
        pass
    coords = ""
    point = cast(env, app, "IPoint3D", obj)
    if point is not None:
        try:
            coords = f" ({point.GetX() / MM:.3f}, {point.GetY() / MM:.3f}, {point.GetZ() / MM:.3f}) мм"
        except Exception as exc:
            coords = f" (ошибка координат: {exc})"
    return f"{label}{name!r}{coords}"


def count(coll) -> int:
    try:
        return coll.GetCount() if coll else 0
    except Exception:
        return 0


def main() -> int:
    env = kompas.load()
    app = env.app()
    if app is None:
        print("КОМПАС не запущен")
        return 2
    env.refresh_version(app)

    doc = app.GetActiveDocument()
    if not doc:
        print("Нет активного документа")
        return 3
    print(f"Активный документ: тип {doc.GetDocumentType()} (4 = деталь)")
    if doc.GetDocumentType() != env.constants.ksDocumentPart:
        print("Это не деталь — открой *.m3d и повтори")
        return 3

    doc3d = env.ksapi.IKompasDocument3D(doc, app)
    part = doc3d.GetTopPart()
    container = part.GetModelContainer()
    c3d = env.constants3d

    print("\n--- 1. IPoints3D (то, что использует инструмент) ---")
    points = container.GetPoints3D()
    n = count(points)
    print(f"   элементов: {n}")
    for i in range(n):
        print("   ", describe(env, app, points.GetPoint3D(i)))

    print("\n--- 2. Объекты модели по типам (GetModelObjects) ---")
    type_names = {
        c3d.o3d_point3D: "o3d_point3D (конструктивная 3D точка)",
        c3d.o3d_conjunctivePoint: "o3d_conjunctivePoint (присоединительная)",
        c3d.o3d_controlPoint: "o3d_controlPoint (контрольная)",
        c3d.o3d_sketch: "o3d_sketch (эскиз)",
        c3d.o3d_planeXOY: "o3d_planeXOY",
    }
    for obj_type, label in type_names.items():
        try:
            objects = container.GetModelObjects([obj_type]) or []
        except Exception as exc:
            print(f"   {label}: ошибка {exc}")
            continue
        print(f"   {label}: {len(objects)}")
        for obj in objects[:12]:
            print("      ", describe(env, app, obj))

    print("\n--- 3. Коллекции вспомогательной геометрии ---")
    aux = cast(env, app, "IAuxiliaryGeomContainer", part)
    print(f"   IAuxiliaryGeomContainer: {bool(aux)}")
    if aux:
        for method, label in (
            ("GetConjunctivePoints", "присоединительные точки"),
            ("GetControlPoints", "контрольные точки"),
            ("GetLocalCoordinateSystems", "ЛСК"),
            ("GetAxes3D", "оси"),
            ("GetPlanes3D", "плоскости"),
        ):
            try:
                coll = getattr(aux, method)()
            except Exception as exc:
                print(f"   {label}: ошибка {exc}")
                continue
            n = count(coll)
            print(f"   {label}: {n}")
            for i in range(min(n, 8)):
                try:
                    obj = coll.GetItem(i) if hasattr(coll, "GetItem") else None
                except Exception:
                    obj = None
                if obj:
                    print("      ", describe(env, app, obj))

    print("\n--- 4. Все эскизы и их точки ---")
    try:
        sketches = container.GetSketchs()
    except Exception as exc:
        sketches = None
        print(f"   ошибка получения эскизов: {exc}")
    n = count(sketches)
    print(f"   эскизов: {n}")
    for i in range(n):
        sketch = sketches.GetItem(i) if hasattr(sketches, "GetItem") else None
        if not sketch:
            continue
        print("   ", describe(env, app, sketch, label="эскиз "))

    print("\n--- 5. Полный обход дерева: типы всех объектов верхнего уровня ---")
    try:
        all_objects = container.GetObjects(0)  # 0 = все типы
    except Exception as exc:
        all_objects = None
        print(f"   ошибка: {exc}")
    if all_objects:
        print(f"   объектов: {len(all_objects)}")
        for obj in all_objects[:40]:
            print("      ", describe(env, app, obj))
    return 0


if __name__ == "__main__":
    sys.exit(main())
