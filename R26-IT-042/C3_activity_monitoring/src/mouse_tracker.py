"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/mouse_tracker.py

MouseTracker — Records mouse movement and click events, computing
behavioural biometric features per configurable window (default 30 s).

Features extracted
──────────────────
  mean_velocity     — avg pixels/sec of movement
  std_velocity      — std-dev of velocity samples
  mean_acceleration — avg change in velocity per second
  mean_curvature    — avg direction-change magnitude (radians)
  click_frequency   — clicks per minute
  idle_ratio        — fraction of window with no movement
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum movement delta (pixels) to register as real motion
_MIN_MOVE_PX = 2


class MouseTracker:
    """
    Cross-platform mouse movement and click biometric recorder.

    Usage
    ─────
    >>> tracker = MouseTracker(window_sec=30)
    >>> tracker.start()
    >>> features = tracker.get_features()
    >>> tracker.stop()
    """

    def __init__(self, window_sec: float = 30.0) -> None:
        """
        Parameters
        ----------
        window_sec:
            Feature extraction window in seconds.
        """
        self._window_sec = window_sec
        self._running = False
        self._listener = None
        self._lock = threading.Lock()

        # (x, y, timestamp)
        self._positions: list[tuple[float, float, float]] = []
        # click timestamps
        self._clicks: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the mouse listener in a background daemon thread."""
        try:
            from pynput import mouse as _m

            self._running = True

            def on_move(x: float, y: float) -> None:
                ts = time.perf_counter()
                with self._lock:
                    self._positions.append((float(x), float(y), ts))
                    # Prune entries outside extended buffer (3x window for stats)
                    cutoff = ts - self._window_sec * 3
                    self._positions = [p for p in self._positions if p[2] >= cutoff]

            def on_click(x: float, y: float, button, pressed: bool) -> None:
                if pressed:
                    ts = time.perf_counter()
                    with self._lock:
                        self._clicks.append(ts)
                        cutoff = ts - self._window_sec * 3
                        self._clicks = [c for c in self._clicks if c >= cutoff]

            self._listener = _m.Listener(on_move=on_move, on_click=on_click)
            self._listener.start()
            logger.info("MouseTracker started (window=%.0fs).", self._window_sec)

        except ImportError:
            logger.warning("pynput not available — MouseTracker disabled.")
        except Exception as exc:
            logger.error("MouseTracker start error: %s", exc)

    def stop(self) -> None:
        """Stop the mouse listener."""
        self._running = False
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
        logger.info("MouseTracker stopped.")

    def record_activity(self) -> None:
        """No-op — kept for interface compatibility with IdleDetector."""
        pass

    def get_features(self) -> dict:
        """
        Compute and return mouse biometric features for the last window.

        Returns
        -------
        dict
            Keys: mean_velocity, std_velocity, mean_acceleration,
                  mean_curvature, click_frequency, idle_ratio
        """
        now = time.perf_counter()
        cutoff = now - self._window_sec

        with self._lock:
            recent_pos = [p for p in self._positions if p[2] >= cutoff]
            recent_clicks = [c for c in self._clicks if c >= cutoff]

        if len(recent_pos) < 2:
            return _empty_mouse_features()

        # ── Velocity samples (pixels/sec) ─────────────────────────────
        velocities: list[float] = []
        for i in range(1, len(recent_pos)):
            x1, y1, t1 = recent_pos[i - 1]
            x2, y2, t2 = recent_pos[i]
            dt = t2 - t1
            if dt <= 0:
                continue
            dist = math.hypot(x2 - x1, y2 - y1)
            if dist < _MIN_MOVE_PX:
                continue
            velocities.append(dist / dt)

        if not velocities:
            return _empty_mouse_features()

        mean_vel = _mean(velocities)
        std_vel = _std(velocities)

        # ── Acceleration (|v[i+1] - v[i]| / dt) ─────────────────────
        accelerations: list[float] = []
        for i in range(1, len(velocities)):
            dv = abs(velocities[i] - velocities[i - 1])
            # Approximate dt from positions
            pos_i = recent_pos[min(i + 1, len(recent_pos) - 1)]
            pos_prev = recent_pos[max(i - 1, 0)]
            dt = max(pos_i[2] - pos_prev[2], 1e-6)
            accelerations.append(dv / dt)

        mean_accel = _mean(accelerations) if accelerations else 0.0

        # ── Curvature (direction change in radians) ───────────────────
        curvatures: list[float] = []
        for i in range(1, len(recent_pos) - 1):
            x0, y0, _ = recent_pos[i - 1]
            x1, y1, _ = recent_pos[i]
            x2, y2, _ = recent_pos[i + 1]
            v1 = (x1 - x0, y1 - y0)
            v2 = (x2 - x1, y2 - y1)
            mag1 = math.hypot(*v1)
            mag2 = math.hypot(*v2)
            if mag1 < 1e-6 or mag2 < 1e-6:
                continue
            cos_a = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (mag1 * mag2)))
            curvatures.append(math.acos(cos_a))

        mean_curvature = _mean(curvatures) if curvatures else 0.0

        # ── Click frequency (clicks per minute) ───────────────────────
        click_frequency = len(recent_clicks) / (self._window_sec / 60.0)

        # ── Idle ratio (fraction with no movement) ────────────────────
        # Count seconds with no movement events
        idle_seconds = 0.0
        for sec_start in range(int(self._window_sec)):
            sec_begin = cutoff + sec_start
            sec_end = sec_begin + 1.0
            has_move = any(sec_begin <= p[2] <= sec_end for p in recent_pos)
            if not has_move:
                idle_seconds += 1.0

        idle_ratio = idle_seconds / self._window_sec

        return {
            "mean_velocity": round(mean_vel, 3),
            "std_velocity": round(std_vel, 3),
            "mean_acceleration": round(mean_accel, 3),
            "mean_curvature": round(mean_curvature, 6),
            "click_frequency": round(click_frequency, 3),
            "idle_ratio": round(min(idle_ratio, 1.0), 4),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_mouse_features() -> dict:
    return {
        "mean_velocity": 0.0,
        "std_velocity": 0.0,
        "mean_acceleration": 0.0,
        "mean_curvature": 0.0,
        "click_frequency": 0.0,
        "idle_ratio": 1.0,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))
