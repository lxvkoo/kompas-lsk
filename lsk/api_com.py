"""COM-бэкенд (API v7) для версий КОМПАСа без Python-обёртки `ksapi.py`.

В КОМПАС v22 нет `ksAPI*` C-обёртки (и `ksAPICLink.dll`), но есть COM-сервер
`KOMPAS.Application.7`, а интерфейсы API v7 зарегистрированы в системе с
universal marshaler — значит к ним можно обращаться извне через `comtypes`,
который генерирует Python-интерфейсы прямо из `kAPI7.tlb` установленного КОМПАСа.

Этот модуль — «переводчик»: он даёт тот же минимальный набор вызовов, что и
`ksapi.py` (`GetX()`, `SetName()`, `InitByMatrix3D()` и т.д.), но через COM.
Благодаря этому `lsk/model.py` и `lsk/picking.py` не знают, какой бэкенд сейчас
работает.

Отличия, которые здесь учтены:
* интерфейсы получаются через ``QueryInterface`` (по типу из typelib), а не
  конструктором `ksapi.I*`;
* COM-свойства (`Name`, `X`, `IsPlanar`) обёрнуты методами `GetName/SetName/...`;
* `[out]`-параметры comtypes возвращает кортежем — порядок приводится к
  привычному `(ok, x, y, z)`;
* удаления объектов «по имени» в COM-API нет вовсе — отмена делается командой
  КОМПАСа (Ctrl+Z), поэтому `Delete` здесь поднимает `ApiMissing`.
"""

from __future__ import annotations

import ctypes
from pathlib import Path


#: GUID библиотеки типов API v7 (одинаков в v22 и v25)
TYPELIB_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"


class ApiMissing(RuntimeError):
    """Операция недоступна в COM-API."""


# --- значения констант (совпадают в v22 и v25, проверено по LDefin3D.pas) ------
class Constants:
    ksDocumentDrawing = 1
    ksDocumentFragment = 2
    ksDocumentSpecification = 3
    ksDocumentPart = 4
    ksDocumentAssembly = 5
    ksDocumentTextual = 6
    ksObjectLocalCoordinateSystem = 11040
    ksObjectFindObject3DParameters = 13173


class Constants3D:
    o3d_planeXOY = 1
    o3d_face = 6
    o3d_sketch = 5
    o3d_controlPoint = 67
    o3d_conjunctivePoint = 68
    o3d_point3D = 70
    o3d_axisOX = 71
    o3d_axisOY = 72
    o3d_axisOZ = 73
    o3d_BlockBySizes = 668


CONSTANTS = Constants()
CONSTANTS3D = Constants3D()


def _tolerant(fn):
    """Не падать, если метод/свойство отсутствует в этой версии."""
    return fn


class _Base:
    def __init__(self, obj, api: "ComApi"):
        self._obj = obj
        self._api = api

    def __bool__(self):
        return self._obj is not None

    # ------------------------------------------------------------------
    def _prop(self, name):
        try:
            return getattr(self._obj, name)
        except Exception:
            return None

    def _set_prop(self, name, value):
        try:
            setattr(self._obj, name, value)
            return True
        except Exception:
            return False

    def _call(self, name, *args):
        try:
            method = getattr(self._obj, name)
        except Exception as exc:
            raise ApiMissing(f"{type(self).__name__}.{name}: {exc}") from exc
        return method(*args)

    def _qi(self, iface_name):
        return self._api.qi(self._obj, iface_name)


# ======================================================================
# Приложение и документы
# ======================================================================
class _Application(_Base):
    def GetActiveDocument(self):
        doc = self._prop("ActiveDocument")
        return _Document(doc, self._api) if doc is not None else None

    def GetMainWindowHandle(self):
        value = self._prop("MainWindowHandle")
        return int(value or 0)

    def GetSystemVersion(self, *defaults):
        """Совместимо с ksapi: (ok, major, minor, release, build)."""
        try:
            major, minor, release, build, ok = self._call("GetSystemVersion")
            return (bool(ok), int(major), int(minor), int(release), int(build))
        except Exception as exc:
            raise ApiMissing(f"GetSystemVersion: {exc}") from exc

    def ExecuteKompasCommand(self, command_id, async_execution=False):
        try:
            self._call("ExecuteKompasCommand", int(command_id), bool(async_execution))
            return True
        except Exception:
            return False

    def GetDocuments(self):
        docs = self._prop("Documents")
        return _Documents(docs, self._api) if docs is not None else None


