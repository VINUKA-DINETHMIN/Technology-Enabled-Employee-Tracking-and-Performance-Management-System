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
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from dataset_handler import DatasetHandler, FEATURE_COLUMNS


MODELS_DIR = Path(__file__).resolve().parent
MODEL_PATH = MODELS_DIR / "user_behavioral_model.pkl"
SCALER_PATH = MODELS_DIR / "feature_scaler.pkl"
AE_MODEL_PATH = MODELS_DIR / "ae_model.pkl"
AE_SCALER_PATH = MODELS_DIR / "ae_scaler.pkl"
AE_THRESHOLD_PATH = MODELS_DIR / "ae_threshold.pkl"
ENSEMBLE_CONFIG_PATH = MODELS_DIR / "ensemble_config.json"


def _train_autoencoder(df: pd.DataFrame) -> dict:
    """Train the secondary autoencoder model on normal rows only."""
    normal_df = df[df["label"] == "normal"].copy()
    if len(normal_df) < 100:
        raise RuntimeError("Not enough normal samples to train a stable autoencoder.")

    scaler = StandardScaler()
    x_normal = normal_df[FEATURE_COLUMNS].values.astype(float)
    x_scaled = scaler.fit_transform(x_normal)

    model = MLPRegressor(
        hidden_layer_sizes=(64, 32, 16, 32, 64),
        activation="relu",
        solver="adam",
        alpha=1e-4,
        learning_rate_init=1e-3,
        max_iter=500,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=20,
        random_state=42,
        verbose=False,
    )
    model.fit(x_scaled, x_scaled)

    recon = model.predict(x_scaled)
    errors = np.mean(np.abs(x_scaled - recon), axis=1)
    threshold = float(np.mean(errors) + 2 * np.std(errors))

    with open(AE_MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    with open(AE_SCALER_PATH, "wb") as f:
        pickle.dump(scaler, f)
    with open(AE_THRESHOLD_PATH, "wb") as f:
        pickle.dump(threshold, f)

    # Optional holdout report using the same validation split as IF.
    return {
        "samples": len(normal_df),
        "threshold": threshold,
    }


def _binary_labels(y: np.ndarray) -> np.ndarray:
    """Map labels to 0 (normal) / 1 (anomaly)."""
    return np.where(y == "normal", 0, 1)


def _ae_risk_from_errors(errors: np.ndarray, threshold: float) -> np.ndarray:
    if threshold <= 0:
        return np.clip(errors * 100.0, 0.0, 100.0)
    return np.clip((errors / threshold) * 50.0, 0.0, 100.0)


def _tune_ensemble(
    if_model,
    if_scaler,
    ae_model,
    ae_scaler,
    ae_threshold: float,
    x_val: np.ndarray,
    y_val: np.ndarray,
) -> dict:
    """Grid search the IF/AE blend on a labeled validation set."""
    if_scores = np.clip((0.5 - if_model.decision_function(if_scaler.transform(x_val))) * 100.0, 0.0, 100.0)
    x_ae = ae_scaler.transform(x_val)
    recon = ae_model.predict(x_ae)
    ae_errors = np.mean(np.abs(x_ae - recon), axis=1)
    ae_scores = _ae_risk_from_errors(ae_errors, ae_threshold)

    y_true = _binary_labels(y_val)

    best = {
        "weight": 0.6,
        "threshold": 50.0,
        "f1": -1.0,
        "auc": -1.0,
        "tpr": -1.0,
        "fpr": 1.0,
        "precision": 0.0,
        "recall": 0.0,
    }

    for weight in np.linspace(0.0, 1.0, 11):
        ensemble = (weight * if_scores) + ((1.0 - weight) * ae_scores)
        for threshold in np.arange(35.0, 81.0, 2.5):
            y_pred = (ensemble >= threshold).astype(int)
            tp = int(np.sum((y_true == 1) & (y_pred == 1)))
            fp = int(np.sum((y_true == 0) & (y_pred == 1)))
            tn = int(np.sum((y_true == 0) & (y_pred == 0)))
            fn = int(np.sum((y_true == 1) & (y_pred == 0)))

            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tpr
            f1 = f1_score(y_true, y_pred, zero_division=0)
            auc = roc_auc_score(y_true, ensemble / 100.0)

            # Prefer higher F1, then higher TPR, then lower FPR, then higher AUC.
            candidate = (f1, tpr, -fpr, auc)
            best_score = (best["f1"], best["tpr"], -best["fpr"], best["auc"])
            if candidate > best_score:
                best.update({
                    "weight": round(float(weight), 2),
                    "threshold": round(float(threshold), 2),
                    "f1": round(float(f1), 4),
                    "auc": round(float(auc), 4),
                    "tpr": round(float(tpr), 4),
                    "fpr": round(float(fpr), 4),
                    "precision": round(float(precision), 4),
                    "recall": round(float(recall), 4),
                })

    return best


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

    ae_info = _train_autoencoder(pd.DataFrame(X, columns=FEATURE_COLUMNS).assign(label=y))

    # Tune ensemble on a validation split using the trained IF and AE models.
    X_tune_train, X_val, y_tune_train, y_val = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=7,
        stratify=y,
    )
    with open(AE_MODEL_PATH, "rb") as f:
        ae_model = pickle.load(f)
    with open(AE_SCALER_PATH, "rb") as f:
        ae_scaler = pickle.load(f)
    with open(AE_THRESHOLD_PATH, "rb") as f:
        ae_threshold = pickle.load(f)

    ensemble_cfg = _tune_ensemble(
        model,
        dh._scaler,
        ae_model,
        ae_scaler,
        float(ae_threshold),
        X_val,
        y_val,
    )

    with open(ENSEMBLE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(ensemble_cfg, f, indent=2)

    print("[OK] IsolationForest training complete")
    print(f"[OK] Features used: {len(FEATURE_COLUMNS)}")
    print(f"[OK] Model saved:  {MODEL_PATH}")
    print(f"[OK] Scaler saved: {SCALER_PATH}")
    print(f"[OK] Autoencoder saved: {AE_MODEL_PATH}")
    print(f"[OK] AE scaler saved: {AE_SCALER_PATH}")
    print(f"[OK] AE threshold saved: {AE_THRESHOLD_PATH}")
    print(f"[OK] Ensemble config saved: {ENSEMBLE_CONFIG_PATH}")
    print(f"[INFO] Best ensemble weight (IF): {ensemble_cfg['weight']:.2f}")
    print(f"[INFO] Best ensemble threshold: {ensemble_cfg['threshold']:.2f}")
    print(f"[INFO] Ensemble validation F1: {ensemble_cfg['f1']:.4f}")
    print(f"[INFO] Ensemble validation AUC: {ensemble_cfg['auc']:.4f}")
    print(f"[INFO] AE threshold: {ae_info['threshold']:.6f}")
    print(f"[INFO] Holdout AUC: {auc:.4f}")


if __name__ == "__main__":
    main()
