"""Подсказка во время протяжки: стрелка на экране вдоль выбранной оси.

Своё прозрачное окошко поверх КОМПАСа: во время удержания клавиши показывает
направление, которое будет выбрано для векторной ЛСК, и подпись оси.
Клики и фокус не перехватывает (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`).

Важные детали, из-за которых была «рябь» и обрезанные подписи:
* прозрачность — по цветовому ключу, поэтому текст рисуется на непрозрачной
  плашке (иначе сглаживание шрифта даёт грязные края поверх модели);
* окошко всегда сдвигается так, чтобы целиком оставаться на экране, а якорь
  рисуется по своим локальным координатам (иначе у края экрана видна только точка);
* стрелка рисуется в два прохода (тёмная обводка + оранжевая линия), чтобы
  читалась на любом фоне;
* перерисовка только при смене оси — никакого мигания.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

TRANSPARENT = "#010101"  # этот цвет станет прозрачным
ARROW_COLOR = "#ff8c00"
OUTLINE_COLOR = "#202020"
LABEL_FG = "#ffffff"
LABEL_BG = "#151515"
ARROW_LENGTH = 96
ARROW_MIN = 26
LABEL_GAP = 18
MARGIN = 8
LABEL_SPACE = 40  # приблизительный размер плашки по направлению стрелки
SIZE = (ARROW_LENGTH + LABEL_GAP) * 2 + 140  # запас под подпись и якорь


class DirectionOverlay:
    """Стрелка с подписью, которая появляется рядом с точкой при протяжке."""

    def __init__(self, root: tk.Misc):
        self._root = root
        self._visible = False
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._arrow_ids: list[int] = []
        self._label_ids: list[int] = []
        self._key: tuple | None = None  # что сейчас нарисовано

    # ------------------------------------------------------------------
    def _ensure(self) -> None:
        if self._win is not None:
            return
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        win.configure(bg=TRANSPARENT)
        canvas = tk.Canvas(
            win, width=SIZE, height=SIZE, bg=TRANSPARENT, highlightthickness=0, bd=0
        )
        canvas.pack()
        win.update_idletasks()
        self._make_click_through(win)
        win.withdraw()
        self._win = win
        self._canvas = canvas

    @staticmethod
    def _make_click_through(win: tk.Toplevel) -> None:
        try:
            hwnd = int(win.wm_frame(), 16)
            user32.GetWindowLongW.restype = ctypes.c_long
            style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
            user32.SetWindowLongW(
                wintypes.HWND(hwnd),
                GWL_EXSTYLE,
                style | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    @staticmethod
    def _screen_size() -> tuple[int, int]:
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))

    def show_at(self, anchor: tuple[int, int], direction: tuple[float, float], text: str) -> None:
        """Показать стрелку из экранной точки `anchor` в направлении `direction`."""
        self._ensure()
        if self._canvas is None or self._win is None:
            return

        # окно сдвигаем «назад» по направлению стрелки: так впереди больше места
        length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
        ux, uy = (direction[0] / length, direction[1] / length) if length > 1e-9 else (0.0, -1.0)
        screen_width, screen_height = self._screen_size()
        left = int(anchor[0] - SIZE / 2 + ux * SIZE / 4)
        top = int(anchor[1] - SIZE / 2 + uy * SIZE / 4)
        left = max(0, min(left, max(0, screen_width - SIZE)))
        top = max(0, min(top, max(0, screen_height - SIZE)))

        key = (left, top, text, round(direction[0], 2), round(direction[1], 2))
        if key != self._key:
            self._win.geometry(f"{SIZE}x{SIZE}+{left}+{top}")
            try:
                self._draw(anchor[0] - left, anchor[1] - top, direction, text)
                self._key = key
            except Exception as exc:  # подсказка не должна ронять панель
                print(f"overlay: {exc}")
        if not self._visible:
            self._win.deiconify()
            self._visible = True

    # ------------------------------------------------------------------
    def _draw(self, cx: float, cy: float, direction: tuple[float, float], text: str) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        for item in self._arrow_ids + self._label_ids:
            canvas.delete(item)
        self._arrow_ids, self._label_ids = [], []

        length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
        if length < 1e-6:
            direction, length = (0.0, -1.0), 1.0
        ux, uy = direction[0] / length, direction[1] / length

        # сколько места есть от якоря до края окна в эту сторону
        available = self._available(cx, cy, ux, uy)
        arrow = ARROW_LENGTH
        if available < arrow + LABEL_GAP + LABEL_SPACE:
            arrow = max(ARROW_MIN, available - LABEL_GAP - LABEL_SPACE)
        ex, ey = cx + ux * arrow, cy + uy * arrow
        arrowshape = (16, 20, 8)

        # обводка + сама стрелка: так линия читается на светлой детали
        self._arrow_ids.append(
            canvas.create_line(cx, cy, ex, ey, fill=OUTLINE_COLOR, width=8,
                               arrow=tk.LAST, arrowshape=arrowshape)
        )
        self._arrow_ids.append(
            canvas.create_line(cx, cy, ex, ey, fill=ARROW_COLOR, width=4,
                               arrow=tk.LAST, arrowshape=arrowshape)
        )
        self._arrow_ids.append(
            canvas.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=ARROW_COLOR,
                               outline=OUTLINE_COLOR, width=2)
        )

        # подпись: ставим за концом стрелки с учётом её реального размера
        text_id = canvas.create_text(
            cx + ux * (arrow + LABEL_GAP), cy + uy * (arrow + LABEL_GAP),
            text=text, fill=LABEL_FG, font=("Segoe UI", 11, "bold"), anchor="center",
        )
        bbox = canvas.bbox(text_id)
        if bbox is not None:
            # ближний к якорю край плашки должен начинаться за концом стрелки
            corners = [(bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[0], bbox[3]), (bbox[2], bbox[3])]
            proj_min = min((corner[0] - cx) * ux + (corner[1] - cy) * uy for corner in corners)
            need = arrow + LABEL_GAP
            if proj_min < need:
                shift = need - proj_min
                canvas.move(text_id, ux * shift, uy * shift)
                bbox = canvas.bbox(text_id) or bbox
        # и всё-таки не даём вылезти за окно
        if bbox is not None:
            shift_x = 0.0
            shift_y = 0.0
            if bbox[0] < MARGIN:
                shift_x = MARGIN - bbox[0]
            elif bbox[2] > SIZE - MARGIN:
                shift_x = SIZE - MARGIN - bbox[2]
            if bbox[1] < MARGIN:
                shift_y = MARGIN - bbox[1]
            elif bbox[3] > SIZE - MARGIN:
                shift_y = SIZE - MARGIN - bbox[3]
            if shift_x or shift_y:
                canvas.move(text_id, shift_x, shift_y)
                bbox = canvas.bbox(text_id) or bbox

        plate = canvas.create_rectangle(
            bbox[0] - 7, bbox[1] - 3, bbox[2] + 7, bbox[3] + 3,
            fill=LABEL_BG, outline=OUTLINE_COLOR, width=1,
        ) if bbox else None
        if plate is not None:
            canvas.tag_lower(plate, text_id)
        # стрелка всегда сверху, чтобы не пряталась за плашкой
        for item in self._arrow_ids:
            canvas.tag_raise(item)
        if plate is not None:
            canvas.tag_raise(text_id)
        self._label_ids = [item for item in (plate, text_id) if item is not None]

    @staticmethod
    def _available(cx: float, cy: float, ux: float, uy: float) -> float:
        """Расстояние от точки внутри окна до его границы в направлении (ux, uy)."""
        limits = []
        if ux > 1e-6:
            limits.append((SIZE - MARGIN - cx) / ux)
        elif ux < -1e-6:
            limits.append((MARGIN - cx) / ux)
        if uy > 1e-6:
            limits.append((SIZE - MARGIN - cy) / uy)
        elif uy < -1e-6:
            limits.append((MARGIN - cy) / uy)
        return min(limits) if limits else float(SIZE)

    def hide(self) -> None:
        if self._win is not None and self._visible:
            self._win.withdraw()
            self._visible = False
            self._key = None

    @property
    def visible(self) -> bool:
        return self._visible
