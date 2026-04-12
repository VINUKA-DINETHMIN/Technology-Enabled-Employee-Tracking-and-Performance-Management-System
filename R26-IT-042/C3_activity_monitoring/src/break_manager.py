"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/break_manager.py

BreakManager — Manages the 4 configurable daily breaks (1 lunch + 3 short),
controls monitoring pause/resume, shows countdown UI, detects overruns, and
triggers face liveness re-check when a break ends.

Break config stored in config/break_config.json (AES-encrypted).

Overrun thresholds
──────────────────
  Lunch:   > 5 minutes past scheduled end → LOW alert + policy_violation
  Short:   > 3 minutes past scheduled end → LOW alert + policy_violation
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

import customtkinter as ctk

logger = logging.getLogger(__name__)

# Paths
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
_BREAK_CONFIG_FILE = _CONFIG_DIR / "break_config.json"

# Default break schedule
_DEFAULT_BREAKS = {
    "lunch":   {"start": "12:00", "duration_minutes": 60},
    "short_1": {"start": "10:00", "duration_minutes": 15},
    "short_2": {"start": "15:00", "duration_minutes": 15},
    "short_3": {"start": "17:00", "duration_minutes": 15},
}

# Overrun thresholds (minutes)
_LUNCH_OVERRUN_MINUTES = 5
_SHORT_OVERRUN_MINUTES = 3


