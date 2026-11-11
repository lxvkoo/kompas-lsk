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
`GetX/Y/Z` — начало.

## Единицы — МИЛЛИМЕТРЫ (проверено на реальной детали)

В документации API встречается «метры», но фактически всё в **миллиметрах**.
Проверка на кольце Ø96×31 мм: `IFace.GetRadius()` вернул `48.0` и `29.0`,
`IFace.GetArea(1)` для торца вернул `4596.15` = π(48² − 29²), координаты точки —
`(0, 31, 8.86)`, где 31 — высота кольца. То есть 1 единица API = 1 мм.
`GetArea(unit)`: `unit = 0` — см², `unit = 1` — мм².

## Привязка к точке и направление: пиксели, а не луч

Главный вывод: **`GetPickRay` использовать нельзя**. Проверено на v25:

* возвращает точку на луче (`z ≈ −1000 мм`, не на модели) и направление взгляда;
* результат «с памятью»: повторные вызовы в одном пикселе стабильны, но стоит
  спросить другой пиксель — следующее значение в исходном пикселе смещается
  (расстояние от точки до луча: 0.05 → 1.18 → 2.18 мм).

Причина частично в анимации: `ZoomPrevNextOrAll(ksZoomAll)` в v25 **плавно**
меняет масштаб, и вид продолжает ехать (проекция точки уплывала до 50 px).
Но и на неподвижном виде полагаться на `GetPickRay` не стоит.

Рабочая схема (в `lsk/picking.py`):

1. 3D-точка → пиксель через `IDocumentFrame.UnConvertCoordinates(kcDocument=1, x, y, z)`;
   Y переворачивается: `y_pixel = client_height − y` (проверено на четырёх точках).
2. Привязка — по расстоянию в пикселях между курсором и проекцией каждой точки
   модели. Это ровно то, что видит пользователь, и не зависит от луча.
3. Направление протяжки — проекции шести осей (±X, ±Y, ±Z) на экран сравниваются
   с вектором протяжки по косинусу (все шесть различимы, кроме оси «в камеру» —
   такие отбрасываются по длине проекции < 4 px).
4. Проекция требует двух вызовов подряд: первый после смены вида бывает неточным.
5. Масштаб вида (мм/пиксель) считается по проекциям единичных отрезков и нужен,
   чтобы допуск привязки задавать в пикселях.

`GetPickRay` остаётся только в диагностике `tools/check_pick.py`.

## Клик по модели (справочно)

* `IDocumentFrame.GetPickRay(windowX, windowY, x, y, z, zx, zy, zz)` — по оконным
  пикселам возвращает точку на луче и направление взгляда (не единичное).
  Координаты пикселей — обычные экранные (y вниз), начало — левый верхний
  угол клиентской области окна документа.
* `IKompasDocument3D.PickModelObjects(ray, findObjectParam)` — объекты вдоль луча.
  `ray` — 6 чисел: точка + вектор (ровно то, что вернул `GetPickRay`).
  `findObjectParam` можно передать `None` (проверено, не падает).
