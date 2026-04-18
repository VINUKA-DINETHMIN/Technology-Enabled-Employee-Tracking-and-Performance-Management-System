"""
Isolation Forest Anomaly Detection Model
Project: R26-IT-042 — Employee Activity Monitoring System
Component: C3 — Activity Monitoring (R.K. Vinuka Dinethmin — IT22248642)

PRIMARY anomaly detection model.
Trains ONLY on normal behavior data.
Detects outliers in 19-dimensional behavioral feature space.
Runs every 60 seconds on employee PC — lightweight, no GPU needed.
"""

import os
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score, recall_score
)
from sklearn.model_selection import train_test_split
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

FEATURE_COLS = [
    'mean_dwell_time', 'std_dwell_time', 'mean_flight_time',
    'typing_speed_wpm', 'error_rate',
    'mean_velocity', 'std_velocity', 'mean_acceleration',
    'mean_curvature', 'click_frequency', 'idle_ratio',
    'app_switch_frequency', 'active_app_entropy', 'total_focus_duration',
    'session_duration_min', 'geolocation_deviation',
    'wifi_ssid_match', 'device_fingerprint_match', 'face_liveness_score'
]

MODEL_PATH  = os.path.join(os.path.dirname(__file__), "if_model.pkl")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "if_scaler.pkl")

THRESHOLD_SOFT_WARNING = 50
THRESHOLD_ALERT        = 75


# ─────────────────────────────────────────────
# ISOLATION FOREST WRAPPER
# ─────────────────────────────────────────────

class IsolationForestModel:
    """
    PRIMARY anomaly detection model for C3_activity_monitoring.
    Trains on normal-only data. Detects behavioral outliers.
    Risk score 0-100: <50 normal, 50-74 soft warning, >=75 ALERT.
    """

    def __init__(self, contamination: float = 0.05, n_estimators: int = 100):
        self.contamination = contamination
        self.n_estimators  = n_estimators
        self.model  = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            random_state=42,
            n_jobs=-1
        )
        self.scaler    = StandardScaler()
        self.is_trained = False

    # ── TRAINING ─────────────────────────────

    def train(self, df: pd.DataFrame) -> None:
        """Train ONLY on normal rows from the dataset."""
        normal_df = df[df['label'] == 'normal'].copy()
        print(f"[IF] Training on {len(normal_df):,} normal samples (of {len(df):,} total)")
        X_normal = normal_df[FEATURE_COLS].values
        X_scaled = self.scaler.fit_transform(X_normal)
        self.model.fit(X_scaled)
        self.is_trained = True
        print("[IF] Training complete.")

    # ── REAL-TIME INFERENCE ───────────────────

    def predict_risk_score(self, feature_vector: dict) -> float:
        """
        Called every 60s by anomaly_engine.py.
        Takes one feature vector dict → returns risk score 0-100.
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call train() or load() first.")
        X = np.array([[feature_vector[col] for col in FEATURE_COLS]])
        X_scaled = self.scaler.transform(X)
        raw_score = self.model.decision_function(X_scaled)[0]
        risk = float(np.clip((0.5 - raw_score) * 100, 0, 100))
        return round(risk, 2)

    def predict_label(self, feature_vector: dict) -> str:
        """Returns 'normal', 'low_risk_anomaly', or 'high_risk_anomaly'."""
        score = self.predict_risk_score(feature_vector)
        if score >= THRESHOLD_ALERT:
            return 'high_risk_anomaly'
        elif score >= THRESHOLD_SOFT_WARNING:
            return 'low_risk_anomaly'
        return 'normal'

    def predict_batch(self, df: pd.DataFrame) -> np.ndarray:
        """Predict risk scores for full DataFrame. Returns array 0-100."""
        X = df[FEATURE_COLS].values
        X_scaled = self.scaler.transform(X)
        raw_scores = self.model.decision_function(X_scaled)
        return np.round(np.clip((0.5 - raw_scores) * 100, 0, 100), 2)

    # ── EVALUATION ───────────────────────────

    def evaluate(self, df: pd.DataFrame) -> dict:
        """
        Full evaluation against labelled test data.
        Returns all metrics from proposal Table 2 (Section 2.2).
        """
        X_scaled = self.scaler.transform(df[FEATURE_COLS].values)
        y_true_01 = np.where(df['label'] == 'normal', 0, 1)  # 1 = anomaly
        y_pred_01 = np.where(self.model.predict(X_scaled) == -1, 1, 0)
        risk_scores = self.predict_batch(df) / 100.0

        tp = int(np.sum((y_true_01 == 1) & (y_pred_01 == 1)))
        fp = int(np.sum((y_true_01 == 0) & (y_pred_01 == 1)))
        tn = int(np.sum((y_true_01 == 0) & (y_pred_01 == 0)))
        fn = int(np.sum((y_true_01 == 1) & (y_pred_01 == 0)))
        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
        auc = roc_auc_score(y_true_01, risk_scores)

        return {
            'total_samples'       : len(df),
            'normal_samples'      : int(np.sum(df['label'] == 'normal')),
            'anomaly_samples'     : int(np.sum(df['label'] != 'normal')),
            'true_positives'      : tp,
            'false_positives'     : fp,
            'true_negatives'      : tn,
            'false_negatives'     : fn,
            'true_positive_rate'  : round(tpr, 4),
            'false_positive_rate' : round(fpr, 4),
            'precision'           : round(precision_score(y_true_01, y_pred_01, zero_division=0), 4),
            'recall'              : round(recall_score(y_true_01, y_pred_01, zero_division=0), 4),
            'f1_score'            : round(f1_score(y_true_01, y_pred_01, zero_division=0), 4),
            'auc_roc'             : round(auc, 4),
            'target_tpr_met'      : tpr >= 0.90,
            'target_fpr_met'      : fpr <= 0.05,
            'target_auc_met'      : auc >= 0.90,
        }

    # ── SAVE / LOAD ───────────────────────────

    def save(self, model_path=MODEL_PATH, scaler_path=SCALER_PATH):
        with open(model_path, 'wb') as f:
            pickle.dump(self.model, f)
        with open(scaler_path, 'wb') as f:
            pickle.dump(self.scaler, f)
        print(f"[IF] Saved → {model_path}")

    def load(self, model_path=MODEL_PATH, scaler_path=SCALER_PATH):
        with open(model_path, 'rb') as f:
            self.model = pickle.load(f)
        with open(scaler_path, 'rb') as f:
            self.scaler = pickle.load(f)
        self.is_trained = True
        print(f"[IF] Loaded from {model_path}")
