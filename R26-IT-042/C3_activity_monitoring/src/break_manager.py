"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/break_manager.py

Suppresses anomaly alerts during scheduled break windows by
delegating to config/break_config.py.
"""

from __future__ import annotations

import logging
from datetime import datetime

from config.break_config import BreakConfig

logger = logging.getLogger(__name__)


class BreakManager:
    """
    Checks whether the current time falls within a scheduled break and
    advises the anomaly pipeline to suppress alerts accordingly.
    """

    def __init__(self, config: BreakConfig | None = None) -> None:
        self._config = config or BreakConfig()

    def should_suppress_alerts(self) -> bool:
        """Return True if the current wall-clock time is a break period."""
        now = datetime.now().time()
        if self._config.is_break_time(now):
            logger.debug("Break time detected — alerts suppressed.")
            return True
        if not self._config.is_work_hours(now):
            logger.debug("Outside work hours — alerts suppressed.")
            return True
        return False

    def current_break_name(self) -> str | None:
        """Return the name of the current break window, or None."""
        now = datetime.now().time()
        for window in self._config.get_windows():
            if window.start <= now <= window.end:
                return window.name
        return None
