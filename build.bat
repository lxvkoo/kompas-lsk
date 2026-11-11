@echo off
rem Сборка exe. Требуется Python 64-бит той же разрядности, что КОМПАС.
rem
rem Результат в dist\:
rem   lsk_placer.exe        один файл (портативный, старт ~2 с)
rem   lsk_placer\lsk_placer.exe  папка (быстрый старт ~0.5 с, для установки)
rem   lsk_probe.exe         диагностика с консолью
rem
rem Иконка: положить icon.ico (или сделать из картинки: python tools\make_icon.py картинка.png)
setlocal
cd /d "%~dp0"

set EXTRAS=--hidden-import ctypes --hidden-import _ctypes --hidden-import winreg ^
 --hidden-import comtypes --hidden-import comtypes.client ^
 --hidden-import comtypes.automation --hidden-import comtypes.typeinfo ^
 --exclude-module unittest --exclude-module doctest --exclude-module pydoc ^
 --exclude-module test --exclude-module lib2to3 ^
 --exclude-module sqlite3

set ICON=
set ICONDATA=
if exist icon.ico set ICON=--icon icon.ico
if exist icon.ico set ICONDATA=--add-data "icon.ico;."

rem версия в ресурсах exe
python tools\make_version_info.py || goto :error

echo === lsk_placer.exe (один файл) ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name lsk_placer %ICON% %ICONDATA% --version-file version_info_lsk_placer.txt ^
  %EXTRAS% main.py || goto :error

echo === lsk_placer (папка, быстрый старт) ===
python -m PyInstaller --noconfirm --onedir --windowed ^
  --name lsk_placer --distpath dist_fast --workpath build_fast ^
  %ICON% %ICONDATA% --version-file version_info_lsk_placer.txt ^
  %EXTRAS% main.py || goto :error

echo === lsk_probe.exe (диагностика, с консолью) ===
python -m PyInstaller --noconfirm --onefile --console ^
  --name lsk_probe %ICON% --version-file version_info_lsk_probe.txt ^
  %EXTRAS% probe_env.py || goto :error

echo.
echo Готово:
echo   dist\lsk_placer.exe              (один файл)
echo   dist_fast\lsk_placer\lsk_placer.exe  (папка, быстрый старт)
echo   dist\lsk_probe.exe               (диагностика)
exit /b 0

:error
echo Сборка не удалась
exit /b 1
