"""Сделать аккуратный многоразмерный `icon.ico` из картинки.

    python tools/make_icon.py картинка.png            # -> icon.ico
    python tools/make_icon.py картинка.png --plate    # с светлой подложкой
    python tools/make_icon.py картинка.png out.ico    # свой путь

Почему не просто `PIL.save('ico', sizes=...)`: каждый размер считается
**из исходника** (а не из уменьшенной копии) и для мелких размеров
дополнительно повышается резкость — иначе на 16x16 получается «мыло».
Подложка (`--plate`) нужна, если рисунок тёмный/тонкий: без неё иконка
теряется на тёмной панели задач и в заголовке окна.
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZES = (16, 24, 32, 48, 64, 128, 256)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _rounded_plate(size: int, colour=(245, 246, 248, 255), radius_ratio: float = 0.22):
    """Светлая скруглённая подложка под рисунок."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(2, int(size * radius_ratio))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=colour)
    return image


def _prepare_source(path: Path, plate: bool) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    side = max(image.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    if plate:
        plate_image = _rounded_plate(side)
        # рисунок чуть уменьшаем, чтобы были поля
        inner = int(side * 0.86)
        art = square.resize((inner, inner), Image.LANCZOS)
        offset = (side - inner) // 2
        plate_image.alpha_composite(art, (offset, offset))
        square = plate_image
    return square


def _render(source: Image.Image, size: int) -> Image.Image:
    """Один размер: из исходника, с повышением резкости для мелких."""
    image = source.resize((size, size), Image.LANCZOS)
    if size <= 48:
        # при сильном уменьшении тонкие линии «мылятся» — подчёркиваем края
        image = image.filter(
            ImageFilter.UnsharpMask(radius=0.6, percent=120 if size <= 24 else 70, threshold=1)
        )
    return image


def _write_ico(images: dict[int, Image.Image], path: Path) -> None:
    """Собрать .ico вручную: каждая запись — PNG (поддерживается с Windows Vista)."""
    entries: list[tuple[int, bytes]] = []
    for size in sorted(images):
        buffer = io.BytesIO()
        images[size].save(buffer, format="PNG", optimize=True)
        entries.append((size, buffer.getvalue()))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory = b""
    blobs = b""
    for size, data in entries:
        edge = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    path.write_bytes(header + directory + blobs)


def make_icon(source_path: str | Path, target: str | Path | None = None,
              plate: bool = False) -> Path:
    src = Path(source_path)
    if not src.is_file():
        raise SystemExit(f"нет файла: {src}")
    dst = Path(target) if target else PROJECT_ROOT / "icon.ico"

    prepared = _prepare_source(src, plate)
    if prepared.width < 256:
        print(f"! исходник {prepared.width}x{prepared.height} — мелковато, будет мыло")

    images = {size: _render(prepared, size) for size in SIZES}
    _write_ico(images, dst)
    # отдельный PNG для иконки окна: Tk не умеет PNG внутри .ico
    window_png = dst.with_name("icon_32.png")
    images[32].save(window_png, format="PNG")
    print(
        f"готово: {dst} и {window_png.name}  "
        f"({', '.join(str(s) for s in SIZES)}; подложка: {'да' if plate else 'нет'})"
    )
    return dst


def preview(source_path: str | Path, plate: bool = False, out: str = "icon_preview.png") -> Path:
    """Картинка-проверка: как иконка выглядит в мелких размерах, крупно и на фоне."""
    prepared = _prepare_source(Path(source_path), plate)
    sizes = (16, 24, 32, 48)
    scale = 8
    cell = max(sizes) * scale
    gap = 12
    width = cell * len(sizes) + gap * (len(sizes) + 1)
    height = cell + gap * 2
    sheet = Image.new("RGBA", (width, height), (32, 34, 40, 255))
    x = gap
    for size in sizes:
        image = _render(prepared, size).resize((size * scale, size * scale), Image.NEAREST)
        sheet.alpha_composite(image, (x, gap))
        x += cell + gap
    path = PROJECT_ROOT / out
    sheet.save(path)
    print(f"проверка: {path}")
    return path


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    plate = "--plate" in args
    args = [a for a in args if a != "--plate"]
    if not args:
        print(__doc__)
        raise SystemExit(2)
    make_icon(args[0], args[1] if len(args) > 1 else None, plate)
    preview(args[0], plate)