class BreakManager:
    """
    Manages scheduled break windows with full UI and monitoring control.

    Usage
    ─────
    >>> bm = BreakManager(trackers=(keyboard, mouse, app))
    >>> bm.load_breaks()
    >>> bm.start_timer_if_break_starting()
    """

    def __init__(
        self,
        trackers: tuple = (),
        db_client=None,
        alert_sender=None,
        user_id: str = "UNKNOWN",
    ) -> None:
        """
        Parameters
        ----------
        trackers:
            Tuple of (KeyboardTracker, MouseTracker, AppUsageMonitor).
        db_client:
            MongoDBClient for saving policy_violations.
        alert_sender:
            AlertSender instance.
        user_id:
            Employee ID for alert attribution.
        """
        self._trackers = trackers
        self._db = db_client
        self._alert_sender = alert_sender
        self._user_id = user_id

        self._breaks: dict = {}
        self._active_break: Optional[str] = None
        self._break_start_time: Optional[datetime] = None
        self._monitoring_paused: bool = False
        self._countdown_window: Optional[ctk.CTkToplevel] = None
        self._countdown_label: Optional[ctk.CTkLabel] = None
        self._countdown_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        # Load encryptor lazily
        self._enc = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure_breaks(self, breaks: dict) -> None:
        """
        Save break configuration to encrypted JSON file.

        Parameters
        ----------
        breaks:
            Dict matching: {break_name: {start: "HH:MM", duration_minutes: int}}
        """
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(breaks, ensure_ascii=False)
        enc = self._get_encryptor()
        if enc:
            encrypted = enc.encrypt(raw).decode("utf-8")
            _BREAK_CONFIG_FILE.write_text(encrypted, encoding="utf-8")
        else:
            _BREAK_CONFIG_FILE.write_text(raw, encoding="utf-8")
        self._breaks = breaks
        logger.info("Break config saved to %s", _BREAK_CONFIG_FILE)

    def load_breaks(self) -> dict:
        """
        Load break configuration from encrypted JSON file.
        Falls back to defaults if file does not exist.

        Returns
        -------
        dict
            The break schedule dict.
        """
        if not _BREAK_CONFIG_FILE.exists():
            logger.info("No break config found — using defaults.")
            self._breaks = _DEFAULT_BREAKS.copy()
            return self._breaks

        try:
            raw = _BREAK_CONFIG_FILE.read_text(encoding="utf-8")
            enc = self._get_encryptor()
            if enc and not raw.strip().startswith("{"):
                raw = enc.decrypt(raw.encode("utf-8"))
            self._breaks = json.loads(raw)
        except Exception as exc:
            logger.warning("Failed to load break config: %s — using defaults.", exc)
            self._breaks = _DEFAULT_BREAKS.copy()

        return self._breaks

    def get_breaks(self) -> dict:
        """Return the currently loaded break schedule."""
        return self._breaks or _DEFAULT_BREAKS.copy()

    # ------------------------------------------------------------------
    # Break state
    # ------------------------------------------------------------------

    def is_in_break(self) -> bool:
        """Return True if the current time falls within any break window."""
        with self._lock:
            if self._monitoring_paused and self._active_break is not None:
                return True
        return self._get_scheduled_active_break() is not None

    def get_active_break(self) -> Optional[str]:
        """
        Return the name of the active break ("lunch", "short_1", etc.)
        or None if not in a break.
        """
        with self._lock:
            if self._monitoring_paused and self._active_break is not None:
                return self._active_break

        return self._get_scheduled_active_break()

    def _get_scheduled_active_break(self) -> Optional[str]:
        """Resolve active break from configured daily schedule."""
        if not self._breaks:
            self.load_breaks()

        now = datetime.now().time()
        for name, cfg in self._breaks.items():
            try:
                h, m = map(int, cfg["start"].split(":"))
                start = dtime(h, m)
                end_minutes = h * 60 + m + int(cfg["duration_minutes"])
                end = dtime(end_minutes // 60 % 24, end_minutes % 60)
                if start <= now <= end:
                    return name
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Timer / countdown
    # ------------------------------------------------------------------

    def start_break_timer(self, break_type: str) -> None:
        """
        Start the break countdown and pause monitoring.

        Parameters
        ----------
        break_type:
            "lunch" | "short_1" | "short_2" | "short_3"
        """
        cfg = self._breaks.get(break_type, _DEFAULT_BREAKS.get(break_type, {}))
        duration_sec = int(cfg.get("duration_minutes", 15)) * 60

        with self._lock:
            if self._countdown_timer is not None:
                self._countdown_timer.cancel()
            self._active_break = break_type
            self._break_start_time = datetime.now()

        self.pause_monitoring()
        self._show_break_started_notice()
        self._show_break_window(break_type, duration_sec)

        # Overrun check timer
        overrun_sec = (
            _LUNCH_OVERRUN_MINUTES * 60
            if break_type == "lunch"
            else _SHORT_OVERRUN_MINUTES * 60
        )
        total_allowed = duration_sec + overrun_sec
        self._countdown_timer = threading.Timer(
            total_allowed, self._on_overrun_detected, args=(break_type,)
        )
        self._countdown_timer.daemon = True
        self._countdown_timer.start()
        logger.info("Break timer started: %s (%d min)", break_type, duration_sec // 60)

    def check_overrun(self) -> bool:
        """Return True if the employee has exceeded the scheduled break duration."""
        if self._active_break is None or self._break_start_time is None:
            return False
        cfg = self._breaks.get(self._active_break, {})
        duration_min = int(cfg.get("duration_minutes", 15))
        threshold_min = (
            duration_min + _LUNCH_OVERRUN_MINUTES
            if self._active_break == "lunch"
            else duration_min + _SHORT_OVERRUN_MINUTES
        )
        elapsed = (datetime.now() - self._break_start_time).total_seconds() / 60.0
        return elapsed > threshold_min

    # ------------------------------------------------------------------
    # Monitoring control
    # ------------------------------------------------------------------

    def pause_monitoring(self) -> None:
        """Stop all trackers completely during a break."""
        with self._lock:
            if self._monitoring_paused:
                return
            self._monitoring_paused = True

        for tracker in self._trackers:
            try:
                tracker.stop()
            except Exception as exc:
                logger.debug("Tracker stop error: %s", exc)

        logger.info("Monitoring paused (break started).")

    def resume_monitoring(self) -> None:
        """Restart all trackers after break ends + trigger face liveness check."""
        with self._lock:
            if not self._monitoring_paused:
                return
            self._monitoring_paused = False
            self._active_break = None
            self._break_start_time = None

        if self._countdown_timer:
            self._countdown_timer.cancel()
            self._countdown_timer = None

        for tracker in self._trackers:
            try:
                tracker.start()
            except Exception as exc:
                logger.debug("Tracker re-start error: %s", exc)

        # Trigger face liveness check
        threading.Thread(target=self._run_return_liveness, daemon=True).start()
        logger.info("Monitoring resumed (break ended).")

    # ------------------------------------------------------------------
    # Break loop (called from initialize_monitoring)
    # ------------------------------------------------------------------

    def _run_loop(self, shutdown_event: threading.Event) -> None:
        """Polls every 30 seconds to detect when a scheduled break starts."""
        last_seen_break: Optional[str] = None
        while not shutdown_event.is_set():
            active = self.get_active_break()
            if active and active != last_seen_break:
                # Break just started
                self.start_break_timer(active)
                last_seen_break = active
            elif not active and last_seen_break:
                # Break window ended → resume if not already
                if self._monitoring_paused:
                    self.resume_monitoring()
                last_seen_break = None
            shutdown_event.wait(timeout=30.0)

    # ------------------------------------------------------------------
    # Overrun handler
    # ------------------------------------------------------------------

    def _on_overrun_detected(self, break_type: str) -> None:
        """Called when overrun threshold is exceeded."""
        logger.warning("Break overrun detected: %s", break_type)

        # Notify employee locally when break limit is exceeded.
        self._show_overrun_notice(break_type)

        # Resume monitoring immediately
        self.resume_monitoring()

        # Send alert
        if self._alert_sender:
            try:
                self._alert_sender.send_alert(
                    user_id=self._user_id,
                    risk_score=30.0,
                    factors=["break_overrun"],
                    level="LOW",
                    extra={"reason": "break_overrun", "break_type": break_type},
                )
            except Exception as exc:
                logger.error("Alert send error (overrun): %s", exc)

        self._persist_overrun_alert(break_type)

        # Log policy violation
        self._log_policy_violation(break_type)

    def _persist_overrun_alert(self, break_type: str) -> None:
        """Persist break-overrun alert so Admin Alerts tab can always display it."""
        if self._db is None or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("alerts")
            if col is None:
                return
            col.insert_one({
                "type": "alert",
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": self._user_id,
                "session_id": None,
                "risk_score": 30.0,
                "level": "LOW",
                "factors": ["break_overrun"],
                "reason": "break_overrun",
                "break_type": break_type,
                "resolved": False,
            })
        except Exception as exc:
            logger.error("Break overrun alert persist error: %s", exc)

    def _log_policy_violation(self, break_type: str) -> None:
        """Write a policy_violation document to MongoDB."""
        if self._db is None or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("policy_violations")
            if col is not None:
                col.insert_one({
                    "user_id": self._user_id,
                    "violation_type": "break_overrun",
                    "break_type": break_type,
                    "timestamp": datetime.utcnow().isoformat(),
                    "threshold_minutes": (
                        _LUNCH_OVERRUN_MINUTES if break_type == "lunch"
                        else _SHORT_OVERRUN_MINUTES
                    ),
                })
        except Exception as exc:
            logger.error("Policy violation log error: %s", exc)

    # ------------------------------------------------------------------
    # Liveness re-check on break end
    # ------------------------------------------------------------------

    def _run_return_liveness(self) -> None:
        """Trigger C2 face liveness check when employee returns from break."""
        try:
            result = None
            try:
                from C3_activity_monitoring.src.session_monitor import run_post_break_session_check
                result = run_post_break_session_check(user_id=self._user_id)
            except ImportError:
                from C2_facial_liveness.src import run_liveness_check
                result = run_liveness_check(user_id=self._user_id)

            if not result:
                logger.warning("Post-break liveness check FAILED for %s", self._user_id)
                if self._alert_sender:
                    self._alert_sender.send_alert(
                        user_id=self._user_id,
                        risk_score=80.0,
                        factors=["post_break_liveness_fail"],
                        level="HIGH",
                    )
        except ImportError:
            logger.debug("C2 liveness not available — skipping post-break check.")
        except Exception as exc:
            logger.error("Post-break liveness error: %s", exc)

    def _show_break_started_notice(self) -> None:
        """Show lightweight top-most notification when break starts."""
        def _build_notice():
            try:
                note = ctk.CTkToplevel()
                note.title("Break Notice")
                note.geometry("300x90")
                note.resizable(False, False)
                note.attributes("-topmost", True)
                note.configure(fg_color="#0f1117")

                ctk.CTkLabel(
                    note,
                    text="Break started - monitoring paused",
                    text_color="#e2e8f0",
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).pack(expand=True, padx=12, pady=18)
                note.after(2200, note.destroy)
                note.mainloop()
            except Exception:
                pass

        threading.Thread(target=_build_notice, daemon=True).start()

    def _show_overrun_notice(self, break_type: str) -> None:
        """Show top-most warning when break time exceeded."""
        def _build_notice():
            try:
                note = ctk.CTkToplevel()
                note.title("Break Exceeded")
                note.geometry("380x120")
                note.resizable(False, False)
                note.attributes("-topmost", True)
                note.configure(fg_color="#2b1111")

                msg = f"{break_type.replace('_', ' ').title()} exceeded. Please return to work."
                ctk.CTkLabel(
                    note,
                    text=msg,
                    text_color="#fecaca",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    wraplength=340,
                ).pack(expand=True, padx=14, pady=(18, 8))

                ctk.CTkLabel(
                    note,
                    text="Admin has been notified.",
                    text_color="#fca5a5",
                    font=ctk.CTkFont(size=11),
                ).pack(pady=(0, 14))

                note.after(3500, note.destroy)
                note.mainloop()
            except Exception:
                pass

        threading.Thread(target=_build_notice, daemon=True).start()

    # ------------------------------------------------------------------
    # Break countdown UI
    # ------------------------------------------------------------------

    def _show_break_window(self, break_type: str, duration_sec: int) -> None:
        """Show always-on-top break countdown window."""
        def _build():
            try:
                win = ctk.CTkToplevel()
                win.title("Break Time")
                win.geometry("320x220")
                win.resizable(False, False)
                win.attributes("-topmost", True)
                win.configure(fg_color="#0f1117")

                labels = {
                    "lunch": "Lunch Break",
                    "short_1": "Short Break 1",
                    "short_2": "Short Break 2",
                    "short_3": "Short Break 3",
                }
                break_label = labels.get(break_type, "Break")

                ctk.CTkLabel(
                    win,
                    text=break_label,
                    font=ctk.CTkFont(size=20, weight="bold"),
                    text_color="#22c55e",
                ).pack(pady=(20, 4))

                ctk.CTkLabel(
                    win,
                    text="Monitoring paused",
                    font=ctk.CTkFont(size=12),
                    text_color="#64748b",
                ).pack()

                self._countdown_label = ctk.CTkLabel(
                    win,
                    text=_format_time(duration_sec),
                    font=ctk.CTkFont(size=36, weight="bold"),
                    text_color="#e2e8f0",
                )
                self._countdown_label.pack(pady=14)

                ctk.CTkButton(
                    win,
                    text="Return to Work",
                    height=40,
                    fg_color="#3b82f6",
                    hover_color="#2563eb",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    command=lambda: self._on_early_return(win),
                ).pack(padx=40, fill="x", pady=(0, 16))

                self._countdown_window = win
                remaining = duration_sec
                self._tick_countdown(win, remaining)
                win.mainloop()

            except Exception as exc:
                logger.warning("Break window error: %s", exc)

        t = threading.Thread(target=_build, daemon=True)
        t.start()

    def _tick_countdown(self, win, remaining: int) -> None:
        if remaining < -300:  # Hard limit 5 min overrun, then auto-close
            try:
                win.destroy()
            except Exception:
                pass
            if self._monitoring_paused:
                self.resume_monitoring()
            return
            
        try:
            if self._countdown_label:
                # Format with minus sign for overruns
                display_time = _format_time(abs(remaining))
                if remaining < 0:
                    display_time = f"-{display_time}"
                    self._countdown_label.configure(text_color="#ef4444")  # C_RED
                    win.title("BREAK OVERRUN!")
                else:
                    self._countdown_label.configure(text=display_time)
                
                self._countdown_label.configure(text=display_time)
                
            win.after(1000, lambda: self._tick_countdown(win, remaining - 1))
        except Exception:
            pass

    def _on_early_return(self, win) -> None:
        """Employee pressed 'Return to Work' before break ends."""
        try:
            win.destroy()
        except Exception:
            pass
        self.resume_monitoring()

    # ------------------------------------------------------------------
    # Config UI popup
    # ------------------------------------------------------------------

    def show_configure_popup(self, parent=None) -> None:
        """Open the break configuration popup window."""
        breaks = self._breaks or _DEFAULT_BREAKS.copy()

        popup = ctk.CTkToplevel(parent)
        popup.title("Configure Break Times")
        popup.geometry("440x480")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        popup.configure(fg_color="#0f1117")

        ctk.CTkLabel(
            popup,
            text="Set Your Break Schedule",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#e2e8f0",
        ).pack(pady=(20, 4))

        ctk.CTkLabel(
            popup, text="Changes take effect from the next session",
            font=ctk.CTkFont(size=11), text_color="#64748b",
        ).pack(pady=(0, 16))

        frame = ctk.CTkScrollableFrame(popup, fg_color="#1a1d27", corner_radius=12)
        frame.pack(padx=20, fill="both", expand=True)

        entries: dict[str, dict] = {}

        def _add_row(parent_frame, key: str, label: str, cfg: dict) -> None:
            row_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(
                row_frame, text=label,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#94a3b8", anchor="w",
            ).pack(fill="x")

            sub = ctk.CTkFrame(row_frame, fg_color="transparent")
            sub.pack(fill="x")

            time_var = ctk.StringVar(value=cfg.get("start", "09:00"))
            dur_var = ctk.StringVar(value=str(cfg.get("duration_minutes", 15)))

            ctk.CTkLabel(sub, text="Start:", text_color="#64748b", font=ctk.CTkFont(size=11), width=40).pack(side="left")
            ctk.CTkEntry(sub, textvariable=time_var, width=80, placeholder_text="HH:MM").pack(side="left", padx=(2, 16))
            ctk.CTkLabel(sub, text="Duration (min):", text_color="#64748b", font=ctk.CTkFont(size=11)).pack(side="left")
            ctk.CTkEntry(sub, textvariable=dur_var, width=60).pack(side="left", padx=2)

            entries[key] = {"time_var": time_var, "dur_var": dur_var}

        break_labels = {
            "lunch":   "Lunch Break",
            "short_1": "Short Break 1",
            "short_2": "Short Break 2",
            "short_3": "Short Break 3",
        }
        for key, lbl in break_labels.items():
            _add_row(frame, key, lbl, breaks.get(key, _DEFAULT_BREAKS.get(key, {})))

        def _save():
            new_cfg = {}
            for key, ev in entries.items():
                new_cfg[key] = {
                    "start": ev["time_var"].get().strip(),
                    "duration_minutes": int(ev["dur_var"].get().strip() or 15),
                }
            self.configure_breaks(new_cfg)
            popup.destroy()

        def _reset():
            for key, ev in entries.items():
                defaults = _DEFAULT_BREAKS.get(key, {})
                ev["time_var"].set(defaults.get("start", "09:00"))
                ev["dur_var"].set(str(defaults.get("duration_minutes", 15)))

        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=12)
        ctk.CTkButton(btn_row, text="Reset to Defaults", fg_color="#374151", hover_color="#4b5563", command=_reset).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Save", fg_color="#3b82f6", hover_color="#2563eb", command=_save).pack(side="right")

    # ------------------------------------------------------------------
    # Old interface compatibility
    # ------------------------------------------------------------------

    def should_suppress_alerts(self) -> bool:
        """Legacy compatibility — delegates to is_in_break()."""
        return self.is_in_break()

    def current_break_name(self) -> Optional[str]:
        """Legacy compatibility — delegates to get_active_break()."""
        return self.get_active_break()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_encryptor(self):
        if self._enc is not None:
            return self._enc
        try:
            from common.encryption import AESEncryptor
            self._enc = AESEncryptor()
        except Exception:
            pass
        return self._enc


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _format_time(seconds: int) -> str:
    """Format seconds as MM:SS string."""
    m, s = divmod(max(seconds, 0), 60)
    return f"{m:02d}:{s:02d}"
