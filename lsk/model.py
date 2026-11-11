"""Работа с моделью-деталью КОМПАСа: точки, ЛСК, дубли, удаление.

Только детали (`ksDocumentPart`) — по требованию проекта.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import geometry


class KompasModelError(RuntimeError):
    """Ошибка работы с моделью (пользователю показываем текст как есть)."""


class NoDocument(KompasModelError):
    pass


class NotPartDocument(KompasModelError):
    pass


@dataclass
class PointInfo:
    name: str
    coords: geometry.Vec


@dataclass
class Created:
    names: list[str]


def _iface(env, cls_name: str, obj, app):
    """Привести объект к интерфейсу через QueryInterface (None, если не получилось).

    Второй аргумент `app` обязателен: обёртка ksapi при неудачном QueryInterface
    иначе падает на `kompasApp._AddSlave`.
    """
    cls = getattr(env.ksapi, cls_name)
    try:
        res = cls(obj, app)
    except Exception:
        return None
    return res if res else None


class PartModel:
    """Активная деталь: коллекция ЛСК, точки, создание тройки ЛСК."""

    def __init__(self, env, app):
        self.env = env
        self.app = app
        self.doc = None
        self.doc3d = None
        self.part = None
        self._lcs = None

    # ------------------------------------------------------------------
    def attach(self, doc):
        """Привязаться к конкретному документу (используется и в тестах)."""
        self.doc = doc
        self.doc3d = self.env.ksapi.IKompasDocument3D(doc, self.app)
        self.part = self.doc3d.GetTopPart()
        self._lcs = self._lcs_collection()
        return self

    def refresh(self) -> "PartModel":
        """Взять активный документ КОМПАСа (пользователь мог переключиться)."""
        doc = self.app.GetActiveDocument()
        if not doc:
            raise NoDocument("В КОМПАСе нет активного документа")
        if doc.GetDocumentType() != self.env.constants.ksDocumentPart:
            raise NotPartDocument(
                "Активный документ — не деталь. Инструмент ставит ЛСК только в деталях (*.m3d)."
            )
        return self.attach(doc)

    # ------------------------------------------------------------------
    def _aux_container(self):
        """IAuxiliaryGeomContainer у детали (через QueryInterface)."""
        try:
            aux = self.env.ksapi.IAuxiliaryGeomContainer(self.part, self.app)
        except Exception:
            return None
        return aux if aux else None

    def _lcs_collection(self):
        """Коллекция ЛСК детали.

        Основной путь (v22+): IAuxiliaryGeomContainer через QueryInterface у IPart.
        Запасной: IModelContainer.AddObject(ksObjectLocalCoordinateSystem) — тогда
        коллекции нет, и каждая ЛСК создаётся отдельно.
        """
        try:
            aux = self.env.ksapi.IAuxiliaryGeomContainer(self.part, self.app)
            if aux:
                coll = aux.GetLocalCoordinateSystems()
                if coll:
                    return coll
        except Exception:
            pass
        return None

    @property
    def has_collection(self) -> bool:
        return self._lcs is not None

    # ------------------------------------------------------------------
    def list_lcs(self) -> list[str]:
        """Имена всех ЛСК детали."""
        if self._lcs is None:
            return []
        names: list[str] = []
        try:
            count = self._lcs.GetCount()
        except Exception:
            return []
        for i in range(count):
            try:
                lcs = self._lcs.GetLocalCoordinateSystem(i)
            except Exception:
                continue
            if lcs:
                try:
                    names.append(lcs.GetName())
                except Exception:
                    pass
        return names

    def lcs_by_name(self, name: str):
        """ЛСК по имени (или None)."""
        if self._lcs is None:
            return None
        try:
            return self._lcs.GetLocalCoordinateSystemByName(name)
        except Exception:
            return None

    def _point_info(self, obj, fallback_name: str) -> PointInfo | None:
        """Объект модели -> PointInfo, если из него можно прочитать координаты."""
        point = _iface(self.env, "IPoint3D", obj, self.app)
        if point is None:
            return None
        try:
            name = point.GetName() or fallback_name
        except Exception:
            name = fallback_name
        try:
            return PointInfo(name=name, coords=(point.GetX(), point.GetY(), point.GetZ()))
        except Exception:
            return None

    def points(self, rebuild_if_empty: bool = True) -> list[PointInfo]:
        """Все 3D-точки модели, любым способом созданные.

        `IModelContainer.GetPoints3D()` отдаёт точки, созданные через API; точки из
        интерфейса КОМПАСа («Точка», «Точка в центре») могут лежать в других
        коллекциях, поэтому собираем из всех известных источников и убираем дубли.
        Если список пуст, а модель могла быть только что изменена — пересчитываем.
        """
        result = self._gather_points()
        if not result and rebuild_if_empty:
            self.rebuild(redraw=False)
            result = self._gather_points()
        return result

    def _gather_points(self) -> list[PointInfo]:
        c3d = self.env.constants3d
        try:
            container = self.part.GetModelContainer()
        except Exception:
            return []
        found: list[PointInfo] = []

        # 1) штатная коллекция точек
        try:
            coll = container.GetPoints3D()
            for i in range(coll.GetCount() if coll else 0):
                info = self._point_info(coll.GetPoint3D(i), f"Точка {i + 1}")
                if info:
                    found.append(info)
        except Exception:
            pass

        # 2) объекты модели по типам точек
        for obj_type in (
            getattr(c3d, "o3d_point3D", 70),
            getattr(c3d, "o3d_conjunctivePoint", 68),
            getattr(c3d, "o3d_controlPoint", 67),
        ):
            try:
                for obj in container.GetModelObjects([obj_type]) or []:
                    info = self._point_info(obj, "Точка")
                    if info:
                        found.append(info)
            except Exception:
                continue

        # 3) коллекции вспомогательной геометрии
        aux = self._aux_container()
        if aux is not None:
            for method in ("GetConjunctivePoints", "GetControlPoints"):
                try:
                    coll = getattr(aux, method)()
                except Exception:
                    continue
                for i in range(coll.GetCount() if coll else 0):
                    try:
                        obj = coll.GetItem(i)
                    except Exception:
                        obj = None
                    info = self._point_info(obj, "Точка") if obj else None
                    if info:
                        found.append(info)

        return self._dedupe(found)

    @staticmethod
    def _dedupe(points: list[PointInfo]) -> list[PointInfo]:
        seen: set[tuple] = set()
        result: list[PointInfo] = []
        for info in points:
            key = (
                round(info.coords[0] * 1e6),
                round(info.coords[1] * 1e6),
                round(info.coords[2] * 1e6),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(info)
        return result

    # ------------------------------------------------------------------
    def _new_lcs(self):
        if self._lcs is not None:
            lcs = self._lcs.Add()
            if not lcs:
                raise KompasModelError("Коллекция ЛСК не создала новый элемент")
            return lcs
        # запасной путь для версий без IAuxiliaryGeomContainer
        obj_type = getattr(self.env.constants, "ksObjectLocalCoordinateSystem", 11040)
        container = self.part.GetModelContainer()
        obj = container.AddObject(obj_type)
        lcs = _iface(self.env, "ILocalCoordinateSystem", obj, self.app)
        if not lcs:
            raise KompasModelError("Не удалось создать ЛСК (AddObject не вернул ILocalCoordinateSystem)")
        return lcs

    def create_triplet(
        self,
        base_name: str,
        origin: geometry.Vec,
        v_axis: geometry.Vec,
        r_axis: geometry.Vec,
        offset: float,
        show_name: bool = True,
    ) -> Created:
        """Создать три ЛСК: базовую, векторную (`_V`) и поворота (`_R`).

        Ориентация у всех трёх — оси детали (без проворота), меняются только
        координаты: `_V` смещена по `v_axis`, `_R` по `r_axis` на `offset`.
        Всё создание обёрнуто в контейнер отмены, поэтому штатный Ctrl+Z в
        КОМПАСе убирает тройку одним шагом.
        """
        plan = [
            (base_name, origin),
            (base_name + "_V", geometry.add(origin, geometry.mul(v_axis, offset))),
            (base_name + "_R", geometry.add(origin, geometry.mul(r_axis, offset))),
        ]
        matrices = [geometry.matrix_from_frame(o, geometry.GLOBAL_AXES) for _n, o in plan]

        names: list[str] = []
        self._undo_container(True)
        try:
            for (name, _origin), mtr in zip(plan, matrices):
                lcs = self._new_lcs()
                lcs.SetName(name)
                if not lcs.InitByMatrix3D(mtr):
                    raise KompasModelError(f"КОМПАС отказался задать матрицу для «{name}»")
                if show_name and self.env.features.show_name:
                    try:
                        lcs.SetShowName(True)
                    except Exception:
                        pass
                lcs.Update()
                names.append(name)
        finally:
            self._undo_container(False)
        self.rebuild()
        return Created(names=names)

    def _undo_container(self, begin: bool) -> None:
        """Сгруппировать изменения в один шаг отмены (Ctrl+Z)."""
        try:
            self.doc3d.SetUndoContainer(begin)
        except Exception:
            pass

    def rebuild(self, redraw: bool = True) -> None:
        try:
            self.part.RebuildModel(redraw)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def existing(self, names: list[str]) -> list[str]:
        current = set(self.list_lcs())
        return [n for n in names if n in current]

    def delete(self, names: list[str]) -> int:
        """Удалить ЛСК по именам. Возвращает количество удалённых (-1 — отменой)."""
        if not self.env.features.doc_delete:
            # в COM-API удаления объектов нет: отменяем последнюю команду (Ctrl+Z),
            # а создание тройки шло внутри контейнера отмены
            try:
                self.doc.SetActive()  # отмена действует на активный документ
                self.app.ExecuteKompasCommand(57643, False)  # ksCMEditUndo
            except Exception as exc:
                raise KompasModelError(f"Не удалось отменить создание ЛСК: {exc}") from exc
            self.rebuild()
            return -1
        if self._lcs is None:
            return 0
        objs = []
        for name in names:
            obj = self.lcs_by_name(name)
            if obj:
                objs.append(obj)
        if not objs:
            return 0
        self._undo_container(True)
        try:
            self.doc.Delete(objs)
        except Exception as exc:
            raise KompasModelError(f"Не удалось удалить ЛСК: {exc}") from exc
        finally:
            self._undo_container(False)
        self.rebuild()
        return len(objs)

    def undo_triplet(self, base_name: str) -> int:
        return self.delete([base_name, base_name + "_V", base_name + "_R"])
