"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/app_usage_monitor.py

Monitors the currently active window title and process name
using psutil + platform-specific window APIs.

Cross-platform approach:
  Windows: ctypes / win32gui
  macOS:   subprocess (osascript)
  Linux:   subprocess (xdotool)
"""

from __future__ import annotations

import logging
import platform
import subprocess
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _get_active_window_title() -> str:
    """Return the title of the currently focused window."""
    os_name = platform.system()
    try:
        if os_name == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or "Unknown"

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
        logger.debug("Could not get active window: %s", exc)
        return "Unknown"


class AppUsageMonitor:
    """
    Polls the active window every *poll_interval* seconds and
    records application usage durations.
    """

    def __init__(
        self,
        on_change: Optional[Callable[[str, float], None]] = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._current_app: str = ""
        self._app_times: dict[str, float] = {}

    def start(self, shutdown_event: Optional[threading.Event] = None) -> None:
        """Start the polling loop in a background thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, args=(shutdown_event,), daemon=True
        )
        self._thread.start()
        logger.info("AppUsageMonitor started.")

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self, shutdown_event: Optional[threading.Event]) -> None:
        last_app = ""
        last_switch_time = time.time()

        while self._running:
            if shutdown_event and shutdown_event.is_set():
                break

            current = _get_active_window_title()

            if current != last_app:
                duration = time.time() - last_switch_time
                if last_app:
                    self._app_times[last_app] = self._app_times.get(last_app, 0) + duration
                    if self._on_change:
                        self._on_change(last_app, duration)
                last_app = current
                last_switch_time = time.time()

            time.sleep(self._poll_interval)

    @property
    def usage_summary(self) -> dict[str, float]:
        """Return accumulated usage time per application (seconds)."""
        return dict(self._app_times)
