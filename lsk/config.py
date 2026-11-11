"""Настройки приложения: имена ЛСК, отступ, допуск привязки, горячая клавиша.

Хранятся в `%APPDATA%\\lsk_placer\\config.json`, чтобы переживать пересборку exe.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_NAMES = (
    "ЛСК_Т03",
    "ЛСК_БКН",
    "ЛСК_Кабельный_Ввод",
    "ЛСК_ПМ",
    "ЛСК_Т01",
)

#: направления векторной ЛСК, которые можно выбрать протяжкой мышью
AXES = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


@dataclass
class Preset:
    """Имя ЛСК + последнее выбранное направление (если потянуть мышью не вышло)."""

    name: str
    last_axis: str = "+Y"


@dataclass
class Config:
    presets: list[Preset] = field(default_factory=lambda: [Preset(n) for n in DEFAULT_NAMES])
    offset_mm: float = 10.0        # отступ векторной и поворотной ЛСК от базовой
    snap_tol_mm: float = 3.0       # минимум допуска привязки к 3D-точке модели
    snap_tol_px: float = 10.0      # и то же в пикселях экрана (зависит от масштаба вида)
    show_name: bool = True         # включать «Показывать надпись» у ЛСК
    hotkey: str = "Ctrl+1"
    drag_threshold_px: float = 12.0  # меньше этого движение считается «нажатием»
    active: int = 0                # индекс выбранного пресета

    # --- доступ к текущему пресету -------------------------------------
    @property
    def preset(self) -> Preset:
        if not self.presets:
            self.presets = [Preset(n) for n in DEFAULT_NAMES]
        self.active = max(0, min(self.active, len(self.presets) - 1))
        return self.presets[self.active]

    # --- файл -----------------------------------------------------------
    @staticmethod
    def path() -> Path:
        root = os.environ.get("APPDATA") or str(Path.home())
        return Path(root) / "lsk_placer" / "config.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or cls.path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        try:
            presets = [
                Preset(
                    name=str(p.get("name", "")).strip() or "ЛСК",
                    last_axis=str(p.get("last_axis", "+Y")),
                )
                for p in raw.get("presets", [])
            ]
            cfg = cls(
                presets=presets or [Preset(n) for n in DEFAULT_NAMES],
                offset_mm=float(raw.get("offset_mm", 10.0)),
                snap_tol_mm=float(raw.get("snap_tol_mm", 3.0)),
                snap_tol_px=float(raw.get("snap_tol_px", 10.0)),
                show_name=bool(raw.get("show_name", True)),
                hotkey=str(raw.get("hotkey", "Ctrl+1")),
                drag_threshold_px=float(raw.get("drag_threshold_px", 12.0)),
                active=int(raw.get("active", 0)),
            )
            for preset in cfg.presets:
                if preset.last_axis.upper() not in AXES:
                    preset.last_axis = "+Y"
            if cfg.hotkey.upper() == "CTRL+ALT+L":
                cfg.hotkey = "Ctrl+1"  # старое значение по умолчанию
            return cfg
        except (TypeError, ValueError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or self.path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # не критично: настройки просто не сохранятся
