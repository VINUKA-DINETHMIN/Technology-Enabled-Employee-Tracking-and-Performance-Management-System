@echo off
setlocal
cd /d "%~dp0"
set "WORKPLUS_LAUNCHER=1"
if not exist ".venv\Scripts\python.exe" (
  echo [WorkPlus] Missing virtual environment Python: .venv\Scripts\python.exe
  exit /b 1
)
".venv\Scripts\python.exe" "main.py" --admin
endlocal
