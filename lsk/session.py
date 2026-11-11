"""Сценарий установки: «навёл курсор на точку → зажал клавишу → потянул → отпустил».

Почему так:
* события мыши КОМПАС в Python не доставляет (проверено), поэтому точку берём по
  позиции курсора, а направление — по протяжке мышью;
* привязка и выбор оси работают в пикселях (`lsk/picking.py`), потому что
  `GetPickRay` в v25 ведёт себя нестабильно;
* всё считается один раз при нажатии: во время протяжки подсказка рисуется без
  обращений к API;
* создание тройки обёрнуто в контейнер отмены, поэтому штатный Ctrl+Z в КОМПАСе
  убирает все три ЛСК одним шагом.

Все вызовы API идут из главного потока (Tk), никаких обратных вызовов из
КОМПАСа — так связь с КОМПАСом остаётся живой.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from . import geometry, picking, win32cursor
from .model import KompasModelError, PartModel


@dataclass
class PressState:
    """Всё, что нужно для постановки ЛСК, посчитанное в момент нажатия."""

    press: tuple[int, int]                       # пиксели клиентской области
    anchor_screen: tuple[int, int]               # экранная точка (для подсказки)
    origin: geometry.Vec | None = None           # координаты найденной точки
    point_name: str = ""
    vectors: dict = field(default_factory=dict)  # ось -> экранное направление
    scale: float = 1.0                           # мм на пиксель
    error: str = ""


class Placer:
    def __init__(self, env, app, cfg, log, confirm_duplicates):
        self.env = env
        self.app = app
        self.cfg = cfg
        self.log = log
        self.confirm_duplicates = confirm_duplicates
        self.model = PartModel(env, app)
        self.last_base: str | None = None
        self.state: PressState | None = None

    # ------------------------------------------------------------------
    def on_press(self) -> None:
        """Клавиша нажата: найти точку и посчитать экранные направления осей."""
        self.state = None
        cursor = self._cursor_client()
        if cursor is None:
            return
        state = PressState(press=cursor, anchor_screen=self._cursor_screen() or cursor)
        self.state = state
        try:
            self.model.refresh()
            frame = self.model.doc.GetDocumentFrame()
            if not frame:
                state.error = "У документа нет окна (модель открыта без окна?)"
                return
            width, height = win32cursor.client_size(frame.GetWindowHandle())
            if not (0 <= cursor[0] < width and 0 <= cursor[1] < height):
                state.error = "Курсор не над окном модели — наведи его на деталь"
                return

            points = self.model.points()
            if not points:
                state.error = (
                    f"В документе «{self.model.doc.GetName() or 'без имени'}» нет 3D-точек. "
                    "Проставь их инструментом «Точка» / «Точка в центре»."
                )
                return

            scale = picking.mm_per_pixel(self.env, self.model, points[0].coords)
            tolerance_px = max(self.cfg.snap_tol_px, self.cfg.snap_tol_mm / max(scale, 1e-6))
            snap = picking.snap_to_point(self.env, self.model, points, cursor, tolerance_px)
            if snap is None:
                nearest_px = None
                for p in points:
                    pixel = picking.point_to_pixel(self.env, self.model, p.coords)
                    if pixel is None:
                        continue
                    d = geometry.length(
                        (float(pixel[0] - cursor[0]), float(pixel[1] - cursor[1]), 0.0)
                    )
                    if nearest_px is None or d < nearest_px:
                        nearest_px = d
                state.error = (
                    f"Рядом нет точки: ближайшая в {nearest_px or 0:.0f} px "
                    f"(≈{(nearest_px or 0) * scale:.1f} мм, допуск {tolerance_px:.0f} px). "
                    "Курсор — точно на точку?"
                )
                return

            state.origin = snap.point.coords
            state.point_name = snap.point.name
            state.scale = scale
            state.vectors = picking.axis_screen_vectors(self.env, self.model, state.origin)
            state.anchor_screen = self._point_screen(state.origin) or state.anchor_screen
        except KompasModelError as exc:
            state.error = str(exc)
        except Exception:
            state.error = "Неожиданная ошибка:\n" + traceback.format_exc(limit=2)

    # ------------------------------------------------------------------
    def preview(self) -> tuple[tuple[int, int], tuple[float, float], str] | None:
        """Подсказка во время протяжки: (экранная точка, направление, подпись).

        Обращений к API нет — только данные, посчитанные при нажатии.
        """
        state = self.state
        if state is None or state.error or state.origin is None or not state.vectors:
            return None
        cursor = self._cursor_client()
        if cursor is None:
            return None
        drag = (float(cursor[0] - state.press[0]), float(cursor[1] - state.press[1]))
        dragged = (drag[0] ** 2 + drag[1] ** 2) ** 0.5 >= self.cfg.drag_threshold_px

        guess = picking.best_axis(drag, state.vectors) if dragged else None
        if guess is not None:
            axis = guess[0]
            label = f"_V: {axis}"
        else:
            axis = self.cfg.preset.last_axis
            label = f"_V: {axis} (как в прошлый раз)"
        direction = state.vectors.get(axis)
        if direction is None:
            return None
        return state.anchor_screen, direction, label

    # ------------------------------------------------------------------
    def on_release(self) -> str | None:
        """Клавиша отпущена: поставить тройку. Возвращает имя базовой ЛСК."""
        state = self.state
        self.state = None
        if state is None:
            return None
        if state.error:
            self.log(state.error)
            return None
        if state.origin is None:
            return None

        cursor = self._cursor_client() or state.press
        drag = (float(cursor[0] - state.press[0]), float(cursor[1] - state.press[1]))
        dragged = (drag[0] ** 2 + drag[1] ** 2) ** 0.5 >= self.cfg.drag_threshold_px

        preset = self.cfg.preset
        axis_name = None
        how = ""
        if dragged:
            guess = picking.best_axis(drag, state.vectors)
            if guess is not None:
                axis_name = guess[0]
                how = f"протяжка (совпадение {guess[1]:.2f})"
        if axis_name is None:
            axis_name = preset.last_axis
            how = "по прежнему выбору"

        try:
            names = [preset.name, preset.name + "_V", preset.name + "_R"]
            duplicates = self.model.existing(names)
            if duplicates and not self.confirm_duplicates(duplicates):
                self.log("Отменено: ЛСК с такими именами уже есть в модели")
                return None

            r_name = picking.perpendicular_axis(axis_name)
            self.model.create_triplet(
                base_name=preset.name,
                origin=state.origin,
                v_axis=picking.AXIS_VECTORS[axis_name],
                r_axis=picking.AXIS_VECTORS[r_name],
                offset=geometry.mm(self.cfg.offset_mm),
                show_name=self.cfg.show_name,
            )
            preset.last_axis = axis_name
            self.cfg.save()
            self.last_base = preset.name
            origin = state.origin
            self.log(
                f"{preset.name}: точка «{state.point_name}» "
                f"({geometry.to_mm(origin[0]):.2f}, {geometry.to_mm(origin[1]):.2f}, "
                f"{geometry.to_mm(origin[2]):.2f}) мм; "
                f"_V: {axis_name}, _R: {r_name}, отступ {self.cfg.offset_mm:g} мм — {how}"
            )
            if duplicates:
                self.log("  ! созданы поверх существующих: " + ", ".join(duplicates))
            return preset.name
        except KompasModelError as exc:
            self.log(f"Ошибка: {exc}")
        except Exception:
            self.log("Неожиданная ошибка:\n" + traceback.format_exc(limit=3))
        return None

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

    # ------------------------------------------------------------------ утилиты
    def _cursor_client(self) -> tuple[int, int] | None:
        try:
            frame = self.model.doc.GetDocumentFrame() if self.model.doc else None
            if not frame:
                self.model.refresh()
                frame = self.model.doc.GetDocumentFrame()
            if not frame:
                return None
            x, y = win32cursor.cursor_client_pos(frame.GetWindowHandle())
            return (x, y) if x >= 0 else None
        except Exception:
            return None

    def _cursor_screen(self) -> tuple[int, int] | None:
        return win32cursor.cursor_screen_pos()

    def _point_screen(self, point: geometry.Vec) -> tuple[int, int] | None:
        try:
            frame = self.model.doc.GetDocumentFrame()
            if not frame:
                return None
            pixel = picking.point_to_pixel(self.env, self.model, point)
            if pixel is None:
                return None
            return win32cursor.client_to_screen(frame.GetWindowHandle(), *pixel)
        except Exception:
            return None