class _Documents(_Base):
    def GetCount(self):
        try:
            return int(self._prop("Count") or 0)
        except Exception:
            return 0

    def GetItem(self, index):
        for attempt in (index, index + 1):
            try:
                doc = self._call("Item", attempt)
                if doc is not None:
                    return _Document(doc, self._api)
            except Exception:
                continue
        return None

    def AddWithDefaultSettings(self, document_type, visible):
        doc = self._call("AddWithDefaultSettings", int(document_type), bool(visible))
        return _Document(doc, self._api) if doc is not None else None


class _Document(_Base):
    def GetDocumentType(self):
        return int(self._prop("DocumentType") or 0)

    def GetName(self):
        return self._prop("Name") or ""

    def GetFullPath(self):
        return self._prop("PathName") or self._prop("Path") or ""

    def IsActive(self):
        return bool(self._prop("Active"))

    def SetActive(self):
        self._set_prop("Active", True)
        return True

    def Close(self, options=0):
        """options: 0 — без сохранения, 1 — сохранить, 2 — спросить."""
        try:
            self._call("Close", int(options))
            return True
        except Exception:
            return False

    def GetDocumentFrame(self):
        try:
            frames = self._qi("IKompasDocument").DocumentFrames
        except Exception:
            return None
        for index in (0, 1):
            try:
                frame = frames.Item(index)
            except Exception:
                continue
            if frame is not None:
                return _Frame(frame, self._api)
        return None

    def Delete(self, objects):
        raise ApiMissing(
            "удаление объектов в COM-API недоступно — отменяйте через Ctrl+Z в КОМПАСе"
        )


class _Document3D(_Base):
    def GetTopPart(self):
        part = self._prop("TopPart")
        return _Part(part, self._api) if part is not None else None

    def SetUndoContainer(self, begin):
        ok = self._set_prop("UndoContainer", bool(begin))
        if not ok:
            raise ApiMissing("SetUndoContainer недоступен")
        return True

    def RebuildDocument(self):
        return bool(self._call("RebuildDocument"))


# ======================================================================
# Деталь, точки, ЛСК
# ======================================================================
class _Part(_Base):
    def GetModelContainer(self):
        try:
            return _ModelContainer(self._qi("IModelContainer"), self._api)
        except Exception:
            return None

    def RebuildModel(self, redraw=True):
        try:
            return bool(self._call("RebuildModel", bool(redraw)))
        except Exception:
            return False

    def FindObjectsByPoint(self, x, y, z, first_level=True):
        return self._api.as_list(self._call("FindObjectsByPoint", x, y, z, bool(first_level)))

    def FindObjectsByPointWithLimit(self, x, y, z, first_level=True, epsilon=0.001):
        try:
            return self._api.as_list(
                self._call("FindObjectsByPointEx", x, y, z, bool(first_level), float(epsilon))
            )
        except ApiMissing:
            return self.FindObjectsByPoint(x, y, z, first_level)

    def GetName(self):
        return self._prop("Name") or ""


class _ModelContainer(_Base):
    def GetPoints3D(self):
        points = self._prop("Points3D")
        return _Points3D(points, self._api) if points is not None else None

    def GetObjects(self, object_type):
        try:
            return self._api.as_list(self._call("Objects", object_type))
        except ApiMissing:
            return []

    def AddObject(self, object_type):
        return self._call("AddObject", int(object_type))


class _Block(_Base):
    """Параллелепипед по трём размерам (нужен самотесту)."""

    def SetLength(self, value):
        return self._set_prop("Length", float(value))

    def SetWidth(self, value):
        return self._set_prop("Width", float(value))

    def SetHeight(self, normal, value):
        try:
            self._call("SetHeight", bool(normal), float(value))
            return True
        except Exception:
            return self._set_prop("Height", float(value))

    def Update(self):
        try:
            return bool(self._call("Update"))
        except Exception:
            return False


class _Points3D(_Base):
    def GetCount(self):
        try:
            return int(self._prop("Count") or 0)
        except Exception:
            return 0

    def GetPoint3D(self, index):
        for attempt in (index, index + 1):
            try:
                point = self._call("Point3D", attempt)
            except Exception:
                continue
            if point is not None:
                return _Point(point, self._api)
        return None

    def Add(self):
        point = self._call("Add")
        return _Point(point, self._api) if point is not None else None


class _Point(_Base):
    def GetName(self):
        return self._prop("Name") or ""

    def SetName(self, name):
        return self._set_prop("Name", str(name))

    def GetX(self):
        return float(self._prop("X") or 0.0)

    def GetY(self):
        return float(self._prop("Y") or 0.0)

    def GetZ(self):
        return float(self._prop("Z") or 0.0)

    def SetX(self, value):
        return self._set_prop("X", float(value))

    def SetY(self, value):
        return self._set_prop("Y", float(value))

    def SetZ(self, value):
        return self._set_prop("Z", float(value))

    def Update(self):
        try:
            return bool(self._call("Update"))
        except Exception:
            return True