* `IApplication.GetMainWindowHandle()` и `IDocumentFrame.GetWindowHandle()` дают
  **один и тот же** HWND: окно документа занимает всю клиентскую область.`
* `IKompasDocument3DEx.PickModelObjectsWithLimit(ray, limit, filter, points)` —
  то же плюс точки пересечения (есть в v25, в v22 может отсутствовать).
* `IFace.NearPointProjection(x, y, z, u, v)` → параметры (u, v) ближайшей точки
  грани; `IFace.GetPoint(u, v)` → 3D-точка; `IFace.GetNormal(u, v)` → нормаль.
* `IFace.IsPlanar/IsCylinder/IsCone/IsSphere/IsTorus` — тип грани.
* `IPart.FindObjectsByPoint(x, y, z, firstLevel)` — объекты, проходящие через
  точку. Это самый надёжный способ получить грань под 3D-точкой (луч не нужен).
* `IDocumentFrame.UnConvertCoordinates(coordinateType, x, y, z, wx, wy)` —
  3D → пиксели. X совпадает с `GetPickRay`, а **Y измеряется от НИЖНЕЙ границы
  клиентской области** (`y_pickray = client_height − y_unconvert`, проверено
  по четырём точкам). Кроме того, точность — целые пиксели, поэтому для точного
  попадания в код добавлен численный решатель `picking.pixel_for_point()`
  (Ньютон по лучу, точность ~0.1 мм).
* `IDocumentFrame.GetWorkAreaRect()` отдаёт область отрисовки, но её origin не
  всегда (0,0) и ведёт себя по-разному в максимизированном окне — для проверки
  «курсор над моделью» надёжнее `GetClientRect` (см. `lsk/win32cursor.py`).
* `ConvertCoordTypeEnum`: `kcDocument = 1`, `kcGeoView = 2`, `kcCurrentPlane = 3`.
* Один пиксель экрана — это несколько миллиметров модели (при `ksZoomAll` на
  детали 100 мм было ≈ 3.2 мм/пиксель). Поэтому допуск привязки к точке задаётся
  в пикселях, а не только в миллиметрах.

## Подсказка направления: своё окно, а не объекты КОМПАСа

Во время протяжки нужно показать, какая ось «поймалась». Рисовать объекты в
модели (отрезки/оси) плохо: они попадают в дерево и в историю отмены, а
обновлять их 20 раз в секунду дорого. Поэтому подсказка — отдельное прозрачное
окно поверх КОМПАСа (`lsk/overlay.py`, Tkinter):

* `Toplevel` с `overrideredirect(True)`, `-topmost`, `-transparentcolor`;
* `WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` — клики проходят
  сквозь, фокус не перехватывается;
* данные для стрелки считаются один раз при нажатии (`axis_screen_vectors`),
  поэтому во время протяжки обращений к API нет вообще.

## COM-путь для v22 (где нет `ksapi.py`)

В v22 в `Bin` нет `ksapi.py` и `ksAPICLink.dll` — Python-обёртки ещё не было.
Зато есть COM-сервер `KOMPAS.Application.7` (в реестре рядом с устаревшим
`KOMPAS.Application.5`) и `kAPI7.tlb`.

Что выяснено на практике:

* `KOMPAS.Application.5` — старый урезанный API (у документа только
  `RebuildDocument/CopyPart/Save/Close`). Нужен именно **`.7`**: у него
  `ActiveDocument`, `Documents`, `ExecuteKompasCommand`, `MainWindowHandle`.
* pywin32/`win32com` тут не годится: `QueryInterface` для интерфейсов КОМПАСа
  даёт «There is no interface object registered that supports this IID».
  Работает `comtypes`: он генерирует Python-интерфейсы прямо из `kAPI7.tlb`
  (`comtypes.client.GetModule(path_to_tlb)`), после чего
  `obj.QueryInterface(module.IAuxiliaryGeomContainer)` ведёт себя как надо.
* IID/GUID всех интерфейсов **совпадают** в v22 и v25 (сверено по
  `KAPI7Dual.h` из SDK обеих версий), поэтому один код работает там и там.
* Имена в COM — свойства, а не `Get*`: `part.TopPart`, `lcs.Name`, `lcs.X`,
  `face.IsPlanar`, `container.Points3D`, `collection.Count`,
  `collection.LocalCoordinateSystem(i)`, `collection.Point3D(i)`,
  `frame.GetHWND()`, `doc.UndoContainer = True`.
* `[out]`-параметры comtypes возвращает кортежем: `face.GetPoint(u, v)` ->
  `(X, Y, Z, ok)`, `frame.UnConvertCoordinates(type, x, y, z)` -> `(lx, ly, ok)`.
* `IKompasDocument.Close(closeOptions)` — числовой enum: `0` без сохранения,
  `1` сохранить, `2` спросить.
* **Удаления объектов в COM-API нет** — только отмена (`Ctrl+Z`,
  `IApplication.ExecuteKompasCommand(57643, false)`); работает, если создание шло
  внутри `UndoContainer`.
* `IApplication.GetSystemVersion()` возвращает `(major, minor, release, build, ok)`.

## Отмена: `SetUndoContainer` группирует операции

`IKompasDocument3D.SetUndoContainer(True)` перед изменениями и `(False)` после —
и вся группа становится **одним шагом отмены**. Проверено: три ЛСК, созданные
внутри контейнера, штатный `Ctrl+Z` КОМПАСа (`IApplication.ExecuteKompasCommand(ksCMEditUndo)`,
id `57643`) убирает все три сразу. Без контейнера — по одной.

`IKompasDocument.Close(2)` — это `kdPromptToSaveChanges` (запрос сохранения!),
без сохранения — `0` (`kdDoNotSaveChanges`).

## Горячая клавиша: нажатие И отпускание

`RegisterHotKey` сообщает только о нажатии. Чтобы поймать жест «зажал → потянул →
отпустил», состояние опрашивается через `GetAsyncKeyState` (в отдельном потоке,
каждые 20 мс). Проверено синтетическими нажатиями: ловится и короткий тап, и
удержание (0.8 с → длительность между press и release 0.83 с).

Глобальная регистрация (`RegisterHotKey`) включается **только пока активно окно
КОМПАСа** (сравниваем pid владельца `GetForegroundWindow()` с pid КОМПАСа —
`IApplication.GetMainWindowHandle()` + `GetWindowThreadProcessId`), и только если
инструмент не выключен галочкой. Иначе клавиша «съедалась» бы во всех
программах — так и было: после перепривязки на `1` она перестала работать в
браузере.

## События мыши — НЕ РАБОТАЮТ из Python (проверено)

Кратко: подписка оформляется без ошибок, КОМПАС остаётся жив, но обработчик
**не вызывается ни разу** — ни на настоящий клик (SendInput), ни с запущенным
`ksapi.RunLoop()`, ни без него. Синтетический `PostMessage(WM_LBUTTONDOWN)` в окно
документа привёл к падению КОМПАСа. Вывод: перехват клика не используем, точку
берём по позиции курсора в момент нажатия горячей клавиши.

Подробности эксперимента — `tools/check_click.py`, `tools/check_click2.py`,
`tools/check_click3.py`.

## События мыши (справочно)

```python
cb = ksapi.IDocumentFrameEvents_OnMouseDownHandler(fn)   # CFUNCTYPE(c_bool, c_uint64, c_int32, c_int32)
frame.Events().AddMouseDownHandler("owner", cb)
frame.Events().RemoveAllHandlers("owner")
```

Подписаться можно только на документ с окном (невидимые документы `DocumentFrame`
не имеют). Обработчик вызывается в потоке КОМПАСа: тяжёлые вызовы API внутри него
лучше не делать — в проекте он только кладёт координаты в очередь.

## Грабли

* `IKompasDocument.Close(closeOptions)`, где `DocumentCloseOptions`
  (`constants.kdDoNotSaveChanges = 0`, `kdSaveChanges = 1`,
  `kdPromptToSaveChanges = 2`). Значение `2` — это **запрос на сохранение**:
  на изменённом документе вылезает модальный диалог и все дальнейшие вызовы API
  висят. Всегда закрывать тестовые документы через `0`.
* Разрядность Python и КОМПАСа должна совпадать (x64).
* `ksapi.IAPIObject.__init__` при неудачном `QueryInterface` обращается к
  `kompasApp._AddSlave`, поэтому интерфейс нужно приводить как
  `ksapi.IFace(obj, app)` (вторым аргументом приложение), иначе `AttributeError`.
  Проверять успех через `bool(result)`.
* `ksapi.IControlPoint`, `IConjunctivePoint` и т.п. — наследники `IPoint3D`;
  координаты читаются так же.
* Документация: `<установка>\SDK\Help\KOMPAS_SDK_ru-RU.zip` (HTML + `jstopics/*.js`
  с текстом справки), примеры: `SDK\Samples\{C++,CSharp,Pascal,Basic}.zip`.
