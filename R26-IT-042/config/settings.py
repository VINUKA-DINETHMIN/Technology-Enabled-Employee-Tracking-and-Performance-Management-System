"""
R26-IT-042 — Employee Activity Monitoring System
config/settings.py

Centralised application settings loaded from the .env file.
All four components import from here — never read os.environ directly.

Usage
─────
>>> from config.settings import settings
>>> print(settings.MONGO_URI)
>>> print(settings.ANOMALY_THRESHOLD)
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Locate the .env file relative to the project root (two levels up from here)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# Load once at import time
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
    logger.debug(".env loaded from: %s", _ENV_PATH)
else:
    logger.warning(
        ".env file not found at %s — using system environment variables only.", _ENV_PATH
    )


class _Settings:
    """
    Singleton settings container.

    All values are read from the .env file (or the process environment).
    Hard-coded defaults are provided for non-sensitive operational parameters.
    """

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    MONGO_URI: str = os.environ.get("MONGO_URI", "")
    MONGO_DB_NAME: str = os.environ.get("MONGO_DB_NAME", "employee_monitor")

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    AES_KEY: str = os.environ.get("AES_KEY", "")

    # ------------------------------------------------------------------
    # WebSocket Dashboard
    # ------------------------------------------------------------------
    WEBSOCKET_URL: str = os.environ.get("WEBSOCKET_URL", "ws://localhost:8765")

    # ------------------------------------------------------------------
    # Application metadata
    # ------------------------------------------------------------------
    APP_NAME: str = os.environ.get("APP_NAME", "WorkPlus")
    VERSION: str = os.environ.get("VERSION", "1.0.0")

    # ------------------------------------------------------------------
    # Anomaly & risk thresholds
    # ------------------------------------------------------------------
    ANOMALY_THRESHOLD: float = float(os.environ.get("ANOMALY_THRESHOLD", "75"))
    RISK_SCORE_SOFT_WARNING: float = float(os.environ.get("RISK_SCORE_SOFT_WARNING", "50"))
    RISK_SCORE_HARD_WARNING: float = float(os.environ.get("RISK_SCORE_HARD_WARNING", "75"))

    # ------------------------------------------------------------------
    # Break schedule (minutes)
    # ------------------------------------------------------------------
    BREAK_LUNCH_MINUTES: int = int(os.environ.get("BREAK_LUNCH_MINUTES", "60"))
    BREAK_SHORT_MINUTES: int = int(os.environ.get("BREAK_SHORT_MINUTES", "15"))

    # ------------------------------------------------------------------
    # Screenshot settings
    # ------------------------------------------------------------------
    SCREENSHOT_INTERVAL_SEC: int = int(os.environ.get("SCREENSHOT_INTERVAL_SEC", "300"))
    SCREENSHOT_DIR: str = os.environ.get(
        "SCREENSHOT_DIR",
        str(_PROJECT_ROOT / "screenshots"),
    )

    # ------------------------------------------------------------------
    # Monitoring intervals (seconds)
    # ------------------------------------------------------------------
    KEYBOARD_SAMPLE_INTERVAL: float = float(os.environ.get("KEYBOARD_SAMPLE_INTERVAL", "1.0"))
    MOUSE_SAMPLE_INTERVAL: float = float(os.environ.get("MOUSE_SAMPLE_INTERVAL", "0.5"))
    IDLE_CHECK_INTERVAL: float = float(os.environ.get("IDLE_CHECK_INTERVAL", "10.0"))
    IDLE_THRESHOLD_SEC: int = int(os.environ.get("IDLE_THRESHOLD_SEC", "300"))

    # ------------------------------------------------------------------
    # SMTP Configuration (Email)
    # ------------------------------------------------------------------
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER: str = os.environ.get("SMTP_USER", "")
    SMTP_PASS: str = os.environ.get("SMTP_PASS", "")

    def validate(self) -> list[str]:
        """
        Check for missing critical settings.

        Returns
        -------
        list[str]
            List of missing/invalid setting names.  Empty means all OK.
        """
        missing = []
        if not self.MONGO_URI:
            missing.append("MONGO_URI")
        if not self.AES_KEY:
            missing.append("AES_KEY")
        if self.AES_KEY and len(self.AES_KEY) != 64:
            missing.append("AES_KEY (must be 64 hex chars / 32 bytes)")
        return missing

    def __repr__(self) -> str:
        return (
            f"<Settings APP={self.APP_NAME} v{self.VERSION} "
            f"MONGO={'set' if self.MONGO_URI else 'MISSING'} "
            f"AES={'set' if self.AES_KEY else 'MISSING'}>"
        )


# ---------------------------------------------------------------------------
# Public singleton
# ---------------------------------------------------------------------------
settings = _Settings()

# Log warnings at import time for missing critical environment variables
_missing = settings.validate()
if _missing:
    logger.warning(
        "Missing required settings: %s — add them to your .env file.", _missing
    )
