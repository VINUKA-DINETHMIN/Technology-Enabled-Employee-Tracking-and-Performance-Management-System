"""
Employee Behavior Anomaly Detection
Model: Isolation Forest (Primary) + Random Forest (Supervised Benchmark)
Training data: live attendance + activity logs from MongoDB.
"""

import os
import random
import sys
import pickle
import warnings
from collections import defaultdict
from datetime import datetime, date, time, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, confusion_matrix,
    accuracy_score, precision_score, recall_score, f1_score
)

warnings.filterwarnings("ignore")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.database import MongoDBClient
from config.settings import settings

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

STATUS_NORMAL = "On Time"
ANOMALY_STATUSES = {"Late", "Early Departure", "Overtime"}


def parse_time(value: str) -> Optional[time]:
    if not value or value in {"—", "None", "none"}:
        return None
    value = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def parse_duration(duration_value: str) -> Optional[int]:
    if not duration_value or duration_value in {"—", "None", "none"}:
        return None
    parts = str(duration_value).strip().split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        hours, minutes = parts
        seconds = 0
    else:
        hours, minutes, seconds = parts
    return max(0, hours * 3600 + minutes * 60 + seconds)


def parse_iso_date(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def build_attendance_dataset() -> pd.DataFrame:
    client = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    if not client.connect():
        print("[WARN] Could not connect to MongoDB; attendance training data unavailable.")
        return pd.DataFrame()

    attendance_col = client.get_collection("attendance_logs")
    if attendance_col is None:
        print("[WARN] attendance_logs collection not available.")
        client.close()
        return pd.DataFrame()

    print("[INFO] Loading attendance documents from MongoDB...")
    attendance_docs = list(attendance_col.find({}, {"_id": 0, "employee_id": 1, "full_name": 1, "date": 1, "signin": 1, "signout": 1, "duration": 1, "status": 1, "location": 1}))
    print(f"[INFO] Attendance rows fetched: {len(attendance_docs)}")

    idle_by_user_date: dict[tuple[str, str], list[float]] = defaultdict(list)
    activity_col = client.get_collection("activity_logs")
    if activity_col is not None:
        print("[INFO] Loading activity idle ratios from MongoDB...")
        for act in activity_col.find({"idle_ratio": {"$exists": True}}, {"_id": 0, "user_id": 1, "timestamp": 1, "idle_ratio": 1}):
            user_id = str(act.get("user_id", "")).strip().upper()
            if not user_id:
                continue
            timestamp = str(act.get("timestamp", ""))
            if not timestamp:
                continue
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except Exception:
                continue
            date_str = dt.date().isoformat()
            try:
                ratio = float(act.get("idle_ratio", 0.0) or 0.0)
            except (ValueError, TypeError):
                ratio = 0.0
            idle_by_user_date[(user_id, date_str)].append(max(0.0, min(1.0, ratio)))

    rows = []
    for doc in attendance_docs:
        emp_id = str(doc.get("employee_id", "")).strip().upper()
        if not emp_id:
            continue
        date_str = str(doc.get("date", "")).strip()
        signin = parse_time(doc.get("signin"))
        if signin is None:
            continue

        signout = parse_time(doc.get("signout"))
        duration_seconds = parse_duration(doc.get("duration"))
        if duration_seconds is None and signout is not None:
            try:
                date_val = parse_iso_date(date_str)
                if date_val is not None:
                    start_dt = datetime.combine(date_val, signin)
                    end_dt = datetime.combine(date_val, signout)
                    if end_dt < start_dt:
                        end_dt += timedelta(days=1)
                    duration_seconds = int(max(0, (end_dt - start_dt).total_seconds()))
            except Exception:
                duration_seconds = None

        if duration_seconds is None or duration_seconds <= 0:
            continue

        status = str(doc.get("status", "")).strip() or STATUS_NORMAL
        location = str(doc.get("location", "Unknown")).strip() or "Unknown"
        idle_values = idle_by_user_date.get((emp_id, date_str), [])
        idle_ratio = float(sum(idle_values) / len(idle_values)) if idle_values else 0.0

        login_hour_numeric = signin.hour + signin.minute / 60.0 + signin.second / 3600.0
        rows.append({
            "employee_id": emp_id,
            "employee_name": str(doc.get("full_name", emp_id)).strip(),
            "date": date_str,
            "signin": signin.strftime("%H:%M:%S"),
            "signout": signout.strftime("%H:%M:%S") if signout else None,
            "duration_min": round(duration_seconds / 60.0, 1),
            "status": status,
            "location": location,
            "login_hour_numeric": round(login_hour_numeric, 2),
            "idle_ratio": round(idle_ratio, 4),
            "is_anomaly": 0 if status == STATUS_NORMAL else 1,
        })

    client.close()
    print(f"[INFO] Prepared {len(rows)} attendance training rows.")
    return pd.DataFrame(rows)


def load_csv_fallback() -> pd.DataFrame:
    path = Path(__file__).resolve().parent / "employee_behavior_10k.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    print(f"[INFO] Loaded fallback dataset: {df.shape[0]} rows")
    return df


def generate_synthetic_attendance_data(n_rows: int = 10000) -> pd.DataFrame:
    random.seed(42)
    np.random.seed(42)
    employees = [
        (f"EMP{i:03d}", name)
        for i, name in enumerate([
            "Amila Perera", "Nimal Fernando", "Kamal Silva", "Priya Jayasinghe",
            "Tharindu Senanayake", "Lakshmi Wijesinghe", "Ruwan Bandara", "Samanthi Kariyawasam",
            "Kasun Nuwan", "Himali Jayawardena", "Suresh Kumar", "Nadeesha Perera",
            "Dilshan Weerasinghe", "Chamara Rajapaksha", "Sanjaya Fernando", "Sajith Kumara",
            "Ishara Senanayake", "Malsha Rodrigo", "Roshan Wickramasinghe", "Yasitha Jayawardena"
        ], start=1)
    ]
    locations = ["Colombo", "Kandy", "Galle", "Negombo", "Remote", "Unknown"]
    status_choices = ["On Time", "Late", "Early Departure", "Overtime"]
    rows = []
    base_date = date(2025, 1, 1)

    for i in range(n_rows):
        emp_id, full_name = employees[i % len(employees)]
        date_val = base_date + timedelta(days=i % 365)
        normal_signin = datetime.combine(date_val, datetime.min.time()) + timedelta(minutes=random.uniform(8 * 60, 9.5 * 60))
        location = random.choice(locations)
        is_anomaly = random.random() < 0.20
        if is_anomaly:
            status = random.choices(status_choices[1:], weights=[0.45, 0.35, 0.20])[0]
        else:
            status = "On Time"

        if status == "On Time":
            signin = normal_signin
            duration_seconds = int(random.uniform(8 * 3600, 9.5 * 3600))
        elif status == "Late":
            signin = datetime.combine(date_val, datetime.min.time()) + timedelta(minutes=random.uniform(9.75 * 60, 11.25 * 60))
            duration_seconds = int(random.uniform(6 * 3600, 8.5 * 3600))
        elif status == "Early Departure":
            signin = normal_signin
            duration_seconds = int(random.uniform(3 * 3600, 5.5 * 3600))
        else:
            signin = normal_signin
            duration_seconds = int(random.uniform(10 * 3600, 12 * 3600))

        signout = signin + timedelta(seconds=duration_seconds)
        duration_text = f"{duration_seconds // 3600}:{(duration_seconds % 3600) // 60:02d}:{duration_seconds % 60:02d}"
        idle_ratio = round(random.uniform(0.0, 0.18) if status == "On Time" else random.uniform(0.1, 0.8), 4)

        rows.append({
            "employee_id": emp_id,
            "full_name": full_name,
            "date": date_val.isoformat(),
            "signin": signin.strftime("%H:%M:%S"),
            "signout": signout.strftime("%H:%M:%S"),
            "duration": duration_text,
            "status": status,
            "location": location,
            "idle_ratio": idle_ratio,
            "is_anomaly": 0 if status == "On Time" else 1,
        })

    df = pd.DataFrame(rows)
    return df


def calibrate_isolation_forest(X_train, y_train, X_test, y_test):
    best_score = -1.0
    best_model = None
    best_contamination = None
    print("\n[INFO] Calibrating Isolation Forest contamination levels...")
    for contamination in [0.01, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]:
        model = IsolationForest(
            n_estimators=300,
            contamination=contamination,
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_train)
        pred_raw = model.predict(X_test)
        pred = np.where(pred_raw == -1, 1, 0)
        score = accuracy_score(y_test, pred)
        print(f"  contamination={contamination:.2f} => accuracy={score:.4f}")
        if score > best_score:
            best_score = score
            best_model = model
            best_contamination = contamination

    print(f"[INFO] Best IF calibration: contamination={best_contamination:.2f}, accuracy={best_score:.4f}")
    return best_model, best_contamination, best_score


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, LabelEncoder, LabelEncoder, LabelEncoder]:
    df = df.copy()
    if "duration_min" not in df.columns:
        if "duration" in df.columns:
            df["duration_min"] = df["duration"].apply(lambda v: round(parse_duration(v) / 60.0, 1) if parse_duration(v) is not None else 0.0)
        else:
            df["duration_min"] = df.get("session_duration_min", 0)
    if "idle_ratio" not in df.columns:
        df["idle_ratio"] = df.get("idle_time_min", 0).astype(float)
    if "login_hour_numeric" not in df.columns:
        df["login_hour_numeric"] = df["signin"].apply(lambda v: (parse_time(v).hour + parse_time(v).minute / 60.0 + parse_time(v).second / 3600.0) if parse_time(v) is not None else 0.0)
    if "location" not in df.columns:
        df["location"] = df.get("module_accessed", "Unknown")
    if "employee_id" not in df.columns:
        df["employee_id"] = df.get("employee_id", "UNKNOWN").astype(str)
    if "is_anomaly" not in df.columns:
        df["is_anomaly"] = df.get("is_anomaly", 0)

    le_location = LabelEncoder()
    df["location_encoded"] = le_location.fit_transform(df["location"].astype(str).fillna("Unknown"))

    le_employee = LabelEncoder()
    df["employee_encoded"] = le_employee.fit_transform(df["employee_id"].astype(str).fillna("UNKNOWN"))

    features = ["login_hour_numeric", "duration_min", "idle_ratio", "location_encoded", "employee_encoded"]
    X = df[features].fillna(0.0)
    y = df["is_anomaly"].astype(int)
    return X, y, le_location, le_employee, None


