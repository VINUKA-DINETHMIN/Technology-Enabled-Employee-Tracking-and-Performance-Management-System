"""
Train and export IsolationForest model for C3 runtime.

Outputs (used directly by C3_activity_monitoring/src/anomaly_engine.py):
  - user_behavioral_model.pkl
  - feature_scaler.pkl

Run:
  python C3_activity_monitoring/models/train_isolation_forest.py
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from dataset_handler import DatasetHandler, FEATURE_COLUMNS


MODELS_DIR = Path(__file__).resolve().parent
MODEL_PATH = MODELS_DIR / "user_behavioral_model.pkl"
SCALER_PATH = MODELS_DIR / "feature_scaler.pkl"


def _binary_labels(y: np.ndarray) -> np.ndarray:
    """Map labels to 0 (normal) / 1 (anomaly)."""
    return np.where(y == "normal", 0, 1)


def main() -> None:
    dh = DatasetHandler()
    X, y = dh.load()

    if y is None:
        raise RuntimeError("Dataset must include 'label' column for training/evaluation.")

    # Train only on normal rows (standard IF unsupervised setup).
    normal_mask = (y == "normal")
    X_normal = X[normal_mask]
    if len(X_normal) < 100:
        raise RuntimeError("Not enough normal samples to train a stable model.")

    Xn_scaled = dh.scale(X_normal, fit=True)

    model = IsolationForest(
        contamination=0.05,
        n_estimators=100,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(Xn_scaled)

    # Optional evaluation on holdout split (label-aware, only for reporting).
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )
    Xt = dh.scale(X_test, fit=False)
    raw = model.decision_function(Xt)
    risk = np.clip((0.5 - raw) * 100.0, 0.0, 100.0)
    auc = roc_auc_score(_binary_labels(y_test), risk / 100.0)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    dh.save_scaler(SCALER_PATH)

    print("[OK] IsolationForest training complete")
    print(f"[OK] Features used: {len(FEATURE_COLUMNS)}")
    print(f"[OK] Model saved:  {MODEL_PATH}")
    print(f"[OK] Scaler saved: {SCALER_PATH}")
    print(f"[INFO] Holdout AUC: {auc:.4f}")


if __name__ == "__main__":
    main()
