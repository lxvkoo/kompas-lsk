"""Привязка к точке и выбор направления — в координатах экрана.

Почему так: `GetPickRay` в v25 ведёт себя нестабильно — вызов в другом пикселе
смещает результат следующего вызова (проверено: расстояние от точки до луча
менялось 0.05 → 1.18 → 2.18 мм при повторных вызовах в одном и том же пикселе,
если между ними спросить другой пиксель). Зато обратный перевод 3D → пиксель
(`IDocumentFrame.UnConvertCoordinates`) стабилен и совпадает с численным
решением по лучу до пикселя.

Поэтому:
* 3D-точки модели проецируются на экран, и привязка идёт по расстоянию в
  пикселях (это ровно то, что видит пользователь);
* направление протяжки сравнивается с экранными проекциями шести осей детали.

Особенность API: `UnConvertCoordinates` отдаёт Y от НИЖНЕЙ границы клиентской
области, поэтому Y переворачиваем (`client_height - y`). Первый вызов после
смены вида может быть неточным — поэтому спрашиваем дважды.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import geometry

#: шесть возможных направлений векторной ЛСК
AXIS_VECTORS = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}


@dataclass
class Snapped:
    point: object      # model.PointInfo
    distance_px: float
    distance_mm: float


def _frame(env, model):
    try:
        return model.doc.GetDocumentFrame()
    except Exception:
        return None


def point_to_pixel(env, model, point: geometry.Vec) -> tuple[int, int] | None:
    """Проекция 3D-точки в пиксели клиентской области окна документа."""
    from . import win32cursor

    frame = _frame(env, model)
    if not frame:
        return None
    hwnd = frame.GetWindowHandle()
    _w, height = win32cursor.client_size(hwnd)
    if height <= 0:
        return None
    result = None
    for _ in range(2):  # первый вызов после смены вида бывает неточным
        ok, x, y = frame.UnConvertCoordinates(1, point[0], point[1], point[2], 0, 0)
        if not ok:
            return None
        result = (int(x), int(height - y))
    return result


def mm_per_pixel(env, model, point: geometry.Vec) -> float:
    """Сколько миллиметров модели в одном пикселе экрана при текущем виде."""
    base = point_to_pixel(env, model, point)
    if base is None:
        return 1.0
    samples = []
    for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        probe = geometry.add(point, geometry.mul(axis, 10.0))
        pixel = point_to_pixel(env, model, probe)
        if pixel is None:
            continue
        pixels = geometry.length(
            (float(pixel[0] - base[0]), float(pixel[1] - base[1]), 0.0)
        )
        if pixels >= 4.0:
            samples.append(10.0 / pixels)
    if not samples:
        return 1.0
    return sum(samples) / len(samples)


def snap_to_point(env, model, points, cursor: tuple[int, int],
                  tolerance_px: float) -> Snapped | None:
    """Ближайшая к курсору 3D-точка модели (в пикселях экрана)."""
    best: Snapped | None = None
    scale = mm_per_pixel(env, model, points[0].coords) if points else 1.0
    for info in points:
        pixel = point_to_pixel(env, model, info.coords)
        if pixel is None:
            continue
        distance = geometry.length(
            (float(pixel[0] - cursor[0]), float(pixel[1] - cursor[1]), 0.0)
        )
        if distance <= tolerance_px and (best is None or distance < best.distance_px):
            best = Snapped(point=info, distance_px=distance, distance_mm=distance * scale)
    return best


def axis_screen_vectors(env, model, origin: geometry.Vec,
                        probe_mm: float = 10.0) -> dict[str, tuple[float, float]]:
    """Экранные направления шести осей детали из данной точки (в пикселях)."""
    base = point_to_pixel(env, model, origin)
    if base is None:
        return {}
    result: dict[str, tuple[float, float]] = {}
    for name, vec in AXIS_VECTORS.items():
        target = geometry.add(origin, geometry.mul(vec, probe_mm))
        pixel = point_to_pixel(env, model, target)
        if pixel is None:
            continue
        dx = float(pixel[0] - base[0])
        dy = float(pixel[1] - base[1])
        if (dx * dx + dy * dy) ** 0.5 < 4.0:  # ось смотрит в камеру
            continue
        result[name] = (dx, dy)
    return result


def best_axis(drag: tuple[float, float], vectors: dict[str, tuple[float, float]],
              min_cosine: float = 0.3) -> tuple[str, float] | None:
    """Ближайшая к протяжке ось по косинусу угла между экранными направлениями."""
    length = (drag[0] ** 2 + drag[1] ** 2) ** 0.5
    if length < 1e-9 or not vectors:
        return None
    unit = (drag[0] / length, drag[1] / length)
    best: tuple[float, str] | None = None
    for name, vec in vectors.items():
        vec_length = (vec[0] ** 2 + vec[1] ** 2) ** 0.5
        if vec_length < 1e-9:
            continue
        cosine = (unit[0] * vec[0] + unit[1] * vec[1]) / vec_length
        if best is None or cosine > best[0]:
            best = (cosine, name)
    if best is None or best[0] < min_cosine:
        return None
    return best[1], best[0]


def axis_from_drag(env, model, origin: geometry.Vec, start_px, end_px,
                   probe_mm: float = 10.0) -> tuple[str, float] | None:
    """Какая из шести осей детали соответствует протяжке мышью."""
    vectors = axis_screen_vectors(env, model, origin, probe_mm)
    return best_axis((float(end_px[0] - start_px[0]), float(end_px[1] - start_px[1])), vectors)


def perpendicular_axis(axis_name: str) -> str:
    """Ось ЛСК поворота: первая из +X, +Y, +Z, не совпадающая с направлением _V."""
    base = axis_name[-1]
    for candidate in ("X", "Y", "Z"):
        if candidate != base:
            return "+" + candidate
    return "+X"
