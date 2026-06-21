@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "VITE_PORT=5522"
set "FOUND=0"

echo.
echo  Tessera — Stop Vite
echo  ===================
echo.

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%VITE_PORT% " ^| findstr LISTENING') do (
    set "FOUND=1"
    echo  Stopping process on port %VITE_PORT% ^(PID %%P^)...
    taskkill /PID %%P /T /F >nul 2>&1
    if errorlevel 1 (
        echo  [WARN] Could not stop PID %%P. Try running as Administrator.
    ) else (
        echo  [OK] Vite stopped.
    )
)

if "!FOUND!"=="0" (
    echo  [INFO] Nothing listening on port %VITE_PORT%.
)

echo.
call "%~dp0status.cmd"
exit /b 0
