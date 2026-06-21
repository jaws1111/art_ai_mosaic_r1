@echo off
setlocal EnableExtensions
cd /d "%~dp0..\..\backend"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Backend venv not found in %CD%
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python run.py
pause
