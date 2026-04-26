@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto run

set "PYTHON_EXE=C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if exist "%PYTHON_EXE%" goto run

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  pause
  exit /b 1
)
set "PYTHON_EXE=python"

:run
echo Starting BTC Signal Agent dashboard...
echo Open http://127.0.0.1:8765
echo Press Ctrl+C to stop.
echo.
"%PYTHON_EXE%" "%~dp0api_server.py"
