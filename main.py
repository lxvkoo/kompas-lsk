"""Точка входа: панель управления расстановкой ЛСК.

Запуск:  python main.py
Требуется запущенный КОМПАС-3D с открытой деталью (*.m3d).

Служебные режимы (в exe без консоли отчёт пишется в файл и открывается):
    main.py --probe      диагностика окружения
    main.py --selftest   автотест во временной детали
"""

from __future__ import annotations

import contextlib
import io
import sys
import traceback


def _fix_streams() -> None:
    """В сборке без консоли sys.stdout/stderr = None: print() не должен падать."""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


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


def _run_probe() -> int:
    """Диагностика окружения: версия КОМПАСа и доступные возможности API."""
    from lsk import kompas
    from lsk.probe import build_report
    from lsk.report import save_and_show

    try:
        env = kompas.load()
    except kompas.KompasNotFound as exc:
        return _fatal(f"КОМПАС не найден.\n\n{exc}")
    save_and_show(build_report(env), "probe_report.txt")
    return 0


def _run_selftest() -> int:
    """Автотест: временная деталь, создание и удаление ЛСК."""
    from lsk.report import save_and_show

    buffer = io.StringIO()
    try:
        import selftest

        with contextlib.redirect_stdout(buffer):
            code = selftest.main()
    except Exception:
        buffer.write(traceback.format_exc())
        code = 1
    save_and_show(buffer.getvalue(), "selftest_report.txt")
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
