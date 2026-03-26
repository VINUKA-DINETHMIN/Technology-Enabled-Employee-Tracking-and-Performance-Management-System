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
        self.assertEqual(tracker.get_wpm(), 0.0)

    def test_wpm_calculation(self):
        """WPM calculation: 300 keystrokes in 60s / 5 chars = 60 WPM."""
        from C3_activity_monitoring.src.keyboard_tracker import KeyboardTracker

        tracker = KeyboardTracker()
        now = time.time()
        # Inject 300 keystrokes spread over the last 60 seconds
        tracker._keystrokes = [now - i * 0.2 for i in range(300)]
        wpm = tracker.get_wpm(window_sec=60.0)
        self.assertGreater(wpm, 0)


if __name__ == "__main__":
    unittest.main()
