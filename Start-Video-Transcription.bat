@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto runtime
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -B scripts\check_dependencies.py --runtime-only
  if errorlevel 1 goto requirements
  choice /C YN /N /M "Create a local Python virtual environment? [Y/N] "
  if errorlevel 2 exit /b 0
  py -3 -m venv .venv
  if errorlevel 1 goto requirements
  goto runtime
)
where python >nul 2>nul
if errorlevel 1 goto requirements
python -B scripts\check_dependencies.py --runtime-only
if errorlevel 1 goto requirements
choice /C YN /N /M "Create a local Python virtual environment? [Y/N] "
if errorlevel 2 exit /b 0
python -m venv .venv
if errorlevel 1 goto requirements
:runtime
".venv\Scripts\python.exe" -B scripts\check_dependencies.py --runtime-only
if errorlevel 1 goto requirements
".venv\Scripts\python.exe" -B scripts\check_dependencies.py --packages-only
if not errorlevel 1 goto ready
choice /C YN /N /M "Install the exact listed dependency versions from PyPI into .venv? [Y/N] "
if errorlevel 2 exit /b 0
".venv\Scripts\python.exe" -m pip install -r scripts\requirements-docx.lock
if errorlevel 1 goto requirements
:ready
".venv\Scripts\python.exe" -B scripts\check_dependencies.py
if errorlevel 1 goto requirements
".venv\Scripts\python.exe" -B scripts\app.py
pause
exit /b 0
:requirements
echo Python 3.10+, FFmpeg and ffprobe are required. See references\dependencies.md.
echo Install only with your permission from official sources, then restart.
pause
exit /b 1
