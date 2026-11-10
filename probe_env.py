"""Диагностика окружения: что доступно в установленном КОМПАСе.

Скрипт специально не зависит от Tkinter и ничего не меняет в моделях —
его можно запустить на машине с другой версией КОМПАСа (например, v22)
и прислать вывод:

    python probe_env.py
"""

from __future__ import annotations

import sys

LINE = "-" * 60


def main() -> int:
    print(LINE)
    print("Диагностика окружения ЛСК-инструмента")
    print(LINE)
    print(f"Python {sys.version.split()[0]} ({8 * 8 if sys.maxsize > 2**32 else 32}-bit)")

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


if __name__ == "__main__":
    sys.exit(main())
