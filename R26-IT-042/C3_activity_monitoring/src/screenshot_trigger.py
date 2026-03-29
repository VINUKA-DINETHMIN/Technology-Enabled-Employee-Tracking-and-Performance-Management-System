"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/screenshot_trigger.py

Captures and encrypts a screenshot when the risk score exceeds the
HIGH threshold.  Saves metadata to MongoDB screenshots collection.

Cross-platform: uses pyautogui.screenshot() which works on
Windows, macOS, and Linux (X11).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"


class ScreenshotTrigger:
    """
    Captures, encrypts, and persists screenshots on high-risk events.

    Usage
    ─────
    >>> trigger = ScreenshotTrigger(encryptor=enc, db_collection=col)
    >>> trigger.capture("EMP001", session_id="abc", risk_score=82.0)
    """

    def __init__(
        self,
        screenshot_dir: Optional[Path] = None,
        encryptor=None,
        db_client=None,
    ) -> None:
        self._dir = Path(screenshot_dir or _DEFAULT_SCREENSHOT_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._encryptor = encryptor
        self._db_col = None
        if db_client is not None:
            try:
                self._db_col = db_client.get_collection("screenshots")
            except AttributeError:
                # Fallback if a collection was passed directly
                self._db_col = db_client

    def capture(
        self,
        user_id: str,
        session_id: str,
        risk_score: float,
        trigger_reason: str = "anomaly",
    ) -> Optional[str]:
        """
        Take a screenshot, encrypt it, and save to disk.

        Returns
        -------
        str | None
            Absolute path of the saved encrypted file, or None on failure.
        """
        try:
            import pyautogui

            ts = datetime.now(timezone.utc)
            filename = f"{user_id}_{ts.strftime('%Y%m%dT%H%M%S')}.enc"
            file_path = self._dir / filename

            # Capture screenshot as bytes (PNG format)
            screenshot = pyautogui.screenshot()
            import io
            buf = io.BytesIO()
            screenshot.save(buf, format="PNG")
            raw_bytes = buf.getvalue()

            # Encrypt if encryptor is available
            if self._encryptor is not None:
                encrypted = self._encryptor.encrypt_bytes(
                    raw_bytes, associated_data=user_id.encode()
                )
                file_path.write_bytes(encrypted)
            else:
                file_path.write_bytes(raw_bytes)

            logger.info("Screenshot saved: %s (risk=%.1f)", file_path, risk_score)

            # Persist metadata to MongoDB (include small preview for remote viewing)
            import base64
            # For the DB, we use a smaller JPEG to save space
            db_buf = io.BytesIO()
            screenshot.save(db_buf, format="JPEG", quality=50)
            b64_img = base64.b64encode(db_buf.getvalue()).decode("utf-8")

            self._save_metadata(user_id, session_id, str(file_path), risk_score, trigger_reason, len(raw_bytes), b64_img)

            return str(file_path)

        except ImportError:
            logger.warning("pyautogui not available — screenshot skipped.")
            return None
        except Exception as exc:
            logger.error("Screenshot capture failed: %s", exc)
            return None

    def _save_metadata(self, user_id, session_id, path, risk_score, reason, size, b64_img) -> None:
        if self._db_col is None:
            return
        try:
            from common.models import ScreenshotDocument
            doc = ScreenshotDocument(
                user_id=user_id,
                session_id=session_id,
                file_path=path,
                image_base64=b64_img,
                trigger_reason=reason,
                risk_score_at_capture=risk_score,
                file_size_bytes=size,
                encrypted=self._encryptor is not None
            )
            self._db_col.insert_one(doc.to_dict())
        except Exception as exc:
            logger.error("Failed to save screenshot metadata: %s", exc)
