"""Подключение к API установленного КОМПАС-3D.

Способов два, и выбираются они автоматически:

* **ksapi (C-обёртка).** В КОМПАС v24/v25 в каталоге `Bin` лежит `ksapi.py` —
  обёртка над `ksAPICLink.dll` (ctypes). Работает быстро и напрямую.
* **COM (API v7).** В более старых версиях (например, v22) `ksapi.py` нет, но
  есть COM-сервер `KOMPAS.Application.7` и typelib `kAPI7.tlb`. Тогда используется
  `lsk/api_com.py` (на базе `comtypes`).

Остальной код (`model.py`, `picking.py`, ...) не знает, какой бэкенд работает:
оба дают одинаковый минимальный набор вызовов.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

NL = chr(10)


class KompasNotFound(RuntimeError):
    """Не удалось найти установленный КОМПАС-3D или его API."""


# ----------------------------------------------------------------------
# Поиск установки
# ----------------------------------------------------------------------
def _registry_bin_dir() -> str | None:
    """Путь к Bin из реестра: HKCR\\KOMPAS.Application.N\\CLSID -> LocalServer32."""
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

    for progid in ("KOMPAS.Application.7", "KOMPAS.Application.5", "KOMPAS.Application"):
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


def bin_inventory(bin_dir: str | Path) -> list[str]:
    """Что из файлов API есть в каталоге Bin (для диагностики)."""
    path = Path(bin_dir)
    if not path.is_dir():
        return [f"{path} — каталога нет"]
    found: list[str] = []
    for pattern in ("*.py", "ks*.dll", "kAPI*", "*.tlb"):
        for hit in sorted(path.glob(pattern)):
            if hit.name not in found:
                found.append(hit.name)
    for sub in ("SDK", "Include", "Samples", "Python"):
        if (path / sub).is_dir():
            found.append(f"[каталог {sub}]")
    return found or ["(ничего похожего на API не найдено)"]


def find_any_bin_dir() -> str:
    """Каталог `Bin` установленного КОМПАСа (любой способ доступа к API)."""
    tried: list[str] = []
    for path in _candidate_bin_dirs():
        if path in tried:
            continue
        tried.append(path)
        if Path(path, "KOMPAS.Exe").is_file() or Path(path, "kAPI7.tlb").is_file():
            return path
    raise KompasNotFound(
        NL.join(
            ["Не найден установленный КОМПАС-3D.", "", "Проверено:"]
            + ["  " + item for item in (tried or ["—"])]
        )
    )


def find_bin_dir() -> str:
    """Каталог `Bin` с `ksapi.py` (для C-обёртки)."""
    tried: list[str] = []
    for path in _candidate_bin_dirs():
        if path in tried:
            continue
        tried.append(path)
        if Path(path, "ksapi.py").is_file() and Path(path, "constants.py").is_file():
            return path

    lines = ["Не найден КОМПАС-3D с Python-обёрткой API (ksapi.py в каталоге Bin).", "", "Проверено:"]
    for path in tried or ["—"]:
        lines.append(f"  {path}")
        if Path(path).is_dir():
            lines.append("    есть: " + ", ".join(bin_inventory(path)[:14]))
    has_link = any(
        Path(item, "ksAPICLink.dll").is_file() for item in tried if Path(item).is_dir()
    )
    lines.append("")
    if has_link:
        lines.append(
            "В каталоге есть ksAPICLink.dll, но нет ksapi.py — можно скопировать "
            "ksapi.py, constants.py и constants3d.py из каталога Bin версии, где "
            "инструмент уже работает, в этот Bin."
        )
    lines.append(
        "Если этой обёртки нет, инструмент попробует COM-API (API v7) — см. отчёт "
        "диагностики (lsk_probe.exe или кнопка «Диагностика»)."
    )
    raise KompasNotFound(NL.join(lines))


# ----------------------------------------------------------------------
# Импорт C-обёртки
# ----------------------------------------------------------------------
class ApiMissing(RuntimeError):
    """Функция объявлена в Python-обёртке, но отсутствует в DLL этой версии КОМПАСа."""


class _MissingFunction:
    """Заглушка вместо отсутствующей функции DLL: объявляется, но не работает."""

    def __init__(self, name: str):
        self.name = name
        self.restype = None
        self.argtypes: list = []

    def __call__(self, *args, **kwargs):
        raise ApiMissing(
            f"в этой версии КОМПАСа нет функции API «{self.name}» "
            "(обёртка новее, чем DLL)"
        )


class _TolerantLib:
    """Прокси над ctypes-библиотекой: отсутствующие символы не ломают импорт."""

    def __init__(self, lib):
        self._lib = lib
        self.missing: set[str] = set()

    def __getattr__(self, name):
        try:
            return getattr(self._lib, name)
        except AttributeError:
            self.missing.add(name)
            return _MissingFunction(name)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(name, None)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------
# Возможности API в этой версии
# ----------------------------------------------------------------------
@dataclass
class Features:
    version: tuple[int, int, int] = (0, 0, 0)
    backend: str = "ksapi"         # "ksapi" (C-обёртка) или "com" (API v7 через COM)
    lcs_collection: bool = False   # коллекция ЛСК (IAuxiliaryGeomContainer)
    lcs_add_object: bool = False   # запасной путь: IModelContainer.AddObject
    show_name: bool = False        # «Показывать надпись»
    pick_ray: bool = False         # IDocumentFrame.GetPickRay (не используем)
    pick_objects: bool = False     # выбор объектов по лучу (не используем)
    mouse_events: bool = False     # события мыши (в Python не доставляются)
    points3d: bool = False         # коллекция 3D-точек
    face_normal: bool = False      # нормаль грани
    doc_delete: bool = False       # удаление объектов из документа
    notes: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        flag = lambda value: "да" if value else "НЕТ"
        backend_text = (
            "ksapi.py (C-обёртка)" if self.backend == "ksapi" else "COM KOMPAS.Application.7"
        )
        rows = [
            f"версия КОМПАС-3D: {self.version[0]}.{self.version[1]}.{self.version[2]}",
            f"способ доступа к API: {backend_text}",
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
        return NL.join(rows)


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


# ----------------------------------------------------------------------
# Загрузка бэкендов
# ----------------------------------------------------------------------
def load(bin_dir: str | None = None) -> KompasEnv:
    """Найти КОМПАС и подключиться к его API подходящим способом.

    Переменная окружения ``LSK_BACKEND=com`` (или ``ksapi``) заставляет выбрать
    бэкенд вручную — полезно для проверки COM-пути на машине с новой версией.
    """
    path = Path(bin_dir) if bin_dir else Path(find_any_bin_dir())
    forced = (os.environ.get("LSK_BACKEND") or "").strip().lower()
    has_wrapper = (path / "ksapi.py").is_file() and (path / "constants.py").is_file()

    if forced == "com" or (not has_wrapper and forced != "ksapi"):
        return _load_com(path)
    return _load_c_api(path)


def _load_com(path: Path) -> KompasEnv:
    """COM-бэкенд (API v7): для версий без Python-обёртки, например v22."""
    from . import api_com

    try:
        api = api_com.ComApi(path)
    except Exception as exc:
        raise KompasNotFound(
            f"Не удалось подключиться к COM-API КОМПАСа из {path}:{NL}{exc}"
        ) from exc

    features = Features(backend="com")
    features.lcs_collection = True
    features.lcs_add_object = False
    features.show_name = True
    features.pick_ray = False       # не используем (нестабилен)
    features.pick_objects = False
    features.mouse_events = False   # в Python не доставляются
    features.points3d = True
    features.face_normal = True
    features.doc_delete = False     # в COM-API удаления объектов нет — только Ctrl+Z
    return KompasEnv(
        bin_dir=path,
        ksapi=api,
        constants=api_com.CONSTANTS,
        constants3d=api_com.CONSTANTS3D,
        features=features,
    )


def _detect_features(ksapi_module) -> Features:
    f = Features()
    lib = ksapi_module.ksapi
    missing = getattr(lib, "missing", set())
    has = lambda name: hasattr(lib, name) and name not in missing
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


def _load_c_api(path: Path) -> KompasEnv:
    """C-обёртка ksapi.py из каталога Bin (v24/v25)."""
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(path))
        except OSError:
            pass
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

    constants = _load_module("constants", path / "constants.py")
    constants3d = _load_module("constants3d", path / "constants3d.py")

    # ksapi.py грузит ksAPICLink.dll и сразу обращается ко всем её функциям:
    # оборачиваем LoadLibrary, чтобы отсутствующие имена не роняли импорт
    import ctypes

    original_load = ctypes.cdll.LoadLibrary
    wrapped_holder: dict = {}

    def tolerant_load(lib_path):
        lib = original_load(lib_path)
        wrapped = _TolerantLib(lib)
        wrapped_holder["lib"] = wrapped
        return wrapped

    ctypes.cdll.LoadLibrary = tolerant_load
    try:
        ksapi = _load_module("ksapi", path / "ksapi.py")
    except OSError as exc:
        raise KompasNotFound(
            f"Не удалось загрузить библиотеку API КОМПАСа из {path}:{NL}{exc}{NL}{NL}"
            "Скорее всего в этой версии КОМПАСа нет ksAPICLink.dll — тогда "
            "используется COM-путь (см. отчёт диагностики)."
        ) from exc
    finally:
        ctypes.cdll.LoadLibrary = original_load

    lib = wrapped_holder.get("lib")
    missing = sorted(lib.missing) if lib is not None else []
    if missing:
        print(
            f"Внимание: в DLL этой версии КОМПАСа нет {len(missing)} функций из "
            f"обёртки — возможности будут недоступны."
        )
        print("  первые: " + ", ".join(missing[:8]))

    features = _detect_features(ksapi)
    return KompasEnv(
        bin_dir=path,
        ksapi=ksapi,
        constants=constants.constants,
        constants3d=constants3d.constants,
        features=features,
    )
