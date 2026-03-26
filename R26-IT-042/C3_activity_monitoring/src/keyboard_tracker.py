"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/keyboard_tracker.py

Records keystroke events and computes words-per-minute and typing rhythm.
Uses pynput to hook keyboard events cross-platform.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class KeyboardTracker:
    """
    Cross-platform keystroke event recorder.

    Usage
    ─────
    >>> tracker = KeyboardTracker(on_event=my_callback)
    >>> tracker.start()
    >>> # ... monitoring runs in background thread ...
    >>> tracker.stop()
    """

    def __init__(
        self,
        on_event: Optional[Callable[[dict], None]] = None,
        sample_interval: float = 1.0,
    ) -> None:
        """
        Parameters
        ----------
        on_event:
            Callback fired with each keystroke event dict.
        sample_interval:
            Seconds between metric aggregation windows.
        """
        self._on_event = on_event
        self._sample_interval = sample_interval
        self._listener = None
        self._running = False
        self._lock = threading.Lock()
        self._keystrokes: list[float] = []  # timestamps

    def start(self) -> None:
        """Start the keyboard listener in a background thread."""
        try:
            from pynput import keyboard as _kb

            self._running = True

            def on_press(key):
                ts = time.time()
                with self._lock:
                    self._keystrokes.append(ts)
                if self._on_event:
                    self._on_event({"type": "keypress", "timestamp": ts})

            self._listener = _kb.Listener(on_press=on_press)
            self._listener.start()
            logger.info("KeyboardTracker started.")
        except ImportError:
            logger.warning("pynput not available — KeyboardTracker disabled.")
        except Exception as exc:
            logger.error("KeyboardTracker start error: %s", exc)

    def stop(self) -> None:
        """Stop the keyboard listener."""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
        logger.info("KeyboardTracker stopped.")

    def get_wpm(self, window_sec: float = 60.0) -> float:
        """
        Calculate approximate WPM over the last *window_sec* seconds.
        Assumes average of 5 keystrokes per word.
        """
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            recent = [t for t in self._keystrokes if t >= cutoff]
        return len(recent) / 5.0 / (window_sec / 60.0)