class _Collection(_Base):
    """Обёртка над произвольной коллекцией COM (Count + Item)."""

    def GetCount(self):
        try:
            return int(self._prop("Count") or 0)
        except Exception:
            return 0

    def GetItem(self, index):
        for attempt in (index, index + 1):
            try:
                item = self._call("Item", attempt)
            except Exception:
                continue
            if item is not None:
                return item
        return None


class _AuxContainer(_Base):
    def GetLocalCoordinateSystems(self):
        coll = self._prop("LocalCoordinateSystems")
        return _LcsCollection(coll, self._api) if coll is not None else None

    def GetConjunctivePoints(self):
        coll = self._prop("ConjunctivePoints")
        return _Collection(coll, self._api) if coll is not None else None

    def GetControlPoints(self):
        coll = self._prop("ControlPoints")
        return _Collection(coll, self._api) if coll is not None else None


class _LcsCollection(_Base):
    def GetCount(self):
        try:
            return int(self._prop("Count") or 0)
        except Exception:
            return 0

    def GetLocalCoordinateSystem(self, index):
        for attempt in (index, index + 1):
            try:
                lcs = self._call("LocalCoordinateSystem", attempt)
            except Exception:
                continue
            if lcs is not None:
                return _Lcs(lcs, self._api)
        return None

    def GetLocalCoordinateSystemByName(self, name):
        for index in range(self.GetCount()):
            lcs = self.GetLocalCoordinateSystem(index)
            if lcs is not None and lcs.GetName() == name:
                return lcs
        return None

    def Add(self):
        lcs = self._call("Add")
        return _Lcs(lcs, self._api) if lcs is not None else None


class _Lcs(_Base):
    def GetName(self):
        return self._prop("Name") or ""

    def SetName(self, name):
        return self._set_prop("Name", str(name))

    def GetX(self):
        return float(self._prop("X") or 0.0)

    def GetY(self):
        return float(self._prop("Y") or 0.0)

    def GetZ(self):
        return float(self._prop("Z") or 0.0)

    def InitByMatrix3D(self, matrix):
        try:
            return bool(self._call("InitByMatrix3D", self._api.as_matrix(matrix)))
        except ApiMissing:
            return False

    def SetShowName(self, show):
        return self._set_prop("ShowName", bool(show))

    def Update(self):
        try:
            return bool(self._call("Update"))
        except Exception:
            return False

    def GetVector(self, axis, x=0.0, y=0.0, z=0.0):
        try:
            vx, vy, vz, ok = self._call("GetVector", int(axis))
            return (bool(ok), float(vx), float(vy), float(vz))
        except Exception:
            return (False, 0.0, 0.0, 0.0)


# ======================================================================
# Окно документа и грани
# ======================================================================
class _Frame(_Base):
    def GetWindowHandle(self):
        for name in ("GetHWND", "HWND"):
            try:
                value = self._call(name) if callable(getattr(self._obj, name, None)) else self._prop(name)
                if value:
                    return int(value)
            except Exception:
                continue
        return 0

    def UnConvertCoordinates(self, coordinate_type, x, y, z, lx=0, ly=0):
        try:
            out_x, out_y, ok = self._call("UnConvertCoordinates", int(coordinate_type), x, y, z)
            return (bool(ok), int(out_x), int(out_y))
        except Exception:
            return (False, 0, 0)

    def GetWorkAreaRect(self, left=0, top=0, right=0, bottom=0):
        try:
            l, t, r, b, _ok = self._call("GetWorkAreaRect")
            return (int(l), int(t), int(r), int(b))
        except Exception:
            return (0, 0, 0, 0)

    def ZoomPrevNextOrAll(self, zoom_type):
        try:
            return bool(self._call("ZoomPrevNextOrAll", int(zoom_type)))
        except Exception:
            return False

    def RefreshWindow(self):
        try:
            self._call("RefreshWindow")
            return True
        except Exception:
            return False

    def ExecuteKompasCommand(self, command_id, async_execution=False):
        try:
            self._call("ExecuteKompasCommand", int(command_id), bool(async_execution))
            return True
        except Exception:
            return False


