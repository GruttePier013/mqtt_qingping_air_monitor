@echo off
rem Qingping CGDN1 Bluetooth setup - starts the GUI on Windows 10/11.
rem First run: creates a local Python environment and installs bleak.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^)
  echo or download QingpingProvision.exe from the GitHub release page.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo First start: preparing Python environment...
  py -3 -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :error
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0qingping_provision_gui.py"
exit /b 0
:error
echo Installation failed. See the messages above.
pause
exit /b 1
