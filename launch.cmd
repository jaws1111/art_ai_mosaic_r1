@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "BACKEND_PORT=8000"
set "VITE_PORT=5522"
set "BACKEND_RUNNING=0"
set "VITE_RUNNING=0"

echo.
echo  Tessera - Launch
echo  ================
echo  Root: %CD%
echo.

if not exist "%~dp0backend\.venv\Scripts\python.exe" (
    echo [ERROR] Backend venv missing. Run:
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "%~dp0frontend\package.json" (
    echo [ERROR] frontend\package.json not found.
    pause
    exit /b 1
)

call "%~dp0status.cmd"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr LISTENING') do (
    echo [SKIP] Backend already on port %BACKEND_PORT% ^(PID %%P^)
    set "BACKEND_RUNNING=1"
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%VITE_PORT% " ^| findstr LISTENING') do (
    echo [SKIP] Vite already on port %VITE_PORT% ^(PID %%P^)
    set "VITE_RUNNING=1"
)

if "!BACKEND_RUNNING!"=="0" (
    echo [START] Backend API - http://127.0.0.1:%BACKEND_PORT%
    start "Tessera API" cmd /k "%~dp0scripts\win\start-api.cmd"
)

if "!VITE_RUNNING!"=="0" (
    echo [START] Vite UI - http://127.0.0.1:%VITE_PORT%
    start "Tessera UI" cmd /k "%~dp0scripts\win\start-ui.cmd"
)

echo.
echo  Done. Use status.cmd to check, stop-vite.cmd to stop UI.
echo.
exit /b 0
