@echo off
cd /d "%~dp0"
if exist "%SystemRoot%\pyw.exe" (
  start "" "%SystemRoot%\pyw.exe" "%~dp0gui.py"
  exit /b 0
)
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw "%~dp0gui.py"
  exit /b 0
)
python "%~dp0gui.py"
