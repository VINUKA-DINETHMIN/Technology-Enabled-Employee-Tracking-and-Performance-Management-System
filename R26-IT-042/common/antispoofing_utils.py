"""
R26-IT-042 — C2: Anti-Spoofing Check Handler
Common module for antispoofing check orchestration

Stores antispoofing check results to MongoDB for admin panel consumption.
"""

from __future__ import annotations

import logging
import time
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
    identity_match: bool | None = None,
    identity_score: float = 0.0,
    identity_status: str = "UNKNOWN",
    verdict: str | None = None,
    extra: Optional[dict] = None,
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
    identity_match:
        True if live face matches stored user face, False if not, None if unknown.
    identity_score:
        Similarity score between live face and stored user face.
    identity_status:
        Identity context string like SAME_PERSON, DIFFERENT_PERSON, NO_TEMPLATE, UNKNOWN.
    verdict:
        Optional explicit verdict string.

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
            "identity_match": identity_match,
            "identity_score": float(identity_score),
            "identity_status": identity_status,
            "verdict": verdict if verdict is not None else ("REAL" if is_real else "FAKE"),
            **(extra or {}),
        }

        col.insert_one(result_doc)
        logger.info(
            "Antispoofing result stored: user=%s verdict=%s confidence=%.2f identity_status=%s",
            user_id,
            result_doc["verdict"],
            confidence,
            identity_status,
        )
        return True

    except Exception as exc:
        logger.error("Failed to store antispoofing result: %s", exc)
        return False


def run_camera_antispoofing_check(
    db_client,
    user_id: str,
    timeout_sec: float = 10.0,
    windows: int = 5,
    source: str = "break_overrun",
) -> bool:
    """Run a camera-based anti-spoofing check and persist the result."""
    start = time.time()

    try:
        from C2_Anti_Spoofing_Detection.src.antispoofing_detector import AntiSpoofingDetector
    except Exception as exc:
        logger.warning("Anti-spoofing detector unavailable: %s", exc)
        return False

    detector = AntiSpoofingDetector()
    model_loaded = detector.load_model()
    try:
        is_real, confidence, reason = detector.predict_from_camera(timeout_sec=timeout_sec, windows=windows)
        duration = time.time() - start
    finally:
        detector.close()

    identity_status = "UNKNOWN" if model_loaded else "VERIFIER_UNAVAILABLE"
    verdict = "REAL" if is_real else "FAKE"
    if not model_loaded:
        verdict = "VERIFIER_UNAVAILABLE"

    return store_antispoofing_result(
        db_client=db_client,
        user_id=user_id,
        is_real=is_real,
        confidence=confidence,
        frame_count=windows,
        avg_score=confidence,
        duration_sec=duration,
        identity_match=None,
        identity_score=0.0,
        identity_status=identity_status,
        verdict=verdict,
        extra={
            "check_source": source,
            "check_reason": reason,
        },
    )


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
