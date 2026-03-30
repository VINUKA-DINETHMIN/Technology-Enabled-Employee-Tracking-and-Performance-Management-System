"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/anomaly_engine.py

Loads the trained IsolationForest model and scaler from models/ and
scores incoming feature vectors.  Returns a risk_score (0–100).

Model file locations
────────────────────
  C3_activity_monitoring/models/user_behavioral_model.pkl
  C3_activity_monitoring/models/feature_scaler.pkl
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_MODEL_PATH = _MODELS_DIR / "user_behavioral_model.pkl"
_SCALER_PATH = _MODELS_DIR / "feature_scaler.pkl"

# Canonical model feature order used during training and runtime inference.
FEATURE_COLUMNS = [
    "mean_dwell_time",
    "std_dwell_time",
    "mean_flight_time",
    "typing_speed_wpm",
    "error_rate",
    "mean_velocity",
    "std_velocity",
    "mean_acceleration",
    "mean_curvature",
    "click_frequency",
    "idle_ratio",
    "app_switch_frequency",
    "active_app_entropy",
    "total_focus_duration",
    "session_duration_min",
    "geolocation_deviation",
    "wifi_ssid_match",
    "device_fingerprint_match",
    "face_liveness_score",
]


class AnomalyEngine:
    """
    Wraps a trained sklearn IsolationForest to produce risk scores.

    Usage
    ─────
    >>> engine = AnomalyEngine()
    >>> engine.load_model()
    >>> score = engine.score(feature_vector.to_array())
    """

    def __init__(self) -> None:
        self._model = None
        self._scaler = None
        self._model_loaded = False

    def _align_feature_length(self, x: np.ndarray, expected: int) -> np.ndarray:
        """Adapt feature vector length to what the loaded scaler/model expects."""
        current = int(x.shape[1])
        if current == expected:
            return x

        # Backward compatibility path: previous runtime sent 14 features.
        # Map to 19 by appending session/context defaults.
        if current == 14 and expected == 19:
            pad = np.array([[0.0, 0.0, 1.0, 1.0, 0.0]], dtype=np.float32)
            logger.warning(
                "AnomalyEngine received legacy 14-feature input; auto-expanding to 19 features."
            )
            return np.hstack([x.astype(np.float32), pad])

        # Generic fallback: truncate or zero-pad to avoid hard failure.
        logger.warning(
            "AnomalyEngine feature length mismatch (got=%d, expected=%d). Applying fallback alignment.",
            current,
            expected,
        )
        if current > expected:
            return x[:, :expected]
        pad = np.zeros((x.shape[0], expected - current), dtype=np.float32)
        return np.hstack([x.astype(np.float32), pad])

    def load_model(self) -> bool:
        """
        Load model and scaler from disk.

        Returns
        -------
        bool
            True if both files loaded successfully.
        """
        try:
            if _MODEL_PATH.exists():
                with open(_MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                logger.info("IsolationForest model loaded from %s", _MODEL_PATH)
            else:
                logger.warning("Model file not found: %s — anomaly scoring disabled.", _MODEL_PATH)
                return False

            if _SCALER_PATH.exists():
                with open(_SCALER_PATH, "rb") as f:
                    self._scaler = pickle.load(f)
                logger.info("Feature scaler loaded from %s", _SCALER_PATH)

            self._model_loaded = True
            return True

        except Exception as exc:
            logger.error("Failed to load anomaly model: %s", exc)
            return False

    def score(self, features: np.ndarray) -> float:
        """
        Compute a risk score (0–100) from a feature vector.

        The IsolationForest returns -1 for anomalies, +1 for normal.
        We convert its raw decision function to a 0–100 scale where
        higher = more anomalous.

        Parameters
        ----------
        features:
            1-D numpy array from FeatureVector.to_array().

        Returns
        -------
        float
            Risk score in range [0, 100].
        """
        if not self._model_loaded or self._model is None:
            # Without a model, return 0 (no risk assumed)
            return 0.0

        try:
            x = features.reshape(1, -1)

            expected_features = None
            if self._scaler is not None:
                expected_features = getattr(self._scaler, "n_features_in_", None)
            if expected_features is None:
                expected_features = getattr(self._model, "n_features_in_", None)
            if expected_features is not None:
                x = self._align_feature_length(x, int(expected_features))

            if self._scaler is not None:
                x = self._scaler.transform(x)

            # decision_function: more negative = more anomalous
            raw_score = self._model.decision_function(x)[0]
            # Map to [0, 100]: raw typically in [-0.5, 0.5]
            risk = max(0.0, min(100.0, (0.5 - raw_score) * 100.0))
            return round(risk, 2)

        except Exception as exc:
            logger.error("Anomaly scoring error: %s", exc)
            return 0.0

    @property
    def is_loaded(self) -> bool:
        return self._model_loaded
