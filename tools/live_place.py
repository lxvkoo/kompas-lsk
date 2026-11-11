"""Живой тест на РЕАЛЬНОЙ детали: поставить тройку ЛСК в выбранную 3D-точку.

Работает с активным документом в запущенном КОМПАСе, курсор не нужен.
Тройка остаётся в модели — чтобы можно было глазами проверить в дереве.
Откатить: штатный Ctrl+Z в КОМПАСе (создание — один шаг отмены) или
`python tools/live_place.py --name ИМЯ --undo`.

    python tools/live_place.py                      # список точек
    python tools/live_place.py --index 0            # поставить (_V по +Y)
    python tools/live_place.py --index 0 --axis +Z  # _V по +Z
    python tools/live_place.py --name ИМЯ --undo
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
    parser.add_argument(
        "--axis", default="+Y", choices=["+X", "-X", "+Y", "-Y", "+Z", "-Z"],
        help="направление векторной ЛСК (_V)",
    )
    parser.add_argument("--offset", type=float, default=10.0)
    parser.add_argument("--undo", action="store_true")
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
    v_axis = picking.AXIS_VECTORS[args.axis]
    r_name = picking.perpendicular_axis(args.axis)
    r_axis = picking.AXIS_VECTORS[r_name]
    print(f"\nточка: {point.name!r}, _V по {args.axis}, _R по {r_name}, отступ {args.offset:g} мм")

    created = model.create_triplet(
        base_name=args.name,
        origin=point.coords,
        v_axis=v_axis,
        r_axis=r_axis,
        offset=geometry.mm(args.offset),
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
    print("Не понравилось — Ctrl+Z в КОМПАСе уберёт все три сразу.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
