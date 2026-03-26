"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/feature_extractor.py

Aggregates raw event streams (keyboard, mouse, app, idle) into
feature vectors suitable for the anomaly detection model.

Features extracted per window
──────────────────────────────
  keystrokes_per_min, wpm, mouse_velocity, click_rate, scroll_rate,
  idle_ratio, top_app, app_switches, window_start, window_end
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FeatureVector:
    """A single window of extracted behavioural features."""
    window_start: float = field(default_factory=time.time)
    window_end: float = 0.0
    keystrokes_per_min: float = 0.0
    wpm: float = 0.0
    mouse_velocity: float = 0.0
    click_rate: float = 0.0
    scroll_rate: float = 0.0
    idle_ratio: float = 0.0
    app_switches: int = 0
    top_app: str = "Unknown"

    def to_array(self) -> np.ndarray:
        """Return numeric features as a 1-D numpy array (for ML model)."""
        return np.array([
            self.keystrokes_per_min,
            self.wpm,
            self.mouse_velocity,
            self.click_rate,
            self.scroll_rate,
            self.idle_ratio,
            self.app_switches,
        ], dtype=np.float32)


class FeatureExtractor:
    """
    Collects raw event counters and produces FeatureVector snapshots
    at the end of each sampling window.
    """

    def __init__(self, window_sec: float = 60.0) -> None:
        self._window = window_sec
        self._reset()

    def _reset(self) -> None:
        self._start = time.time()
        self._keystrokes = 0
        self._clicks = 0
        self._scrolls = 0
        self._idle_sec = 0.0
        self._app_switches = 0
        self._last_app = ""
        self._velocity_samples: list[float] = []

    def record_keystroke(self) -> None:
        self._keystrokes += 1

    def record_click(self) -> None:
        self._clicks += 1

    def record_scroll(self) -> None:
        self._scrolls += 1

    def record_idle(self, seconds: float) -> None:
        self._idle_sec += seconds

    def record_app_change(self, new_app: str) -> None:
        if new_app != self._last_app:
            self._app_switches += 1
            self._last_app = new_app

    def record_velocity(self, velocity: float) -> None:
        self._velocity_samples.append(velocity)

    def extract(self) -> FeatureVector:
        """
        Compute and return the feature vector for the current window,
        then reset accumulators.
        """
        now = time.time()
        elapsed_min = max((now - self._start) / 60.0, 1e-6)
        elapsed_sec = max(now - self._start, 1e-6)

        fv = FeatureVector(
            window_start=self._start,
            window_end=now,
            keystrokes_per_min=self._keystrokes / elapsed_min,
            wpm=self._keystrokes / 5.0 / elapsed_min,
            mouse_velocity=float(np.mean(self._velocity_samples)) if self._velocity_samples else 0.0,
            click_rate=self._clicks / elapsed_min,
            scroll_rate=self._scrolls / elapsed_min,
            idle_ratio=self._idle_sec / elapsed_sec,
            app_switches=self._app_switches,
            top_app=self._last_app,
        )
        self._reset()
        return fv
