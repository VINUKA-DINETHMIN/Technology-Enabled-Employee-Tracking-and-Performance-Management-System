import numpy as np
from C3_activity_monitoring.src.anomaly_engine import AnomalyEngine, FEATURE_COLUMNS

engine = AnomalyEngine()
loaded = engine.load_model()
print('LOADED', loaded, 'IS_LOADED', engine.is_loaded)
print('FEATURE_COUNT', len(FEATURE_COLUMNS))

normal = np.array([
    25.0, 5.0, 20.0, 45.0, 0.02,   # typing
    1.0, 0.2, 0.4, 0.1, 1.2,       # mouse
    0.10, 2.0, 1.0, 600.0, 8.0,    # idle/app/session
    1.0, 1.0, 1.0, 0.95            # geo/identity
], dtype=np.float32)

anomaly = np.array([
    1.0, 0.5, 0.8, 2.0, 0.65,      # very low typing + errors
    0.1, 0.1, 0.1, 0.9, 0.2,      # weak mouse
    0.95, 0.2, 0.05, 30.0, 0.5,   # high idle + low app usage
    0.0, 0.0, 0.0, 0.30           # geo/identity mismatch
], dtype=np.float32)

print('NORMAL_SCORE', engine.score(normal))
print('ANOMALY_SCORE', engine.score(anomaly))
