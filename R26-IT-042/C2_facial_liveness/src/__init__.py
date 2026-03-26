"""
R26-IT-042 — C2: Facial Liveness
C2_facial_liveness/src/__init__.py

Public interface for the C2 facial liveness component.
Provides run_liveness_check() called by main.py and break_manager.py.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def run_liveness_check(
    user_id: str = "UNKNOWN",
    timeout_sec: float = 30.0,
    show_window: bool = False,
) -> bool:
    """
    Run a quick liveness check using the camera.

    This is called:
      - After login password + MFA pass (in app/login.py Step 3)
      - After a break ends (in break_manager.py resume_monitoring)

    Parameters
    ----------
    user_id:
        Employee ID for logging purposes.
    timeout_sec:
        Maximum seconds to wait for liveness confirmation.
    show_window:
        If True, show a preview window (used in non-login contexts).

    Returns
    -------
    bool
        True if liveness is confirmed, False otherwise.
    """
    try:
        import cv2
        import numpy as np
        from C2_facial_liveness.src.liveness_detector import LivenessDetector

        detector = LivenessDetector()
        if not detector.initialize():
            logger.warning("Liveness detector could not initialize — bypassing check.")
            return True  # Fail-open when camera/mediapipe unavailable

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.warning("No webcam for liveness check — bypassing.")
            detector.close()
            return True

        start = __import__("time").time()
        face_frames = 0

        while (__import__("time").time() - start) < timeout_sec:
            ret, frame = cap.read()
            if not ret:
                break
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if detector.process_frame(frame_rgb):
                face_frames += 1

            result = detector.get_result()
            if result.passed:
                break

            # Check periodically
            if __import__("time").time() - start > 5 and face_frames < 5:
                # No face detected at all — bail out
                logger.warning("No face detected during liveness check for %s.", user_id)
                break

        cap.release()
        result = detector.get_result()
        detector.close()

        logger.info(
            "Liveness check for %s: passed=%s score=%.2f blinks=%d",
            user_id, result.passed, result.liveness_score, result.blink_count,
        )
        return result.passed

    except ImportError as exc:
        logger.warning("C2 liveness dependencies missing (%s) — bypassing.", exc)
        return True
    except Exception as exc:
        logger.error("Liveness check error: %s", exc)
        return True  # Fail-open to avoid blocking login


def get_liveness_score(user_id: str = "UNKNOWN", frames_limit: int = 90) -> float:
    """
    Collect liveness score without blocking UI (used in background threads).

    Returns
    -------
    float
        Liveness score 0.0–1.0
    """
    try:
        import cv2
        from C2_facial_liveness.src.liveness_detector import LivenessDetector

        detector = LivenessDetector()
        if not detector.initialize():
            return 1.0

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            detector.close()
            return 1.0

        for _ in range(frames_limit):
            ret, frame = cap.read()
            if not ret:
                break
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detector.process_frame(frame_rgb)

        cap.release()
        result = detector.get_result()
        detector.close()
        return result.liveness_score

    except Exception:
        return 1.0