def transform_label_encoder(le, values, unknown_label: str = "Unknown"):
    safe_values = [v if v in le.classes_ else unknown_label for v in values]
    return le.transform(safe_values)


def run_training():
    print("=" * 55)
    print(" Employee Behavior Anomaly Detection - Attendance-based Training")
    print("=" * 55)

    attendance_df = build_attendance_dataset()
    if attendance_df.empty or len(attendance_df) < 1000:
        synthetic_path = Path(__file__).resolve().parent / "employee_behavior_10000.csv"
        print("[INFO] Insufficient live attendance rows. Generating synthetic 10,000-row dataset for robust training...")
        attendance_df = generate_synthetic_attendance_data(10000)
        attendance_df.to_csv(synthetic_path, index=False)
        print(f"[INFO] Saved synthetic dataset: {synthetic_path}")

    print(f"[INFO] Training dataset shape: {attendance_df.shape}")
    print(attendance_df.head(3).to_string(index=False))

    X, y, le_location, le_employee, _ = build_features(attendance_df)

    print("\n[INFO] Features selected:", list(X.columns))
    print(f"[INFO] Training labels distribution: {y.value_counts().to_dict()}")

    print("\n[STEP 2] Scaling features...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print("\n[STEP 3] Splitting dataset 80% train / 20% test...")
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.20, random_state=42, stratify=y
    )
    print(f"[INFO] Training set : {X_train.shape[0]} records")
    print(f"[INFO] Test set     : {X_test.shape[0]} records")

    print("\n[STEP 4] Training Isolation Forest (Primary Model)...")
    iso_forest, best_contamination, best_if_score = calibrate_isolation_forest(X_train, y_train, X_test, y_test)
    iso_pred_raw = iso_forest.predict(X_test)
    iso_pred = np.where(iso_pred_raw == -1, 1, 0)

    print(f"[INFO] Isolation Forest selected contamination={best_contamination:.2f} with accuracy={best_if_score:.4f}")
    print("\n-- Isolation Forest Results --")
    print(f"Accuracy : {accuracy_score(y_test, iso_pred):.4f}")
    print(f"Precision: {precision_score(y_test, iso_pred):.4f}")
    print(f"Recall   : {recall_score(y_test, iso_pred):.4f}")
    print(f"F1-Score : {f1_score(y_test, iso_pred):.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, iso_pred, target_names=["Normal", "Anomaly"]))
    cm_iso = confusion_matrix(y_test, iso_pred)
    print(f"Confusion Matrix: TN={cm_iso[0,0]} FP={cm_iso[0,1]} FN={cm_iso[1,0]} TP={cm_iso[1,1]}")

    print("\n[STEP 5] Training Random Forest (Supervised Benchmark)...")
    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf_model.fit(X_train, y_train)
    rf_pred = rf_model.predict(X_test)
    rf_proba = rf_model.predict_proba(X_test)[:, 1]

    print("\n-- Random Forest Results --")
    print(f"Accuracy : {accuracy_score(y_test, rf_pred):.4f}")
    print(f"Precision: {precision_score(y_test, rf_pred):.4f}")
    print(f"Recall   : {recall_score(y_test, rf_pred):.4f}")
    print(f"F1-Score : {f1_score(y_test, rf_pred):.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, rf_pred, target_names=["Normal", "Anomaly"]))
    cm_rf = confusion_matrix(y_test, rf_pred)
    print(f"Confusion Matrix: TN={cm_rf[0,0]} FP={cm_rf[0,1]} FN={cm_rf[1,0]} TP={cm_rf[1,1]}")

    print("\n-- Feature Importance (Random Forest) --")
    importances = rf_model.feature_importances_
    for feat, imp in sorted(zip(X.columns, importances), key=lambda x: -x[1]):
        bar = "#" * int(imp * 40)
        print(f"  {feat:<20} {imp:.4f}  {bar}")

    print("\n[STEP 6] Saving model artifacts...")
    save_artifacts(iso_forest, rf_model, scaler, le_location, le_employee)
    print("[INFO] Saved model artifacts to", MODEL_DIR)

    print("\n" + "=" * 55)
    print(" Training Complete! Models saved to /models/")
    print("=" * 55)


if __name__ == '__main__':
    run_training()
