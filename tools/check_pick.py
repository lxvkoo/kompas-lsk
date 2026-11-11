"""Проверка «клика без клика»: луч взгляда и выбор объектов по лучу.

Открывает ВИДИМЫЙ временный документ (в КОМПАСе появится окно), строит в нём
параллелепипед и прогоняет цепочку, которая используется при клике:

    GetWorkAreaRect -> GetPickRay -> PickModelObjects / FindNearestObject

Каждый шаг печатается сразу (flush): если КОМПАС упадёт, в логе будет видно,
на каком именно вызове. Документ закрывается без сохранения.

    python tools/check_pick.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lsk import geometry, kompas  # noqa: E402

MM = 1.0  # единицы API КОМПАСа — миллиметры


def step(text):
    print(text, flush=True)


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

    docs = app.GetDocuments()
    doc = docs.AddWithDefaultSettings(env.constants.ksDocumentPart, True)
    step(f"документ: {bool(doc)}")
    try:
        doc3d = env.ksapi.IKompasDocument3D(doc, app)
        part = doc3d.GetTopPart()
        container = part.GetModelContainer()

        block = iface(env, app, "IBlockBySizes", container.AddObject(env.constants3d.o3d_BlockBySizes))
        if block:
            block.SetLength(100 * MM)
            block.SetWidth(50 * MM)
            block.SetHeight(1, 20 * MM)
            block.Update()
        part.RebuildModel(True)
        step("модель построена")

        frame = doc.GetDocumentFrame()
        step(f"окно документа: {bool(frame)}")
        frame.SetActive()
        frame.ZoomPrevNextOrAll(env.constants.ksZoomAll)
        frame.RefreshWindow()

        left, top, right, bottom = frame.GetWorkAreaRect(0, 0, 0, 0)
        step(f"рабочая область: {left},{top} - {right},{bottom}")
        cx, cy = (left + right) // 2, (top + bottom) // 2

        step("--- GetPickRay ---")
        ok, px, py, pz, dx, dy, dz = frame.GetPickRay(cx, cy, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        step(f"   ok={ok} point=({px / MM:.2f}, {py / MM:.2f}, {pz / MM:.2f}) мм dir=({dx:.3f}, {dy:.3f}, {dz:.3f})")
        if not ok:
            step("   луч не попал в модель — дальше не идём")
            return 1
        ray = [px, py, pz, dx, dy, dz]

        step("--- PickModelObjects(ray, None) ---")
        objects = doc3d.PickModelObjects(ray, None)
        step(f"   объектов: {len(objects or [])}")
        for obj in objects or []:
            face = iface(env, app, "IFace", obj)
            kind = "плоскость" if face and face.IsPlanar() else ("грань" if face else "не грань")
            step(f"     - {kind}")

        step("--- фильтр через GetInterface(ksObjectFindObject3DParameters) ---")
        raw = doc.GetInterface(env.constants.ksObjectFindObject3DParameters)
        step(f"   интерфейс: {bool(raw)}")
        filt = iface(env, app, "IFindObjectParameters", raw) if raw else None
        step(f"   IFindObjectParameters: {bool(filt)}")
        if filt:
            objects2 = doc3d.PickModelObjects(ray, filt)
            step(f"   объектов с фильтром: {len(objects2 or [])}")

        step("--- FindNearestObject(ray, None) ---")
        nearest = doc3d.FindNearestObject(ray, None)
        step(f"   объект: {bool(nearest)}")

        step("--- нормаль по найденной грани ---")
        for obj in objects or []:
            face = iface(env, app, "IFace", obj)
            if not face:
                continue
            ok2, u, v = face.NearPointProjection(px, py, pz, 0.0, 0.0)
            if not ok2:
                continue
            ok3, nx, ny, nz = face.GetNormal(u, v, 0.0, 0.0, 0.0)
            normal = geometry.normalize((nx, ny, nz))
            step(f"   нормаль: ({normal[0]:.3f}, {normal[1]:.3f}, {normal[2]:.3f})")
            break
        step("ГОТОВО: пайплайн клика не уронил КОМПАС")
        return 0
    finally:
        step("закрываю документ")
        doc.Close(0)  # kdDoNotSaveChanges


if __name__ == "__main__":
    sys.exit(main())
