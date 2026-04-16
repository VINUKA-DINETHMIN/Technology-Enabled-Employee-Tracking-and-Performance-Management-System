@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment Python not found: .venv\Scripts\python.exe
    echo Run setup first, then try again.
    pause
    exit /b 1
)

echo Starting admin app...
".venv\Scripts\python.exe" main.py --admin
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Admin app exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
