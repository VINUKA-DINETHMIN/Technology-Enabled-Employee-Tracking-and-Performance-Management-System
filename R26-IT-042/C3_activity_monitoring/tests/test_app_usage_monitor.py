"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_app_usage_monitor.py

Unit tests for AppUsageMonitor.
Run with: pytest C3_activity_monitoring/tests/test_app_usage_monitor.py
"""

import threading
import time
import unittest
from unittest.mock import patch

from C3_activity_monitoring.src.app_usage_monitor import AppUsageMonitor


class TestAppUsageMonitor(unittest.TestCase):

    @patch("C3_activity_monitoring.src.app_usage_monitor._get_active_app")
    @patch("C3_activity_monitoring.src.app_usage_monitor._POLL_INTERVAL", 0.05)
    def test_no_duplicate_segments_on_switch(self, mock_get_active_app):
        """Switching apps should not create duplicate overlapping segments."""
        sequence = ["Code", "Code", "Chrome", "Chrome", "Code", "Code"]
        fallback = sequence[-1]

        def _next_app():
            if sequence:
                return sequence.pop(0)
            return fallback

        mock_get_active_app.side_effect = _next_app

        monitor = AppUsageMonitor(window_sec=30)
        shutdown = threading.Event()
        monitor.start(shutdown_event=shutdown)
        time.sleep(0.45)
        monitor.stop()
        shutdown.set()
        time.sleep(0.1)

        segments = list(monitor._segments)

        # Ensure no adjacent duplicate app segments remain.
        for i in range(1, len(segments)):
            self.assertNotEqual(segments[i]["app"], segments[i - 1]["app"])

        features = monitor.get_features()
        self.assertGreater(features["total_focus_duration"], 0.0)
        self.assertGreaterEqual(features["app_switch_frequency"], 1.0)


if __name__ == "__main__":
    unittest.main()
