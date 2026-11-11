"""Подсказка во время протяжки: стрелка на экране вдоль выбранной оси.

Своё прозрачное окошко поверх КОМПАСа: во время удержания клавиши показывает
направление, которое будет выбрано для векторной ЛСК, и подпись оси.
Клики и фокус не перехватывает (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`).
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
LABEL_BG = "#1f1f1f"
LABEL_FG = "#ffffff"
ARROW_LENGTH = 110
SIZE = ARROW_LENGTH * 2 + 40


class DirectionOverlay:
    """Стрелка с подписью, которая появляется рядом с точкой при протяжке."""

    def __init__(self, root: tk.Misc):
        self._root = root
        self._visible = False
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._label_id = None
        self._arrow_ids: list[int] = []

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
            pass  # не Windows-тема — просто будет непрозрачный фон
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
    def show_at(self, anchor: tuple[int, int], direction: tuple[float, float], text: str) -> None:
        """Показать стрелку из экранной точки `anchor` в направлении `direction`."""
        self._ensure()
        if self._canvas is None or self._win is None:
            return

        length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
        if length < 1e-6:
            direction, length = (0.0, -1.0), 1.0
        ux, uy = direction[0] / length, direction[1] / length

        left = int(anchor[0] - SIZE / 2)
        top = int(anchor[1] - SIZE / 2)
        self._win.geometry(f"{SIZE}x{SIZE}+{left}+{top}")

        cx = cy = SIZE / 2
        ex, ey = cx + ux * ARROW_LENGTH, cy + uy * ARROW_LENGTH
        head = 14
        px, py = -uy, ux  # перпендикуляр

        canvas = self._canvas
        for item in self._arrow_ids:
            canvas.delete(item)
        self._arrow_ids = [
            canvas.create_line(cx, cy, ex, ey, fill=ARROW_COLOR, width=4, arrow=tk.LAST,
                               arrowshape=(head, head * 1.2, head * 0.5)),
            canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=ARROW_COLOR, outline=""),
            canvas.create_line(ex - px * 10, ey - py * 10, ex + px * 10, ey + py * 10,
                               fill=ARROW_COLOR, width=2),
        ]
        if self._label_id is not None:
            canvas.delete(self._label_id)
        lx = cx + ux * (ARROW_LENGTH + 26)
        ly = cy + uy * (ARROW_LENGTH + 26)
        self._label_id = canvas.create_text(
            lx, ly, text=text, fill=LABEL_FG, font=("Segoe UI", 11, "bold"),
            anchor="center",
        )
        if not self._visible:
            self._win.deiconify()
            self._visible = True

    def hide(self) -> None:
        if self._win is not None and self._visible:
            self._win.withdraw()
            self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible
