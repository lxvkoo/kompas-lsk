"""Пути и сохранение отчётов (работает и в исходниках, и в собранном exe)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def app_dir() -> Path:
    """Каталог рядом с exe (или с исходниками)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resource_path(name: str) -> Path:
    """Путь к файлу-ресурсу: рядом с exe или внутри сборки PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base / name


def save_and_show(text: str, filename: str, open_in_notepad: bool = True) -> Path:
    """Сохранить отчёт рядом с exe и показать его пользователю."""
    path = app_dir() / filename
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        path = Path(os.environ.get("TEMP", ".")) / filename
        path.write_text(text, encoding="utf-8")
    print(f"\nОтчёт сохранён: {path}")
    print(text)
    if open_in_notepad:
        try:
            subprocess.Popen(["notepad.exe", str(path)])
        except Exception:
            pass
    return path
