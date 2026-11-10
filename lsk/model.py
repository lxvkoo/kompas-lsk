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

    def points(self) -> list[PointInfo]:
        """Все 3D-точки модели (в т.ч. проставленные пользователем вручную)."""
        try:
            coll = self.part.GetModelContainer().GetPoints3D()
        except Exception as exc:
            raise KompasModelError(f"Не удалось получить точки модели: {exc}") from exc
        if not coll:
            return []
        result: list[PointInfo] = []
        for i in range(coll.GetCount()):
            pt = coll.GetPoint3D(i)
            if not pt:
                continue
            try:
                result.append(
                    PointInfo(
                        name=pt.GetName() or f"Точка {i + 1}",
                        coords=(pt.GetX(), pt.GetY(), pt.GetZ()),
                    )
                )
            except Exception:
                continue
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
        axes: tuple[geometry.Vec, geometry.Vec, geometry.Vec],
        offset: float,
        v_sign: int,
        r_axis: str,
        show_name: bool = True,
    ) -> Created:
        """Создать три ЛСК: базовую, векторную (`_V`) и поворота (`_R`).

        origin — метры, offset — метры.
        """
        x, y, z = axes
        v_origin = geometry.add(origin, geometry.mul(y, offset * (1 if v_sign >= 0 else -1)))
        r_origin = geometry.add(origin, geometry.mul(geometry.axis_vector(axes, r_axis), offset))

        plan = [
            (base_name, origin),
            (base_name + "_V", v_origin),
            (base_name + "_R", r_origin),
        ]
        matrix = [geometry.matrix_from_frame(o, (x, y, z)) for _n, o in plan]

        names: list[str] = []
        for (name, _origin), mtr in zip(plan, matrix):
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

        self.rebuild()
        return Created(names=names)

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
        """Удалить ЛСК по именам. Возвращает количество удалённых."""
        if self._lcs is None:
            return 0
        objs = []
        for name in names:
            obj = self.lcs_by_name(name)
            if obj:
                objs.append(obj)
        if not objs:
            return 0
        try:
            self.doc.Delete(objs)
        except Exception as exc:
            raise KompasModelError(f"Не удалось удалить ЛСК: {exc}") from exc
        self.rebuild()
        return len(objs)

    def undo_triplet(self, base_name: str) -> int:
        return self.delete([base_name, base_name + "_V", base_name + "_R"])
