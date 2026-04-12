"""
R26-IT-042 — Admin Panel
dashboard/app_usage_tracker.py

AppUsageTrackerUI — CustomTkinter component for displaying employee app usage
analytics with time range selection, summary cards, and detailed table.

Usage
─────
>>> tracker = AppUsageTrackerUI(parent_frame, db_client=db, emp_id="EMP001")
>>> tracker.show()
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from common.database import MongoDBClient

# Color constants (match admin_panel.py)
C_BG        = "#0b0e17"
C_CARD      = "#151b2d"
C_BORDER    = "#1e2a40"
C_TEXT      = "#e2e8f0"
C_MUTED     = "#64748b"
C_GREEN     = "#22c55e"
C_BLUE      = "#3b82f6"
C_AMBER     = "#f59e0b"
C_RED       = "#ef4444"
C_TEAL      = "#14b8a6"
C_TEAL_D    = "#0d9488"


class AppUsageTrackerUI:
    """
    CustomTkinter UI for app usage analytics.
    Shows summary cards, app usage table, and time range controls.
    """

    def __init__(
        self,
        parent: ctk.CTkFrame,
        db_client: Optional["MongoDBClient"] = None,
        emp_id: str = "UNKNOWN",
    ) -> None:
        self._parent = parent
        self._db = db_client
        self._emp_id = emp_id
        self._current_period = "today"
        self._refresh_active = False
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_after_id = None
        self._main_frame: Optional[ctk.CTkFrame] = None

    def show(self) -> None:
        """Build and display the app usage tracker in parent frame."""
        self._main_frame = ctk.CTkFrame(
            self._parent, fg_color=C_CARD, corner_radius=12
        )
        self._main_frame.pack(fill="x", pady=(0, 12))

        # Header with title
        hdr = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            hdr,
            text="App Usage Analytics",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C_TEXT,
        ).pack(side="left")

        # Time range buttons
        btn_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_frame.pack(side="right")

        for period, label in [("today", "Today"), ("week", "Week"), ("month", "Month")]:
            btn = ctk.CTkButton(
                btn_frame,
                text=label,
                width=60,
                height=24,
                fg_color=C_TEAL if period == "today" else C_BORDER,
                hover_color=C_TEAL_D if period == "today" else C_BLUE,
                font=ctk.CTkFont(size=10),
                command=lambda p=period: self._set_period(p),
            )
            btn.pack(side="left", padx=2)

        # Summary cards container
        cards_frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        cards_frame.pack(fill="x", padx=16, pady=8)

        self._card_most_app = self._make_card(cards_frame, "Most Used App", "—")
        self._card_total_time = self._make_card(cards_frame, "Total Active Time", "—")
        self._card_app_count = self._make_card(cards_frame, "Apps Used Count", "—")
        self._card_avg_focus = self._make_card(cards_frame, "Avg Focus Time", "—")

        # Apps table header
        table_hdr = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        table_hdr.pack(fill="x", padx=16, pady=(12, 4))

        col_w = [150, 80, 60, 80, 80, 100]  # App, Time, Sessions, %, Risk, Last Used
        labels = [
            "Application",
            "Time Spent",
            "Sessions",
            "Usage %",
            "Risk",
            "Last Used",
        ]

        for label, width in zip(labels, col_w):
            ctk.CTkLabel(
                table_hdr,
                text=label,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=C_MUTED,
                width=width,
            ).pack(side="left", padx=4)

        # Apps table rows container
        self._table_frame = ctk.CTkScrollableFrame(
            self._main_frame, fg_color=C_BG, corner_radius=0, height=200
        )
        self._table_frame.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        # Load initial data
        self._refresh_data()

        # Keep analytics view updated while detail window is open.
        self.start_auto_refresh(interval_minutes=1)

    def _make_card(
        self, parent: ctk.CTkFrame, label: str, value: str
    ) -> ctk.CTkLabel:
        """Create and return a summary card label."""
        card = ctk.CTkFrame(parent, fg_color=C_BORDER, corner_radius=8)
        card.pack(side="left", expand=True, fill="both", padx=2)

        ctk.CTkLabel(
            card,
            text=label,
            font=ctk.CTkFont(size=9),
            text_color=C_MUTED,
        ).pack(pady=(4, 0), padx=8)

        val_label = ctk.CTkLabel(
            card,
            text=value,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C_TEXT,
        )
        val_label.pack(pady=(0, 4), padx=8)

        return val_label

    def _set_period(self, period: str) -> None:
        """Change time period and refresh."""
        self._current_period = period
        self._refresh_data()

    def _refresh_data(self) -> None:
        """Fetch and display app usage data."""
        if self._db is None or not self._db.is_connected:
            return

        try:
            from C3_activity_monitoring.src.app_usage_analytics import AppUsageAnalytics

            analytics = AppUsageAnalytics(db_client=self._db)
            summary = analytics.get_apps_by_period(
                user_id=self._emp_id, period=self._current_period
            )

            # Update summary cards
            self._card_most_app.configure(text=summary.most_used_app)
            self._card_total_time.configure(text=summary.get_hours_string(summary.total_time_sec))
            self._card_app_count.configure(text=str(summary.app_count))
            self._card_avg_focus.configure(text=summary.get_hours_string(summary.avg_focus_time))

            # Clear and populate table
            for widget in self._table_frame.winfo_children():
                widget.destroy()

            if not summary.apps:
                ctk.CTkLabel(
                    self._table_frame,
                    text="No app usage data available.",
                    text_color=C_MUTED,
                    font=ctk.CTkFont(size=11),
                ).pack(pady=8)
                return

            for app_data in summary.apps:
                self._render_app_row(summary, app_data)

        except Exception as exc:
            ctk.CTkLabel(
                self._table_frame,
                text=f"Error: {exc}",
                text_color=C_RED,
                font=ctk.CTkFont(size=11),
            ).pack(pady=8)

    def _render_app_row(self, summary, app_data: dict) -> None:
        """Render a single app usage row in the table."""
        row = ctk.CTkFrame(self._table_frame, fg_color=C_BORDER, corner_radius=6)
        row.pack(fill="x", pady=2)

        app_name = app_data.get("app", "Unknown")
        time_sec = app_data.get("time_sec", 0.0)
        sessions = app_data.get("sessions", 0)
        percentage = app_data.get("percentage", 0.0)
        risk_score = app_data.get("avg_risk_score", 0.0)
        last_used = app_data.get("last_used", "—")

        # Format last used
        try:
            if last_used:
                # Convert UTC/offset timestamp to local timezone for display.
                dt = datetime.fromisoformat(str(last_used).replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                last_used_str = dt.strftime("%H:%M")
            else:
                last_used_str = "—"
        except Exception:
            last_used_str = "—"

        # Determine app color
        unproductive_apps = [
            "youtube",
            "netflix",
            "facebook",
            "instagram",
            "tiktok",
            "gaming",
            "steam",
        ]
        app_color = C_RED if app_name.lower() in unproductive_apps else C_GREEN

        # Format time spent
        hours = int(time_sec // 3600)
        minutes = int((time_sec % 3600) // 60)
        time_str = f"{hours}h {minutes:02d}m" if hours > 0 else f"{minutes}m"

        # Format risk color
        risk_color = C_RED if risk_score >= 50 else (C_AMBER if risk_score >= 25 else C_GREEN)

        # Render columns
        ctk.CTkLabel(
            row,
            text=app_name,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=app_color,
            width=150,
            anchor="w",
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkLabel(
            row,
            text=time_str,
            font=ctk.CTkFont(size=10),
            text_color=C_TEXT,
            width=80,
        ).pack(side="left", padx=4)

        ctk.CTkLabel(
            row,
            text=str(sessions),
            font=ctk.CTkFont(size=10),
            text_color=C_TEXT,
            width=60,
        ).pack(side="left", padx=4)

        ctk.CTkLabel(
            row,
            text=f"{percentage:.1f}%",
            font=ctk.CTkFont(size=10),
            text_color=C_TEXT,
            width=80,
        ).pack(side="left", padx=4)

        ctk.CTkLabel(
            row,
            text=f"{risk_score:.0f}",
            font=ctk.CTkFont(size=10),
            text_color=risk_color,
            width=80,
        ).pack(side="left", padx=4)

        ctk.CTkLabel(
            row,
            text=last_used_str,
            font=ctk.CTkFont(size=10),
            text_color=C_MUTED,
            width=100,
        ).pack(side="left", padx=4)

    def start_auto_refresh(self, interval_minutes: int = 5) -> None:
        """Start periodic refresh using Tk's UI thread scheduler."""
        if self._refresh_active:
            return

        self._refresh_active = True
        delay_ms = max(10_000, int(interval_minutes * 60 * 1000))

        def _tick() -> None:
            if not self._refresh_active:
                return
            try:
                self._refresh_data()
            finally:
                if self._main_frame is not None and self._main_frame.winfo_exists():
                    self._refresh_after_id = self._main_frame.after(delay_ms, _tick)

        if self._main_frame is not None and self._main_frame.winfo_exists():
            self._refresh_after_id = self._main_frame.after(delay_ms, _tick)

    def stop_auto_refresh(self) -> None:
        """Stop auto-refresh loop."""
        self._refresh_active = False
        if self._refresh_after_id is not None and self._main_frame is not None:
            try:
                self._main_frame.after_cancel(self._refresh_after_id)
            except Exception:
                pass
        self._refresh_after_id = None
