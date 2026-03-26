"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/idle_detector.py

Detects employee idle periods by checking for absence of keyboard and
mouse events for longer than the configured IDLE_THRESHOLD_SEC.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class IdleDetector:
    """
    Detects idle periods by comparing last-event time to a threshold.

    Usage
    ─────
    >>> detector = IdleDetector(threshold_sec=300, on_idle=my_callback)
    >>> detector.start()
    >>> detector.record_activity()  # called from KeyboardTracker / MouseTracker
    """

    def __init__(
        self,
        threshold_sec: int = 300,
        check_interval: float = 10.0,
        on_idle: Optional[Callable[[float], None]] = None,
        on_resume: Optional[Callable[[], None]] = None,
    ) -> None:
        self._threshold = threshold_sec
        self._check_interval = check_interval
        self._on_idle = on_idle
        self._on_resume = on_resume
        self._last_activity = time.time()
        self._is_idle = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def record_activity(self) -> None:
        """Call this whenever any keyboard or mouse event occurs."""
        was_idle = self._is_idle
        self._last_activity = time.time()
        if was_idle:
            self._is_idle = False
            if self._on_resume:
                self._on_resume()

    def start(self, shutdown_event: Optional[threading.Event] = None) -> None:
        """Start the idle-check polling loop."""
        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop, args=(shutdown_event,), daemon=True
        )
        self._thread.start()
        logger.info("IdleDetector started (threshold=%ds).", self._threshold)

    def stop(self) -> None:
        self._running = False

    def _check_loop(self, shutdown_event: Optional[threading.Event]) -> None:
        while self._running:
            if shutdown_event and shutdown_event.is_set():
                break

            idle_duration = time.time() - self._last_activity
            if idle_duration >= self._threshold and not self._is_idle:
                self._is_idle = True
                logger.info("Idle detected — duration so far: %.0fs", idle_duration)
                if self._on_idle:
                    self._on_idle(idle_duration)

            time.sleep(self._check_interval)

    @property
    def is_idle(self) -> bool:
        return self._is_idle

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity if self._is_idle else 0.0
