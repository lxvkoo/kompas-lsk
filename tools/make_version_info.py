"""Сгенерировать `version_info.txt` для PyInstaller из версии проекта.

PyInstaller с `--version-file version_info.txt` вписывает версию в ресурсы exe —
она видна в «Свойствах» файла и в диспетчере задач.

    python tools/make_version_info.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lsk import __version__  # noqa: E402

TEMPLATE = """# Файл создан tools/make_version_info.py — руками не править.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers},
    prodvers={vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', ''),
         StringStruct('FileDescription', 'ЛСК → КОМПАС - расстановка локальных систем координат'),
         StringStruct('FileVersion', '{text}'),
         StringStruct('InternalName', 'lsk_placer'),
         StringStruct('OriginalFilename', '{exe}'),
         StringStruct('ProductName', 'ЛСК → КОМПАС'),
         StringStruct('ProductVersion', '{text}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def build(exe_name: str = "lsk_placer.exe") -> Path:
    parts = [int(p) for p in __version__.split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    text = ".".join(str(p) for p in parts)
    content = TEMPLATE.format(vers=tuple(parts[:4]), text=text, exe=exe_name)
    path = ROOT / f"version_info_{Path(exe_name).stem}.txt"
    path.write_text(content, encoding="utf-8")
    print(f"версия {text} -> {path.name}")
    return path


if __name__ == "__main__":
    build("lsk_placer.exe")
    build("lsk_probe.exe")
