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
_HEAD_MOVE_THRESHOLD = 0.010
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
        """Load MediaPipe Face Mesh. Returns True on success, else sets up fallback."""
        try:
            # Suppress TensorFlow stderr clutter on systems without AVX
            import os
            import warnings
            os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
            os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
            warnings.filterwarnings(
                "ignore",
                message=r"SymbolDatabase.GetPrototype\(\) is deprecated.*",
                category=UserWarning,
            )
            
            import mediapipe as mp
            if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "face_mesh"):
                raise RuntimeError("This mediapipe build does not expose mp.solutions.face_mesh")
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._initialized = True
            self._fallback_mode = False
            logger.info("LivenessDetector initialized (MediaPipe FaceMesh).")
            return True
        except (ImportError, Exception) as exc:
            # CPU likely lacks AVX or MediaPipe is missing
            self._initialized = True # Mark as initialized for fallback processing
            self._face_mesh = None
            self._fallback_mode = True
            # Fallback state
            self._prev_gray = None
            self._movement_energy = 0.0
            logger.warning(f"MediaPipe error: {exc}. Liveness detector running in FE-Fallback (Movement) mode.")
            return True

    def process_frame(self, frame_rgb: np.ndarray) -> bool:
        if not self._initialized:
            return False

        self._frame_count += 1
        import cv2

        # ── Fallback Movement Detection ──────────────────────────────
        if self._fallback_mode:
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            # Apply Gaussian blur to reduce noise
            gray = cv2.GaussianBlur(gray, (7, 7), 0)
            
            if self._prev_gray is not None:
                div = cv2.absdiff(self._prev_gray, gray)
                # Calculate movement intensity (average change per pixel)
                # High threshold to ignore sensor noise, low enough to catch breathing/eye movements
                _, thresh = cv2.threshold(div, 25, 255, cv2.THRESH_BINARY)
                energy = np.sum(thresh) / (frame_rgb.shape[0] * frame_rgb.shape[1])
                self._movement_energy += energy
            
            self._prev_gray = gray
            return True

        # ── Standard MediaPipe/TensorFlow Detection ─────────────────
        try:
            results = self._face_mesh.process(frame_rgb)
            if not results.multi_face_landmarks:
                return False

            lm = results.multi_face_landmarks[0].landmark

            # Blink detection
            left_ear  = _eye_aspect_ratio(lm, _LEFT_EYE)
            right_ear = _eye_aspect_ratio(lm, _RIGHT_EYE)
            avg_ear   = (left_ear + right_ear) / 2.0

            if avg_ear < self._ear_threshold:
                self._below_threshold = True
            elif self._below_threshold:
                self._blink_count += 1
                self._below_threshold = False

            # Head movement
            nose = lm[_NOSE_TIP]
            self._head_positions.append((nose.x, nose.y))
            if len(self._head_positions) > _ANALYSIS_FRAMES:
                self._head_positions.pop(0)

            return True
        except Exception:
            return False

    def get_result(self) -> "LivenessResult":
        if self._fallback_mode:
            # In fallback mode, "pass" if we detected enough movement frames
            # movement_energy accumulates over time; 3.0 is a conservative threshold
            passed = self._movement_energy >= 3.0 
            return LivenessResult(
                passed=passed,
                blink_count=0,
                head_moved=passed,
                liveness_score=0.7 if passed else 0.0,
                frame_count=self._frame_count,
            )

        # Standard calculation
        head_moved = False
        if len(self._head_positions) >= 10:
            xs = [p[0] for p in self._head_positions]
            ys = [p[1] for p in self._head_positions]
            head_range = max(max(xs) - min(xs), max(ys) - min(ys))
            head_moved = head_range >= self._head_move_threshold

        blink_ok = self._blink_count >= self._min_blinks
        blink_score = min(self._blink_count / self._min_blinks, 1.0) * 0.5
        head_score  = 0.5 if head_moved else 0.0
        score       = round(blink_score + head_score, 3)

        # Accept either a natural blink or clear head movement.
        passed = (blink_ok or head_moved) and score >= 0.45 and self._frame_count >= 12

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
