"""Живой тест на РЕАЛЬНОЙ детали: поставить тройку ЛСК в выбранную 3D-точку.

Работает с активным документом в запущенном КОМПАСе, курсор не нужен.
Тройка остаётся в модели — чтобы можно было глазами проверить в дереве.
Удалить её: `python tools/live_place.py --undo`.

    python tools/live_place.py              # список точек
    python tools/live_place.py --index 1    # поставить ЛСК во 2-ю точку
    python tools/live_place.py --index 1 --undo

Параметры: --name ИМЯ (по умолчанию ТЕСТ_ЛСК), --r-axis +X|-X|+Z|-Z,
--offset 10, --inside (векторная ЛСК внутрь).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import geometry, kompas, picking  # noqa: E402
from lsk.model import PartModel  # noqa: E402

MM = 1.0  # единицы API КОМПАСа — миллиметры


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--name", default="ТЕСТ_ЛСК")
    parser.add_argument("--r-axis", default="+X", choices=["+X", "-X", "+Z", "-Z"])
    parser.add_argument("--offset", type=float, default=10.0)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--undo", action="store_true")
    parser.add_argument("--normal", action="store_true",
                        help="ориентация по нормали грани (по умолчанию — без проворота)")
    parser.add_argument("--tolerance", type=float, default=1.0)
    args = parser.parse_args()

    env = kompas.load()
    app = env.app()
    if app is None:
        print("КОМПАС не запущен")
        return 2

    model = PartModel(env, app)
    try:
        model.refresh()
    except Exception as exc:
        print(f"Ошибка: {exc}")
        return 3

    print(f"документ: {model.doc.GetName() or '(без имени)'}")
    print(f"ЛСК в модели: {model.list_lcs() or '—'}")

    if args.undo:
        removed = model.undo_triplet(args.name)
        print(f"удалено ЛСК: {removed} ({args.name})")
        return 0

    points = model.points()
    print(f"\nнайдено 3D-точек: {len(points)}")
    for i, pt in enumerate(points):
        print(
            f"  [{i}] {pt.name!r}  "
            f"({pt.coords[0] / MM:.3f}, {pt.coords[1] / MM:.3f}, {pt.coords[2] / MM:.3f}) мм"
        )

    if args.index is None:
        print("\nукажи --index N, чтобы поставить ЛСК в эту точку")
        return 0
    if not points:
        print("\nточек нет — нечего ставить")
        return 1
    if not 0 <= args.index < len(points):
        print(f"\nнет точки с индексом {args.index}")
        return 1

    point = points[args.index]
    if args.normal:
        direction = picking.face_at_point(
            env, app, model, point.coords, geometry.mm(args.tolerance)
        )
        if direction is None:
            print("\nне нашёл грань через эту точку — направление определить нечем")
            return 1
        normal = direction.normal
        if args.inside:
            normal = geometry.mul(normal, -1.0)
        axes = geometry.frame_from_normal(normal)
        print(
            f"\nточка: {point.name!r}, грань: {direction.source}, "
            f"нормаль: ({normal[0]:.3f}, {normal[1]:.3f}, {normal[2]:.3f})"
        )
        if direction.warning:
            print("  !", direction.warning)
    else:
        axes = geometry.GLOBAL_AXES
        print(f"\nточка: {point.name!r}, ориентация: оси детали (без проворота)")

    created = model.create_triplet(
        base_name=args.name,
        origin=point.coords,
        axes=axes,
        offset=geometry.mm(args.offset),
        v_sign=-1 if args.inside else 1,
        r_axis=args.r_axis,
        show_name=True,
    )
    print(f"создано: {created.names}")
    for name in created.names:
        lcs = model.lcs_by_name(name)
        if lcs:
            print(
                f"  {name}: ({lcs.GetX() / MM:.3f}, {lcs.GetY() / MM:.3f}, {lcs.GetZ() / MM:.3f}) мм"
            )
    print("\nПосмотри в дереве модели: должны появиться три ЛСК с надписями.")
    print(f"Убрать их: python tools/live_place.py --name {args.name} --undo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
