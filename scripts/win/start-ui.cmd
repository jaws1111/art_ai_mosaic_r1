@echo off
setlocal EnableExtensions
cd /d "%~dp0..\..\frontend"
if not exist "package.json" (
    echo [ERROR] frontend\package.json not found in %CD%
    pause
    exit /b 1
)
if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)
call npm run dev
pause
