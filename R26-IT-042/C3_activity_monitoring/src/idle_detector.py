"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/idle_detector.py

IdleDetector — Detects employee idle state based on combined keyboard
and mouse inactivity.  Distinct from break periods — idle during work
hours (beyond threshold) is flagged as a behavioural anomaly signal.

Default IDLE_THRESHOLD = 120 seconds (configurable).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Default idle threshold in seconds (2 minutes)
IDLE_THRESHOLD = 120


class IdleDetector:
    """
    Detects idle periods by watching time-since-last-activity.

    Works by receiving activity notifications from KeyboardTracker and
    MouseTracker.  No direct input hooking is done here.

    Usage
    ─────
    >>> detector = IdleDetector(threshold_sec=120)
    >>> detector.start()
    >>> detector.record_activity()   # called from trackers
    >>> print(detector.is_idle())
    >>> print(detector.get_idle_ratio())
    >>> detector.stop()
    """

    def __init__(
        self,
        threshold_sec: int = IDLE_THRESHOLD,
        check_interval: float = 5.0,
        on_idle: Optional[Callable[[float], None]] = None,
        on_resume: Optional[Callable[[], None]] = None,
        window_sec: float = 60.0,
    ) -> None:
        """
        Parameters
        ----------
        threshold_sec:
            Seconds of inactivity before the employee is considered idle.
        check_interval:
            How often to poll for idle state (seconds).
        on_idle:
            Callback fired with idle_duration when idle begins.
        on_resume:
            Callback fired when activity resumes from idle.
        window_sec:
            Window over which to compute idle_ratio.
        """
        self._threshold = threshold_sec
        self._check_interval = check_interval
        self._on_idle = on_idle
        self._on_resume = on_resume
        self._window_sec = window_sec

        self._last_activity: float = time.perf_counter()
        self._is_idle_state: bool = False
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Window-level idle tracking for idle_ratio computation
        # List of (period_start, period_end) tuples of idle periods within window
        self._idle_periods: list[tuple[float, float]] = []
        self._idle_start: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_activity(self) -> None:
        """
        Notify the detector that keyboard or mouse activity occurred.
        Should be called from KeyboardTracker and MouseTracker event hooks.
        """
        now = time.perf_counter()
        with self._lock:
            was_idle = self._is_idle_state
            self._last_activity = now

            if was_idle:
                self._is_idle_state = False
                # Close current idle period
                if self._idle_start is not None:
                    self._idle_periods.append((self._idle_start, now))
                    self._idle_start = None
                if self._on_resume:
                    threading.Thread(target=self._on_resume, daemon=True).start()

    def is_idle(self) -> bool:
        """Return True if the employee is currently idle."""
        with self._lock:
            return self._is_idle_state

    def get_idle_ratio(self) -> float:
        """
        Return the fraction of the last window_sec spent idle (0.0 – 1.0).

        Parameters
        ----------
        None

        Returns
        -------
        float
            0.0 = fully active, 1.0 = fully idle.
        """
        now = time.perf_counter()
        cutoff = now - self._window_sec

        with self._lock:
            idle_sec = 0.0
            for start, end in self._idle_periods:
                if end < cutoff:
                    continue
                clamped_start = max(start, cutoff)
                clamped_end = min(end, now)
                idle_sec += max(clamped_end - clamped_start, 0.0)

            # Include current ongoing idle period
            if self._is_idle_state and self._idle_start is not None:
                clamped_start = max(self._idle_start, cutoff)
                idle_sec += max(now - clamped_start, 0.0)

        return min(idle_sec / self._window_sec, 1.0)

    @property
    def idle_seconds(self) -> float:
        """Return seconds elapsed since last activity (0 if not idle)."""
        now = time.perf_counter()
        with self._lock:
            if self._is_idle_state:
                return now - self._last_activity
        return 0.0

    def start(self, shutdown_event: Optional[threading.Event] = None) -> None:
        """Start the idle-check polling loop in a background daemon thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop,
            args=(shutdown_event,),
            daemon=True,
            name="IdleDetector",
        )
        self._thread.start()
        logger.info("IdleDetector started (threshold=%ds).", self._threshold)

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        logger.info("IdleDetector stopped.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_loop(self, shutdown_event: Optional[threading.Event]) -> None:
        while self._running:
            if shutdown_event and shutdown_event.is_set():
                break

            now = time.perf_counter()
            with self._lock:
                idle_duration = now - self._last_activity
                if idle_duration >= self._threshold and not self._is_idle_state:
                    self._is_idle_state = True
                    self._idle_start = now - idle_duration
                    logger.info(
                        "Idle detected — employee inactive for %.0fs.", idle_duration
                    )
                    if self._on_idle:
                        _dur = idle_duration
                        threading.Thread(
                            target=self._on_idle, args=(_dur,), daemon=True
                        ).start()

                # Prune old idle periods outside 3x window buffer
                cutoff = now - self._window_sec * 3
                self._idle_periods = [
                    (s, e) for s, e in self._idle_periods if e >= cutoff
                ]

            time.sleep(self._check_interval)
