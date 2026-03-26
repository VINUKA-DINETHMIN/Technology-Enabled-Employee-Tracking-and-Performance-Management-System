#!/usr/bin/env bash
# ============================================================
# R26-IT-042 — Employee Activity Monitoring System
# setup.sh — macOS / Linux setup script
# ============================================================

set -e  # Exit on any error

echo ""
echo " ╔══════════════════════════════════════════════════════╗"
echo " ║    R26-IT-042  Employee Activity Monitoring System   ║"
echo " ║                  macOS / Linux Setup                 ║"
echo " ╚══════════════════════════════════════════════════════╝"
echo ""

# ── macOS permission warning ────────────────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "⚠️  macOS Permissions Required:"
    echo "   • Camera access  (Facial Liveness — C2)"
    echo "   • Accessibility  (Keyboard/Mouse tracking — C3)"
    echo ""
    echo "   Grant these in: System Preferences → Privacy & Security"
    echo ""
fi

# ── Check Python 3 ──────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found."
    echo "        Install it from https://python.org or via Homebrew:"
    echo "        brew install python3"
    exit 1
fi
echo "[OK] $(python3 --version)"

# ── Create virtual environment ──────────────────────────────
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv venv
    echo "[OK] Virtual environment created."
else
    echo "[OK] Virtual environment already exists."
fi

# ── Activate ────────────────────────────────────────────────
echo "[*] Activating virtual environment..."
# shellcheck disable=SC1091
source venv/bin/activate

# ── Upgrade pip ─────────────────────────────────────────────
echo "[*] Upgrading pip..."
pip install --upgrade pip --quiet

# ── Install dependencies ────────────────────────────────────
echo "[*] Installing dependencies from requirements.txt ..."
pip install -r requirements.txt
echo "[OK] All dependencies installed."

# ── Create .env template if missing ─────────────────────────
if [ ! -f ".env" ]; then
    echo "[*] Creating .env template..."
    cat > .env <<'EOF'
MONGO_URI=
AES_KEY=
WEBSOCKET_URL=ws://localhost:8765
APP_NAME=Employee Monitor
VERSION=1.0.0
EOF
    echo "[OK] .env template created. Fill in your values before running."
else
    echo "[OK] .env already exists."
fi

# ── Ensure this script is executable for future use ─────────
chmod +x setup.sh
chmod +x build.sh 2>/dev/null || true

# ── Done ────────────────────────────────────────────────────
echo ""
echo " ======================================================"
echo "  Setup complete!  Edit .env then run:"
echo "    source venv/bin/activate"
echo "    python3 main.py"
echo " ======================================================"
echo ""
