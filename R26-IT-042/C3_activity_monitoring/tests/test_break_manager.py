"""
R26-IT-042 — C3: Tests
C3_activity_monitoring/tests/test_break_manager.py

Unit tests for BreakManager overrun behavior.
Run with: python -m unittest C3_activity_monitoring.tests.test_break_manager -v
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from C3_activity_monitoring.src.break_manager import BreakManager


class _MockCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(doc)
        return type("InsertResult", (), {"inserted_id": "mock-id"})()


class _MockDB:
    is_connected = True

    def __init__(self):
        self.alerts = _MockCollection()
        self.policy_violations = _MockCollection()

    def get_collection(self, name):
        if name == "alerts":
            return self.alerts
        if name == "policy_violations":
            return self.policy_violations
        return None


class TestBreakManager(unittest.TestCase):

    def test_check_overrun_short_break_threshold(self):
        """check_overrun should be True after duration + short overrun threshold."""
        bm = BreakManager()
        bm._breaks = {"short_1": {"start": "10:00", "duration_minutes": 15}}
        bm._active_break = "short_1"
        bm._break_start_time = datetime.now() - timedelta(minutes=19, seconds=30)

        self.assertTrue(bm.check_overrun())

    @patch.object(BreakManager, "_start_overrun_verification")
    @patch.object(BreakManager, "_show_overrun_notice")
    def test_overrun_alert_reaches_employee_and_admin_paths(self, mock_notice, mock_start_verification):
        """Overrun should send websocket alert and persist docs used by admin/employee UIs."""
        db = _MockDB()
        sender = MagicMock()

        bm = BreakManager(db_client=db, alert_sender=sender, user_id="EMP001")
        bm._on_overrun_detected("short_2")

        mock_notice.assert_called_once_with("short_2")
        mock_start_verification.assert_called_once_with("short_2")

        sender.send_alert.assert_called_once()
        sent_kwargs = sender.send_alert.call_args.kwargs
        self.assertEqual(sent_kwargs["user_id"], "EMP001")
        self.assertEqual(sent_kwargs["level"], "LOW")
        self.assertEqual(sent_kwargs["extra"]["reason"], "break_overrun")
        self.assertEqual(sent_kwargs["extra"]["break_type"], "short_2")

        self.assertEqual(len(db.alerts.docs), 1)
        alert_doc = db.alerts.docs[0]
        # Admin panel path: user_id + level/factors/timestamp/risk_score
        self.assertEqual(alert_doc["user_id"], "EMP001")
        self.assertEqual(alert_doc["level"], "LOW")
        self.assertEqual(alert_doc["factors"], ["break_overrun"])
        self.assertIn("timestamp", alert_doc)
        self.assertIn("risk_score", alert_doc)
        # Employee panel path: reason + unresolved flag + break type
        self.assertEqual(alert_doc["reason"], "break_overrun")
        self.assertEqual(alert_doc["break_type"], "short_2")
        self.assertFalse(alert_doc["resolved"])

        self.assertEqual(len(db.policy_violations.docs), 1)
        violation_doc = db.policy_violations.docs[0]
        self.assertEqual(violation_doc["user_id"], "EMP001")
        self.assertEqual(violation_doc["violation_type"], "break_overrun")
        self.assertEqual(violation_doc["break_type"], "short_2")


if __name__ == "__main__":
    unittest.main()
