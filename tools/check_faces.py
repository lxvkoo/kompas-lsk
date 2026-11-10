"""Безопасная проверка геометрической части: без кликов и без окон.

Создаёт временную (невидимую) деталь, строит в ней параллелепипед, затем
проверяет то, на чём держится расстановка ЛСК:

* поиск грани по точке (`IPart.FindObjectsByPoint`);
* проекция точки на грань (`IFace.NearPointProjection`);
* нормаль грани в этой точке (`IFace.GetNormal`);
* построение базиса и матрицы ЛСК.

Твои модели не трогаются: временный документ закрывается без сохранения.

    python tools/check_faces.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import geometry, kompas  # noqa: E402

MM = 0.001
FAILS: list[str] = []


def check(name, condition, detail=""):
    if not condition:
        FAILS.append(f"{name}: {detail}")
    print(f"[{'ok ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def iface(env, app, cls_name, obj):
    try:
        res = getattr(env.ksapi, cls_name)(obj, app)
    except Exception as exc:
        print("   cast error:", exc)
        return None
    return res if res else None


def main() -> int:
    env = kompas.load()
    app = env.app()
    if app is None:
        print("КОМПАС не запущен")
        return 2

    doc = app.GetDocuments().AddWithDefaultSettings(env.constants.ksDocumentPart, False)
    try:
        doc3d = env.ksapi.IKompasDocument3D(doc, app)
        part = doc3d.GetTopPart()
        container = part.GetModelContainer()

        # параллелепипед 100 x 50 x 20 мм в начале координат
        raw = container.AddObject(env.constants3d.o3d_BlockBySizes)
        block = iface(env, app, "IBlockBySizes", raw)
        check("параллелепипед создан", bool(block))
        if block:
            raw_pos = block.GetBlockPosition()
            position = iface(env, app, "IPlacement3D", raw_pos) if raw_pos else None
            print("   положение блока:", "задано" if position else "по умолчанию (0,0,0)")
            if position:
                position.SetOrigin(0.0, 0.0, 0.0)
            block.SetLength(100 * MM)
            block.SetWidth(50 * MM)
            block.SetHeight(1, 20 * MM)
            block.Update()
        part.RebuildModel(False)
        print("   тел в детали:", container.GetElementaryBodies().GetCount())

        # точка чуть внутри верхней грани (z = 20 мм)
        probe = (10 * MM, 5 * MM, 20 * MM)
        objects = part.FindObjectsByPoint(probe[0], probe[1], probe[2], True) or []
        print("   объектов в точке:", len(objects))
        faces = [iface(env, app, "IFace", obj) for obj in objects]
        faces = [f for f in faces if f]
        check("грань по точке найдена", bool(faces), f"объектов {len(objects)}")

        if faces:
            face = faces[0]
            ok, u, v = face.NearPointProjection(probe[0], probe[1], probe[2], 0.0, 0.0)
            check("проекция точки на грань", bool(ok), f"u={u:.4f} v={v:.4f}")
            ok, x, y, z = face.GetPoint(u, v, 0.0, 0.0, 0.0)
            check(
                "точка на грани",
                geometry.distance((x, y, z), probe) < 1e-9,
                f"({x / MM:.3f}, {y / MM:.3f}, {z / MM:.3f}) мм",
            )
            ok, nx, ny, nz = face.GetNormal(u, v, 0.0, 0.0, 0.0)
            normal = geometry.normalize((nx, ny, nz))
            check("нормаль грани", bool(ok) and abs(abs(normal[2]) - 1.0) < 1e-6, str(normal))
            kind = "плоскость" if face.IsPlanar() else "не плоскость"
            print("   тип грани:", kind)

            axes = geometry.frame_from_normal(normal)
            mtr = geometry.matrix_from_frame((x, y, z), axes)
            check("матрица 4x4 собрана", len(mtr) == 16 and mtr[15] == 1.0)
            check("ось Y = нормаль", geometry.distance(axes[1], normal) < 1e-9)

            # что именно пишет v_sign: ЛСК «наружу»
            v_origin = geometry.add((x, y, z), geometry.mul(axes[1], 10 * MM))
            print(
                "   LCS_V при v_sign=+1: "
                f"({v_origin[0] / MM:.2f}, {v_origin[1] / MM:.2f}, {v_origin[2] / MM:.2f}) мм"
            )
    finally:
        doc.Close(0)  # kdDoNotSaveChanges

    print()
    if FAILS:
        print("ПРОВАЛЫ:")
        for fail in FAILS:
            print("  - " + fail)
        return 1
    print("Геометрия граней работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
