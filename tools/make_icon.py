"""Сделать многоразмерный `icon.ico` из обычной картинки (PNG/JPG/BMP/...).

    python tools/make_icon.py путь\\к\\картинке.png           # -> icon.ico
    python tools/make_icon.py картинка.png значок.ico

Нужен квадратный исходник не меньше 256x256 — из него делаются размеры
16/24/32/48/64/128/256, которые Windows показывает в списке файлов, на панели
задач и в свойствах exe.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

SIZES = (16, 24, 32, 48, 64, 128, 256)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def make_icon(source: str | Path, target: str | Path | None = None) -> Path:
    src = Path(source)
    if not src.is_file():
        raise SystemExit(f"нет файла: {src}")
    dst = Path(target) if target else PROJECT_ROOT / "icon.ico"

    image = Image.open(src).convert("RGBA")
    side = max(image.size)
    if side < 64:
        print(f"! картинка маленькая ({image.width}x{image.height}), будет мыло")
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    if side != 256:
        square = square.resize((256, 256), Image.LANCZOS)
        print(f"  приведено к 256x256 (из {image.width}x{image.height})")

    square.save(dst, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"готово: {dst}  (размеры: {', '.join(str(s) for s in SIZES)})")
    return dst


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    make_icon(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
