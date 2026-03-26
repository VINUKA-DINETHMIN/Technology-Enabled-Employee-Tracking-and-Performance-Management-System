"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/models/dataset_handler.py

Loads and preprocesses the employee monitoring dataset CSV for
training the IsolationForest anomaly model.

Expected CSV columns (from employee_monitoring_dataset.csv)
────────────────────────────────────────────────────────────
  user_id, session_id, keystrokes_per_min, wpm, mouse_velocity,
  click_rate, scroll_rate, idle_ratio, app_switches, label (optional)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "employee_monitoring_dataset.csv"

FEATURE_COLUMNS = [
    "keystrokes_per_min",
    "wpm",
    "mouse_velocity",
    "click_rate",
    "scroll_rate",
    "idle_ratio",
    "app_switches",
]


class DatasetHandler:
    """
    Loads and preprocesses the monitoring dataset for model training.

    Usage
    ─────
    >>> dh = DatasetHandler()
    >>> X, y = dh.load()
    >>> X_scaled = dh.scale(X)
    """

    def __init__(self, csv_path: Optional[Path] = None) -> None:
        self._path = csv_path or _DATA_FILE
        self._scaler = None

    def load(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Load the dataset and return (X, y).

        Returns
        -------
        X: np.ndarray — shape (n_samples, n_features)
        y: np.ndarray | None — labels if 'label' column present
        """
        if not self._path.exists():
            logger.error("Dataset not found: %s", self._path)
            raise FileNotFoundError(f"Dataset not found: {self._path}")

        df = pd.read_csv(self._path)
        missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Dataset missing columns: {missing}")

        X = df[FEATURE_COLUMNS].fillna(0).values.astype(np.float32)
        y = df["label"].values if "label" in df.columns else None
        logger.info("Dataset loaded: %d samples, %d features.", *X.shape)
        return X, y

    def scale(self, X: np.ndarray, fit: bool = True) -> np.ndarray:
        """
        Standard-scale *X*.  Fits the scaler if *fit* is True.
        Call with fit=False to transform test data using a fitted scaler.
        """
        from sklearn.preprocessing import StandardScaler

        if fit or self._scaler is None:
            self._scaler = StandardScaler()
            return self._scaler.fit_transform(X)
        return self._scaler.transform(X)

    def save_scaler(self, path: Path) -> None:
        """Persist the fitted scaler to disk."""
        import pickle
        if self._scaler is None:
            raise RuntimeError("Scaler has not been fitted yet.")
        with open(path, "wb") as f:
            pickle.dump(self._scaler, f)
        logger.info("Scaler saved to %s", path)
