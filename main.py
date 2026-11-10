"""Точка входа: панель управления расстановкой ЛСК.

Запуск:  python main.py
Требуется запущенный КОМПАС-3D с открытой деталью (*.m3d).
"""

from __future__ import annotations

import sys

from lsk import kompas
from lsk import config as config_mod
from lsk import ui


def main() -> int:
    try:
        env = kompas.load()
    except kompas.KompasNotFound as exc:
        print(exc)
        return 2

    app = env.app()
    if app is None:
        print("КОМПАС не запущен — запусти КОМПАС-3D, открой деталь и повтори.")
        print(env.features.as_text())
        return 3

    env.refresh_version(app)
    print(env.features.as_text())
    print()

    cfg = config_mod.Config.load()
    ui.Panel(env, app, cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
