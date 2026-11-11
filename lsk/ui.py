"""Панель управления (Tkinter): имена ЛСК, отступ, журнал.

Установка: навести курсор на 3D-точку, зажать горячую клавишу, потянуть мышью
в нужную сторону и отпустить. Направление векторной ЛСК (_V) берётся из
протяжки, _R — по первой перпендикулярной оси.
"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import config as config_mod
from .hotkey import KeyWatcher, parse_hotkey
from .session import Placer

TITLE = "ЛСК → КОМПАС"

GESTURE_HINT = (
    "1. Наведи курсор на 3D-точку модели\n"
    "2. Зажми {key} и потяни мышью в нужную сторону\n"
    "3. Отпусти клавишу — появятся три ЛСК\n"
    "Потянул мало — направление как в прошлый раз.\n"
    "Ошибся? Штатный Ctrl+Z уберёт все три сразу."
)


class Panel:
    def __init__(self, env, app, cfg: config_mod.Config):
        self.env = env
        self.app = app
        self.cfg = cfg
        self._events: queue.Queue[str] = queue.Queue()
        self._log_lines = 0

        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.placer = Placer(
            env=env,
            app=app,
            cfg=cfg,
            log=self.log,
            confirm_duplicates=self._confirm_duplicates,
        )

        self._build()
        self._start_watcher()
        self.root.after(60, self._tick)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 3}
        outer = ttk.Frame(self.root, padding=8)
        outer.grid(row=0, column=0, sticky="nsew")

        ttk.Label(outer, text="Имя ЛСК (ставятся три: имя, _V, _R):").grid(
            row=0, column=0, sticky="w", **pad
        )

        list_frame = ttk.Frame(outer)
        list_frame.grid(row=1, column=0, sticky="we", **pad)
        self.names = tk.Listbox(list_frame, height=6, width=34, exportselection=False)
        self.names.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, command=self.names.yview)
        scroll.pack(side="right", fill="y")
        self.names.configure(yscrollcommand=scroll.set)
        self.names.bind("<<ListboxSelect>>", self._on_name_selected)
        self._fill_names()

        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, sticky="we", **pad)
        ttk.Button(buttons, text="Добавить", command=self._add_name, width=10).pack(side="left")
        ttk.Button(buttons, text="Переименовать", command=self._rename_name, width=14).pack(
            side="left", padx=4
        )
        ttk.Button(buttons, text="Удалить", command=self._remove_name, width=9).pack(side="left")

        numbers = ttk.LabelFrame(outer, text="Параметры", padding=6)
        numbers.grid(row=3, column=0, sticky="we", **pad)
        ttk.Label(numbers, text="Отступ, мм:").grid(row=0, column=0, sticky="w")
        self.offset = tk.StringVar(value=f"{self.cfg.offset_mm:g}")
        ttk.Spinbox(
            numbers, from_=1, to=500, increment=1, width=6, textvariable=self.offset,
            command=self._on_numbers,
        ).grid(row=0, column=1, sticky="w", padx=(2, 12))
        ttk.Label(numbers, text="Допуск привязки, мм:").grid(row=0, column=2, sticky="w")
        self.snap_tol = tk.StringVar(value=f"{self.cfg.snap_tol_mm:g}")
        ttk.Spinbox(
            numbers, from_=0.5, to=50, increment=0.5, width=6, textvariable=self.snap_tol,
            command=self._on_numbers,
        ).grid(row=0, column=3, sticky="w", padx=2)
        self.show_name = tk.BooleanVar(value=self.cfg.show_name)
        ttk.Checkbutton(
            numbers, text="«Показывать надпись»", variable=self.show_name, command=self._on_numbers
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        action = ttk.LabelFrame(outer, text="Установка", padding=6)
        action.grid(row=4, column=0, sticky="we", **pad)
        self.hint = ttk.Label(action, text=GESTURE_HINT.format(key=self.cfg.hotkey), justify="left")
        self.hint.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(action, text="Клавиша:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.hotkey_var = tk.StringVar(value=self.cfg.hotkey)
        ttk.Entry(action, textvariable=self.hotkey_var, width=12).grid(
            row=1, column=1, sticky="w", padx=4, pady=(8, 0)
        )
        ttk.Button(action, text="Применить", width=10, command=self._apply_hotkey).grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )

        ttk.Button(outer, text="Удалить последнюю тройку ЛСК", command=self.placer.undo_last).grid(
            row=5, column=0, sticky="we", **pad
        )

        ttk.Label(outer, text="Журнал:").grid(row=6, column=0, sticky="w", padx=6, pady=(6, 0))
        self.log_box = tk.Text(outer, height=8, width=50, state="disabled", wrap="word")
        self.log_box.grid(row=7, column=0, sticky="we", **pad)

    # ------------------------------------------------------------- события
    def run(self) -> None:
        self.root.mainloop()

    def _on_close(self) -> None:
        self._watcher.stop()
        self._on_numbers()
        self.cfg.save()
        self.root.destroy()

    def _on_name_selected(self, _event=None) -> None:
        selection = self.names.curselection()
        if not selection:
            return
        self.cfg.active = selection[0]
        self.cfg.save()

    def _on_numbers(self) -> None:
        try:
            self.cfg.offset_mm = max(0.1, float(self.offset.get().replace(",", ".")))
        except ValueError:
            self.offset.set(f"{self.cfg.offset_mm:g}")
        try:
            self.cfg.snap_tol_mm = max(0.1, float(self.snap_tol.get().replace(",", ".")))
        except ValueError:
            self.snap_tol.set(f"{self.cfg.snap_tol_mm:g}")
        self.cfg.show_name = bool(self.show_name.get())
        self.cfg.save()

    # ------------------------------------------------------------- имена
    def _fill_names(self) -> None:
        self.names.delete(0, tk.END)
        for preset in self.cfg.presets:
            self.names.insert(tk.END, preset.name)
        index = max(0, min(self.cfg.active, len(self.cfg.presets) - 1))
        self.names.selection_clear(0, tk.END)
        self.names.selection_set(index)
        self.names.activate(index)

    def _add_name(self) -> None:
        name = simpledialog.askstring(TITLE, "Имя новой ЛСК:", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        if any(p.name == name for p in self.cfg.presets):
            messagebox.showwarning(TITLE, f"«{name}» уже есть в списке.", parent=self.root)
            return
        self.cfg.presets.append(config_mod.Preset(name))
        self.cfg.active = len(self.cfg.presets) - 1
        self._fill_names()
        self.cfg.save()

    def _rename_name(self) -> None:
        selection = self.names.curselection()
        if not selection:
            return
        preset = self.cfg.presets[selection[0]]
        name = simpledialog.askstring(TITLE, "Новое имя:", initialvalue=preset.name, parent=self.root)
        if not name or not name.strip():
            return
        preset.name = name.strip()
        self._fill_names()
        self.cfg.save()

    def _remove_name(self) -> None:
        selection = self.names.curselection()
        if not selection:
            return
        preset = self.cfg.presets[selection[0]]
        if not messagebox.askyesno(TITLE, f"Удалить «{preset.name}» из списка?", parent=self.root):
            return
        del self.cfg.presets[selection[0]]
        if not self.cfg.presets:
            self.cfg.presets = [config_mod.Preset(n) for n in config_mod.DEFAULT_NAMES]
        self.cfg.active = 0
        self._fill_names()
        self.cfg.save()

    # ------------------------------------------------------------- клавиша
    def _confirm_duplicates(self, names: list[str]) -> bool:
        return messagebox.askyesno(
            TITLE,
            "В модели уже есть ЛСК с такими именами:\n\n"
            + "\n".join("  • " + n for n in names)
            + "\n\nСоздать дубли (имена не меняются)?",
            parent=self.root,
            default="no",
        )

    def log(self, text: str) -> None:
        self._log_lines += 1
        stamp = f"{self._log_lines:>3}. "
        self.log_box.configure(state="normal")
        self.log_box.insert(tk.END, stamp + text.rstrip() + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state="disabled")
        print(text)

    def _start_watcher(self) -> None:
        self._watcher = KeyWatcher(
            self.cfg.hotkey,
            on_press=lambda: self._events.put("press"),
            on_release=lambda: self._events.put("release"),
        )
        if not self._watcher.start():
            self.log(f"Горячая клавиша недоступна: {self._watcher.error}")
        elif self._watcher.error:
            self.log(self._watcher.error)

    def _apply_hotkey(self) -> None:
        spec = self.hotkey_var.get().strip()
        if parse_hotkey(spec) is None:
            self.log(f"Не понял сочетание «{spec}». Примеры: Ctrl+1, Ctrl+Alt+L, F9")
            return
        self._watcher.stop()
        self.cfg.hotkey = spec
        self.cfg.save()
        self._start_watcher()
        self.hint.configure(text=GESTURE_HINT.format(key=spec))
        self.log(f"Горячая клавиша: {spec}")

    def _tick(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event == "press":
                self.placer.on_press()
            else:
                self.placer.on_release()
        self.root.after(60, self._tick)
