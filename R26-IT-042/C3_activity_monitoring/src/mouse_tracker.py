"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/mouse_tracker.py

Tracks mouse movement velocity, click frequency, and scroll events.
Cross-platform via pynput.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class MouseTracker:
    """
    Cross-platform mouse event recorder.

    Computes velocity (pixels/second), click count, and scroll events
    over configurable sampling windows.
    """

    def __init__(
        self,
        on_event: Optional[Callable[[dict], None]] = None,
        sample_interval: float = 0.5,
    ) -> None:
        self._on_event = on_event
        self._sample_interval = sample_interval
        self._listener = None
        self._running = False
        self._lock = threading.Lock()
        self._positions: list[tuple[float, float, float]] = []  # (x, y, ts)
        self._clicks: list[float] = []
        self._scrolls: list[float] = []

    def start(self) -> None:
        """Start mouse listener in a background thread."""
        try:
            from pynput import mouse as _m

            self._running = True

            def on_move(x, y):
                ts = time.time()
                with self._lock:
                    self._positions.append((x, y, ts))

            def on_click(x, y, button, pressed):
                if pressed:
                    with self._lock:
                        self._clicks.append(time.time())
                if self._on_event:
                    self._on_event({"type": "click", "x": x, "y": y, "timestamp": time.time()})

            def on_scroll(x, y, dx, dy):
                with self._lock:
                    self._scrolls.append(time.time())

            self._listener = _m.Listener(
                on_move=on_move, on_click=on_click, on_scroll=on_scroll
            )
            self._listener.start()
            logger.info("MouseTracker started.")
        except ImportError:
            logger.warning("pynput not available — MouseTracker disabled.")
        except Exception as exc:
            logger.error("MouseTracker start error: %s", exc)

    def stop(self) -> None:
        """Stop the mouse listener."""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
        logger.info("MouseTracker stopped.")

    def get_velocity(self, window_sec: float = 10.0) -> float:
        """Return average mouse velocity in pixels/second over the last window."""
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            recent = [(x, y, t) for x, y, t in self._positions if t >= cutoff]

        if len(recent) < 2:
            return 0.0

        total_dist = sum(
            math.hypot(recent[i][0] - recent[i-1][0], recent[i][1] - recent[i-1][1])
            for i in range(1, len(recent))
        )
        elapsed = recent[-1][2] - recent[0][2]
        return total_dist / elapsed if elapsed > 0 else 0.0

    def get_click_rate(self, window_sec: float = 60.0) -> float:
        """Return clicks per minute over the last window."""
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            recent = [t for t in self._clicks if t >= cutoff]
        return len(recent) / (window_sec / 60.0)
