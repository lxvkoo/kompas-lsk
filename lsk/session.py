"""Сценарий установки: «курсор над точкой модели + горячая клавиша».

Почему так, а не перехват клика: события мыши КОМПАС в Python не доставляет
(проверено на v25 — обработчик не вызывается ни при настоящем клике, ни при
синтетическом; на синтетический PostMessage КОМПАС вообще падал). Поэтому точку
берём по позиции курсора в момент нажатия горячей клавиши — это ещё и быстрее:
одно действие вместо двух.

Все вызовы API идут из главного потока (Tk), никаких обратных вызовов из
КОМПАСа — так связь остаётся живой.
"""

from __future__ import annotations

import traceback

from . import geometry, picking, win32cursor
from .model import KompasModelError, PartModel


class Placer:
    def __init__(self, env, app, cfg, log, confirm_duplicates):
        self.env = env
        self.app = app
        self.cfg = cfg
        self.log = log
        self.confirm_duplicates = confirm_duplicates
        self.model = PartModel(env, app)
        self.last_base: str | None = None

    # ------------------------------------------------------------------
    def place_under_cursor(self) -> bool:
        """Поставить тройку ЛСК по 3D-точке под курсором."""
        preset = self.cfg.preset
        tol = geometry.mm(self.cfg.snap_tol_mm)
        try:
            self.model.refresh()
            frame = self.model.doc.GetDocumentFrame()
            if not frame:
                self.log("У документа нет окна (модель открыта без окна?)")
                return False

            hwnd = frame.GetWindowHandle()
            window_x, window_y = win32cursor.cursor_client_pos(hwnd)
            if window_x < 0:
                self.log("Не смог определить позицию курсора")
                return False
            left, top, right, bottom = frame.GetWorkAreaRect(0, 0, 0, 0)
            if not (left <= window_x <= right and top <= window_y <= bottom):
                self.log("Курсор не над областью модели — наведи его на деталь в окне КОМПАСа")
                return False

            ray = picking.ray_at(self.env, self.model, window_x, window_y)
            if ray is None:
                self.log("КОМПАС не вернул луч взгляда для этой точки экрана")
                return False

            # допуск в пикселях: при мелком масштабе 1 пиксель — это миллиметры
            scale = picking.pixel_size_mm(self.env, self.model)
            tol = max(tol, scale * max(1.0, self.cfg.snap_tol_px))
            points = self.model.points()
            if not points:
                self.log(
                    "В модели нет 3D-точек. Проставь их инструментом «Точка» / "
                    "«Точка в центре» и повтори."
                )
                return False

            snap = picking.snap_to_point(points, ray, tol)
            if snap is None:
                nearest = min(
                    geometry.distance_to_ray(p.coords, ray.origin, ray.direction)[0]
                    for p in points
                )
                self.log(
                    f"Рядом нет точки: ближайшая в {nearest / 0.001:.1f} мм "
                    f"(допуск {self.cfg.snap_tol_mm:g} мм). Курсор — точно на точку?"
                )
                return False

            origin = snap.point.coords
            direction = picking.face_at_point(self.env, self.app, self.model, origin, tol)
            if direction is None:
                self.log(
                    "Не нашёл грань через эту точку — не могу определить направление. "
                    "Точка должна лежать на грани детали."
                )
                return False

            normal = direction.normal
            if preset.v_sign < 0:
                normal = geometry.mul(normal, -1.0)
            axes = geometry.frame_from_normal(normal)

            names = [preset.name, preset.name + "_V", preset.name + "_R"]
            duplicates = self.model.existing(names)
            if duplicates and not self.confirm_duplicates(duplicates):
                self.log("Отменено: ЛСК с такими именами уже есть в модели")
                return False

            self.model.create_triplet(
                base_name=preset.name,
                origin=origin,
                axes=axes,
                offset=geometry.mm(self.cfg.offset_mm),
                v_sign=preset.v_sign,
                r_axis=preset.r_axis,
                show_name=self.cfg.show_name,
            )
            self.last_base = preset.name
            self.log(
                f"{preset.name}: точка «{snap.point.name}» "
                f"({origin[0] / 0.001:.2f}, {origin[1] / 0.001:.2f}, {origin[2] / 0.001:.2f}) мм, "
                f"грань: {direction.source}, R:{preset.r_axis}, "
                f"V:{'наружу' if preset.v_sign > 0 else 'внутрь'}"
            )
            if direction.warning:
                self.log("  ! " + direction.warning)
            if duplicates:
                self.log("  ! созданы поверх существующих: " + ", ".join(duplicates))
            return True
        except KompasModelError as exc:
            self.log(f"Ошибка: {exc}")
        except Exception:
            self.log("Неожиданная ошибка:\n" + traceback.format_exc(limit=3))
        return False

    # ------------------------------------------------------------------
    def undo_last(self) -> None:
        if not self.last_base:
            self.log("Нечего отменять в этой сессии")
            return
        try:
            self.model.refresh()
            removed = self.model.undo_triplet(self.last_base)
            self.log(f"Удалено ЛСК: {removed} ({self.last_base})")
            self.last_base = None
        except KompasModelError as exc:
            self.log(f"Ошибка: {exc}")
