"""Сценарий установки: «навёл курсор на точку → зажал клавишу → потянул → отпустил».

Почему так:
* события мыши КОМПАС в Python не доставляет (проверено), поэтому точку берём по
  позиции курсора, а направление — по протяжке мышью;
* создание тройки обёрнуто в контейнер отмены, поэтому штатный Ctrl+Z в КОМПАСе
  убирает все три ЛСК одним шагом.

Все вызовы API идут из главного потока (Tk), никаких обратных вызовов из
КОМПАСа — так связь с КОМПАСом остаётся живой.
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
        self._press: tuple[int, int] | None = None

    # ------------------------------------------------------------------
    def on_press(self) -> None:
        """Пользователь нажал горячую клавишу — запомним, где стоял курсор."""
        self._press = self._cursor_client()

    def on_release(self) -> None:
        """Клавиша отпущена: считаем протяжку и ставим ЛСК."""
        press = self._press
        self._press = None
        release = self._cursor_client()
        if press is None or release is None:
            self.log("Не смог определить позицию курсора")
            return
        self.place(press, release)

    def _cursor_client(self) -> tuple[int, int] | None:
        try:
            self.model.refresh()
            frame = self.model.doc.GetDocumentFrame()
            if not frame:
                return None
            x, y = win32cursor.cursor_client_pos(frame.GetWindowHandle())
            return (x, y) if x >= 0 else None
        except KompasModelError as exc:
            self.log(str(exc))
        except Exception:
            self.log("Неожиданная ошибка:\n" + traceback.format_exc(limit=2))
        return None

    # ------------------------------------------------------------------
    def place(self, press: tuple[int, int], release: tuple[int, int]) -> bool:
        """Поставить тройку ЛСК: точка — под курсором в момент нажатия,
        направление _V — по протяжке от нажатия к отпусканию."""
        preset = self.cfg.preset
        try:
            self.model.refresh()
            frame = self.model.doc.GetDocumentFrame()
            if not frame:
                self.log("У документа нет окна (модель открыта без окна?)")
                return False

            width, height = win32cursor.client_size(frame.GetWindowHandle())
            if not (0 <= press[0] < width and 0 <= press[1] < height):
                self.log("Курсор не над окном модели — наведи его на деталь")
                return False

            points = self.model.points()
            if not points:
                self.log(
                    f"В документе «{self.model.doc.GetName() or 'без имени'}» нет 3D-точек. "
                    "Проставь их инструментом «Точка» / «Точка в центре»."
                )
                return False

            scale = picking.mm_per_pixel(self.env, self.model, points[0].coords)
            tolerance_px = max(self.cfg.snap_tol_px, self.cfg.snap_tol_mm / max(scale, 1e-6))
            snap = picking.snap_to_point(self.env, self.model, points, press, tolerance_px)
            if snap is None:
                nearest = min(
                    (picking.point_to_pixel(self.env, self.model, p.coords) or (10**6, 10**6))
                    for p in points
                )
                distance_px = geometry.length(
                    (float(nearest[0] - press[0]), float(nearest[1] - press[1]), 0.0)
                )
                self.log(
                    f"Рядом нет точки: ближайшая в {distance_px:.0f} px "
                    f"(≈{distance_px * scale:.1f} мм, допуск {tolerance_px:.0f} px). "
                    "Курсор — точно на точку?"
                )
                return False

            origin = snap.point.coords

            # направление: протяжка мышью, иначе — последнее выбранное для этого имени
            dx = release[0] - press[0]
            dy = release[1] - press[1]
            axis_name = None
            how = ""
            if (dx * dx + dy * dy) ** 0.5 >= self.cfg.drag_threshold_px:
                guess = picking.axis_from_drag(self.env, self.model, origin, press, release)
                if guess is not None:
                    axis_name, cosine = guess
                    how = f"протяжка (совпадение {cosine:.2f})"
            if axis_name is None:
                axis_name = preset.last_axis
                how = "по прежнему выбору"

            v_axis = picking.AXIS_VECTORS[axis_name]
            r_name = picking.perpendicular_axis(axis_name)
            r_axis = picking.AXIS_VECTORS[r_name]

            names = [preset.name, preset.name + "_V", preset.name + "_R"]
            duplicates = self.model.existing(names)
            if duplicates and not self.confirm_duplicates(duplicates):
                self.log("Отменено: ЛСК с такими именами уже есть в модели")
                return False

            self.model.create_triplet(
                base_name=preset.name,
                origin=origin,
                v_axis=v_axis,
                r_axis=r_axis,
                offset=geometry.mm(self.cfg.offset_mm),
                show_name=self.cfg.show_name,
            )
            preset.last_axis = axis_name
            self.cfg.save()
            self.last_base = preset.name
            self.log(
                f"{preset.name}: точка «{snap.point.name}» "
                f"({geometry.to_mm(origin[0]):.2f}, {geometry.to_mm(origin[1]):.2f}, "
                f"{geometry.to_mm(origin[2]):.2f}) мм; "
                f"_V: {axis_name}, _R: {r_name}, отступ {self.cfg.offset_mm:g} мм — {how}"
            )
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
            self.log("Нечего отменять в этой сессии (в КОМПАСе работает обычный Ctrl+Z)")
            return
        try:
            self.model.refresh()
            removed = self.model.undo_triplet(self.last_base)
            self.log(f"Удалено ЛСК: {removed} ({self.last_base})")
            self.last_base = None
        except KompasModelError as exc:
            self.log(f"Ошибка: {exc}")
