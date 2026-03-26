@echo off
REM ============================================================
REM R26-IT-042 — Employee Activity Monitoring System
REM build.bat — Windows PyInstaller build script
REM ============================================================

echo.
echo  [R26-IT-042] Building Windows executable...
echo.

REM ── Activate venv ───────────────────────────────────────────
IF NOT EXIST venv\Scripts\activate.bat (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

REM ── Run PyInstaller ─────────────────────────────────────────
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "EmployeeActivityMonitor" ^
    --icon "assets\logo.ico" ^
    --add-data "assets;assets" ^
    --add-data "config;config" ^
    --hidden-import sklearn ^
    --hidden-import sklearn.utils._cython_blas ^
    --hidden-import sklearn.neighbors._typedefs ^
    --hidden-import cv2 ^
    --hidden-import mediapipe ^
    --hidden-import pynput ^
    --hidden-import pynput.keyboard ^
    --hidden-import pynput.mouse ^
    --hidden-import customtkinter ^
    --hidden-import pymongo ^
    --hidden-import cryptography ^
    --hidden-import websockets ^
    --hidden-import pyotp ^
    --hidden-import dotenv ^
    main.py

IF ERRORLEVEL 1 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo  [OK] Build complete!  Executable is in: dist\EmployeeActivityMonitor.exe
echo.
pause
