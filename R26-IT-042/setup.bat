@echo off
REM ============================================================
REM R26-IT-042 — Employee Activity Monitoring System
REM setup.bat — Windows setup script
REM ============================================================

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║    R26-IT-042  Employee Activity Monitoring System   ║
echo  ║                  Windows Setup                       ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

REM ── Check Python ────────────────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
echo [OK] Python found.

REM ── Create virtual environment ──────────────────────────────
IF NOT EXIST venv (
    echo [*] Creating virtual environment...
    python -m venv venv
    IF ERRORLEVEL 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) ELSE (
    echo [OK] Virtual environment already exists.
)

REM ── Activate ────────────────────────────────────────────────
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

REM ── Upgrade pip ─────────────────────────────────────────────
echo [*] Upgrading pip...
python -m pip install --upgrade pip --quiet

REM ── Install dependencies ────────────────────────────────────
echo [*] Installing dependencies from requirements.txt ...
pip install -r requirements.txt
IF ERRORLEVEL 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)
echo [OK] All dependencies installed.

REM ── Create .env template if missing ─────────────────────────
IF NOT EXIST .env (
    echo [*] Creating .env template...
    (
        echo MONGO_URI=
        echo AES_KEY=
        echo WEBSOCKET_URL=ws://localhost:8765
        echo APP_NAME=Employee Monitor
        echo VERSION=1.0.0
    ) > .env
    echo [OK] .env template created. Fill in your values before running the app.
) ELSE (
    echo [OK] .env already exists.
)

REM ── Done ────────────────────────────────────────────────────
echo.
echo  ======================================================
echo   Setup complete!  Edit .env then run:
echo     venv\Scripts\activate
echo     python main.py
echo  ======================================================
echo.
pause
