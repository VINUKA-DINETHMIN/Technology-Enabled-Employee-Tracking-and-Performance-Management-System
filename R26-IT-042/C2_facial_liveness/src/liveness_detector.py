"""
R26-IT-042 — Employee Activity Monitoring System
C2_facial_liveness/src/liveness_detector.py

LivenessDetector — OpenCV + MediaPipe face mesh liveness detection.
Detects:
  • Eye blink (EAR — Eye Aspect Ratio < threshold)
  • Head movement (nose landmark shifts between frames)

Used by:
  - app/login.py  → Step 3 face verification
  - break_manager.py → post-break return check
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Eye Aspect Ratio threshold for blink detection
_EAR_THRESHOLD = 0.21
# Minimum head movement (normalized units) for movement detection
_HEAD_MOVE_THRESHOLD = 0.015
# How many frames to collect for analysis
_ANALYSIS_FRAMES = 60
# Minimum blinks required to pass
_MIN_BLINKS = 1


def _eye_aspect_ratio(landmarks, eye_indices: list[int]) -> float:
    """Compute EAR from 6 eye landmark points."""
    pts = [np.array([landmarks[i].x, landmarks[i].y]) for i in eye_indices]
    # Vertical distances
    v1 = np.linalg.norm(pts[1] - pts[5])
    v2 = np.linalg.norm(pts[2] - pts[4])
    # Horizontal distance
    h = np.linalg.norm(pts[0] - pts[3])
    if h < 1e-6:
        return 0.0
    return (v1 + v2) / (2.0 * h)


# MediaPipe face mesh landmark indices for eyes
_LEFT_EYE  = [362, 385, 387, 263, 373, 380]
_RIGHT_EYE = [33,  160, 158, 133, 153, 144]
# Nose tip index for head movement
_NOSE_TIP = 4


class LivenessDetector:
    """
    Frame-by-frame liveness analysis using MediaPipe Face Mesh.

    Usage
    ─────
    >>> detector = LivenessDetector()
    >>> detector.process_frame(frame_rgb)
    >>> result = detector.get_result()
    >>> print(result.passed, result.blink_count, result.liveness_score)
    """

    def __init__(
        self,
        ear_threshold: float = _EAR_THRESHOLD,
        min_blinks: int = _MIN_BLINKS,
        head_move_threshold: float = _HEAD_MOVE_THRESHOLD,
    ) -> None:
        self._ear_threshold = ear_threshold
        self._min_blinks = min_blinks
        self._head_move_threshold = head_move_threshold

        self._blink_count = 0
        self._prev_ear: Optional[float] = None
        self._below_threshold = False
        self._head_positions: list[tuple[float, float]] = []
        self._frame_count = 0
        self._face_mesh = None
        self._initialized = False

    def initialize(self) -> bool:
        """Load MediaPipe Face Mesh. Returns True on success."""
        try:
            import mediapipe as mp
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._initialized = True
            logger.info("LivenessDetector initialized (MediaPipe FaceMesh).")
            return True
        except ImportError:
            logger.warning("mediapipe not installed — liveness detection disabled.")
            return False
        except Exception as exc:
            logger.error("LivenessDetector init error: %s", exc)
            return False

    def process_frame(self, frame_rgb: np.ndarray) -> bool:
        """
        Process one RGB video frame.

        Parameters
        ----------
        frame_rgb:
            numpy array of shape (H, W, 3) in RGB format.

        Returns
        -------
        bool
            True if a face was detected in this frame.
        """
        if not self._initialized or self._face_mesh is None:
            return False

        self._frame_count += 1
        try:
            import mediapipe as mp
            results = self._face_mesh.process(frame_rgb)
            if not results.multi_face_landmarks:
                return False

            lm = results.multi_face_landmarks[0].landmark

            # ── Blink detection ────────────────────────────────────────
            left_ear  = _eye_aspect_ratio(lm, _LEFT_EYE)
            right_ear = _eye_aspect_ratio(lm, _RIGHT_EYE)
            avg_ear   = (left_ear + right_ear) / 2.0

            if avg_ear < self._ear_threshold:
                self._below_threshold = True
            elif self._below_threshold:
                self._blink_count += 1
                self._below_threshold = False

            # ── Head movement ─────────────────────────────────────────
            nose = lm[_NOSE_TIP]
            self._head_positions.append((nose.x, nose.y))
            if len(self._head_positions) > _ANALYSIS_FRAMES:
                self._head_positions.pop(0)

            return True
        except Exception as exc:
            logger.debug("Frame processing error: %s", exc)
            return False

    def get_result(self) -> "LivenessResult":
        """
        Compute final liveness result from collected frames.

        Returns
        -------
        LivenessResult
        """
        # Head movement: range of nose positions
        head_moved = False
        if len(self._head_positions) >= 10:
            xs = [p[0] for p in self._head_positions]
            ys = [p[1] for p in self._head_positions]
            head_range = max(max(xs) - min(xs), max(ys) - min(ys))
            head_moved = head_range >= self._head_move_threshold

        blink_ok = self._blink_count >= self._min_blinks

        # Liveness score 0–1
        blink_score = min(self._blink_count / self._min_blinks, 1.0) * 0.6
        head_score  = 0.4 if head_moved else 0.0
        score       = round(blink_score + head_score, 3)

        passed = blink_ok and score >= 0.6

        return LivenessResult(
            passed=passed,
            blink_count=self._blink_count,
            head_moved=head_moved,
            liveness_score=score,
            frame_count=self._frame_count,
        )

    def reset(self) -> None:
        """Reset all counters for a new session."""
        self._blink_count = 0
        self._prev_ear = None
        self._below_threshold = False
        self._head_positions = []
        self._frame_count = 0

    def close(self) -> None:
        """Release MediaPipe resources."""
        if self._face_mesh is not None:
            try:
                self._face_mesh.close()
            except Exception:
                pass
        self._initialized = False


class LivenessResult:
    """Result container for a liveness check."""

    def __init__(
        self,
        passed: bool,
        blink_count: int,
        head_moved: bool,
        liveness_score: float,
        frame_count: int,
    ) -> None:
        self.passed = passed
        self.blink_count = blink_count
        self.head_moved = head_moved
        self.liveness_score = liveness_score
        self.frame_count = frame_count

    def __repr__(self) -> str:
        return (
            f"<LivenessResult passed={self.passed} "
            f"blinks={self.blink_count} "
            f"head_moved={self.head_moved} "
            f"score={self.liveness_score:.2f}>"
        )
