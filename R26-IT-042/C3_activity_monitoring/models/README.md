# Models — evaluation, outputs, and recommendations

This folder contains trained artifacts and a small ensemble engine for anomaly detection. This README summarizes the performance reported during evaluation, explains the outputs, and gives practical recommendations for production use.

## Files produced

- `if_model.pkl` — trained Isolation Forest model
- `if_scaler.pkl` — StandardScaler fitted on normal training data (required before scoring)
- `ae_model.pkl` — MLPRegressor used as the Autoencoder (predicts reconstructions)
- `ensemble_config.json` — tuned ensemble configuration (weights, threshold, meta-LR coeffs) and AE mse bounds
- `ensemble_engine.py` — loader and scoring helpers (CLI smoke-test available)

## Key evaluation results (test set)

Two evaluation runs are summarized below: an initial simple average ensemble and a later tuning run that optimized ensemble weight and trained a logistic-regression meta-classifier.

1) Simple average ensemble (one-off evaluation)
- Isolation Forest (IF): Precision=0.6767, Recall=0.6222, F1=0.6483, AUC=0.8870
- Autoencoder (AE): Precision=0.5990, Recall=0.6806, F1=0.6372, AUC=0.8648
- Ensemble (average): Precision=0.6215, Recall=0.6750, F1=0.6471, AUC=0.8751

2) Tuned ensemble + meta-classifier (validation-based tuning)
- Best validation weight: IF weight = 0.925, threshold = 0.50 (val F1 = 0.7163)
- Weighted ensemble on test: Precision=0.7075, Recall=0.5778, F1=0.6361, AUC=0.8742
  - Confusion (tn, fp, fn, tp) = [977, 43, 76, 104]
- Meta-classifier (Logistic Regression) on test: Precision=0.9495, Recall=0.5222, F1=0.6738, AUC=0.8497
  - Confusion (tn, fp, fn, tp) = [1015, 5, 86, 94]

Notes on the numbers:
- Precision = TP / (TP + FP). High precision means fewer false alarms.
- Recall = TP / (TP + FN). High recall means fewer missed anomalies.
- F1 balances precision and recall — useful summary when classes are imbalanced.
- AUC is threshold-independent and measures ranking quality.

## Interpretation & robustness

- The Isolation Forest is a strong baseline (highest AUC and precision in these runs). The Autoencoder provides complementary recall benefits.
- The average ensemble sits between the two models. The tuned ensemble favored the Isolation Forest (weight ≈ 0.925), indicating IF is generally more informative for this dataset.
- The meta-classifier trades recall for precision (very low false-positive count). Use it when false alarms are costly.
- Robustness considerations:
  - The models were validated with a single stratified train/val/test split. For robust estimates, run repeated cross-validation or bootstrapping.
  - The AE normalization depends on AE reconstruction distribution on normal data; if training data changes, recompute `ae_mse_min`/`ae_mse_max` and `if_scaler.pkl`.
  - Data drift, missing features, or different feature ordering will break scoring. Ensure the production pipeline preserves `FEATURE_COLS` order.
  - Adversarial / corrupted inputs: validate inputs, clip outliers, and monitor input statistics in production.

## Are these models ready for production?

Short answer: They are usable as a prototype or internal monitoring system, but not yet a production-grade deployment. Recommended next steps before production:

1. Reproducible training pipeline
   - Package training code, fix random seeds, and save model versions (e.g., `if_model_v1.pkl`).
2. Stronger validation
   - Use repeated splits or K-fold where possible and compute confidence intervals for metrics.
3. Threshold tuning by business objective
   - Decide acceptable FPR (e.g., ≤ 0.05) and tune threshold/weights to meet that constraint.
4. Monitoring & retraining
   - Add telemetry: input feature distributions, model scores, alert counts. Retrain when drift is detected.
5. Packaging & serving
   - Wrap `ensemble_engine.py` behind a lightweight API (Flask/FastAPI), add input validation, and set logging/audit trails.
6. Tests & CI
   - Unit tests for `ensemble_engine.score_batch`, small integration tests, and a CI pipeline that verifies models load and a smoke inference runs.

## Quick reproduction & smoke commands

From the project root you can:

Run the smoke test in the engine (it will load models/config and try a small dataset sample):
```bash
python3 models/ensemble_engine.py
```

Run the evaluation script used earlier (reproduces metrics and tuning):
```bash
# (this script was executed interactively during development; the repo contains notebook/train_models.py)
python3 notebook/train_models.py
```

Run the ensemble tuning script used to generate `ensemble_config.json` (reproduces weight sweep & meta-LR):
```bash
# If you want to re-run tuning from scratch, run the tuning snippet used in the session or ask me to add a runnable script 'scripts/tune_ensemble.py'
```

## Decision guidance (how to pick between IF, AE, and ensemble)

- If you must minimize false positives (alerts are costly): use the meta-classifier configuration (meta-LR) and set operating threshold conservatively.
- If you must minimize missed anomalies (safety-critical): tune ensemble threshold for higher recall; consider weighting AE more.
- If compute/latency is limited: Isolation Forest alone is fastest to serve.

## Next recommended engineering tasks I can implement

- Persist `meta_lr.pkl` and update `ensemble_engine.py` to load it directly.
- Add `scripts/score_csv.py` that accepts a CSV and writes per-row scores and predictions.
- Add basic unit tests and a small `Dockerfile` + `README_DEPLOY.md` for production deployment.

If you want, I will add `meta_lr.pkl` and `scripts/score_csv.py` next — tell me which one to do first.
