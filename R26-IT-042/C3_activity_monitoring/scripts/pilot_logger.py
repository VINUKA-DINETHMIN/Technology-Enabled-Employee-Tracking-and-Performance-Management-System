"""
Pilot logger — score a CSV with the trained models and save top-N alerts for human review.
Usage:
  python3 scripts/pilot_logger.py --input data/employee_monitoring_dataset.csv --top 50 --out models/pilot_alerts.csv

Outputs a CSV with selected fields and scores for manual labeling.
"""
import argparse
from pathlib import Path
import pickle
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / 'models'
DEFAULT_INPUT = ROOT / 'data' / 'employee_monitoring_dataset.csv'
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
    ae_threshold = None
    try:
        with open(MODELS_DIR / 'ae_threshold.pkl','rb') as f:
            ae_threshold = pickle.load(f)
    except Exception:
        ae_threshold = None
    iso = None
    try:
        with open(MODELS_DIR / 'composite_iso.pkl','rb') as f:
            iso = pickle.load(f)
    except Exception:
        iso = None
    meta = None
    try:
        with open(MODELS_DIR / 'meta_lr.pkl','rb') as f:
            meta = pickle.load(f)
    except Exception:
        meta = None
    return if_model, if_scaler, ae_model, ae_scaler, ae_threshold, iso, meta


def score_df(df, models, weight_if=0.6):
    if_model, if_scaler, ae_model, ae_scaler, ae_threshold, iso, meta = models
    X = df[FEATURE_COLS].values
    X_if = if_scaler.transform(X)
    raw_if = if_model.decision_function(X_if)
    if_risk = np.clip((0.5 - raw_if) * 100, 0, 100) / 100.0

    X_ae = ae_scaler.transform(X)
    rec = ae_model.predict(X_ae)
    ae_err = np.mean((X_ae - rec)**2, axis=1)
    ae_risk = np.clip((ae_err / ae_threshold) * 50, 0, 100) / 100.0 if ae_threshold is not None else (ae_err - ae_err.min())/(ae_err.max()-ae_err.min()+1e-9)

    composite = (if_risk * weight_if) + (ae_risk * (1-weight_if))
    calibrated = iso.transform(composite) if iso is not None else composite
    meta_prob = meta.predict_proba(np.vstack([if_risk, ae_risk]).T)[:,1] if meta is not None else None

    return if_risk, ae_risk, composite, calibrated, meta_prob


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', type=Path, default=DEFAULT_INPUT)
    p.add_argument('--top', '-n', type=int, default=50)
    p.add_argument('--out', '-o', type=Path, default=MODELS_DIR / 'pilot_alerts.csv')
    p.add_argument('--mode', choices=['calibrated','composite','meta'], default='calibrated', help='Which score to sort alerts by')
    p.add_argument('--weight_if', type=float, default=0.6)
    args = p.parse_args()

    if not args.input.exists():
        print('Input file not found:', args.input)
        return

    print('Loading input:', args.input)
    df = pd.read_csv(args.input, parse_dates=['timestamp'])
    models = load_models()
    if_risk, ae_risk, composite, calibrated, meta_prob = score_df(df, models, weight_if=args.weight_if)

    df_out = df.copy()
    df_out['if_risk'] = if_risk
    df_out['ae_risk'] = ae_risk
    df_out['composite_raw'] = composite
    df_out['composite_calibrated'] = calibrated
    if meta_prob is not None:
        df_out['meta_prob'] = meta_prob

    if args.mode == 'meta' and 'meta_prob' in df_out.columns:
        sort_col = 'meta_prob'
    elif args.mode == 'composite':
        sort_col = 'composite_raw'
    else:
        sort_col = 'composite_calibrated'

    df_sorted = df_out.sort_values(sort_col, ascending=False).reset_index(drop=True)

    topn = df_sorted.head(args.top)
    # select helpful columns for human review
    cols = ['timestamp','user_id','session_id','location_mode','label', 'if_risk','ae_risk','composite_calibrated']
    if 'meta_prob' in df_sorted.columns:
        cols.append('meta_prob')
    cols = [c for c in cols if c in df_sorted.columns]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    topn.to_csv(args.out, index=False)
    print(f'Saved top {args.top} alerts to', args.out)
    print('\nSample (top 5):')
    print(topn[cols].head(5).to_string(index=False))

if __name__ == '__main__':
    main()
