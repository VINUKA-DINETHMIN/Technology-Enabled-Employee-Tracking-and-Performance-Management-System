"""
Shallow Autoencoder training for C3 runtime.

Trains on normal behavior data only and exports:
  - ae_model.pkl
  - ae_scaler.pkl
  - ae_threshold.pkl

This is used by the runtime anomaly engine as the secondary model in the
combined IsolationForest + Autoencoder ensemble.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from dataset_handler import DatasetHandler, FEATURE_COLUMNS


MODELS_DIR = Path(__file__).resolve().parent
MODEL_PATH = MODELS_DIR / "ae_model.pkl"
SCALER_PATH = MODELS_DIR / "ae_scaler.pkl"
THRESHOLD_PATH = MODELS_DIR / "ae_threshold.pkl"


class AutoencoderModel:
    """Compact sklearn-based autoencoder for anomaly reconstruction."""

    def __init__(
        self,
        hidden_layer_sizes=(64, 32, 16, 32, 64),
        activation: str = "relu",
        solver: str = "adam",
        alpha: float = 1e-4,
        learning_rate_init: float = 1e-3,
        max_iter: int = 500,
        early_stopping: bool = True,
        validation_fraction: float = 0.1,
        n_iter_no_change: int = 20,
    ) -> None:
        self.model = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            activation=activation,
            solver=solver,
            alpha=alpha,
            learning_rate_init=learning_rate_init,
            max_iter=max_iter,
            early_stopping=early_stopping,
            validation_fraction=validation_fraction,
            n_iter_no_change=n_iter_no_change,
            random_state=42,
            verbose=False,
        )
        self.scaler = StandardScaler()
        self.error_threshold: float | None = None
        self.is_trained = False

    def train(self, df) -> None:
        normal_df = df[df["label"] == "normal"].copy()
        print(f"[AE] Training on {len(normal_df):,} normal samples (of {len(df):,} total)")

        x_normal = normal_df[FEATURE_COLUMNS].values.astype(float)
        x_scaled = self.scaler.fit_transform(x_normal)

        self.model.fit(x_scaled, x_scaled)

        recon = self.model.predict(x_scaled)
        errors = np.mean(np.abs(x_scaled - recon), axis=1)
        self.error_threshold = float(np.mean(errors) + 2 * np.std(errors))
        self.is_trained = True

        print(f"[AE] Training complete. Threshold (MAE): {self.error_threshold:.6f}")

    def predict_batch_errors(self, df) -> np.ndarray:
        x = df[FEATURE_COLUMNS].values.astype(float)
        x_scaled = self.scaler.transform(x)
        recon = self.model.predict(x_scaled)
        return np.mean(np.abs(x_scaled - recon), axis=1)

    def predict_batch_risk(self, df) -> np.ndarray:
        if self.error_threshold is None or self.error_threshold <= 0:
            raise RuntimeError("Autoencoder threshold not available. Train first.")
        errors = self.predict_batch_errors(df)
        risk = np.clip((errors / self.error_threshold) * 50.0, 0, 100)
        return np.round(risk, 2)

    def evaluate(self, df) -> dict:
        errors = self.predict_batch_errors(df)
        y_true = np.where(df["label"] == "normal", 0, 1)
        y_pred = (errors > float(self.error_threshold)).astype(int)

        tp = int(np.sum((y_true == 1) & (y_pred == 1)))
        fp = int(np.sum((y_true == 0) & (y_pred == 1)))
        tn = int(np.sum((y_true == 0) & (y_pred == 0)))
        fn = int(np.sum((y_true == 1) & (y_pred == 0)))
        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
        auc = roc_auc_score(y_true, np.clip((errors / float(self.error_threshold)), 0, 1))

        return {
            "total_samples": len(df),
            "normal_samples": int(np.sum(df["label"] == "normal")),
            "anomaly_samples": int(np.sum(df["label"] != "normal")),
            "error_threshold": round(float(self.error_threshold), 8) if self.error_threshold is not None else None,
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "true_positive_rate": round(tpr, 4),
            "false_positive_rate": round(fpr, 4),
            "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
            "f1_score": round(f1_score(y_true, y_pred, zero_division=0), 4),
            "auc_roc": round(auc, 4),
        }

    def save(self, model_path=MODEL_PATH, scaler_path=SCALER_PATH, threshold_path=THRESHOLD_PATH):
        with open(model_path, "wb") as f:
            pickle.dump(self.model, f)
        with open(scaler_path, "wb") as f:
            pickle.dump(self.scaler, f)
        with open(threshold_path, "wb") as f:
            pickle.dump(self.error_threshold, f)
        print(f"[AE] Saved model -> {model_path}")

    def load(self, model_path=MODEL_PATH, scaler_path=SCALER_PATH, threshold_path=THRESHOLD_PATH):
        with open(model_path, "rb") as f:
            self.model = pickle.load(f)
        with open(scaler_path, "rb") as f:
            self.scaler = pickle.load(f)
        with open(threshold_path, "rb") as f:
            self.error_threshold = pickle.load(f)
        self.is_trained = True
        print(f"[AE] Loaded model from {model_path}")


def main() -> None:
    dh = DatasetHandler()
    x, y = dh.load()

    if y is None:
        raise RuntimeError("Dataset must include 'label' column for autoencoder training.")

    if np.sum(y == "normal") < 100:
        raise RuntimeError("Not enough normal samples to train a stable autoencoder.")

    df = pd.read_csv(dh._path)

    ae = AutoencoderModel()
    ae.train(df)

    # Holdout evaluation for reporting only.
    _, test_df = train_test_split(df, test_size=0.2, random_state=42, stratify=df["label"])
    metrics = ae.evaluate(test_df)

    ae.save()
    print("[AE] Training complete")
    print(f"[OK] Features used: {len(FEATURE_COLUMNS)}")
    print(f"[INFO] Holdout AUC: {metrics['auc_roc']:.4f}")


if __name__ == "__main__":
    main()