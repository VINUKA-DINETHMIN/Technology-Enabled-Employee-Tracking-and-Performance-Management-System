import os
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from scipy import sparse
from lime.lime_tabular import LimeTabularExplainer
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, LabelEncoder


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    data_path = base_dir / "employee_productivity_dataset.csv"
    output_dir = base_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    df = pd.read_csv(data_path)

    target_col = "performance_label"
    drop_cols = [
        "record_id",
        "task_id",
        "employee_name",
        "task_title",
        "task_description",
        "assigned_by",
        "completed_date",
        target_col,
    ]

    if target_col not in df.columns:
        raise ValueError(f"Missing target column: {target_col}")

    X = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore").copy()
    y = df[target_col].astype(str)

    # Convert date columns to numeric day offsets for model compatibility.
    date_cols = [c for c in ["join_date", "assigned_date", "deadline_date"] if c in X.columns]
    for col in date_cols:
        dt = pd.to_datetime(X[col], errors="coerce")
        X[col] = (dt - dt.min()).dt.days.fillna(0).astype(int)

    categorical_cols = X.select_dtypes(include=["object", "category", "string"]).columns.tolist()
    numeric_cols = [c for c in X.columns if c not in categorical_cols]

    y_encoder = LabelEncoder()
    y_encoded = y_encoder.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y_encoded,
        test_size=0.2,
        random_state=42,
        stratify=y_encoded,
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
            ("num", "passthrough", numeric_cols),
        ]
    )

    model = RandomForestClassifier(
        n_estimators=300,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )

    clf = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )

    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    report = classification_report(y_test, y_pred, target_names=y_encoder.classes_)
    cm = confusion_matrix(y_test, y_pred)

    report_path = output_dir / "classification_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Classification Report\n")
        f.write("====================\n")
        f.write(report)
        f.write("\nConfusion Matrix\n")
        f.write("================\n")
        f.write(str(cm))

    # Persist model artifacts.
    joblib.dump(clf, output_dir / "productivity_classifier.joblib")
    joblib.dump(y_encoder, output_dir / "label_encoder.joblib")

    # Prepare transformed matrices and feature names for explainability.
    pre = clf.named_steps["preprocessor"]
    rf = clf.named_steps["model"]

    X_train_trans = pre.transform(X_train)
    X_test_trans = pre.transform(X_test)

    if sparse.issparse(X_train_trans):
        X_train_trans = X_train_trans.toarray()
    if sparse.issparse(X_test_trans):
        X_test_trans = X_test_trans.toarray()

    X_train_trans = np.asarray(X_train_trans, dtype=float)
    X_test_trans = np.asarray(X_test_trans, dtype=float)

    feature_names = pre.get_feature_names_out()

    # SHAP summary plot (class-agnostic mean absolute SHAP values).
    explainer = shap.TreeExplainer(rf)
    shap_values = explainer.shap_values(X_test_trans)

    if isinstance(shap_values, list):
        shap_plot_values = shap_values[0]
    else:
        # For multiclass outputs with array shape: (n_samples, n_features, n_classes)
        if len(shap_values.shape) == 3:
            shap_plot_values = shap_values[:, :, 0]
        else:
            shap_plot_values = shap_values

    plt.figure(figsize=(12, 7))
    shap.summary_plot(
        shap_plot_values,
        features=X_test_trans,
        feature_names=feature_names,
        show=False,
        max_display=20,
    )
    plt.tight_layout()
    plt.savefig(output_dir / "shap_summary.png", dpi=150)
    plt.close()

    # LIME explanation for one prediction.
    class_names = list(y_encoder.classes_)
    lime_explainer = LimeTabularExplainer(
        training_data=X_train_trans,
        feature_names=list(feature_names),
        class_names=class_names,
        mode="classification",
        discretize_continuous=True,
    )

    sample_index = 0
    sample = X_test_trans[sample_index]

    exp = lime_explainer.explain_instance(
        data_row=sample,
        predict_fn=rf.predict_proba,
        num_features=15,
        top_labels=1,
    )

    exp.save_to_file(str(output_dir / "lime_explanation_sample.html"))

    print("Training complete.")
    print(f"Saved model and reports in: {output_dir}")
    print(f"Class labels: {class_names}")


if __name__ == "__main__":
    main()
