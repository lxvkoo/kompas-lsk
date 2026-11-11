"""Диагностика окружения: что доступно в установленной версии КОМПАСа.

Собирает текстовый отчёт. Используется и консольным `probe_env.py`,
и кнопкой «Диагностика» в панели — чтобы на машине с другой версией КОМПАСа
не нужно было ничего запускать с флагами.
"""

from __future__ import annotations

import sys

LINE = "-" * 60

_TYPE_NAMES = {
    1: "Чертёж",
    2: "Фрагмент",
    3: "Спецификация",
    4: "Деталь",
    5: "Сборка",
    6: "Текстовый документ",
}


def build_report(env, app=None) -> str:
    """Текст отчёта по окружению. Ошибки не бросает — пишет их в отчёт."""
    lines: list[str] = [LINE, "Диагностика окружения ЛСК-инструмента", LINE]
    lines.append(f"Python {sys.version.split()[0]} ({'64' if sys.maxsize > 2**32 else '32'}-bit)")
    lines.append(f"Каталог Bin: {env.bin_dir}")

    if app is None:
        app = env.app()
    if app is None:
        lines.append("")
        lines.append("КОМПАС не запущен — запусти КОМПАС и повтори, тогда будет видна версия")
        return "\n".join(lines)

    env.refresh_version(app)
    lines.append("")
    lines.append(env.features.as_text())

    lib = getattr(env.ksapi, "ksapi", None)
    missing = sorted(getattr(lib, "missing", set()) or [])
    if missing:
        lines.append("")
        lines.append(f"В DLL этой версии нет {len(missing)} функций из Python-обёртки:")
        for name in missing[:60]:
            lines.append(f"  - {name}")
        if len(missing) > 60:
            lines.append(f"  ... и ещё {len(missing) - 60}")

    doc = app.GetActiveDocument()
    if doc is None:
        lines.append("")
        lines.append("Активный документ: нет")
        return "\n".join(lines)

    try:
        doc_type = doc.GetDocumentType()
    except Exception as exc:
        lines.append(f"\nАктивный документ: ошибка — {exc}")
        return "\n".join(lines)

    doc_name = ""
    try:
        doc_name = doc.GetName() or ""
    except Exception:
        pass
    lines.append("")
    lines.append(f"Активный документ: {_TYPE_NAMES.get(doc_type, doc_type)} {doc_name}".strip())
    lines.append("--- возможности на этом документе ---")

    from .model import PartModel

    try:
        model = PartModel(env, app).refresh()
    except Exception as exc:
        lines.append(f"  модель недоступна: {exc}")
        return "\n".join(lines)

    lines.append(f"  коллекция ЛСК: {'да' if model.has_collection else 'НЕТ (пойдёт AddObject)'}")
    try:
        lines.append(f"  ЛСК в модели: {len(model.list_lcs())}")
    except Exception as exc:
        lines.append(f"  ЛСК: ошибка — {exc}")
    try:
        points = model.points()
        lines.append(f"  3D-точек в модели: {len(points)}")
        for info in points[:5]:
            lines.append(
                f"    · {info.name}: "
                f"({info.coords[0]:.3f}, {info.coords[1]:.3f}, {info.coords[2]:.3f}) мм"
            )
    except Exception as exc:
        lines.append(f"  3D-точки: ошибка — {exc}")

    # проверка проекции 3D -> пиксель (на ней держится привязка курсора)
    try:
        from . import picking, win32cursor

        frame = doc.GetDocumentFrame()
        if frame and points:
            first = points[0]
            pixel = picking.point_to_pixel(env, model, first.coords)
            width, height = win32cursor.client_size(frame.GetWindowHandle())
            lines.append(f"  окно документа: {width}x{height} px")
            lines.append(f"  проекция первой точки в пиксель: {pixel}")
            if pixel is not None:
                inside = 0 <= pixel[0] < width and 0 <= pixel[1] < height
                lines.append(f"  пиксель внутри окна: {'да' if inside else 'НЕТ (проверь вид/масштаб)'}")
                scale = picking.mm_per_pixel(env, model, first.coords)
                lines.append(f"  масштаб вида: {scale:.4f} мм/пиксель")
            else:
                lines.append("  проекция не удалась — привязка к точке работать не будет")
        else:
            lines.append("  проекция в пиксель: нет окна документа или нет точек")
    except Exception as exc:
        lines.append(f"  проверка проекции: ошибка — {exc}")

    return "\n".join(lines)
