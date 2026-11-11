"""Панель управления (Tkinter): имена ЛСК, направление, отступ, журнал.

Установка ЛСК: навести курсор на 3D-точку в окне модели и нажать горячую
клавишу (по умолчанию Ctrl+Alt+L). Панель можно держать рядом с КОМПАСом.
"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import config as config_mod
from .hotkey import HotkeyListener
from .session import Placer

TITLE = "ЛСК → КОМПАС"


class Panel:
    def __init__(self, env, app, cfg: config_mod.Config):
        self.env = env
        self.app = app
        self.cfg = cfg
        self._hotkey_queue: queue.Queue[int] = queue.Queue()
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
        self._start_hotkey()
        self.root.after(80, self._tick)

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
        self.names = tk.Listbox(list_frame, height=6, width=30, exportselection=False)
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

        settings = ttk.LabelFrame(outer, text="Направления для выбранного имени", padding=6)
        settings.grid(row=3, column=0, sticky="we", **pad)

        self.no_rotation = tk.BooleanVar(value=self.cfg.orientation != "normal")
        ttk.Checkbutton(
            settings,
            text="Без проворота (оси как у детали)",
            variable=self.no_rotation,
            command=self._on_orientation,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(settings, text="Векторная ЛСК (_V):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.v_sign = tk.IntVar(value=self.cfg.preset.v_sign)
        ttk.Radiobutton(
            settings, text="+Y", value=1, variable=self.v_sign, command=self._on_direction
        ).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Radiobutton(
            settings, text="−Y", value=-1, variable=self.v_sign, command=self._on_direction
        ).grid(row=1, column=2, sticky="w", pady=(6, 0))

        ttk.Label(settings, text="Ось ЛСК поворота (_R):").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        self.r_axis = tk.StringVar(value=self.cfg.preset.r_axis)
        axes = ttk.Frame(settings)
        axes.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0))
        for i, axis in enumerate(config_mod.R_AXES):
            ttk.Radiobutton(
                axes, text=axis, value=axis, variable=self.r_axis, command=self._on_direction
            ).grid(row=0, column=i, padx=2)

        numbers = ttk.LabelFrame(outer, text="Параметры", padding=6)
        numbers.grid(row=4, column=0, sticky="we", **pad)
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
        action.grid(row=5, column=0, sticky="we", **pad)
        ttk.Label(
            action,
            text=f"Наведи курсор на точку в окне модели\nи нажми {self.cfg.hotkey}",
            justify="center",
        ).grid(row=0, column=0, sticky="we")
        self.hotkey_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            action,
            text="Ловить горячую клавишу",
            variable=self.hotkey_enabled,
            command=self._on_hotkey_toggle,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        ttk.Button(outer, text="Отменить последнюю тройку ЛСК", command=self.placer.undo_last).grid(
            row=6, column=0, sticky="we", **pad
        )

        ttk.Label(outer, text="Журнал:").grid(row=7, column=0, sticky="w", padx=6, pady=(6, 0))
        self.log_box = tk.Text(outer, height=9, width=48, state="disabled", wrap="word")
        self.log_box.grid(row=8, column=0, sticky="we", **pad)

        version = self.env.features.version
        ttk.Label(
            outer,
            text=(
                f"КОМПАС {version[0]}.{version[1]}.{version[2]} · "
                f"{'ЛСК: коллекция' if self.env.features.lcs_collection else 'ЛСК: AddObject'}"
            ),
            foreground="#555",
        ).grid(row=9, column=0, sticky="w", padx=6, pady=(2, 0))

    # ------------------------------------------------------------- события
    def run(self) -> None:
        self.log("Готово: выбери имя ЛСК, наведи курсор на точку и нажми горячую клавишу.")
        self.log(self.placer.describe_model())
        self.root.mainloop()

    def _on_close(self) -> None:
        self._hotkey.stop()
        self._on_numbers()
        self.cfg.save()
        self.root.destroy()

    def _on_name_selected(self, _event=None) -> None:
        selection = self.names.curselection()
        if not selection:
            return
        self.cfg.active = selection[0]
        preset = self.cfg.preset
        self.v_sign.set(preset.v_sign)
        self.r_axis.set(preset.r_axis)

    def _on_orientation(self) -> None:
        self.cfg.orientation = "global" if self.no_rotation.get() else "normal"
        self.cfg.save()
        self.log(
            "Ориентация ЛСК: оси детали (без проворота)"
            if self.cfg.orientation == "global"
            else "Ориентация ЛСК: по нормали грани в точке"
        )

    def _on_direction(self) -> None:
        preset = self.cfg.preset
        preset.v_sign = int(self.v_sign.get())
        preset.r_axis = self.r_axis.get()
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

    def _on_hotkey_toggle(self) -> None:
        enabled = bool(self.hotkey_enabled.get())
        self.log("Горячая клавиша включена" if enabled else "Горячая клавиша выключена")

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
        self._on_direction()
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

    # ------------------------------------------------------------- прочее
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

    def _start_hotkey(self) -> None:
        self._hotkey = HotkeyListener(self.cfg.hotkey, lambda: self._hotkey_queue.put(1))
        if not self._hotkey.start():
            self.log(f"Горячая клавиша недоступна: {self._hotkey.error}")

    def _tick(self) -> None:
        fired = False
        while True:
            try:
                self._hotkey_queue.get_nowait()
                fired = True
            except queue.Empty:
                break
        if fired:
            if self.hotkey_enabled.get():
                self.placer.place_under_cursor()
            else:
                self.log("Горячая клавиша выключена в панели")
        self.root.after(80, self._tick)