class _Face(_Base):
    def NearPointProjection(self, x, y, z, u=0.0, v=0.0):
        try:
            out_u, out_v, ok = self._call("NearPointProjection", x, y, z)
            return (bool(ok), float(out_u), float(out_v))
        except Exception:
            return (False, 0.0, 0.0)

    def GetPoint(self, param_u, param_v, x=0.0, y=0.0, z=0.0):
        try:
            out_x, out_y, out_z, ok = self._call("GetPoint", param_u, param_v)
            return (bool(ok), float(out_x), float(out_y), float(out_z))
        except Exception:
            return (False, 0.0, 0.0, 0.0)

    def GetNormal(self, param_u, param_v, x=0.0, y=0.0, z=0.0):
        try:
            out_x, out_y, out_z, ok = self._call("GetNormal", param_u, param_v)
            return (bool(ok), float(out_x), float(out_y), float(out_z))
        except Exception:
            return (False, 0.0, 0.0, 0.0)

    def _flag(self, name):
        try:
            return bool(self._prop(name))
        except Exception:
            return False

    def IsPlanar(self):
        return self._flag("IsPlanar")

    def IsCylinder(self):
        return self._flag("IsCylinder")

    def IsCone(self):
        return self._flag("IsCone")

    def IsSphere(self):
        return self._flag("IsSphere")

    def IsTorus(self):
        return self._flag("IsTorus")

    def IsNurbsSurface(self):
        return self._flag("IsNurbsSurface")

    def GetName(self):
        return self._prop("Name") or ""


# ======================================================================
# Сам фасад (подменяет модуль ksapi)
# ======================================================================
class ComApi:
    """Повторяет тот минимум `ksapi`, который использует инструмент."""

    def __init__(self, bin_dir: str | Path):
        self.bin_dir = Path(bin_dir)
        self.missing: set[str] = set()
        self.prog_id = "KOMPAS.Application.7"
        self._typelib = self._load_typelib()
        self._app: _Application | None = None

    # ------------------------------------------------------------------
    def _load_typelib(self):
        import comtypes.client

        for name in ("kAPI7.tlb", "kAPI.tlb", "KSAPI.tlb"):
            path = self.bin_dir / name
            if path.is_file():
                try:
                    return comtypes.client.GetModule(str(path))
                except Exception as exc:
                    raise ApiMissing(f"не удалось загрузить {path}: {exc}") from exc

        # файла .tlb нет — пробуем взять библиотеку типов из реестра по GUID
        for spec in ((TYPELIB_GUID, 1, 0), (TYPELIB_GUID,)):
            try:
                return comtypes.client.GetModule(spec)
            except Exception:
                continue
        raise ApiMissing(
            f"не нашёл описание интерфейсов API (kAPI7.tlb) в {self.bin_dir} "
            "и в реестре — COM-доступ к КОМПАСу невозможен"
        )

    def qi(self, obj, iface_name):
        """QueryInterface по имени интерфейса из typelib."""
        iface = getattr(self._typelib, iface_name, None)
        if iface is None:
            raise ApiMissing(f"в typelib нет интерфейса {iface_name}")
        return obj.QueryInterface(iface)

    # ------------------------------------------------------------------
    def as_list(self, value):
        """VARIANT/SAFEARRAY -> список объектов (или пустой список)."""
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        try:
            return [item for item in value]
        except TypeError:
            return [value]

    def as_matrix(self, values):
        """Список из 16 double -> SAFEARRAY(VT_R8) для InitByMatrix3D."""
        from comtypes.automation import _midlSAFEARRAY

        return _midlSAFEARRAY(ctypes.c_double).create(list(values))

    # ------------------------------------------------------------------
    def GetKompas(self):
        """Подключиться к запущенному КОМПАСу (или None)."""
        import comtypes.client

        if self._app is not None:
            return self._app
        for factory in (comtypes.client.GetActiveObject, comtypes.client.CreateObject):
            try:
                app = factory(self.prog_id)
            except Exception:
                continue
            if app is not None:
                self._app = _Application(app, self)
                return self._app
        return None

    # --- приведение интерфейсов (как ksapi.I*...) ----------------------
    def IKompasDocument3D(self, document, app=None):
        return self._wrap_qi(document, "IKompasDocument3D", _Document3D)

    def IKompasDocument(self, document, app=None):
        if isinstance(document, _Document):
            return document
        return _Document(document, self)

    def IAuxiliaryGeomContainer(self, part, app=None):
        return self._wrap_qi(part, "IAuxiliaryGeomContainer", _AuxContainer)

    def IFace(self, obj, app=None):
        return self._wrap_qi(obj, "IFace", _Face)

    def IPoint3D(self, obj, app=None):
        return self._wrap_qi(obj, "IPoint3D", _Point)

    def _wrap_qi(self, obj, iface_name, cls):
        base = obj._obj if isinstance(obj, _Base) else obj
        if base is None:
            return None
        try:
            iface = self.qi(base, iface_name)
        except Exception:
            return None
        return cls(iface, self)

    # --- фабрики для тестов/диагностики --------------------------------
    def IBlockBySizes(self, obj, app=None):
        return self._wrap_qi(obj, "IBlockBySizes", _Block)

    def IPlacement3D(self, obj, app=None):
        return self._wrap_qi(obj, "IPlacement3D", _Base)
