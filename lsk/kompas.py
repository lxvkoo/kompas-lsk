"""Загрузка официальной Python-обёртки API КОМПАС-3D.

В КОМПАС (начиная с v22 и точно в v25) в каталоге `Bin` лежит `ksapi.py` —
обёртка над `ksAPICLink.dll` (ctypes, без COM и без pywin32). Импортировать
её можно только добавив каталог `Bin` в `sys.path`, поэтому здесь:

1. ищем каталог установки КОМПАСа (реестр -> типовые пути -> переменная окружения);
2. проверяем, что в нём есть `ksapi.py` и `constants.py`;
3. аккуратно грузим `constants`, `constants3d`, `ksapi` под их штатными именами;
4. заодно определяем, какие возможности API доступны в этой версии (features).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


class KompasNotFound(RuntimeError):
    """Не удалось найти установленный КОМПАС-3D с Python-обёрткой API."""


def _registry_bin_dir() -> str | None:
    """Путь к Bin из реестра: HKCR\\KOMPAS.Application.5\\CLSID -> LocalServer32."""
    try:
        import winreg
    except ImportError:  # не Windows
        return None

    def _default_value(root, path):
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, None)
                return value
        except OSError:
            return None

    for progid in ("KOMPAS.Application.5", "KOMPAS.Application"):
        clsid = _default_value(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID")
        if not clsid:
            continue
        server = _default_value(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32")
        if not server:
            continue
        exe = server.strip().strip('"').split('"')[0]
        return str(Path(exe).parent)
    return None


def _candidate_bin_dirs() -> list[str]:
    seen: list[str] = []
    env = os.environ.get("KOMPAS_BIN")
    if env:
        seen.append(env)
    reg = _registry_bin_dir()
    if reg:
        seen.append(reg)

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path("D:/apps"),
        Path("C:/ASCON"),
        Path("D:/ASCON"),
    ]
    for root in roots:
        for pattern in ("ASCON/KOMPAS-3D v*/Bin", "ASCON/KOMPAS-3D*/Bin", "kompas/Bin", "KOMPAS*/Bin"):
            for hit in sorted(root.glob(pattern), reverse=True):
                seen.append(str(hit))
    return seen


def find_bin_dir() -> str:
    """Каталог `Bin` установленного КОМПАСа, в котором есть ksapi.py."""
    tried: list[str] = []
    for path in _candidate_bin_dirs():
        tried.append(path)
        if Path(path, "ksapi.py").is_file() and Path(path, "constants.py").is_file():
            return path
    raise KompasNotFound(
        "Не найден КОМПАС-3D с Python-обёрткой API (ksapi.py в каталоге Bin).\n"
        "Проверено:\n  " + "\n  ".join(tried or ["—"])
    )


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(name, None)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Features:
    """Что из API доступно в этой версии КОМПАСа (v22 отличается от v25)."""

    version: tuple[int, int, int] = (0, 0, 0)
    lcs_collection: bool = False   # IAuxiliaryGeomContainer.GetLocalCoordinateSystems
    lcs_add_object: bool = False   # запасной путь: IModelContainer.AddObject
    show_name: bool = False        # ILocalCoordinateSystem.SetShowName ("Показывать надпись")
    pick_ray: bool = False         # IDocumentFrame.GetPickRay
    pick_objects: bool = False     # IKompasDocument3D.PickModelObjects
    mouse_events: bool = False     # события мыши окна документа
    points3d: bool = False         # коллекция 3D-точек модели
    face_normal: bool = False      # IFace.NearPointProjection + GetNormal
    doc_delete: bool = False       # IKompasDocument.Delete
    notes: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        flag = lambda v: "да" if v else "НЕТ"
        rows = [
            f"версия КОМПАС-3D: {self.version[0]}.{self.version[1]}.{self.version[2]}",
            f"ЛСК через IAuxiliaryGeomContainer: {flag(self.lcs_collection)}",
            f"ЛСК через AddObject: {flag(self.lcs_add_object)}",
            f"«Показывать надпись»: {flag(self.show_name)}",
            f"луч взгляда (GetPickRay): {flag(self.pick_ray)}",
            f"выбор объектов по лучу: {flag(self.pick_objects)}",
            f"события мыши: {flag(self.mouse_events)}",
            f"коллекция 3D-точек: {flag(self.points3d)}",
            f"нормаль грани: {flag(self.face_normal)}",
            f"удаление объектов: {flag(self.doc_delete)}",
        ]
        rows.extend(self.notes)
        return "\n".join(rows)


@dataclass
class KompasEnv:
    """Всё, что нужно приложению от установленного КОМПАСа."""

    bin_dir: Path
    ksapi: object
    constants: object     # constants.constants     (общие константы API)
    constants3d: object   # constants3d.constants   (3D-объекты, оси)
    features: Features = field(default_factory=Features)

    def app(self):
        """Интерфейс запущенного КОМПАСа (None, если он не запущен)."""
        return self.ksapi.GetKompas()

    def refresh_version(self, app=None) -> tuple[int, int, int]:
        """Прочитать версию запущенного КОМПАСа в features.version."""
        app = app if app is not None else self.app()
        if app is None:
            return self.features.version
        try:
            ok, major, minor, release, _build = app.GetSystemVersion(0, 0, 0, 0)
        except Exception:
            return self.features.version
        if ok:
            self.features.version = (major, minor, release)
        return self.features.version


def _detect_features(ksapi_module) -> Features:
    f = Features()
    lib = ksapi_module.ksapi
    has = lambda name: hasattr(lib, name)
    f.lcs_collection = has("IAuxiliaryGeomContainer_GetLocalCoordinateSystems") and has(
        "ILocalCoordinateSystems_Add"
    )
    f.lcs_add_object = has("IModelContainer_AddObject")
    f.show_name = has("ILocalCoordinateSystem_SetShowName")
    f.pick_ray = has("IDocumentFrame_GetPickRay")
    f.pick_objects = has("IKompasDocument3D_PickModelObjects")
    # типы колбэков объявлены в модуле, а не в C-библиотеке
    f.mouse_events = has("IDocumentFrameEvents_AddMouseDownHandler") and hasattr(
        ksapi_module, "IDocumentFrameEvents_OnMouseDownHandler"
    )
    f.points3d = has("IModelContainer_GetPoints3D") and has("IPoints3D_GetPoint3D")
    f.face_normal = has("IFace_NearPointProjection") and has("IFace_GetNormal")
    f.doc_delete = has("IKompasDocument_Delete")
    return f


def load(bin_dir: str | None = None) -> KompasEnv:
    """Найти КОМПАС и импортировать его Python-API."""
    path = Path(bin_dir) if bin_dir else Path(find_bin_dir())

    # ksAPICLink.dll подтягивает соседние DLL — разрешаем поиск рядом с ним
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(path))
        except OSError:
            pass
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

    constants = _load_module("constants", path / "constants.py")
    constants3d = _load_module("constants3d", path / "constants3d.py")
    ksapi = _load_module("ksapi", path / "ksapi.py")

    features = _detect_features(ksapi)
    return KompasEnv(
        bin_dir=path,
        ksapi=ksapi,
        constants=constants.constants,
        constants3d=constants3d.constants,
        features=features,
    )
