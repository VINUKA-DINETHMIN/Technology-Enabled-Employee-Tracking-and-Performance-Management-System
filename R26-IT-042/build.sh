#!/usr/bin/env bash
# ============================================================
# R26-IT-042 — Employee Activity Monitoring System
# build.sh — macOS / Linux PyInstaller build script
# ============================================================

set -e

echo ""
echo " [R26-IT-042] Building macOS/Linux executable..."
echo ""

# ── Activate venv ───────────────────────────────────────────
if [ ! -f "venv/bin/activate" ]; then
    echo "[ERROR] Virtual environment not found. Run ./setup.sh first."
    exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

# ── Determine icon path (icns for macOS, png fallback for Linux) ─
if [[ "$OSTYPE" == "darwin"* ]]; then
    ICON_ARG="--icon assets/logo.icns"
else
    ICON_ARG="--icon assets/logo.png"
fi

# ── Run PyInstaller ─────────────────────────────────────────
pyinstaller \
    --onefile \
    --windowed \
    --name "EmployeeActivityMonitor" \
    $ICON_ARG \
    --add-data "assets:assets" \
    --add-data "config:config" \
    --hidden-import sklearn \
    --hidden-import sklearn.utils._cython_blas \
    --hidden-import sklearn.neighbors._typedefs \
    --hidden-import cv2 \
    --hidden-import mediapipe \
    --hidden-import pynput \
    --hidden-import pynput.keyboard \
    --hidden-import pynput.mouse \
    --hidden-import customtkinter \
    --hidden-import pymongo \
    --hidden-import cryptography \
    --hidden-import websockets \
    --hidden-import pyotp \
    --hidden-import dotenv \
    main.py

echo ""
echo " [OK] Build complete!  Executable is in: dist/EmployeeActivityMonitor"
echo ""
