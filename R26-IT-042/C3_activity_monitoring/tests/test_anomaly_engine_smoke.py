"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_anomaly_engine_smoke.py

Smoke test for the real anomaly model files in this workspace.
Run with: python -m unittest C3_activity_monitoring.tests.test_anomaly_engine_smoke -v
"""

import unittest
import numpy as np

from C3_activity_monitoring.src.anomaly_engine import AnomalyEngine


class TestAnomalyEngineSmoke(unittest.TestCase):

    def test_real_model_loads_and_scores(self):
        """Real model files should load and give a higher score for anomalous input."""
        engine = AnomalyEngine()
        loaded = engine.load_model()
        self.assertTrue(loaded)
        self.assertTrue(engine.is_loaded)

        normal = np.array([
            25.0, 5.0, 20.0, 45.0, 0.02,
            1.0, 0.2, 0.4, 0.1, 1.2,
            0.10, 2.0, 1.0, 600.0, 8.0,
            1.0, 1.0, 1.0, 0.95,
        ], dtype=np.float32)

        anomaly = np.array([
            1.0, 0.5, 0.8, 2.0, 0.65,
            0.1, 0.1, 0.1, 0.9, 0.2,
            0.95, 0.2, 0.05, 30.0, 0.5,
            0.0, 0.0, 0.0, 0.30,
        ], dtype=np.float32)

        normal_score = engine.score(normal)
        anomaly_score = engine.score(anomaly)

        self.assertGreaterEqual(normal_score, 0.0)
        self.assertLessEqual(normal_score, 100.0)
        self.assertGreaterEqual(anomaly_score, 0.0)
        self.assertLessEqual(anomaly_score, 100.0)
        self.assertGreater(anomaly_score, normal_score)


if __name__ == "__main__":
    unittest.main()
