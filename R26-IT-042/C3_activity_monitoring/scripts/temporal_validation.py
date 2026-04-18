"""
Temporal validation script
- Splits by timestamp using a split date (default: median timestamp)
- Loads saved models from ../models/
- Scores IF, AE, and ensemble/meta
- Generates precision@FPR table and recommended thresholds
"""
import os, sys, pickle
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
DATA_PATH = ROOT / "data" / "employee_monitoring_dataset.csv"

FEATURE_COLS = [
    'mean_dwell_time', 'std_dwell_time', 'mean_flight_time',
    'typing_speed_wpm', 'error_rate',
    'mean_velocity', 'std_velocity', 'mean_acceleration',
    'mean_curvature', 'click_frequency', 'idle_ratio',
    'app_switch_frequency', 'active_app_entropy', 'total_focus_duration',
    'session_duration_min', 'geolocation_deviation',
    'wifi_ssid_match', 'device_fingerprint_match', 'face_liveness_score'
]

def load_models():
    with open(MODELS_DIR / 'if_model.pkl','rb') as f:
        if_model = pickle.load(f)
    with open(MODELS_DIR / 'if_scaler.pkl','rb') as f:
        if_scaler = pickle.load(f)
    with open(MODELS_DIR / 'ae_model.pkl','rb') as f:
        ae_model = pickle.load(f)
    with open(MODELS_DIR / 'ae_scaler.pkl','rb') as f:
        ae_scaler = pickle.load(f)
    with open(MODELS_DIR / 'ae_threshold.pkl','rb') as f:
        ae_threshold = pickle.load(f)
    meta = None
    try:
        with open(MODELS_DIR / 'meta_lr.pkl','rb') as f:
            meta = pickle.load(f)
    except Exception:
        meta = None
    return if_model, if_scaler, ae_model, ae_scaler, ae_threshold, meta


def score_models(df, if_model, if_scaler, ae_model, ae_scaler, ae_threshold, meta=None, weight_if=0.6):
    X = df[FEATURE_COLS].values
    X_if = if_scaler.transform(X)
    if_raw = if_model.decision_function(X_if)
    if_risk = np.clip((0.5 - if_raw) * 100, 0, 100) / 100.0

    X_ae = ae_scaler.transform(X)
    ae_rec = ae_model.predict(X_ae)
    ae_err = np.mean((X_ae - ae_rec)**2, axis=1)
    ae_risk = np.clip((ae_err / ae_threshold) * 50, 0, 100) / 100.0

    if meta is not None:
        # meta may be a sklearn logistic regression expecting [[if_score, ae_score]]
        meta_prob = meta.predict_proba(np.vstack([if_risk, ae_risk]).T)[:,1]
    else:
        meta_prob = None

    composite = (if_risk * weight_if) + (ae_risk * (1-weight_if))
    return if_risk, ae_risk, composite, meta_prob


def precision_at_fprs(y_true, scores, fpr_targets=(0.01,0.02,0.05,0.1)):
    # Compute thresholds for target FPRs and report precision
    from sklearn.metrics import roc_curve
    fpr, tpr, thr = roc_curve(y_true, scores)
    out = {}
    for target in fpr_targets:
        idx = np.where(fpr <= target)[0]
        if len(idx)==0:
            out[target] = {'threshold': None, 'precision': None}
        else:
            t = thr[idx[-1]]
            preds = (scores >= t).astype(int)
            tp = int(((y_true==1) & (preds==1)).sum())
            fp = int(((y_true==0) & (preds==1)).sum())
            precision = tp / (tp+fp) if (tp+fp)>0 else None
            out[target] = {'threshold': float(t), 'precision': precision}
    return out


def main(split_date=None):
    print('Loading dataset:', DATA_PATH)
    df = pd.read_csv(DATA_PATH, parse_dates=['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    if split_date is None:
        split_date = df['timestamp'].median()
    print('Using temporal split date:', split_date)
    train = df[df['timestamp'] <= split_date]
    test  = df[df['timestamp'] >  split_date]
    print(f"Train rows: {len(train):,}, Test rows: {len(test):,}")

    if_model, if_scaler, ae_model, ae_scaler, ae_threshold, meta = load_models()

    # Score on both train (for calibration / meta retrain) and test
    y_train = np.where(train['label']=='normal', 0, 1)
    y_test  = np.where(test['label']=='normal', 0, 1)

    if_risk_tr, ae_risk_tr, composite_tr, meta_prob_tr = score_models(train, if_model, if_scaler, ae_model, ae_scaler, ae_threshold, meta)
    if_risk_te, ae_risk_te, composite_te, meta_prob_te = score_models(test,  if_model, if_scaler, ae_model, ae_scaler, ae_threshold, meta)

    print('\nBaseline Precision@FPR for IF:')
    print(precision_at_fprs(y_test, if_risk_te))
    print('\nBaseline Precision@FPR for AE:')
    print(precision_at_fprs(y_test, ae_risk_te))
    print('\nBaseline Precision@FPR for Composite (weight_if=0.6):')
    print(precision_at_fprs(y_test, composite_te))
    if meta_prob_te is not None:
        print('\nBaseline Precision@FPR for Meta classifier:')
        print(precision_at_fprs(y_test, meta_prob_te))

    # --- Calibration on composite using train fold ---
    try:
        print('\nFitting isotonic calibration on composite (train)')
        iso = IsotonicRegression(out_of_bounds='clip')
        iso.fit(composite_tr, y_train)
        calibrated_te = iso.transform(composite_te)
        # persist calibrator
        with open(MODELS_DIR / 'composite_iso.pkl','wb') as f:
            pickle.dump(iso, f)
        print('Saved isotonic calibrator to', MODELS_DIR / 'composite_iso.pkl')
        print('\nPrecision@FPR for Calibrated Composite:')
        print(precision_at_fprs(y_test, calibrated_te))
    except Exception as e:
        print('Calibration failed:', e)
        calibrated_te = composite_te

    # --- Retrain meta classifier (stacking) on train fold using IF & AE scores ---
    try:
        print('\nRetraining meta LogisticRegression on IF+AE scores (train)')
        X_meta_tr = np.vstack([if_risk_tr, ae_risk_tr]).T
        X_meta_te = np.vstack([if_risk_te, ae_risk_te]).T
        meta_new = LogisticRegression(max_iter=2000)
        meta_new.fit(X_meta_tr, y_train)
        # Save retrained meta
        with open(MODELS_DIR / 'meta_lr.pkl', 'wb') as f:
            pickle.dump(meta_new, f)
        meta_prob_te_new = meta_new.predict_proba(X_meta_te)[:,1]
        print('\nPrecision@FPR for Retrained Meta classifier:')
        print(precision_at_fprs(y_test, meta_prob_te_new))
    except Exception as e:
        print('Meta retrain failed:', e)
        meta_prob_te_new = meta_prob_te

    # Recommend thresholds for calibrated composite and retrained meta at FPR <= 0.05
    rec_cal = precision_at_fprs(y_test, calibrated_te, fpr_targets=(0.05,0.02,0.01))
    rec_meta = precision_at_fprs(y_test, meta_prob_te_new, fpr_targets=(0.05,0.02,0.01))
    print('\nRecommended thresholds (Calibrated Composite):')
    print(rec_cal)
    print('\nRecommended thresholds (Retrained Meta):')
    print(rec_meta)

if __name__ == '__main__':
    main()
