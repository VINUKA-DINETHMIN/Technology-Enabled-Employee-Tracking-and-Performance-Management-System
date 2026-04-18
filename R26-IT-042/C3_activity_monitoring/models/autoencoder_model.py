"""
Shallow Autoencoder Anomaly Detection Model
Project: R26-IT-042 — Employee Activity Monitoring System
Component: C3 — Activity Monitoring (R.K. Vinuka Dinethmin — IT22248642)

SECONDARY anomaly detection model.
3-layer network: 19 inputs → 10 bottleneck → 19 outputs.
High reconstruction error = behavioral anomaly.
Catches gradual drift that Isolation Forest misses.
Pure sklearn — no GPU, no PyTorch required.
"""

import os
import pickle
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score
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

MODEL_PATH  = os.path.join(os.path.dirname(__file__), "ae_model.pkl")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "ae_scaler.pkl")

# Reconstruction error threshold — above this = anomaly
"""
Improved scikit-learn Autoencoder using MLPRegressor with deeper architecture and regularization.

This implementation avoids TensorFlow dependency and increases model capacity using scikit-learn
MLPRegressor. It trains on NORMAL rows only and saves model/scaler/threshold similar to the previous version.
"""

import os
import pickle
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score
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

MODEL_PATH = os.path.join(os.path.dirname(__file__), "ae_model.pkl")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "ae_scaler.pkl")
THRESHOLD_PATH = os.path.join(os.path.dirname(__file__), "ae_threshold.pkl")

THRESHOLD_SOFT_WARNING = 50
THRESHOLD_ALERT = 75


class AutoencoderModel:
    """Deeper MLP-based autoencoder using scikit-learn."""

    def __init__(self,
                 hidden_layer_sizes=(64, 32, 16, 32, 64),
                 activation='relu',
                 solver='adam',
                 alpha=1e-4,
                 learning_rate_init=1e-3,
                 max_iter=500,
                 early_stopping=True,
                 validation_fraction=0.1,
                 n_iter_no_change=20):

        self.model = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            activation=activation,
            solver=solver,
            alpha=alpha,  # L2 regularization
            learning_rate_init=learning_rate_init,
            max_iter=max_iter,
            early_stopping=early_stopping,
            validation_fraction=validation_fraction,
            n_iter_no_change=n_iter_no_change,
            random_state=42,
            verbose=False
        )
        self.scaler = StandardScaler()
        self.error_threshold = None
        self.is_trained = False

    def train(self, df: pd.DataFrame):
        normal_df = df[df['label'] == 'normal'].copy()
        print(f"[AE] Training on {len(normal_df):,} normal samples (of {len(df):,} total)")

        X = normal_df[FEATURE_COLS].values.astype(float)
        Xs = self.scaler.fit_transform(X)

        # Fit to reconstruct input
        self.model.fit(Xs, Xs)

        recon = self.model.predict(Xs)
        # Use MAE for reconstruction error (more robust to outliers)
        errors = np.mean(np.abs(Xs - recon), axis=1)

        self.error_threshold = float(np.mean(errors) + 2 * np.std(errors))
        self.is_trained = True

        print(f"[AE] Training complete. Threshold (MAE): {self.error_threshold:.6f}")

    def predict_batch_errors(self, df: pd.DataFrame) -> np.ndarray:
        X = df[FEATURE_COLS].values.astype(float)
        Xs = self.scaler.transform(X)
        recon = self.model.predict(Xs)
        errors = np.mean(np.abs(Xs - recon), axis=1)
        return errors

    def predict_batch_risk(self, df: pd.DataFrame) -> np.ndarray:
        errors = self.predict_batch_errors(df)
        risk = np.clip((errors / self.error_threshold) * 50, 0, 100)
        return np.round(risk, 2)

    def evaluate(self, df: pd.DataFrame) -> dict:
        errors = self.predict_batch_errors(df)
        y_true = np.where(df['label'] == 'normal', 0, 1)
        y_pred = (errors > self.error_threshold).astype(int)

        tp = int(np.sum((y_true == 1) & (y_pred == 1)))
        fp = int(np.sum((y_true == 0) & (y_pred == 1)))
        tn = int(np.sum((y_true == 0) & (y_pred == 0)))
        fn = int(np.sum((y_true == 1) & (y_pred == 0)))

        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
        auc = roc_auc_score(y_true, np.clip((errors / self.error_threshold), 0, 1))

        return {
            'total_samples': len(df),
            'normal_samples': int(np.sum(df['label'] == 'normal')),
            'anomaly_samples': int(np.sum(df['label'] != 'normal')),
            'error_threshold': round(self.error_threshold, 8) if self.error_threshold is not None else None,
            'true_positives': tp,
            'false_positives': fp,
            'true_negatives': tn,
            'false_negatives': fn,
            'true_positive_rate': round(tpr, 4),
            'false_positive_rate': round(fpr, 4),
            'precision': round(precision_score(y_true, y_pred, zero_division=0), 4),
            'recall': round(recall_score(y_true, y_pred, zero_division=0), 4),
            'f1_score': round(f1_score(y_true, y_pred, zero_division=0), 4),
            'auc_roc': round(auc, 4)
        }

    def save(self, model_path=MODEL_PATH, scaler_path=SCALER_PATH, threshold_path=THRESHOLD_PATH):
        with open(model_path, 'wb') as f:
            pickle.dump(self.model, f)
        with open(scaler_path, 'wb') as f:
            pickle.dump(self.scaler, f)
        with open(threshold_path, 'wb') as f:
            pickle.dump(self.error_threshold, f)
        print(f"[AE] Saved model -> {model_path}")

    def load(self, model_path=MODEL_PATH, scaler_path=SCALER_PATH, threshold_path=THRESHOLD_PATH):
        with open(model_path, 'rb') as f:
            self.model = pickle.load(f)
        with open(scaler_path, 'rb') as f:
            self.scaler = pickle.load(f)
        with open(threshold_path, 'rb') as f:
            self.error_threshold = pickle.load(f)
        self.is_trained = True
        print(f"[AE] Loaded model from {model_path}")
