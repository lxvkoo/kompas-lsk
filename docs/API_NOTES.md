# Заметки по API КОМПАС-3D (проверено на v25.0.5 x64)

Всё ниже проверено живыми запусками (`selftest.py`), а не взято из головы.

## Где лежит Python-API

`<каталог установки КОМПАСа>\Bin\`:

* `ksapi.py` — обёртка на ctypes над `ksAPICLink.dll` (91288 строк, по одному
  методу на каждый метод C++ API);
* `constants.py` — `constants.constants` (общие константы API: типы объектов,
  команды и т.д.), импортируется в `ksapi.py` по имени, поэтому каталог `Bin`
  обязан быть в `sys.path`;
* `constants3d.py` — `constants.constants` (3D-объекты и оси);
* `kAPI5.dll`, `kAPI7.dll`, `kAPI3D5.dll`… — сами реализации.

Поиск установки: `HKCR\KOMPAS.Application.5\CLSID` → `HKCR\CLSID\{...}\LocalServer32`
→ путь к `KOMPAS.Exe` → его каталог (это и есть `Bin`).

## Ключевые цепочки

Получение запущенного приложения: `ksapi.GetKompas()` → `IApplication` (None, если
КОМПАС не запущен). `ksapi.OpenKompasInvisible()` на машине с уже запущенным
КОМПАСом **зависает** — не использовать.

```python
app  = ksapi.GetKompas()
docs = app.GetDocuments()
doc  = docs.AddWithDefaultSettings(constants.ksDocumentPart, False)   # невидимый
doc3d = ksapi.IKompasDocument3D(doc)
part  = doc3d.GetTopPart()
aux   = ksapi.IAuxiliaryGeomContainer(part)         # QueryInterface к IPart
lcss  = aux.GetLocalCoordinateSystems()             # ILocalCoordinateSystems
lcs   = lcss.Add()                                  # ILocalCoordinateSystem
lcs.SetName("ЛСК_Т03")
lcs.InitByMatrix3D(mtr16)                           # матрица (см. ниже)
lcs.SetShowName(True)                               # «Показывать надпись»
lcs.Update()
part.RebuildModel(True)
doc.Close(2)                                        # 2 = без сохранения
```

Точки модели: `part.GetModelContainer().GetPoints3D()` → `IPoints3D`, у элементов
`GetName()`, `GetX/Y/Z()` (наследуют `IPoint3D`).

Удаление ЛСК: `lcss.GetLocalCoordinateSystemByName(name)` → `doc.Delete([...])`.

## Матрица ЛСК

`ILocalCoordinateSystem.InitByMatrix3D` принимает 16 чисел (`VT_ARRAY | VT_R8`),
row-major 4×4:

```
[ ax.x, ax.y, ax.z, 0 ]   строка 0 — единичная ось X
[ ay.x, ay.y, ay.z, 0 ]   строка 1 — ось Y
[ az.x, az.y, az.z, 0 ]   строка 2 — ось Z
[  o.x,  o.y,  o.z, 1 ]   строка 3 — начало координат
```

Проверка: `InitByMatrix3D` + `GetVector(o3d_axisOX/OY/OZ)` возвращает те же оси,
`GetX/Y/Z` — начало. **Единицы — метры** (10 мм = `0.01`).

## Клик по модели

* `IDocumentFrame.GetPickRay(windowX, windowY, x, y, z, zx, zy, zz)` — оконные
  пикселы → точка на ближайшем объекте (`x, y, z`) + направление взгляда (`zx, zy, zz`).
* `IKompasDocument3D.PickModelObjects(ray, findObjectParam)` — объекты вдоль луча.
  `ray` — 6 чисел: точка + вектор (ровно то, что вернул `GetPickRay`).
  `findObjectParam` можно передать `None`.
* `IKompasDocument3DEx.PickModelObjectsWithLimit(ray, limit, filter, points)` —
  то же плюс точки пересечения (есть в v25, в v22 может отсутствовать).
* `IFace.NearPointProjection(x, y, z, u, v)` → параметры (u, v) ближайшей точки
  грани; `IFace.GetPoint(u, v)` → 3D-точка; `IFace.GetNormal(u, v)` → нормаль.
* `IFace.IsPlanar/IsCylinder/IsCone/IsSphere/IsTorus` — тип грани.

## События мыши

```python
cb = ksapi.IDocumentFrameEvents_OnMouseDownHandler(fn)   # CFUNCTYPE(c_bool, c_uint64, c_int32, c_int32)
frame.Events().AddMouseDownHandler("owner", cb)
frame.Events().RemoveAllHandlers("owner")
```

Подписаться можно только на документ с окном (невидимые документы `DocumentFrame`
не имеют). Обработчик вызывается в потоке КОМПАСа: тяжёлые вызовы API внутри него
лучше не делать — в проекте он только кладёт координаты в очередь.

## Грабли

* Разрядность Python и КОМПАСа должна совпадать (x64).
* `ksapi.IAPIObject.__init__` при неудачном `QueryInterface` обращается к
  `kompasApp._AddSlave`, поэтому интерфейс нужно приводить как
  `ksapi.IFace(obj, app)` (вторым аргументом приложение), иначе `AttributeError`.
  Проверять успех через `bool(result)`.
* `ksapi.IControlPoint`, `IConjunctivePoint` и т.п. — наследники `IPoint3D`;
  координаты читаются так же.
* Документация: `<установка>\SDK\Help\KOMPAS_SDK_ru-RU.zip` (HTML + `jstopics/*.js`
  с текстом справки), примеры: `SDK\Samples\{C++,CSharp,Pascal,Basic}.zip`.
