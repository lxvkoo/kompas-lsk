"""Векторная математика и матрицы ЛСК. Без зависимостей от КОМПАСа — легко тестируется.

Соглашения (проверены на КОМПАС v25):

* координаты API — **метры** (10 мм = 0.01);
* `ILocalCoordinateSystem.InitByMatrix3D` принимает массив из 16 чисел (row-major):
  строки 0/1/2 — единичные векторы осей X/Y/Z, строка 3 — начало координат (x, y, z, 1).
  Проверка round-trip через `GetVector()` подтвердила именно такой порядок.
"""

from __future__ import annotations

import math

Vec = tuple[float, float, float]

EPS = 1e-9


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Vec) -> Vec:
    ln = length(a)
    if ln < EPS:
        raise ValueError("нулевой вектор нельзя нормализовать")
    return (a[0] / ln, a[1] / ln, a[2] / ln)


def distance(a: Vec, b: Vec) -> float:
    return length(sub(a, b))


def frame_from_normal(normal: Vec, refs: tuple[Vec, ...] = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))):
    """Построить правый ортонормированный базис, у которого ось Y = `normal`.

    Ось X — проекция первого подходящего опорного направления на плоскость грани,
    ось Z = X × Y. Так база «смотрит» наружу по нормали, а поворот вокруг нормали
    остаётся предсказуемым (X — вдоль глобальной оси, если она не параллельна).
    """
    y = normalize(normal)
    for ref in refs:
        x = sub(ref, mul(y, dot(ref, y)))
        if length(x) > 1e-6:
            x = normalize(x)
            break
    else:
        raise ValueError("не удалось подобрать ось X для нормали")
    z = normalize(cross(x, y))
    return x, y, z


def matrix_from_frame(origin: Vec, axes: tuple[Vec, Vec, Vec]) -> list[float]:
    """16 чисел для InitByMatrix3D: строки X, Y, Z, начало координат."""
    ax, ay, az = axes
    return [
        ax[0], ax[1], ax[2], 0.0,
        ay[0], ay[1], ay[2], 0.0,
        az[0], az[1], az[2], 0.0,
        origin[0], origin[1], origin[2], 1.0,
    ]


def axis_vector(axes: tuple[Vec, Vec, Vec], r_axis: str) -> Vec:
    """Вектор оси для ЛСК поворота: '+X', '-X', '+Z', '-Z' (в системе базовой ЛСК)."""
    ax, _ay, az = axes
    table = {"+X": ax, "-X": mul(ax, -1.0), "+Z": az, "-Z": mul(az, -1.0)}
    return table.get(r_axis.upper(), ax)


def distance_to_ray(point: Vec, origin: Vec, direction: Vec) -> tuple[float, float]:
    """Расстояние от точки до луча. Возвращает (расстояние, параметр вдоль луча).

    Нужно, чтобы понять, по какой 3D-точке модели кликнули: сравниваем её
    с лучом взгляда, а не с точкой попадания (клик может быть рядом с точкой).
    """
    d = normalize(direction)
    t = dot(sub(point, origin), d)
    if t < 0.0:
        return distance(point, origin), t
    return distance(point, add(origin, mul(d, t))), t


def mm(value: float) -> float:
    """Миллиметры -> метры (единицы API КОМПАСа)."""
    return value * 0.001
