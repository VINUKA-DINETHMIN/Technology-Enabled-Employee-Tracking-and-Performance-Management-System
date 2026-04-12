"""
R26-IT-042 — C2: Anti-Spoofing Check Handler
Common module for antispoofing check orchestration

Stores antispoofing check results to MongoDB for admin panel consumption.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def store_antispoofing_result(
    db_client,
    user_id: str,
    is_real: bool,
    confidence: float,
    frame_count: int,
    avg_score: float,
    duration_sec: float,
) -> bool:
    """
    Store antispoofing check result to MongoDB.

    Parameters
    ----------
    db_client:
        MongoDBClient instance.
    user_id:
        Employee ID.
    is_real:
        True if face determined to be real, False if fake.
    confidence:
        Model confidence (0.0–1.0).
    frame_count:
        Number of frames processed.
    avg_score:
        Average antispoofing score across frames.
    duration_sec:
        Time taken for check.

    Returns
    -------
    bool
        True if stored successfully.
    """
    if not db_client or not db_client.is_connected:
        logger.warning("Database not connected; cannot store antispoofing result.")
        return False

    try:
        col = db_client.get_collection("antispoofing_checks")
        if col is None:
            logger.warning("antispoofing_checks collection unavailable.")
            return False

        result_doc = {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_real": is_real,
            "confidence": float(confidence),
            "frame_count": int(frame_count),
            "avg_score": float(avg_score),
            "check_duration_sec": float(duration_sec),
            "verdict": "REAL" if is_real else "FAKE",
        }

        col.insert_one(result_doc)
        logger.info(
            "Antispoofing result stored: user=%s verdict=%s confidence=%.2f",
            user_id,
            result_doc["verdict"],
            confidence,
        )
        return True

    except Exception as exc:
        logger.error("Failed to store antispoofing result: %s", exc)
        return False


def get_latest_antispoofing_check(db_client, user_id: str) -> Optional[dict]:
    """
    Retrieve the latest antispoofing check for a user.

    Parameters
    ----------
    db_client:
        MongoDBClient instance.
    user_id:
        Employee ID.

    Returns
    -------
    dict | None
        Latest check result, or None if not found.
    """
    if not db_client or not db_client.is_connected:
        return None

    try:
        col = db_client.get_collection("antispoofing_checks")
        if col is None:
            return None

        return col.find_one({"user_id": user_id}, sort=[("timestamp", -1)])
    except Exception as exc:
        logger.error("Failed to retrieve antispoofing check: %s", exc)
        return None
