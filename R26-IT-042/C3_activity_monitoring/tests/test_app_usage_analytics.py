"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_app_usage_analytics.py

Unit tests for AppUsageAnalytics.
Run with: pytest C3_activity_monitoring/tests/test_app_usage_analytics.py
"""

import unittest
from datetime import datetime, timezone

from C3_activity_monitoring.src.app_usage_analytics import AppUsageAnalytics


class _MockCollection:
    def aggregate(self, _pipeline):
        return [
            {
                "_id": "Code",
                "total_time": 7200,
                "session_count": 4,
                "last_used": datetime.now(timezone.utc).isoformat(),
                "avg_risk_score": 12.0,
                "productivity_avg": 90.0,
            },
            {
                "_id": "Browser",
                "total_time": 1800,
                "session_count": 2,
                "last_used": datetime.now(timezone.utc).isoformat(),
                "avg_risk_score": 40.0,
                "productivity_avg": 45.0,
            },
        ]


class _MockDB:
    is_connected = True

    def get_collection(self, name):
        if name == "activity_logs":
            return _MockCollection()
        return None


class TestAppUsageAnalytics(unittest.TestCase):

    def test_get_apps_by_period_today(self):
        """Today period should return ranked apps and computed percentages."""
        analytics = AppUsageAnalytics(db_client=_MockDB())
        summary = analytics.get_apps_by_period(user_id="EMP001", period="today")

        self.assertEqual(summary.app_count, 2)
        self.assertEqual(summary.most_used_app, "Code")
        self.assertEqual(int(summary.total_time_sec), 9000)
        self.assertEqual(summary.apps[0]["rank"], 1)
        self.assertAlmostEqual(summary.apps[0]["percentage"], 80.0, places=1)


if __name__ == "__main__":
    unittest.main()
