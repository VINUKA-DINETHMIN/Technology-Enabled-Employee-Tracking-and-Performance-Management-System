"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_anomaly_engine.py

Unit tests for AnomalyEngine.
Run with: pytest C3_activity_monitoring/tests/test_anomaly_engine.py
"""

import unittest
import numpy as np
from unittest.mock import MagicMock, patch


class TestAnomalyEngine(unittest.TestCase):

    def test_score_returns_zero_without_model(self):
        """AnomalyEngine.score() should return 0.0 if no model is loaded."""
        from C3_activity_monitoring.src.anomaly_engine import AnomalyEngine

        engine = AnomalyEngine()
        x = np.zeros(7, dtype=np.float32)
        score = engine.score(x)
        self.assertEqual(score, 0.0)

    def test_score_in_range(self):
        """Score should be between 0 and 100 for any valid feature vector."""
        from C3_activity_monitoring.src.anomaly_engine import AnomalyEngine

        engine = AnomalyEngine()
        # Inject a mock model
        mock_model = MagicMock()
        mock_model.decision_function.return_value = np.array([-0.3])
        engine._model = mock_model
        engine._model_loaded = True

        x = np.array([200, 40, 150, 12, 5, 0.05, 8], dtype=np.float32)
        score = engine.score(x)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_load_model_missing_file(self):
        """load_model() should return False when model files are absent."""
        from C3_activity_monitoring.src.anomaly_engine import AnomalyEngine

        engine = AnomalyEngine()
        result = engine.load_model()
        # Model files don't exist in CI/test environment
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
