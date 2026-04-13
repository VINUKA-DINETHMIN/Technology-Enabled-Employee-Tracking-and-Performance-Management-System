"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_activity_logger_factors.py

Unit tests for explicit anomaly factor generation.
Run with: python -m unittest C3_activity_monitoring.tests.test_activity_logger_factors -v
"""

import unittest

from C3_activity_monitoring.src.activity_logger import _get_contributing_factors


class TestActivityLoggerFactors(unittest.TestCase):

    def test_low_mouse_movement_factor_is_explicit(self):
        """Low mouse movement should be called out directly in contributing factors."""
        fv = {
            "idle_ratio": 0.10,
            "typing_speed_wpm": 22.0,
            "error_rate": 0.02,
            "app_switch_frequency": 1.0,
            "active_app_entropy": 1.2,
            "wifi_ssid_match": True,
            "device_fingerprint_match": True,
            "face_liveness_score": 0.95,
            "geolocation_deviation": 0.0,
            "inside_office_geofence": True,
            "vpn_proxy_detected": False,
            "hosting_detected": False,
            "location_trust_score": 85.0,
            "top_app": "Code",
            "mean_velocity": 20.0,
            "click_frequency": 1.0,
            "mean_curvature": 0.05,
        }

        factors = _get_contributing_factors(fv, risk_score=72.0)
        self.assertIn("low_mouse_movement", factors)


if __name__ == "__main__":
    unittest.main()
