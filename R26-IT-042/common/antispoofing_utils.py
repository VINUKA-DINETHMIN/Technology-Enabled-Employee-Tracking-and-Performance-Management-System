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

_IDENTITY_THRESHOLD = 0.70


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

    in_seat, identity_status, identity_match, identity_score = _evaluate_presence_and_identity(
        db_client=db_client,
        user_id=user_id,
        timeout_sec=min(timeout_sec, 6.0),
    )

    if in_seat is False:
        identity_status = "NO_FACE_DETECTED"
    elif in_seat is True and identity_status == "UNKNOWN":
        # If a face exists but identity is still unknown, keep it explicit.
        identity_status = "REAL_UNKNOWN"

    if not model_loaded and identity_status == "UNKNOWN":
        identity_status = "VERIFIER_UNAVAILABLE"

    verdict = "REAL" if is_real else "FAKE"
    if in_seat is False:
        verdict = "NO_FACE"
    elif identity_status == "SAME_PERSON" and is_real:
        verdict = "REAL_SAME_PERSON"
    elif identity_status == "DIFFERENT_PERSON" and is_real:
        verdict = "REAL_DIFFERENT_PERSON"
    elif not model_loaded and identity_status == "VERIFIER_UNAVAILABLE":
        verdict = "VERIFIER_UNAVAILABLE"

    return store_antispoofing_result(
        db_client=db_client,
        user_id=user_id,
        is_real=is_real,
        confidence=confidence,
        frame_count=windows,
        avg_score=confidence,
        duration_sec=duration,
        identity_match=identity_match,
        identity_score=identity_score,
        identity_status=identity_status,
        verdict=verdict,
        extra={
            "check_source": source,
            "check_reason": reason,
            "in_seat": in_seat,
        },
    )


def _evaluate_presence_and_identity(db_client, user_id: str, timeout_sec: float = 6.0) -> tuple[Optional[bool], str, Optional[bool], float]:
    """Check whether a face is present and if it matches the stored user template."""
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        logger.debug("Presence/identity dependencies unavailable: %s", exc)
        return None, "UNKNOWN", None, 0.0

    stored_embedding = None
    try:
        if db_client and db_client.is_connected:
            col = db_client.get_collection("employees")
            if col is not None:
                doc = col.find_one({"employee_id": user_id}, {"face_embedding": 1})
                if doc is not None and doc.get("face_embedding"):
                    stored_embedding = doc.get("face_embedding")
    except Exception as exc:
        logger.debug("Could not load stored embedding for %s: %s", user_id, exc)

    verifier = None
    verifier_available = False
    try:
        from C3_activity_monitoring.src.face_verifier import FaceVerifier
        verifier = FaceVerifier(model_path="models/face_recognition_sface.onnx")
        verifier_available = True
    except Exception as exc:
        logger.debug("Face verifier unavailable for presence check: %s", exc)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        if verifier is not None:
            verifier.close()
        return None, "UNKNOWN", None, 0.0

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        cascade = None

    face_frames = 0
    best_identity_score = 0.0
    identity_match_count = 0
    start = time.time()

    try:
        while (time.time() - start) < max(1.5, timeout_sec):
            ret, frame = cap.read()
            if not ret:
                continue

            detection_box = None
            if cascade is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.1, 5)
                if len(faces) > 0:
                    detection_box = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[0]
                    face_frames += 1

            if (
                detection_box is not None
                and verifier_available
                and verifier is not None
                and stored_embedding is not None
            ):
                try:
                    matched, score = verifier.verify(
                        frame,
                        stored_embedding,
                        threshold=_IDENTITY_THRESHOLD,
                        detection_box=np.array(detection_box, dtype=np.uint32),
                    )
                    best_identity_score = max(best_identity_score, float(score))
                    if matched:
                        identity_match_count += 1
                except Exception:
                    pass
    finally:
        cap.release()
        if verifier is not None:
            verifier.close()

    in_seat = face_frames > 0
    if not in_seat:
        return False, "NO_FACE_DETECTED", None, 0.0

    if stored_embedding is None:
        return True, "NO_TEMPLATE", None, 0.0

    if not verifier_available:
        return True, "VERIFIER_UNAVAILABLE", None, best_identity_score

    if identity_match_count >= 1 or best_identity_score >= _IDENTITY_THRESHOLD:
        return True, "SAME_PERSON", True, round(best_identity_score, 4)

    return True, "DIFFERENT_PERSON", False, round(best_identity_score, 4)


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
