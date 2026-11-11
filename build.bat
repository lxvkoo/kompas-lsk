@echo off
rem Сборка двух exe: панель (без консоли) и диагностика (с консолью).
rem Требуется Python 64-бит той же разрядности, что КОМПАС.
setlocal
cd /d "%~dp0"

echo === lsk_placer.exe (панель) ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name lsk_placer ^
  --hidden-import ctypes --hidden-import _ctypes --hidden-import winreg ^
  --hidden-import comtypes --hidden-import comtypes.client ^
  --hidden-import comtypes.automation --hidden-import comtypes.typeinfo ^
  --collect-submodules comtypes ^
  main.py || goto :error

echo === lsk_probe.exe (диагностика) ===
python -m PyInstaller --noconfirm --onefile --console ^
  --name lsk_probe ^
  --hidden-import ctypes --hidden-import _ctypes --hidden-import winreg ^
  --hidden-import comtypes --hidden-import comtypes.client ^
  --hidden-import comtypes.automation --hidden-import comtypes.typeinfo ^
  --collect-submodules comtypes ^
  probe_env.py || goto :error

echo.
echo Готово: dist\lsk_placer.exe и dist\lsk_probe.exe
exit /b 0

:error
echo Сборка не удалась
exit /b 1
