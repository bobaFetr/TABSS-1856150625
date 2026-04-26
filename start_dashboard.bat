@echo off
setlocal
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0start_dashboard.ps1"
if errorlevel 1 (
    echo.
    echo The dashboard stopped because of an error.
    pause
)
