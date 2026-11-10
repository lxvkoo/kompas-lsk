"""Настройки приложения: имена ЛСК, отступ, допуск привязки, горячая клавиша.

Хранятся в `%APPDATA%\\lsk_placer\\config.json`, чтобы переживать пересборку exe.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

R_AXES = ("+X", "-X", "+Z", "-Z")

DEFAULT_NAMES = (
    "ЛСК_Т03",
    "ЛСК_БКН",
    "ЛСК_Кабельный_Ввод",
    "ЛСК_ПМ",
    "ЛСК_Т01",
)


@dataclass
class Preset:
    """Имя ЛСК + запомненные для него настройки направления."""

    name: str
    r_axis: str = "+X"   # куда смещается ЛСК поворота: +X/-X/+Z/-Z в базовой системе
    v_sign: int = 1      # +1 — векторная ЛСК наружу по нормали, -1 — внутрь


@dataclass
class Config:
    presets: list[Preset] = field(default_factory=lambda: [Preset(n) for n in DEFAULT_NAMES])
    offset_mm: float = 10.0        # отступ векторной и поворотной ЛСК от базовой
    snap_tol_mm: float = 3.0       # радиус привязки клика к 3D-точке модели
    show_name: bool = True         # включать «Показывать надпись» у ЛСК
    hotkey: str = "Ctrl+Alt+L"
    swallow_click: bool = True     # не отдавать клик КОМПАСу (не менять выделение)
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
                    r_axis=str(p.get("r_axis", "+X")),
                    v_sign=1 if int(p.get("v_sign", 1)) >= 0 else -1,
                )
                for p in raw.get("presets", [])
            ]
            cfg = cls(
                presets=presets or [Preset(n) for n in DEFAULT_NAMES],
                offset_mm=float(raw.get("offset_mm", 10.0)),
                snap_tol_mm=float(raw.get("snap_tol_mm", 3.0)),
                show_name=bool(raw.get("show_name", True)),
                hotkey=str(raw.get("hotkey", "Ctrl+Alt+L")),
                swallow_click=bool(raw.get("swallow_click", True)),
                active=int(raw.get("active", 0)),
            )
            for p in cfg.presets:  # защита от опечаток в файле
                if p.r_axis.upper() not in R_AXES:
                    p.r_axis = "+X"
            return cfg
        except (TypeError, ValueError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or self.path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(self)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # не критично: настройки просто не сохранятся
