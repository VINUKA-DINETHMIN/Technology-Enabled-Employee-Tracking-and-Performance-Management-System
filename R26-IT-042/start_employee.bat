@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment Python not found: .venv\Scripts\python.exe
    echo Run setup first, then try again.
    pause
    exit /b 1
)

echo Starting employee app...
".venv\Scripts\python.exe" main.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Employee app exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
