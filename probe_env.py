"""Диагностика окружения: что доступно в установленном КОМПАСе.

Скрипт специально не зависит от Tkinter и ничего не меняет в моделях —
его можно запустить на машине с другой версией КОМПАСа (например, v22)
и прислать вывод:

    python probe_env.py
"""

from __future__ import annotations

import sys

LINE = "-" * 60


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


def _save_report(text: str) -> None:
    """Дублировать вывод в файл рядом с exe — удобно прислать разработчику."""
    from pathlib import Path

    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    try:
        path = base / "probe_report.txt"
        path.write_text(text, encoding="utf-8")
        print(f"\nОтчёт сохранён: {path}")
    except OSError:
        pass


def main() -> int:
    _prepare_console()
    print(LINE)
    print("Диагностика окружения ЛСК-инструмента")
    print(LINE)
    print(f"Python {sys.version.split()[0]} ({'64' if sys.maxsize > 2**32 else '32'}-bit)")

    try:
        from lsk import kompas
    except Exception as exc:
        print(f"Не удалось импортировать пакет lsk: {exc}")
        return 1

    try:
        env = kompas.load()
    except kompas.KompasNotFound as exc:
        print("КОМПАС не найден.")
        print(exc)
        return 2

    print(f"Каталог Bin: {env.bin_dir}")
    print()

    app = env.app()
    if app is None:
        print("КОМПАС не запущен — возможности версии проверить не удалось.")
        print("Запусти КОМПАС и повтори, чтобы увидеть версию и активный документ.")
        return 3

    env.refresh_version(app)
    print(env.features.as_text())
    print()

    doc = app.GetActiveDocument()
    if doc is None:
        print("Активный документ: нет")
        return 0

    type_names = {
        env.constants.ksDocumentDrawing: "Чертёж",
        env.constants.ksDocumentFragment: "Фрагмент",
        env.constants.ksDocumentPart: "Деталь",
        env.constants.ksDocumentAssembly: "Сборка",
        env.constants.ksDocumentTextual: "Текстовый документ",
    }
    doc_type = doc.GetDocumentType()
    print(f"Активный документ: {type_names.get(doc_type, doc_type)}")

    if doc_type == env.constants.ksDocumentPart:
        try:
            from lsk.model import PartModel

            model = PartModel(env, app).refresh()
            print(f"  Коллекция ЛСК доступна: {'да' if model.has_collection else 'НЕТ'}")
            print(f"  ЛСК в модели: {len(model.list_lcs())}")
            try:
                print(f"  3D-точек в модели: {len(model.points())}")
            except Exception as exc:
                print(f"  3D-точек: ошибка — {exc}")
        except Exception as exc:
            print(f"  Ошибка чтения модели: {exc}")
    return 0


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


if __name__ == "__main__":
    _prepare_console()
    tee = _Tee()
    original = sys.stdout
    sys.stdout = tee
    try:
        code = main()
    finally:
        sys.stdout = original
    _save_report(tee.text())
    sys.exit(code)
