"""
R26-IT-042 — Employee Activity Monitoring System
config/break_config.py

BreakConfig — Defines when scheduled breaks occur during the workday.
Used by C3_activity_monitoring/src/break_manager.py to suppress anomaly
alerts during legitimate rest periods.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time


@dataclass
class BreakWindow:
    """A single break period in the workday."""
    name: str
    start: time           # Local wall-clock time
    end: time
    suppress_alerts: bool = True


@dataclass
class BreakConfig:
    """
    Default workday break schedule.

    Override by subclassing or mutating the singleton after import.
    All times are local (wall-clock) to the employee's device.
    """

    # Lunch break: 12:30 – 13:30 (60 min)
    lunch_start: time = time(12, 30)
    lunch_end: time = time(13, 30)

    # Morning short break: 10:30 – 10:45 (15 min)
    morning_break_start: time = time(10, 30)
    morning_break_end: time = time(10, 45)

    # Afternoon short break: 15:30 – 15:45 (15 min)
    afternoon_break_start: time = time(15, 30)
    afternoon_break_end: time = time(15, 45)

    # Core hours (alerts paused entirely outside these)
    work_start: time = time(8, 0)
    work_end: time = time(18, 0)

    def get_windows(self) -> list[BreakWindow]:
        """Return all defined break windows."""
        return [
            BreakWindow("Lunch", self.lunch_start, self.lunch_end),
            BreakWindow("Morning Break", self.morning_break_start, self.morning_break_end),
            BreakWindow("Afternoon Break", self.afternoon_break_start, self.afternoon_break_end),
        ]

    def is_break_time(self, current: time) -> bool:
        """
        Return True if *current* falls inside any scheduled break window.

        Parameters
        ----------
        current:
            Local wall-clock time to check.
        """
        for window in self.get_windows():
            if window.start <= current <= window.end:
                return True
        return False

    def is_work_hours(self, current: time) -> bool:
        """Return True if monitoring should be active at *current* time."""
        return self.work_start <= current <= self.work_end
