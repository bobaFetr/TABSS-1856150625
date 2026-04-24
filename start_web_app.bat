@echo off
setlocal
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0start_web_app.ps1"
if errorlevel 1 (
    echo.
    echo The app stopped because of an error.
    pause
)
