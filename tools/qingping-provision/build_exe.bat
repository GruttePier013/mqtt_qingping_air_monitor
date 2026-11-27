@echo off
rem Build a standalone QingpingProvision.exe (no Python needed on the target PC).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller
copy /y "..\..\custom_components\qingping_cgdn1\ble_provision.py" "ble_provision.py" >nul
".venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name QingpingProvision ^
  --icon app.ico --add-data "app.ico;." --add-data "logo.png;." --add-data "ble_provision.py;." ^
  --hidden-import qingping_provision --collect-all bleak --collect-submodules winrt ^
  qingping_provision_gui.py
del ble_provision.py
echo.
echo Done: dist\QingpingProvision.exe
pause
