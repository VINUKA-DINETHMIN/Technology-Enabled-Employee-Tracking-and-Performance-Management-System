"""
R26-IT-042 — Employee Activity Monitoring System
dashboard/admin_panel.py

Full CustomTkinter Admin Panel with sidebar navigation:
  - Dashboard   : Live employee overview, color-coded risk scores
  - Alerts      : Real-time WebSocket feed, alert management
  - Tasks       : Task assignment with tkcalendar date picker
  - Attendance  : Date-filterable attendance log
  - Settings    : Application configuration

Run standalone:
    python dashboard/admin_panel.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Path bootstrap ────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import customtkinter as ctk
from tkinter import messagebox
import tkinter as tk

try:
    from tkcalendar import DateEntry
    _HAS_CALENDAR = True
except ImportError:
    _HAS_CALENDAR = False

from common.database import MongoDBClient
from common.alerts import AlertSender
from config.settings import settings

# ── Appearance ────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Color palette
C_BG        = "#0b0e17"
C_SIDEBAR   = "#0f1420"
C_CARD      = "#151b2d"
C_BORDER    = "#1e2a40"
C_TEAL      = "#14b8a6"
C_TEAL_D    = "#0d9488"
C_RED       = "#ef4444"
C_AMBER     = "#f59e0b"
C_GREEN     = "#22c55e"
C_TEXT      = "#e2e8f0"
C_MUTED     = "#64748b"
C_BLUE      = "#3b82f6"

POLL_INTERVAL_MS = 10_000   # 10 seconds

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _risk_color(score: float) -> str:
    if score < 50:
        return C_GREEN
    if score < 75:
        return C_AMBER
    return C_RED


def _level_color(level: str) -> str:
    return {
        "LOW": "#6366f1",
        "MEDIUM": C_AMBER,
        "HIGH": C_RED,
        "CRITICAL": "#dc2626",
    }.get(level.upper(), C_MUTED)


def _play_alert_sound() -> None:
    """Play system beep for CRITICAL alerts (cross-platform)."""
    try:
        if sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        elif sys.platform == "darwin":
            os.system("afplay /System/Library/Sounds/Funk.aiff &")
    except Exception:
        pass


def _fmt_time(ts_str: str) -> str:
    """Format ISO timestamp to HH:MM string."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return ts_str[:5] if ts_str else "--"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Summary Card Widget
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SummaryCard(ctk.CTkFrame):
    def __init__(self, parent, title: str, value: str, accent: str = C_TEAL, **kw):
        super().__init__(parent, fg_color=C_CARD, corner_radius=14, **kw)
        ctk.CTkLabel(
            self, text=title,
            font=ctk.CTkFont(size=11), text_color=C_MUTED,
        ).pack(anchor="w", padx=16, pady=(14, 2))
        self._val = ctk.CTkLabel(
            self, text=value,
            font=ctk.CTkFont(size=28, weight="bold"), text_color=accent,
        )
        self._val.pack(anchor="w", padx=16, pady=(0, 14))

    def set_value(self, val: str) -> None:
        self._val.configure(text=val)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Employee Detail Window
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EmployeeDetailWindow(ctk.CTkToplevel):
    def __init__(self, parent, employee: dict, db: MongoDBClient):
        super().__init__(parent)
        self._db = db
        self._emp = employee
        emp_id = employee.get("employee_id", "?")
        name = employee.get("full_name", emp_id)

        self.title(f"Employee Detail — {name}")
        self.geometry("780x600")
        self.configure(fg_color=C_BG)
        self.attributes("-topmost", True)

        # Header
        hdr = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=64)
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr, text=f"{name}  •  {emp_id}",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=C_TEXT,
        ).pack(side="left", padx=20, pady=16)

        body = ctk.CTkScrollableFrame(self, fg_color=C_BG)
        body.pack(fill="both", expand=True, padx=16, pady=16)

        # Risk score
        risk_doc = self._latest_activity(emp_id)
        risk = risk_doc.get("composite_risk_score", 0.0) if risk_doc else 0.0
        risk_color = _risk_color(risk)

        rframe = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
        rframe.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(rframe, text="Composite Risk Score", font=ctk.CTkFont(size=12), text_color=C_MUTED).pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(rframe, text=f"{risk:.1f} / 100", font=ctk.CTkFont(size=32, weight="bold"), text_color=risk_color).pack(anchor="w", padx=16)
        progress = ctk.CTkProgressBar(rframe, height=10, progress_color=risk_color, fg_color=C_BORDER)
        progress.set(risk / 100.0)
        progress.pack(fill="x", padx=16, pady=(4, 12))

        # Contributing factors
        if risk_doc:
            factors = risk_doc.get("contributing_factors", [])
            if factors:
                ff = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
                ff.pack(fill="x", pady=(0, 12))
                ctk.CTkLabel(ff, text="Contributing Factors", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))
                for f in factors:
                    ctk.CTkLabel(ff, text=f"  • {f.replace('_', ' ').title()}", font=ctk.CTkFont(size=12), text_color=C_AMBER).pack(anchor="w", padx=16)
                ctk.CTkFrame(ff, fg_color="transparent", height=8).pack()

        # Alert history
        alerts = self._get_alerts(emp_id)
        af = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
        af.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(af, text=f"Recent Alerts ({len(alerts)})", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        for a in alerts[:5]:
            row = ctk.CTkFrame(af, fg_color=C_BORDER, corner_radius=8)
            row.pack(fill="x", padx=16, pady=3)
            lvl = a.get("level", "LOW")
            ctk.CTkLabel(row, text=f"[{lvl}]", text_color=_level_color(lvl), font=ctk.CTkFont(size=11, weight="bold"), width=60).pack(side="left", padx=8, pady=6)
            ctk.CTkLabel(row, text=", ".join(a.get("factors", [])) or "—", text_color=C_TEXT, font=ctk.CTkFont(size=11)).pack(side="left")
            ctk.CTkLabel(row, text=_fmt_time(a.get("timestamp", "")), text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="right", padx=8)
        ctk.CTkFrame(af, fg_color="transparent", height=8).pack()

        # Tasks assigned
        tasks = self._get_tasks(emp_id)
        tf = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
        tf.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(tf, text=f"Assigned Tasks ({len(tasks)})", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        for t in tasks[:5]:
            row = ctk.CTkFrame(tf, fg_color=C_BORDER, corner_radius=8)
            row.pack(fill="x", padx=16, pady=3)
            status_color = {
                "pending": C_MUTED, "in_progress": C_AMBER, "completed": C_GREEN
            }.get(t.get("status", ""), C_MUTED)
            ctk.CTkLabel(row, text=t.get("title", "?"), text_color=C_TEXT, font=ctk.CTkFont(size=11)).pack(side="left", padx=8, pady=6)
            ctk.CTkLabel(row, text=t.get("status", "").replace("_", " ").title(), text_color=status_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=8)
        ctk.CTkFrame(tf, fg_color="transparent", height=8).pack()

        # Force screenshot button
        ctk.CTkButton(
            body,
            text="Force Screenshot",
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            height=38,
            command=lambda: self._force_screenshot(emp_id),
        ).pack(pady=(4, 0))

    def _latest_activity(self, emp_id: str) -> Optional[dict]:
        try:
            col = self._db.get_collection("activity_logs")
            if col:
                return col.find_one({"user_id": emp_id}, sort=[("timestamp", -1)])
        except Exception:
            pass
        return None

    def _get_alerts(self, emp_id: str) -> list:
        try:
            col = self._db.get_collection("alerts")
            if col:
                return list(col.find({"user_id": emp_id}, {"_id": 0}).sort("timestamp", -1).limit(10))
        except Exception:
            pass
        return []

    def _get_tasks(self, emp_id: str) -> list:
        try:
            col = self._db.get_collection("tasks")
            if col:
                return list(col.find({"employee_id": emp_id}, {"_id": 0}).sort("assigned_at", -1).limit(10))
        except Exception:
            pass
        return []

    def _force_screenshot(self, emp_id: str) -> None:
        try:
            from C3_activity_monitoring.src.screenshot_trigger import ScreenshotTrigger
            st = ScreenshotTrigger(db_client=self._db)
            st.capture(user_id=emp_id, session_id="admin_forced", risk_score=100.0)
            messagebox.showinfo("Screenshot", f"Screenshot captured for {emp_id}.")
        except Exception as exc:
            messagebox.showerror("Error", f"Screenshot failed: {exc}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Admin Panel
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AdminPanel(ctk.CTk):
    """
    Full-featured CustomTkinter Admin Panel for the monitoring system.
    """

    def __init__(self, db: Optional[MongoDBClient] = None) -> None:
        super().__init__()

        self._db = db or self._init_db()
        self._alert_sender = AlertSender(ws_url=settings.WEBSOCKET_URL)
        self._active_tab = "dashboard"
        self._employee_rows: dict = {}

        self.title(f"{settings.APP_NAME} — Admin Panel")
        w, h = 1200, 780
        self.geometry(f"{w}x{h}")
        self.minsize(900, 600)
        self.configure(fg_color=C_BG)

        # Centre on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._build_layout()
        self._switch_tab("dashboard")
        self._start_polling()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        # Sidebar
        self._sidebar = ctk.CTkFrame(self, width=210, fg_color=C_SIDEBAR, corner_radius=0)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # App logo/title area
        logo_frame = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=16, pady=(24, 20))
        ctk.CTkLabel(
            logo_frame, text=settings.APP_NAME,
            font=ctk.CTkFont(size=20, weight="bold"), text_color=C_TEAL,
        ).pack(anchor="w")
        ctk.CTkLabel(
            logo_frame, text="Admin Console",
            font=ctk.CTkFont(size=11), text_color=C_MUTED,
        ).pack(anchor="w")

        # Separator
        ctk.CTkFrame(self._sidebar, height=1, fg_color=C_BORDER).pack(fill="x", padx=16, pady=(0, 16))

        nav_items = [
            ("dashboard",  "  Dashboard"),
            ("employees",  "  Employees"),
            ("alerts",     "  Alerts"),
            ("tasks",      "  Tasks"),
            ("attendance", "  Attendance"),
            ("settings",   "  Settings"),
        ]
        self._nav_btns: dict = {}
        for tab_id, label in nav_items:
            btn = ctk.CTkButton(
                self._sidebar,
                text=label,
                height=44,
                font=ctk.CTkFont(size=13),
                anchor="w",
                fg_color="transparent",
                text_color=C_MUTED,
                hover_color="#1a2133",
                corner_radius=8,
                command=lambda t=tab_id: self._switch_tab(t),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_btns[tab_id] = btn

        # Main content area
        self._content = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        self._content.pack(side="right", fill="both", expand=True)

        # Header bar
        self._header = ctk.CTkFrame(self._content, height=58, fg_color=C_CARD, corner_radius=0)
        self._header.pack(fill="x")
        self._page_title = ctk.CTkLabel(
            self._header, text="Dashboard",
            font=ctk.CTkFont(size=17, weight="bold"), text_color=C_TEXT,
        )
        self._page_title.pack(side="left", padx=24, pady=14)

        self._conn_lbl = ctk.CTkLabel(
            self._header,
            text="⬤ Connected" if (self._db and self._db.is_connected) else "⬤ Offline",
            font=ctk.CTkFont(size=11),
            text_color=C_GREEN if (self._db and self._db.is_connected) else C_RED,
        )
        self._conn_lbl.pack(side="right", padx=24)

        # Tab frame container
        self._tab_frame = ctk.CTkFrame(self._content, fg_color=C_BG, corner_radius=0)
        self._tab_frame.pack(fill="both", expand=True)

        # Initialise all tab panels
        self._tabs: dict = {
            "dashboard":  self._build_dashboard_tab(),
            "employees":  self._build_employees_tab(),
            "alerts":     self._build_alerts_tab(),
            "tasks":      self._build_tasks_tab(),
            "attendance": self._build_attendance_tab(),
            "settings":   self._build_settings_tab(),
        }

    def _switch_tab(self, tab_id: str) -> None:
        self._active_tab = tab_id
        for tid, widget in self._tabs.items():
            widget.pack_forget()
        self._tabs[tab_id].pack(fill="both", expand=True)

        self._page_title.configure(text=tab_id.title())
        for tid, btn in self._nav_btns.items():
            if tid == tab_id:
                btn.configure(fg_color="#1e3a5f", text_color=C_TEAL)
            else:
                btn.configure(fg_color="transparent", text_color=C_MUTED)

    # ------------------------------------------------------------------
    # Dashboard Tab
    # ------------------------------------------------------------------

    def _build_dashboard_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color=C_BG, corner_radius=0)

        # Summary cards row
        cards_row = ctk.CTkFrame(frame, fg_color="transparent")
        cards_row.pack(fill="x", padx=20, pady=(16, 12))

        self._card_online    = SummaryCard(cards_row, "Employees Online", "—", accent=C_TEAL)
        self._card_alerts    = SummaryCard(cards_row, "Alerts Today",     "—", accent=C_AMBER)
        self._card_highrisk  = SummaryCard(cards_row, "High Risk",        "—", accent=C_RED)
        self._card_avg_prod  = SummaryCard(cards_row, "Avg Productivity",  "—", accent=C_GREEN)

        for card in (self._card_online, self._card_alerts, self._card_highrisk, self._card_avg_prod):
            card.pack(side="left", expand=True, fill="both", padx=6)

        # Employee list
        ctk.CTkLabel(
            frame, text="Live Employee Status",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEXT,
        ).pack(anchor="w", padx=24, pady=(8, 4))

        # Column headers
        hdr = ctk.CTkFrame(frame, fg_color=C_SIDEBAR, corner_radius=8, height=34)
        hdr.pack(fill="x", padx=20)
        for col, w in [("Employee", 180), ("ID", 90), ("Risk", 80), ("Location", 90), ("Status", 90), ("Last Seen", 90), ("", 80)]:
            ctk.CTkLabel(hdr, text=col, font=ctk.CTkFont(size=11), text_color=C_MUTED, width=w, anchor="w").pack(side="left", padx=4)

        self._emp_list_frame = ctk.CTkScrollableFrame(frame, fg_color=C_BG, corner_radius=0)
        self._emp_list_frame.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        return frame

    def _refresh_dashboard(self) -> None:
        """Refresh summary cards and employee list from MongoDB."""
        if not self._db or not self._db.is_connected:
            return
        try:
            sessions_col = self._db.get_collection("sessions")
            alerts_col   = self._db.get_collection("alerts")
            activity_col = self._db.get_collection("activity_logs")
            emps_col     = self._db.get_collection("employees")

            # Count active sessions
            online_cnt = sessions_col.count_documents({"status": "active"}) if sessions_col else 0
            self._card_online.set_value(str(online_cnt))

            # Alerts today
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            alerts_today = alerts_col.count_documents({"timestamp": {"$gte": today_start.isoformat()}}) if alerts_col else 0
            self._card_alerts.set_value(str(alerts_today))

            # High risk
            high_risk = activity_col.count_documents({"composite_risk_score": {"$gte": 75}}) if activity_col else 0
            self._card_highrisk.set_value(str(high_risk))

            # Avg productivity (last hour)
            pipeline = [{"$group": {"_id": None, "avg": {"$avg": "$productivity_score"}}}]
            avg_result = list(activity_col.aggregate(pipeline)) if activity_col else []
            avg_prod = avg_result[0]["avg"] if avg_result else 0.0
            self._card_avg_prod.set_value(f"{avg_prod:.0f}%")

            # Employee rows
            employees = list(emps_col.find({}, {"_id": 0, "password_hash": 0, "face_images": 0, "face_embedding": 0, "mfa_secret": 0}).limit(50)) if emps_col else []
            self._update_employee_list(employees, activity_col)

        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Dashboard refresh error: %s", exc)

    def _update_employee_list(self, employees: list, activity_col) -> None:
        for widget in self._emp_list_frame.winfo_children():
            widget.destroy()

        for emp in employees:
            emp_id = emp.get("employee_id", "?")
            # Get latest activity
            act = None
            try:
                if activity_col:
                    act = activity_col.find_one({"user_id": emp_id}, sort=[("timestamp", -1)])
            except Exception:
                pass

            risk = act.get("composite_risk_score", 0.0) if act else 0.0
            risk_color = _risk_color(risk)
            status = "Break" if (act and act.get("in_break")) else ("Idle" if risk == 0 else "Active")
            location = act.get("location_mode", "—") if act else "—"
            last_seen = _fmt_time(act.get("timestamp", "")) if act else "—"

            row = ctk.CTkFrame(self._emp_list_frame, fg_color=C_CARD, corner_radius=10, height=44)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=emp.get("full_name", emp_id), text_color=C_TEXT, font=ctk.CTkFont(size=12), width=180, anchor="w").pack(side="left", padx=8)
            ctk.CTkLabel(row, text=emp_id, text_color=C_MUTED, font=ctk.CTkFont(size=11), width=90, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"{risk:.0f}", text_color=risk_color, font=ctk.CTkFont(size=12, weight="bold"), width=80, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=location.title(), text_color=C_MUTED, font=ctk.CTkFont(size=11), width=90, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=status, text_color=C_TEXT, font=ctk.CTkFont(size=11), width=90, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=last_seen, text_color=C_MUTED, font=ctk.CTkFont(size=11), width=90, anchor="w").pack(side="left")
            ctk.CTkButton(
                row, text="Details", width=72, height=28,
                fg_color=C_BORDER, hover_color=C_BLUE,
                font=ctk.CTkFont(size=11),
                command=lambda e=emp: EmployeeDetailWindow(self, e, self._db),
            ).pack(side="right", padx=8)

    # ------------------------------------------------------------------
    # Employees Tab
    # ------------------------------------------------------------------

    def _build_employees_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color=C_BG, corner_radius=0)

        topbar = ctk.CTkFrame(frame, fg_color="transparent")
        topbar.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(topbar, text="Employee Directory", font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkButton(
            topbar, text="Register New Employee", width=180,
            fg_color=C_TEAL, hover_color=C_TEAL_D,
            command=self._open_registration,
        ).pack(side="right")

        self._all_emp_frame = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._all_emp_frame.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        return frame

    def _open_registration(self) -> None:
        try:
            from dashboard.employee_registration import EmployeeRegistration
            EmployeeRegistration(self, db=self._db)
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open registration: {exc}")

    # ------------------------------------------------------------------
    # Alerts Tab
    # ------------------------------------------------------------------

    def _build_alerts_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color=C_BG, corner_radius=0)

        topbar = ctk.CTkFrame(frame, fg_color="transparent")
        topbar.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(topbar, text="Alert Feed", font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkButton(topbar, text="Refresh", width=90, fg_color=C_BORDER, hover_color=C_BLUE, command=self._refresh_alerts).pack(side="right")

        self._alerts_frame = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._alerts_frame.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        return frame

    def _refresh_alerts(self) -> None:
        if not self._db or not self._db.is_connected:
            return
        for w in self._alerts_frame.winfo_children():
            w.destroy()
        try:
            col = self._db.get_collection("alerts")
            if not col:
                return
            alerts = list(col.find({}, {"_id": 0}).sort("timestamp", -1).limit(50))
            for alert in alerts:
                self._add_alert_card(alert)
        except Exception as exc:
            ctk.CTkLabel(self._alerts_frame, text=f"Error: {exc}", text_color=C_RED).pack()

    def _add_alert_card(self, alert: dict) -> None:
        level = alert.get("level", "LOW").upper()
        color = _level_color(level)

        card = ctk.CTkFrame(self._alerts_frame, fg_color=C_CARD, corner_radius=12)
        card.pack(fill="x", pady=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(top, text=f"  {level}  ", fg_color=color, corner_radius=6,
                     font=ctk.CTkFont(size=11, weight="bold"), text_color="#fff", width=70).pack(side="left")
        ctk.CTkLabel(top, text=f"  {alert.get('user_id', '?')}", text_color=C_TEXT, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=8)
        ctk.CTkLabel(top, text=f"Risk: {alert.get('risk_score', 0):.1f}", text_color=_risk_color(alert.get("risk_score", 0)), font=ctk.CTkFont(size=12)).pack(side="left", padx=12)
        ctk.CTkLabel(top, text=_fmt_time(alert.get("timestamp", "")), text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="right")

        factors_str = ", ".join(alert.get("factors", [])) or "No factors listed"
        ctk.CTkLabel(card, text=factors_str, text_color=C_MUTED, font=ctk.CTkFont(size=11), anchor="w").pack(fill="x", padx=16, pady=(0, 6))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))

        alert_id = str(alert.get("_id", ""))
        ctk.CTkButton(btn_row, text="Mark Resolved", width=120, height=28, fg_color="#166534",
                      hover_color="#15803d", font=ctk.CTkFont(size=11),
                      command=lambda aid=alert_id: self._mark_resolved(aid, card)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="View Employee", width=120, height=28, fg_color=C_BORDER,
                      hover_color=C_BLUE, font=ctk.CTkFont(size=11),
                      command=lambda a=alert: self._view_emp_from_alert(a)).pack(side="left")

        if level == "CRITICAL":
            _play_alert_sound()

    def _mark_resolved(self, alert_id: str, card_widget) -> None:
        try:
            from bson import ObjectId
            col = self._db.get_collection("alerts")
            if col and alert_id:
                col.update_one({"_id": ObjectId(alert_id)}, {"$set": {"resolved": True, "resolved_at": datetime.utcnow().isoformat()}})
            card_widget.configure(fg_color="#0d2010")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _view_emp_from_alert(self, alert: dict) -> None:
        emp_id = alert.get("user_id")
        try:
            col = self._db.get_collection("employees")
            emp = col.find_one({"employee_id": emp_id}, {"_id": 0, "password_hash": 0, "face_images": 0, "face_embedding": 0}) if col else None
            if emp:
                EmployeeDetailWindow(self, emp, self._db)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tasks Tab
    # ------------------------------------------------------------------

    def _build_tasks_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color=C_BG, corner_radius=0)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 0))

        # Assignment form
        form = ctk.CTkFrame(top, fg_color=C_CARD, corner_radius=14)
        form.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(form, text="Assign New Task", font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(14, 8))

        row1 = ctk.CTkFrame(form, fg_color="transparent")
        row1.pack(fill="x", padx=16)

        # Employee dropdown
        ctk.CTkLabel(row1, text="Employee:", text_color=C_MUTED, font=ctk.CTkFont(size=12), width=90, anchor="w").pack(side="left")
        self._task_emp_var = ctk.StringVar(value="Select employee")
        self._task_emp_dd = ctk.CTkOptionMenu(row1, variable=self._task_emp_var, values=["Loading..."], width=180, fg_color=C_BORDER, button_color=C_BORDER)
        self._task_emp_dd.pack(side="left", padx=(0, 16))
        self._refresh_employee_dropdown()

        # Priority
        ctk.CTkLabel(row1, text="Priority:", text_color=C_MUTED, font=ctk.CTkFont(size=12), width=60, anchor="w").pack(side="left")
        self._task_priority = ctk.StringVar(value="medium")
        ctk.CTkOptionMenu(row1, variable=self._task_priority, values=["low", "medium", "high"], width=100, fg_color=C_BORDER, button_color=C_BORDER).pack(side="left", padx=(0, 16))

        # Due date
        ctk.CTkLabel(row1, text="Due:", text_color=C_MUTED, font=ctk.CTkFont(size=12), width=40, anchor="w").pack(side="left")
        if _HAS_CALENDAR:
            self._due_date = DateEntry(row1, width=12, background="#1a1d27", foreground="white", borderwidth=0, date_pattern="yyyy-mm-dd")
            self._due_date.pack(side="left")
        else:
            self._due_var = ctk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
            ctk.CTkEntry(row1, textvariable=self._due_var, width=110).pack(side="left")

        row2 = ctk.CTkFrame(form, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(row2, text="Title:", text_color=C_MUTED, font=ctk.CTkFont(size=12), width=90, anchor="w").pack(side="left")
        self._task_title_var = ctk.StringVar()
        ctk.CTkEntry(row2, textvariable=self._task_title_var, placeholder_text="Task title...", width=400).pack(side="left", fill="x", expand=True)

        row3 = ctk.CTkFrame(form, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(row3, text="Description:", text_color=C_MUTED, font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w")
        self._task_desc_box = ctk.CTkTextbox(form, height=80, fg_color=C_BG, border_color=C_BORDER)
        self._task_desc_box.pack(fill="x", padx=16, pady=(4, 0))

        ctk.CTkButton(form, text="Assign Task", fg_color=C_TEAL, hover_color=C_TEAL_D, height=38,
                      command=self._assign_task).pack(padx=16, pady=12, anchor="e")

        # Task list
        ctk.CTkLabel(frame, text="All Tasks", font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=24, pady=(4, 6))
        self._task_list_frame = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._task_list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        return frame

    def _refresh_employee_dropdown(self) -> None:
        if not self._db or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("employees")
            if col:
                emps = list(col.find({}, {"employee_id": 1, "full_name": 1, "_id": 0}))
                values = [f"{e['employee_id']} — {e.get('full_name','')}" for e in emps]
                self._task_emp_dd.configure(values=values or ["No employees"])
        except Exception:
            pass

    def _assign_task(self) -> None:
        title = self._task_title_var.get().strip()
        desc = self._task_desc_box.get("1.0", "end").strip()
        emp_raw = self._task_emp_var.get()
        priority = self._task_priority.get()

        if not title or not emp_raw or "Select" in emp_raw:
            messagebox.showwarning("Validation", "Employee and title are required.")
            return

        emp_id = emp_raw.split("—")[0].strip()
        due = ""
        if _HAS_CALENDAR:
            due = self._due_date.get_date().isoformat()
        else:
            due = self._due_var.get()

        task_doc = {
            "task_id": str(uuid.uuid4()),
            "employee_id": emp_id,
            "title": title,
            "description": desc,
            "due_date": due,
            "priority": priority,
            "status": "pending",
            "assigned_by": "ADMIN",
            "assigned_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
        }

        try:
            col = self._db.get_collection("tasks")
            if col:
                col.insert_one(task_doc)
                messagebox.showinfo("Success", f"Task '{title}' assigned to {emp_id}.")
                self._task_title_var.set("")
                self._task_desc_box.delete("1.0", "end")
                self._refresh_task_list()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _refresh_task_list(self) -> None:
        for w in self._task_list_frame.winfo_children():
            w.destroy()
        if not self._db or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("tasks")
            if not col:
                return
            tasks = list(col.find({}, {"_id": 0}).sort("assigned_at", -1).limit(40))
            for t in tasks:
                status = t.get("status", "pending")
                s_color = {"pending": C_MUTED, "in_progress": C_AMBER, "completed": C_GREEN}.get(status, C_MUTED)
                p_color = {"low": C_BLUE, "medium": C_AMBER, "high": C_RED}.get(t.get("priority", ""), C_MUTED)
                row = ctk.CTkFrame(self._task_list_frame, fg_color=C_CARD, corner_radius=10, height=44)
                row.pack(fill="x", pady=3)
                row.pack_propagate(False)
                ctk.CTkLabel(row, text=t.get("title", "?"), text_color=C_TEXT, font=ctk.CTkFont(size=12), anchor="w").pack(side="left", padx=12)
                ctk.CTkLabel(row, text=t.get("employee_id", "?"), text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=8)
                ctk.CTkLabel(row, text=t.get("priority", "").title(), text_color=p_color, font=ctk.CTkFont(size=11)).pack(side="left", padx=8)
                ctk.CTkLabel(row, text=status.replace("_", " ").title(), text_color=s_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)
                ctk.CTkLabel(row, text=t.get("due_date", ""), text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="right", padx=8)
        except Exception as exc:
            ctk.CTkLabel(self._task_list_frame, text=str(exc), text_color=C_RED).pack()

    # ------------------------------------------------------------------
    # Attendance Tab
    # ------------------------------------------------------------------

    def _build_attendance_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color=C_BG, corner_radius=0)

        filter_bar = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=10)
        filter_bar.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(filter_bar, text="Filter:", text_color=C_MUTED, font=ctk.CTkFont(size=12)).pack(side="left", padx=12, pady=10)

        if _HAS_CALENDAR:
            self._att_date = DateEntry(filter_bar, width=12, background="#1a1d27", foreground="white", date_pattern="yyyy-mm-dd")
            self._att_date.pack(side="left", padx=(0, 12), pady=10)
        else:
            self._att_date_var = ctk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
            ctk.CTkEntry(filter_bar, textvariable=self._att_date_var, width=110).pack(side="left", padx=4, pady=10)

        self._att_emp_var = ctk.StringVar(value="All Employees")
        ctk.CTkEntry(filter_bar, textvariable=self._att_emp_var, placeholder_text="Employee ID...", width=140).pack(side="left", padx=4)
        ctk.CTkButton(filter_bar, text="Search", fg_color=C_TEAL, hover_color=C_TEAL_D, width=80, command=self._refresh_attendance).pack(side="left", padx=8)

        # Table header
        hdr = ctk.CTkFrame(frame, fg_color=C_SIDEBAR, corner_radius=8, height=34)
        hdr.pack(fill="x", padx=20, pady=(0, 2))
        for col in ["Name", "ID", "Date", "Sign-in", "Sign-out", "Duration", "Status"]:
            ctk.CTkLabel(hdr, text=col, font=ctk.CTkFont(size=11), text_color=C_MUTED, anchor="w").pack(side="left", padx=12, pady=8, expand=True)

        self._att_list_frame = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._att_list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        return frame

    def _refresh_attendance(self) -> None:
        for w in self._att_list_frame.winfo_children():
            w.destroy()
        if not self._db or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("attendance_logs")
            if not col:
                return
            query = {}
            if _HAS_CALENDAR:
                date_str = self._att_date.get_date().isoformat()
            else:
                date_str = self._att_date_var.get()
            if date_str:
                query["date"] = date_str
            emp_filter = self._att_emp_var.get().strip()
            if emp_filter and emp_filter != "All Employees":
                query["employee_id"] = emp_filter

            docs = list(col.find(query, {"_id": 0}).limit(50))
            for d in docs:
                status_color = {"On Time": C_GREEN, "Late": C_AMBER, "Early Departure": C_RED, "Overtime": C_BLUE}.get(d.get("status", ""), C_MUTED)
                row = ctk.CTkFrame(self._att_list_frame, fg_color=C_CARD, corner_radius=8, height=40)
                row.pack(fill="x", pady=2)
                row.pack_propagate(False)
                for val in [d.get("full_name","?"), d.get("employee_id","?"), d.get("date",""), d.get("signin","—"), d.get("signout","—"), d.get("duration","—")]:
                    ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=12, expand=True)
                ctk.CTkLabel(row, text=d.get("status","—"), text_color=status_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)
        except Exception as exc:
            ctk.CTkLabel(self._att_list_frame, text=str(exc), text_color=C_RED).pack()

    # ------------------------------------------------------------------
    # Settings Tab
    # ------------------------------------------------------------------

    def _build_settings_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color=C_BG, corner_radius=0)
        form = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=14)
        form.pack(padx=40, pady=40, fill="x")
        ctk.CTkLabel(form, text="Application Settings", font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=20, pady=(16, 8))
        ctk.CTkLabel(form, text=f"App Name:   {settings.APP_NAME}", text_color=C_MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20)
        ctk.CTkLabel(form, text=f"Version:    {settings.VERSION}", text_color=C_MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20)
        ctk.CTkLabel(form, text=f"DB Status:  {'Connected' if self._db and self._db.is_connected else 'Offline'}", text_color=C_GREEN if (self._db and self._db.is_connected) else C_RED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(0, 16))
        return frame

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        self._do_poll()

    def _do_poll(self) -> None:
        if self._active_tab == "dashboard":
            threading.Thread(target=self._refresh_dashboard, daemon=True).start()
        elif self._active_tab == "alerts":
            threading.Thread(target=self._refresh_alerts, daemon=True).start()
        elif self._active_tab == "tasks":
            threading.Thread(target=self._refresh_task_list, daemon=True).start()
        elif self._active_tab == "attendance":
            threading.Thread(target=self._refresh_attendance, daemon=True).start()
        self.after(POLL_INTERVAL_MS, self._do_poll)

    # ------------------------------------------------------------------
    # DB init
    # ------------------------------------------------------------------

    def _init_db(self) -> MongoDBClient:
        db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
        db.connect()
        return db


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def launch_admin_panel(db: Optional[MongoDBClient] = None) -> None:
    """Launch the admin panel as a standalone window."""
    panel = AdminPanel(db=db)
    panel.mainloop()


if __name__ == "__main__":
    launch_admin_panel()
