"""Определение точки и направления по клику в окне модели.

Порядок:

1. `IDocumentFrame.GetPickRay(x, y)` — по оконным пикселам даёт точку под курсором
   (на ближайшем объекте) и направление взгляда. Шесть чисел: точка + вектор.
2. `PickModelObjects(ray, filter)` — объекты модели вдоль луча (грани, тела...).
3. Привязка к 3D-точке: среди точек модели ищем ближайшую к *лучу* (не к точке
   попадания) в пределах допуска — так клик «рядом с точкой» всё равно попадает в неё.
4. Направление: нормаль грани в этой точке (`IFace.NearPointProjection` -> `GetNormal`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geometry


@dataclass
class Pick:
    window: tuple[int, int]
    ray: list[float] | None = None
    hit_point: geometry.Vec | None = None
    objects: list = field(default_factory=list)
    warning: str = ""

    @property
    def ok(self) -> bool:
        return self.ray is not None


@dataclass
class Snapped:
    point: object          # model.PointInfo
    distance: float        # расстояние до луча, метры


@dataclass
class Direction:
    normal: geometry.Vec
    distance: float        # расстояние от точки до грани, метры
    source: str            # описание грани (для журнала)
    warning: str = ""


def _face(env, obj):
    try:
        res = env.ksapi.IFace(obj, obj.kompasApp)
    except Exception:
        return None
    return res if res else None


def pick_at(env, model, window_x: int, window_y: int) -> Pick:
    pick = Pick(window=(window_x, window_y))
    frame = model.doc.GetDocumentFrame()
    if not frame or not env.features.pick_ray:
        pick.warning = "GetPickRay недоступен — не могу определить точку под курсором"
        return pick
    ok, px, py, pz, dx, dy, dz = frame.GetPickRay(window_x, window_y, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    if not ok:
        pick.warning = "Курсор не над моделью — КОМПАС не вернул луч взгляда"
        return pick
    pick.ray = [px, py, pz, dx, dy, dz]
    pick.hit_point = (px, py, pz)
    try:
        pick.objects = model.doc3d.PickModelObjects(pick.ray, None) or []
    except Exception as exc:  # фильтр необязателен
        pick.warning = f"PickModelObjects: {exc}"
        pick.objects = []
    return pick


def snap_to_point(points, pick: Pick, tolerance: float) -> Snapped | None:
    """Ближайшая к лучу 3D-точка модели в пределах допуска (метры)."""
    if not pick.ray or not points:
        return None
    origin = (pick.ray[0], pick.ray[1], pick.ray[2])
    direction = (pick.ray[3], pick.ray[4], pick.ray[5])
    best: Snapped | None = None
    for pt in points:
        dist, _t = geometry.distance_to_ray(pt.coords, origin, direction)
        if dist <= tolerance and (best is None or dist < best.distance):
            best = Snapped(point=pt, distance=dist)
    return best


def face_direction(env, pick: Pick, origin: geometry.Vec, tolerance: float) -> Direction | None:
    """Нормаль грани в точке `origin`.

    Из объектов под лучом берём грани и выбираем ту, что ближе всего к точке
    (клик мог попасть в отверстие — тогда берём грань под курсором и предупреждаем).
    """
    faces = []
    for obj in pick.objects:
        face = _face(env, obj)
        if face is not None:
            faces.append(face)
    if not faces:
        return None

    reference = origin if origin else pick.hit_point
    if reference is None:
        return None

    best = None  # (расстояние, нормаль, грань)
    for face in faces:
        try:
            ok, u, v = face.NearPointProjection(reference[0], reference[1], reference[2], 0.0, 0.0)
            if not ok:
                continue
            ok, x, y, z = face.GetPoint(u, v, 0.0, 0.0, 0.0)
            if not ok:
                continue
            dist = geometry.distance((x, y, z), reference)
            ok, nx, ny, nz = face.GetNormal(u, v, 0.0, 0.0, 0.0)
            if not ok or geometry.length((nx, ny, nz)) < 1e-9:
                continue
            if best is None or dist < best[0]:
                best = (dist, geometry.normalize((nx, ny, nz)), face)
        except Exception:
            continue

    if best is None:
        return None

    dist, normal, face = best
    warning = ""
    if dist > tolerance:
        warning = (
            f"Точка не лежит на грани (расстояние {dist / 0.001:.2f} мм) — "
            "направление взято по ближайшей грани под курсором"
        )
    return Direction(normal=normal, distance=dist, source=_face_kind(face), warning=warning)


def _face_kind(face) -> str:
    checks = (
        ("IsPlanar", "плоскость"),
        ("IsCylinder", "цилиндр"),
        ("IsCone", "конус"),
        ("IsSphere", "сфера"),
        ("IsTorus", "тор"),
        ("IsNurbsSurface", "NURBS-поверхность"),
    )
    for method, name in checks:
        try:
            if getattr(face, method)():
                return name
        except Exception:
            continue
    return "грань"
