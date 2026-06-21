@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "BACKEND_PORT=8000"
set "VITE_PORT=5522"
set "BACKEND_PID="
set "VITE_PID="

echo.
echo  Tessera - Status
echo  =================
echo.

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr LISTENING') do set "BACKEND_PID=%%P"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%VITE_PORT% " ^| findstr LISTENING') do set "VITE_PID=%%P"

if defined BACKEND_PID (
    echo  [RUNNING] Backend API
    echo            URL:  http://127.0.0.1:%BACKEND_PORT%
    echo            Port: %BACKEND_PORT%
    echo            PID:  %BACKEND_PID%
    tasklist /FI "PID eq %BACKEND_PID%" /FO LIST 2>nul | findstr /I "Image Name"
) else (
    echo  [STOPPED] Backend API ^(port %BACKEND_PORT%^)
)

echo.

if defined VITE_PID (
    echo  [RUNNING] Vite frontend
    echo            URL:  http://127.0.0.1:%VITE_PORT%
    echo            Port: %VITE_PORT%
    echo            PID:  %VITE_PID%
    tasklist /FI "PID eq %VITE_PID%" /FO LIST 2>nul | findstr /I "Image Name"
) else (
    echo  [STOPPED] Vite frontend ^(port %VITE_PORT%^)
)

echo.
echo  Commands: launch.cmd   status.cmd   stop-vite.cmd   stop-backend.cmd
echo.
exit /b 0
