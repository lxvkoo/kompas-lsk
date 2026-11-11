"""Точка входа: панель управления расстановкой ЛСК.

Запуск:  python main.py
Требуется запущенный КОМПАС-3D с открытой деталью (*.m3d).

Служебные режимы (полезны в собранном exe, где нет консоли):
    main.py --probe      диагностика окружения (пишет report.txt и открывает его)
    main.py --selftest   автотест во временной детали
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import traceback
from pathlib import Path


def _fix_streams() -> None:
    """В сборке без консоли sys.stdout/stderr = None: print() не должен падать."""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def _app_dir() -> Path:
    """Каталог рядом с exe (или с исходниками)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _fatal(message: str) -> int:
    """Сообщить об ошибке так, чтобы это увидели и без консоли."""
    print(message)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("ЛСК → КОМПАС", message)
        root.destroy()
    except Exception:
        pass
    return 1


def _save_and_show(text: str, filename: str, title: str) -> Path:
    """Сохранить отчёт рядом с exe и открыть в блокноте (консоли может не быть)."""
    path = _app_dir() / filename
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        path = Path(os.environ.get("TEMP", ".")) / filename
        path.write_text(text, encoding="utf-8")
    print(f"\nОтчёт сохранён: {path}")
    print(text)
    try:
        subprocess.Popen(["notepad.exe", str(path)])
    except Exception:
        pass
    return path


def _run_probe() -> int:
    """Диагностика окружения: версия КОМПАСа и доступные возможности API."""
    from lsk import kompas

    lines: list[str] = []
    try:
        env = kompas.load()
    except kompas.KompasNotFound as exc:
        _fatal(f"КОМПАС не найден.\n\n{exc}")
        return 2

    lines.append(f"Python {sys.version.split()[0]} ({'64' if sys.maxsize > 2**32 else '32'}-bit)")
    lines.append(f"Каталог Bin: {env.bin_dir}")

    app = env.app()
    if app is None:
        lines.append("КОМПАС не запущен — запусти КОМПАС и повтори, тогда будет видна версия")
    else:
        env.refresh_version(app)
        lines.append("")
        lines.append(env.features.as_text())
        doc = app.GetActiveDocument()
        if doc is None:
            lines.append("\nАктивный документ: нет")
        else:
            type_names = {
                env.constants.ksDocumentDrawing: "Чертёж",
                env.constants.ksDocumentFragment: "Фрагмент",
                env.constants.ksDocumentPart: "Деталь",
                env.constants.ksDocumentAssembly: "Сборка",
                env.constants.ksDocumentTextual: "Текстовый документ",
            }
            doc_type = doc.GetDocumentType()
            lines.append(f"\nАктивный документ: {type_names.get(doc_type, doc_type)}")
            if doc_type == env.constants.ksDocumentPart:
                try:
                    from lsk.model import PartModel

                    model = PartModel(env, app).refresh()
                    lines.append(f"  коллекция ЛСК: {'да' if model.has_collection else 'НЕТ'}")
                    lines.append(f"  ЛСК в модели: {len(model.list_lcs())}")
                    try:
                        lines.append(f"  3D-точек в модели: {len(model.points())}")
                    except Exception as exc:
                        lines.append(f"  3D-точки: ошибка — {exc}")
                except Exception as exc:
                    lines.append(f"  ошибка чтения модели: {exc}")

    text = "\n".join(lines)
    _save_and_show(text, "probe_report.txt", "Диагностика")
    return 0


def _run_selftest() -> int:
    """Автотест: временная деталь, создание и удаление ЛСК."""
    import contextlib

    buffer = io.StringIO()
    try:
        import selftest

        with contextlib.redirect_stdout(buffer):
            code = selftest.main()
    except Exception:
        buffer.write(traceback.format_exc())
        code = 1
    _save_and_show(buffer.getvalue(), "selftest_report.txt", "Самотест")
    return code


def _run_panel() -> int:
    from lsk import kompas
    from lsk import config as config_mod
    from lsk import ui

    try:
        env = kompas.load()
    except kompas.KompasNotFound as exc:
        return _fatal(
            "Не найден КОМПАС-3D с Python-обёрткой API (ksapi.py в каталоге Bin).\n\n"
            f"{exc}"
        )

    app = env.app()
    if app is None:
        return _fatal(
            "КОМПАС не запущен.\n\n"
            "Запусти КОМПАС-3D, открой деталь (*.m3d) и запусти инструмент снова."
        )

    env.refresh_version(app)
    print(env.features.as_text())
    print()

    cfg = config_mod.Config.load()
    ui.Panel(env, app, cfg).run()
    return 0


def main() -> int:
    _fix_streams()
    args = [a.lower() for a in sys.argv[1:]]
    if "--probe" in args or "-p" in args:
        return _run_probe()
    if "--selftest" in args:
        return _run_selftest()
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    try:
        return _run_panel()
    except Exception:
        return _fatal("Неожиданная ошибка:\n\n" + traceback.format_exc())


if __name__ == "__main__":
    sys.exit(main())
