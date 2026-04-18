"""
Anomaly Engine — Composite Scoring (IF + AE)
Project: R26-IT-042 — Employee Activity Monitoring System
Component: C3 — Activity Monitoring (R.K. Vinuka Dinethmin — IT22248642)

Combines Isolation Forest + Autoencoder into one composite risk score.
Called every 60 seconds by feature_extractor.py.
Triggers alert when score >= 75 for 2 consecutive windows.
"""

import os
import pandas as pd
import numpy as np
from isolation_forest_model import IsolationForestModel, FEATURE_COLS
from autoencoder_model import AutoencoderModel

# Weights — IF is primary, AE is secondary
IF_WEIGHT = 0.60
AE_WEIGHT = 0.40

THRESHOLD_SOFT_WARNING  = 50   # log only
THRESHOLD_ALERT         = 75   # trigger alert + screenshot
CONSECUTIVE_ALERT_COUNT = 2    # must exceed threshold twice before alerting


class AnomalyEngine:
    """
    Composite anomaly detection engine.
    Combines Isolation Forest (primary) + Autoencoder (secondary).
    Maintains consecutive window counter to reduce false positives.
    """

    def __init__(self):
        self.if_model       = IsolationForestModel()
        self.ae_model       = AutoencoderModel()
        self.high_risk_count = 0  # consecutive high-risk windows

    def load_models(self) -> None:
        """Load pre-trained models from disk."""
        self.if_model.load()
        self.ae_model.load()
        print("[Engine] Both models loaded. Ready for inference.")

    def get_composite_score(self, feature_vector: dict) -> dict:
        """
        Main method called every 60s by feature_extractor.py.
        Returns full anomaly assessment dict.
        """
        if_score = self.if_model.predict_risk_score(feature_vector)
        ae_score = self.ae_model.predict_risk_score(feature_vector)

        # Weighted composite score
        composite = round((if_score * IF_WEIGHT) + (ae_score * AE_WEIGHT), 2)

        # Consecutive window tracking
        if composite >= THRESHOLD_ALERT:
            self.high_risk_count += 1
        else:
            self.high_risk_count = 0  # reset on any normal window

        # Alert only after 2 consecutive high-risk windows (120 seconds)
        alert_triggered = self.high_risk_count >= CONSECUTIVE_ALERT_COUNT

        # Determine label
        if composite >= THRESHOLD_ALERT:
            label = 'high_risk_anomaly'
        elif composite >= THRESHOLD_SOFT_WARNING:
            label = 'low_risk_anomaly'
        else:
            label = 'normal'

        return {
            'if_score'          : if_score,
            'ae_score'          : ae_score,
            'composite_score'   : composite,
            'label'             : label,
            'alert_triggered'   : alert_triggered,
            'consecutive_count' : self.high_risk_count,
        }
