"""Определение точки и направления: курсор -> луч -> точка модели -> нормаль грани.

Порядок работы (проверено на v25):

1. Позиция курсора в клиентских координатах окна документа
   (`win32cursor.cursor_client_pos`), проверка, что курсор в рабочей области.
2. `IDocumentFrame.GetPickRay(x, y, ...)` — возвращает **начало луча (камера)** и
   направление взгляда. Точки попадания в модель он не даёт (в проверке начало
   луча было (0, 1.6, −1000) мм при блоке в начале координат), поэтому:
3. привязка к 3D-точке — по расстоянию «точка модели ↔ луч»;
4. направление — по грани, проходящей через найденную точку
   (`IPart.FindObjectsByPoint`), нормаль в проекции точки на грань.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geometry


@dataclass
class Ray:
    origin: geometry.Vec
    direction: geometry.Vec
    window: tuple[int, int]

    def as_list(self) -> list[float]:
        return [*self.origin, *self.direction]


@dataclass
class Snapped:
    point: object          # model.PointInfo
    distance: float        # расстояние до луча, метры


@dataclass
class Direction:
    normal: geometry.Vec
    distance: float        # расстояние от точки до грани (метры)
    source: str            # тип грани, для журнала
    face: object = None
    warning: str = ""


def _cast(env, app, cls_name, obj):
    """QueryInterface с обязательным app (иначе обёртка падает на kompasApp=None)."""
    if not obj:
        return None
    try:
        res = getattr(env.ksapi, cls_name)(obj, app)
    except Exception:
        return None
    return res if res else None


def ray_at(env, model, window_x: int, window_y: int) -> Ray | None:
    """Луч взгляда по оконным координатам."""
    frame = model.doc.GetDocumentFrame()
    if not frame:
        return None
    ok, px, py, pz, dx, dy, dz = frame.GetPickRay(
        window_x, window_y, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    )
    if not ok:
        return None
    if geometry.length((dx, dy, dz)) < 1e-12:
        return None
    return Ray(origin=(px, py, pz), direction=geometry.normalize((dx, dy, dz)),
               window=(window_x, window_y))


def pixel_size_mm(env, model) -> float:
    """Сколько миллиметров в одном пикселе экрана при текущем масштабе вида.

    Курсор мыши даёт целые пиксели, поэтому при мелком масштабе ошибка попадания
    в точку — это несколько миллиметров. Допуск привязки считаем в пикселях.
    """
    frame = model.doc.GetDocumentFrame()
    if not frame:
        return 15.0
    left, top, right, bottom = frame.GetWorkAreaRect(0, 0, 0, 0)
    cx, cy = (left + right) // 2, (top + bottom) // 2
    probes = []
    for dx, dy in ((0, 0), (120, 0), (0, 120)):
        ok, px, py, pz, _zx, _zy, _zz = frame.GetPickRay(
            cx + dx, cy + dy, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
        if not ok:
            continue
        probes.append(((cx + dx, cy + dy), (px, py, pz)))
    if len(probes) < 3:
        return 15.0
    (p0, a0), (p1, a1), (p2, a2) = probes[:3]
    scale_x = geometry.distance(a0, a1) / max(1e-9, abs(p1[0] - p0[0]) or 1)
    scale_y = geometry.distance(a0, a2) / max(1e-9, abs(p2[1] - p0[1]) or 1)
    return max(scale_x, scale_y)


def snap_to_point(points, ray: Ray, tolerance: float) -> Snapped | None:
    """Ближайшая к лучу 3D-точка модели в пределах допуска (метры)."""
    if ray is None or not points:
        return None
    best: Snapped | None = None
    for pt in points:
        dist, _t = geometry.distance_to_ray(pt.coords, ray.origin, ray.direction)
        if dist <= tolerance and (best is None or dist < best.distance):
            best = Snapped(point=pt, distance=dist)
    return best


def face_at_point(env, app, model, point: geometry.Vec, tolerance: float) -> Direction | None:
    """Грань, проходящая через точку, и её нормаль в этой точке."""
    objects = []
    try:
        objects = list(model.part.FindObjectsByPoint(point[0], point[1], point[2], True) or [])
    except Exception:
        objects = []
    if not objects:  # запасной вариант — с допуском
        try:
            objects = list(
                model.part.FindObjectsByPointWithLimit(point[0], point[1], point[2], True, tolerance)
                or []
            )
        except Exception:
            objects = []

    best = None  # (расстояние, нормаль, грань)
    for obj in objects:
        face = _cast(env, app, "IFace", obj)
        if face is None:
            continue
        try:
            ok, u, v = face.NearPointProjection(point[0], point[1], point[2], 0.0, 0.0)
            if not ok:
                continue
            ok, x, y, z = face.GetPoint(u, v, 0.0, 0.0, 0.0)
            if not ok:
                continue
            dist = geometry.distance((x, y, z), point)
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
            f"точка не лежит на грани (расстояние {dist / 0.001:.2f} мм) — "
            "направление взято по ближайшей грани"
        )
    return Direction(normal=normal, distance=dist, source=face_kind(face), face=face,
                     warning=warning)


def face_kind(face) -> str:
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
