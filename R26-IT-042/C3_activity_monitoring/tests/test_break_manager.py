"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_break_manager.py

Unit tests for BreakManager.
Run with: pytest C3_activity_monitoring/tests/test_break_manager.py
"""

import unittest
from datetime import time
from config.break_config import BreakConfig


class TestBreakManager(unittest.TestCase):

    def setUp(self):
        self.config = BreakConfig()

    def test_lunch_time_is_break(self):
        """12:45 should be detected as break (lunch 12:30-13:30)."""
        from C3_activity_monitoring.src.break_manager import BreakManager
        bm = BreakManager(config=self.config)
        # Monkey-patch datetime.now().time() for 12:45
        import C3_activity_monitoring.src.break_manager as bm_module
        from unittest.mock import patch
        import datetime

        mock_now = datetime.datetime(2025, 1, 1, 12, 45)
        with patch("C3_activity_monitoring.src.break_manager.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = bm.should_suppress_alerts()
        self.assertTrue(result)

    def test_work_hours_not_break(self):
        """10:00 (non-break) should not suppress alerts."""
        from C3_activity_monitoring.src.break_manager import BreakManager
        import C3_activity_monitoring.src.break_manager as bm_module
        from unittest.mock import patch
        import datetime

        bm = BreakManager(config=self.config)
        mock_now = datetime.datetime(2025, 1, 1, 10, 0)
        with patch("C3_activity_monitoring.src.break_manager.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = bm.should_suppress_alerts()
        self.assertFalse(result)

    def test_is_break_time(self):
        """BreakConfig.is_break_time should recognise lunch and short breaks."""
        self.assertTrue(self.config.is_break_time(time(12, 30)))
        self.assertTrue(self.config.is_break_time(time(10, 40)))
        self.assertTrue(self.config.is_break_time(time(15, 35)))
        self.assertFalse(self.config.is_break_time(time(9, 0)))


if __name__ == "__main__":
    unittest.main()
