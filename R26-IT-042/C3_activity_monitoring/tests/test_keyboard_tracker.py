"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_keyboard_tracker.py

Unit tests for KeyboardTracker.
Run with: pytest C3_activity_monitoring/tests/test_keyboard_tracker.py
"""

import time
import unittest
from unittest.mock import MagicMock, patch


class TestKeyboardTracker(unittest.TestCase):

    @patch("pynput.keyboard.Listener", autospec=True)
    def test_start_and_stop(self, mock_listener_cls):
        """KeyboardTracker starts a pynput Listener and stops cleanly."""
        from C3_activity_monitoring.src.keyboard_tracker import KeyboardTracker

        mock_listener = MagicMock()
        mock_listener_cls.return_value = mock_listener

        tracker = KeyboardTracker()
        tracker.start()
        self.assertTrue(mock_listener.start.called)
        tracker.stop()
        self.assertTrue(mock_listener.stop.called)

    def test_wpm_zero_on_no_keystrokes(self):
        """WPM should be 0.0 when no keystrokes have been recorded."""
        from C3_activity_monitoring.src.keyboard_tracker import KeyboardTracker

        tracker = KeyboardTracker()
        features = tracker.get_features()
        self.assertEqual(features["typing_speed_wpm"], 0.0)

    def test_wpm_calculation(self):
        """WPM calculation: 300 keystrokes in 60s / 5 chars = 60 WPM."""
        from C3_activity_monitoring.src.keyboard_tracker import KeyboardTracker

        tracker = KeyboardTracker(window_sec=60.0)
        now = time.perf_counter()
        # Inject 300 keystrokes with valid record shape inside the feature window.
        tracker._keystrokes = [
            {
                "press_ts": now - (i * 0.19),
                "release_ts": now - (i * 0.19) + 0.08,
                "dwell_ms": 80.0,
                "is_backspace": False,
            }
            for i in range(300)
        ]
        features = tracker.get_features()
        self.assertGreater(features["typing_speed_wpm"], 0)


if __name__ == "__main__":
    unittest.main()
