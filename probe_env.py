"""Диагностика окружения: что доступно в установленном КОМПАСе.

Запускать при открытом КОМПАСе (лучше с открытой деталью). Ничего не меняет.

    python probe_env.py

В собранном виде это `lsk_probe.exe`: печатает отчёт в консоль и рядом с собой
сохраняет `probe_report.txt` — его удобно прислать разработчику.
То же самое доступно кнопкой «Диагностика» в панели инструмента.
"""

from __future__ import annotations

import sys

from lsk import kompas
from lsk.probe import build_report
from lsk.report import save_and_show


def _prepare_console() -> None:
    """Чтобы русский текст нормально выводился в консоли и попадал в файл."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass


class _Tee:
    """Пишем и в консоль, и в буфер — чтобы сохранить отчёт в файл."""

    def __init__(self):
        self._parts: list[str] = []

    def write(self, text: str) -> None:
        self._parts.append(text)
        try:
            sys.__stdout__.write(text)
        except Exception:
            pass

    def flush(self) -> None:
        pass

    def text(self) -> str:
        return "".join(self._parts)


def main() -> int:
    try:
        env = kompas.load()
    except kompas.KompasNotFound as exc:
        print("КОМПАС не найден.")
        print(exc)
        return 2
    print(build_report(env))
    return 0


if __name__ == "__main__":
    _prepare_console()
    tee = _Tee()
    original = sys.stdout
    sys.stdout = tee
    try:
        code = main()
    finally:
        sys.stdout = original
    save_and_show(tee.text(), "probe_report.txt", open_in_notepad=False)
    sys.exit(code)
