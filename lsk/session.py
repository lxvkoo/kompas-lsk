"""Оркестрация: режим установки, перехват клика, создание тройки ЛСК.

Клик перехватывается событием окна документа (`IDocumentFrameEvents.MouseDown`).
Обработчик выполняется в потоке КОМПАСа, поэтому он только кладёт координаты
в очередь, а вся работа с API идёт из главного потока (Tk) в `poll()`.
"""

from __future__ import annotations

import queue
import traceback

from . import geometry, picking
from .model import KompasModelError, PartModel

OWNER = "lsk_placer"  # имя владельца обработчиков событий в КОМПАСе


class Placer:
    def __init__(self, env, app, cfg, log, confirm_duplicates):
        self.env = env
        self.app = app
        self.cfg = cfg
        self.log = log
        self.confirm_duplicates = confirm_duplicates
        self.model = PartModel(env, app)

        self._armed = False
        self._events = None
        self._frame = None
        self._callback = None
        self._queue: queue.Queue[tuple[int, int]] = queue.Queue()
        self.last_base: str | None = None

    # ------------------------------------------------------------------
    @property
    def armed(self) -> bool:
        return self._armed

    def arm(self) -> bool:
        """Начать ловить клики в активной детали."""
        try:
            self.model.refresh()
        except KompasModelError as exc:
            self.log(str(exc))
            return False
        if not self.env.features.mouse_events:
            self.log("В этой версии КОМПАСа нет событий мыши API — режим недоступен")
            return False
        try:
            self._frame = self.model.doc.GetDocumentFrame()
            self._events = self._frame.Events()
            if self._callback is None:
                self._callback = self.env.ksapi.IDocumentFrameEvents_OnMouseDownHandler(
                    self._on_mouse_down
                )
            self._events.AddMouseDownHandler(OWNER, self._callback)
        except Exception as exc:
            self.log(f"Не удалось подписаться на клики: {exc}")
            return False
        self._armed = True
        self.log("Режим установки включён — кликай по точкам на модели")
        return True

    def disarm(self, quiet: bool = False) -> None:
        if self._events is not None:
            try:
                self._events.RemoveAllHandlers(OWNER)
            except Exception:
                pass
        self._events = None
        self._frame = None
        self._armed = False
        while not self._queue.empty():  # накопленные клики уже не нужны
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        if not quiet:
            self.log("Режим установки выключен")

    def toggle(self) -> bool:
        if self._armed:
            self.disarm()
            return False
        return self.arm()

    # ------------------------------------------------------------------
    def _on_mouse_down(self, pressed_keys, x, y) -> bool:
        """Обработчик КОМПАСа (его поток). Только складываем координаты в очередь."""
        if not self._armed:
            return False
        try:  # реагируем только на левую кнопку, остальное отдаём КОМПАСу
            keys = self.env.ksapi.IPressedKeys(pressed_keys, self.app)
            if keys and not keys.IsMouseLeftButton():
                return False
        except Exception:
            pass
        self._queue.put((int(x), int(y)))
        return bool(self.cfg.swallow_click)

    def poll(self) -> None:
        """Вызывается из главного потока (Tk `after`)."""
        while True:
            try:
                x, y = self._queue.get_nowait()
            except queue.Empty:
                return
            if not self._armed:
                continue
            self.place(x, y)

    # ------------------------------------------------------------------
    def place(self, window_x: int, window_y: int) -> None:
        """Обработать клик: найти точку, направление и поставить три ЛСК."""
        preset = self.cfg.preset
        tol = geometry.mm(self.cfg.snap_tol_mm)
        try:
            self.model.refresh()  # пользователь мог переключить документ
            pick = picking.pick_at(self.env, self.model, window_x, window_y)
            if not pick.ok:
                self.log(pick.warning or "Клик не по модели")
                return

            snap = picking.snap_to_point(self.model.points(), pick, tol)
            if snap is None:
                self.log(
                    f"Рядом с курсором нет 3D-точки модели (допуск {self.cfg.snap_tol_mm:g} мм). "
                    "Проставь точку инструментом «Точка»/«Точка в центре» и кликни по ней."
                )
                return

            origin = snap.point.coords
            direction = picking.face_direction(self.env, self.app, pick, origin, tol)
            if direction is None:
                self.log("Не удалось определить направление: под курсором нет грани")
                return

            normal = direction.normal
            if preset.v_sign < 0:
                normal = geometry.mul(normal, -1.0)
            axes = geometry.frame_from_normal(normal)

            names = [preset.name, preset.name + "_V", preset.name + "_R"]
            duplicates = self.model.existing(names)
            if duplicates and not self.confirm_duplicates(duplicates):
                self.log("Отменено: ЛСК с такими именами уже есть в модели")
                return

            offset = geometry.mm(self.cfg.offset_mm)
            self.model.create_triplet(
                base_name=preset.name,
                origin=origin,
                axes=axes,
                offset=offset,
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
                self.log("  ! созданы наложением на существующие: " + ", ".join(duplicates))
        except KompasModelError as exc:
            self.log(f"Ошибка: {exc}")
        except Exception:
            self.log("Неожиданная ошибка:\n" + traceback.format_exc(limit=3))

    # ------------------------------------------------------------------
    def undo_last(self) -> None:
        if not self.last_base:
            self.log("Нечего отменять в этой сессии")
            return
        try:
            self.model.refresh()
            removed = self.model.undo_triplet(self.last_base)
            self.log(f"Удалено ЛСК: {removed} ({self.last_base})")
        except KompasModelError as exc:
            self.log(f"Ошибка: {exc}")
        self.last_base = None
