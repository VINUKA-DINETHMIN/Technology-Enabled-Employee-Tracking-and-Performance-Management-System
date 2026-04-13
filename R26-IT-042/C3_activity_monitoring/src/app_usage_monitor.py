"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/app_usage_monitor.py

AppUsageMonitor — Tracks the active foreground application and computes
app-switching behavioural features per configurable window (default 30 s).

Features extracted
──────────────────
  active_app_entropy    — Shannon entropy of app usage distribution
  app_switch_frequency  — app switches per minute
  total_focus_duration  — seconds spent in foreground apps
  top_app               — most-used app name (anonymised hash in production)

Cross-platform
──────────────
  Windows: ctypes.windll (no extra deps)
  macOS:   osascript subprocess
  Linux:   xdotool subprocess
"""

from __future__ import annotations

import logging
import math
import platform
import subprocess
import sys
import threading
import time
from collections import defaultdict
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Polling interval for active window detection (seconds)
_POLL_INTERVAL = 1.0


def _get_active_app() -> str:
    """Return the name of the currently active application (cross-platform)."""
    os_name = platform.system()
    try:
        if os_name == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.c_ulong(0)
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            import psutil
            try:
                proc = psutil.Process(pid.value)
                return proc.name().replace(".exe", "").strip() or "Unknown"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return "Unknown"

        elif os_name == "Darwin":
            script = 'tell application "System Events" to get name of first process whose frontmost is true'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=2,
            )
            return result.stdout.strip() or "Unknown"

        else:  # Linux
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2,
            )
            return result.stdout.strip() or "Unknown"

    except Exception as exc:
        logger.debug("Could not get active app: %s", exc)
        return "Unknown"


class AppUsageMonitor:
    """
    Polls the active application every second and tracks usage durations.

    Usage
    ─────
    >>> monitor = AppUsageMonitor(window_sec=30)
    >>> monitor.start()
    >>> features = monitor.get_features()
    >>> monitor.stop()
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
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # List of (app_name, start_ts, end_ts) per window
        self._segments: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, shutdown_event: Optional[threading.Event] = None) -> None:
        """Start polling loop in a background daemon thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(shutdown_event,),
            daemon=True,
            name="AppUsageMonitor",
        )
        self._thread.start()
        logger.info("AppUsageMonitor started (window=%.0fs).", self._window_sec)

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        logger.info("AppUsageMonitor stopped.")

    def get_features(self) -> dict:
        """
        Compute and return app-usage features for the last window.

        Returns
        -------
        dict
            Keys: active_app_entropy, app_switch_frequency,
                  total_focus_duration, top_app
        """
        now = time.perf_counter()
        cutoff = now - self._window_sec

        with self._lock:
            recent = [s for s in self._segments if s["end_ts"] >= cutoff]

        if not recent:
            return _empty_app_features()

        # Clip segments to window boundary
        app_durations: dict[str, float] = defaultdict(float)
        switch_count = 0

        for seg in recent:
            start = max(seg["start_ts"], cutoff)
            end = min(seg["end_ts"], now)
            duration = max(end - start, 0.0)
            app_durations[seg["app"]] += duration

        # Switch count: count distinct consecutive app changes within window
        sorted_segs = sorted(recent, key=lambda s: s["start_ts"])
        for i in range(1, len(sorted_segs)):
            if sorted_segs[i]["app"] != sorted_segs[i - 1]["app"]:
                switch_count += 1

        # ── Shannon entropy ───────────────────────────────────────────
        total_time = sum(app_durations.values())
        entropy = 0.0
        if total_time > 0:
            for dur in app_durations.values():
                p = dur / total_time
                if p > 0:
                    entropy -= p * math.log2(p)

        # ── Top app ───────────────────────────────────────────────────
        top_app = max(app_durations, key=app_durations.__getitem__) if app_durations else "Unknown"

        # ── Switch frequency (switches per minute) ────────────────────
        elapsed_min = self._window_sec / 60.0
        app_switch_frequency = switch_count / elapsed_min

        return {
            "active_app_entropy": round(entropy, 4),
            "app_switch_frequency": round(app_switch_frequency, 3),
            "total_focus_duration": round(total_time, 2),
            "top_app": top_app,
        }

    @property
    def current_app(self) -> str:
        """Return the currently active application name."""
        with self._lock:
            if self._segments:
                return self._segments[-1]["app"]
        return "Unknown"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll_loop(self, shutdown_event: Optional[threading.Event]) -> None:
        last_app = ""
        last_ts = time.perf_counter()

        while self._running:
            if shutdown_event and shutdown_event.is_set():
                break

            current_app = _get_active_app()
            now = time.perf_counter()

            with self._lock:
                if current_app != last_app:
                    if last_app:
                        # Close previous app segment without duplicating entries.
                        if self._segments and self._segments[-1]["app"] == last_app:
                            self._segments[-1]["end_ts"] = now
                        else:
                            self._segments.append({
                                "app": last_app,
                                "start_ts": last_ts,
                                "end_ts": now,
                            })

                    # Start a new segment for the current app immediately.
                    self._segments.append({
                        "app": current_app,
                        "start_ts": now,
                        "end_ts": now,
                    })
                    last_app = current_app
                    last_ts = now
                else:
                    # Update end_ts of current ongoing segment
                    if self._segments and self._segments[-1]["app"] == current_app:
                        self._segments[-1]["end_ts"] = now
                    else:
                        self._segments.append({
                            "app": current_app,
                            "start_ts": last_ts,
                            "end_ts": now,
                        })

                # Prune old segments
                cutoff = now - self._window_sec * 3
                self._segments = [s for s in self._segments if s["end_ts"] >= cutoff]

            time.sleep(_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_app_features() -> dict:
    return {
        "active_app_entropy": 0.0,
        "app_switch_frequency": 0.0,
        "total_focus_duration": 0.0,
        "top_app": "Unknown",
    }
