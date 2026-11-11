@echo off
rem Сборка одного exe. Требуется Python 64-бит (та же разрядность, что КОМПАС).
rem Результат: dist\lsk_placer.exe
rem
rem Иконка: icon.ico (пересобрать из картинки: python tools\make_icon.py icon.png --plate)
setlocal
cd /d "%~dp0"

set EXTRAS=--hidden-import ctypes --hidden-import _ctypes --hidden-import winreg ^
 --hidden-import comtypes --hidden-import comtypes.client ^
 --hidden-import comtypes.automation --hidden-import comtypes.typeinfo ^
 --exclude-module unittest --exclude-module doctest --exclude-module pydoc ^
 --exclude-module test --exclude-module lib2to3 --exclude-module sqlite3

set ICON=
set ICONDATA=
if exist icon.ico set ICON=--icon icon.ico
if exist icon.ico set ICONDATA=--add-data "icon.ico;."
if exist icon_32.png set ICONDATA=--add-data "icon_32.png;."

rem версия в ресурсах exe (из lsk\__init__.py)
python tools\make_version_info.py || goto :error

echo === lsk_placer.exe ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name lsk_placer %ICON% %ICONDATA% ^
  --version-file version_info_lsk_placer.txt ^
  %EXTRAS% main.py || goto :error

echo.
echo Готово: dist\lsk_placer.exe
echo   диагностика: lsk_placer.exe --probe    (пишет probe_report.txt и открывает его)
echo   самотест:    lsk_placer.exe --selftest
exit /b 0

:error
echo Сборка не удалась
exit /b 1
