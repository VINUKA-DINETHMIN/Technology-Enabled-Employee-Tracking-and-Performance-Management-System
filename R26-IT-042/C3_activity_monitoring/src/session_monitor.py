"""
R26-IT-042 — C2: Facial Liveness
C2_facial_liveness/src/session_monitor.py

Post-break session monitoring hook used by C3 BreakManager.
"""

from __future__ import annotations

from C2_facial_liveness.src import run_liveness_check


def run_post_break_session_check(user_id: str = "UNKNOWN", timeout_sec: float = 30.0) -> bool:
    """Run liveness check when an employee returns from break."""
    return run_liveness_check(user_id=user_id, timeout_sec=timeout_sec, show_window=False)
