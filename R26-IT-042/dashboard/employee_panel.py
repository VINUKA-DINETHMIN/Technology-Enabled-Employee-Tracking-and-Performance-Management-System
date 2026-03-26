"""
R26-IT-042 — Employee Activity Monitoring System
dashboard/employee_panel.py

Employee personal dashboard — shown after successful login.
Tabs:  My Tasks | My Status | My Attendance
Features: task start/complete timer, break config popup, toast notifications.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import customtkinter as ctk
import tkinter as tk

from common.database import MongoDBClient
from config.settings import settings

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_BG    = "#0b0e17"
C_CARD  = "#151b2d"
C_BORDER= "#1e2a40"
C_TEAL  = "#14b8a6"
C_TEAL_D= "#0d9488"
C_RED   = "#ef4444"
C_AMBER = "#f59e0b"
C_GREEN = "#22c55e"
C_BLUE  = "#3b82f6"
C_TEXT  = "#e2e8f0"
C_MUTED = "#64748b"

POLL_TASKS_MS = 30_000      # 30 seconds
TOAST_DURATION_MS = 4_000   # 4 seconds


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m:02d}m {s:02d}s"


def _priority_color(priority: str) -> str:
    return {"low": C_BLUE, "medium": C_AMBER, "high": C_RED}.get(priority.lower(), C_MUTED)


def _status_color(status: str) -> str:
    return {"pending": C_MUTED, "in_progress": C_AMBER, "completed": C_GREEN}.get(status, C_MUTED)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Toast Notification
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ToastNotification(ctk.CTkToplevel):
    """Small bottom-right toast popup."""

    def __init__(self, parent, message: str, accent: str = C_TEAL) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=C_CARD)

        ctk.CTkLabel(
            self, text=message,
            font=ctk.CTkFont(size=12), text_color=C_TEXT,
            wraplength=260, justify="left",
        ).pack(padx=16, pady=12)

        ctk.CTkFrame(self, height=3, fg_color=accent, corner_radius=0).pack(fill="x", side="bottom")

        self.update_idletasks()
        w, h = 280, 60
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 60}")

        self.after(TOAST_DURATION_MS, self.destroy)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Break Config Popup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BreakConfigPopup(ctk.CTkToplevel):
    def __init__(self, parent, user_id: str, db: MongoDBClient) -> None:
        super().__init__(parent)
        self._user_id = user_id
        self._db = db
        self.title("Set My Break Times")
        self.geometry("420x430")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self.attributes("-topmost", True)
        self._entries: dict = {}
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Configure Your Break Schedule",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(pady=(20, 4))
        ctk.CTkLabel(self, text="Times are applied from the next session",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(pady=(0, 12))

        defaults = {
            "lunch":   {"start": "12:00", "duration_minutes": 60},
            "short_1": {"start": "10:00", "duration_minutes": 15},
            "short_2": {"start": "15:00", "duration_minutes": 15},
            "short_3": {"start": "17:00", "duration_minutes": 15},
        }

        # Load existing config from break_manager
        try:
            from C3_activity_monitoring.src.break_manager import BreakManager
            bm = BreakManager()
            existing = bm.load_breaks()
        except Exception:
            existing = defaults.copy()

        labels = {"lunch": "Lunch Break", "short_1": "Short Break 1", "short_2": "Short Break 2", "short_3": "Short Break 3"}

        frame = ctk.CTkScrollableFrame(self, fg_color=C_CARD, corner_radius=12)
        frame.pack(padx=16, fill="both", expand=True)

        for key, label in labels.items():
            cfg = existing.get(key, defaults[key])
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C_TEXT, width=120, anchor="w").pack(side="left")
            t_var = ctk.StringVar(value=cfg.get("start", "09:00"))
            d_var = ctk.StringVar(value=str(cfg.get("duration_minutes", 15)))
            ctk.CTkEntry(row, textvariable=t_var, width=76, placeholder_text="HH:MM").pack(side="left", padx=4)
            ctk.CTkLabel(row, text="min:", text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=4)
            ctk.CTkEntry(row, textvariable=d_var, width=52).pack(side="left")
            self._entries[key] = {"time_var": t_var, "dur_var": d_var}

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(btn_row, text="Reset Defaults", fg_color=C_BORDER, hover_color="#374151",
                      command=self._reset).pack(side="left")
        ctk.CTkButton(btn_row, text="Save", fg_color=C_TEAL, hover_color=C_TEAL_D,
                      command=self._save).pack(side="right")

    def _reset(self) -> None:
        defaults = {
            "lunch": ("12:00", 60), "short_1": ("10:00", 15),
            "short_2": ("15:00", 15), "short_3": ("17:00", 15),
        }
        for key, (t, d) in defaults.items():
            self._entries[key]["time_var"].set(t)
            self._entries[key]["dur_var"].set(str(d))

    def _save(self) -> None:
        cfg = {}
        for key, ev in self._entries.items():
            cfg[key] = {"start": ev["time_var"].get().strip(),
                        "duration_minutes": int(ev["dur_var"].get().strip() or 15)}
        try:
            from C3_activity_monitoring.src.break_manager import BreakManager
            bm = BreakManager(user_id=self._user_id)
            bm.configure_breaks(cfg)
        except Exception as exc:
            import tkinter.messagebox as mb
            mb.showerror("Error", str(exc))
            return
        self.destroy()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Task Card Widget
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TaskCard(ctk.CTkFrame):
    def __init__(self, parent, task: dict, db: MongoDBClient, user_id: str, **kw):
        super().__init__(parent, fg_color=C_CARD, corner_radius=14, **kw)
        self._task = task
        self._db = db
        self._user_id = user_id
        self._timer_running = False
        self._timer_start: Optional[float] = None
        self._timer_label: Optional[ctk.CTkLabel] = None
        self._build()

    def _build(self) -> None:
        task = self._task
        priority = task.get("priority", "medium")
        status = task.get("status", "pending")

        # Header row
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 4))

        ctk.CTkLabel(hdr, text=task.get("title", "Untitled"),
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(hdr, text=f"  {priority.upper()}  ",
                     fg_color=_priority_color(priority), corner_radius=6,
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="#fff", width=60).pack(side="right")

        ctk.CTkLabel(self, text=task.get("description", "")[:120],
                     font=ctk.CTkFont(size=11), text_color=C_MUTED,
                     wraplength=420, justify="left").pack(anchor="w", padx=16)

        meta = ctk.CTkFrame(self, fg_color="transparent")
        meta.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(meta, text=f"Due: {task.get('due_date','—')}", text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="left")

        self._status_lbl = ctk.CTkLabel(meta, text=status.replace("_", " ").title(),
                                        text_color=_status_color(status), font=ctk.CTkFont(size=11))
        self._status_lbl.pack(side="right")

        # Timer label (hidden initially)
        self._timer_label = ctk.CTkLabel(self, text="",
                                         font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEAL)
        self._timer_label.pack(anchor="w", padx=16)

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(4, 14))

        if status == "pending":
            ctk.CTkButton(btn_row, text="Start Task", width=110, fg_color=C_TEAL, hover_color=C_TEAL_D,
                          height=32, font=ctk.CTkFont(size=12), command=self._start_task).pack(side="left")

        elif status == "in_progress":
            ctk.CTkButton(btn_row, text="Complete", width=110, fg_color=C_GREEN, hover_color="#15803d",
                          height=32, font=ctk.CTkFont(size=12), command=self._complete_task).pack(side="left")
            # Restart timer if started_at exists
            if task.get("started_at"):
                try:
                    started = datetime.fromisoformat(task["started_at"].replace("Z", "+00:00"))
                    self._timer_start = started.timestamp()
                    self._timer_running = True
                    self._tick_timer()
                except Exception:
                    pass

    def _start_task(self) -> None:
        now = datetime.utcnow().isoformat()
        try:
            col = self._db.get_collection("tasks")
            if col:
                col.update_one(
                    {"task_id": self._task["task_id"]},
                    {"$set": {"status": "in_progress", "started_at": now}},
                )
            self._task["status"] = "in_progress"
            self._task["started_at"] = now
            self._status_lbl.configure(text="In Progress", text_color=C_AMBER)
            self._timer_start = time.time()
            self._timer_running = True
            self._tick_timer()

            # Log to C4 hook
            self._log_task_start(now)
        except Exception as exc:
            import tkinter.messagebox as mb
            mb.showerror("Error", str(exc))

    def _complete_task(self) -> None:
        now = datetime.utcnow().isoformat()
        self._timer_running = False
        try:
            col = self._db.get_collection("tasks")
            if col:
                col.update_one(
                    {"task_id": self._task["task_id"]},
                    {"$set": {"status": "completed", "completed_at": now}},
                )
            self._status_lbl.configure(text="Completed", text_color=C_GREEN)
            if self._timer_label:
                self._timer_label.configure(text="Task completed")
        except Exception as exc:
            import tkinter.messagebox as mb
            mb.showerror("Error", str(exc))

    def _tick_timer(self) -> None:
        if not self._timer_running or self._timer_start is None:
            return
        elapsed = time.time() - self._timer_start
        if self._timer_label:
            self._timer_label.configure(text=f"Active: {_fmt_duration(elapsed)}")
        self.after(1000, self._tick_timer)

    def _log_task_start(self, started_at: str) -> None:
        """Feed task start to C4 productivity prediction."""
        try:
            col = self._db.get_collection("task_logs")
            if col:
                col.insert_one({
                    "task_id": self._task.get("task_id"),
                    "employee_id": self._user_id,
                    "started_at": started_at,
                    "estimated_duration": None,
                    "title": self._task.get("title", ""),
                })
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Employee Panel
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EmployeePanel(ctk.CTkToplevel):
    """
    Employee personal dashboard.  Opened after successful login.
    """

    def __init__(
        self,
        parent,
        employee: dict,
        db: MongoDBClient,
        session_id: Optional[str] = None,
        break_manager=None,
    ) -> None:
        super().__init__(parent)
        self._emp = employee
        self._db = db
        self._user_id = employee.get("employee_id", "?")
        self._session_id = session_id or str(uuid.uuid4())
        self._bm = break_manager
        self._session_start = time.time()
        self._known_task_ids: set = set()

        emp_name = employee.get("full_name", self._user_id)
        self.title(f"WorkPlus — {emp_name}")
        self.geometry("680x720")
        self.minsize(600, 600)
        self.configure(fg_color=C_BG)

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 680) // 2
        y = (self.winfo_screenheight() - 720) // 2
        self.geometry(f"680x720+{x}+{y}")

        self._build()
        self._refresh_all()
        self._start_polling()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # Top bar
        topbar = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=58)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        emp_name = self._emp.get("full_name", self._user_id)
        location = self._emp.get("work_location", "unknown").title()
        loc_color = C_GREEN if location == "Office" else C_AMBER

        ctk.CTkLabel(topbar, text=emp_name,
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(side="left", padx=16, pady=14)
        ctk.CTkLabel(topbar, text=f"  {self._user_id}  ",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(side="left")

        ctk.CTkLabel(topbar, text=f"  {location}  ", fg_color=loc_color, corner_radius=6,
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="#fff").pack(side="left")

        self._time_lbl = ctk.CTkLabel(topbar, text="", font=ctk.CTkFont(size=11), text_color=C_MUTED)
        self._time_lbl.pack(side="right", padx=16)
        self._update_clock()

        ctk.CTkLabel(topbar, text="⬤ Monitoring Active",
                     font=ctk.CTkFont(size=11), text_color=C_GREEN).pack(side="right", padx=8)

        # Tab bar
        tab_bar = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=0, height=44)
        tab_bar.pack(fill="x")

        self._tab_btns: dict = {}
        self._active_tab = "tasks"
        for tid, label in [("tasks", "My Tasks"), ("status", "My Status"), ("attendance", "My Attendance")]:
            btn = ctk.CTkButton(
                tab_bar, text=label, height=44, corner_radius=0,
                font=ctk.CTkFont(size=12),
                fg_color=C_TEAL if tid == "tasks" else "transparent",
                hover_color=C_TEAL_D, text_color=C_TEXT,
                command=lambda t=tid: self._switch_tab(t),
            )
            btn.pack(side="left", padx=2)
            self._tab_btns[tid] = btn

        self._content = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        self._content.pack(fill="both", expand=True)

        self._tab_frames: dict = {
            "tasks":      self._build_tasks_tab(),
            "status":     self._build_status_tab(),
            "attendance": self._build_attendance_tab(),
        }
        self._switch_tab("tasks")

    def _switch_tab(self, tab_id: str) -> None:
        self._active_tab = tab_id
        for tid, f in self._tab_frames.items():
            f.pack_forget()
        self._tab_frames[tab_id].pack(fill="both", expand=True)
        for tid, btn in self._tab_btns.items():
            btn.configure(fg_color=C_TEAL if tid == tab_id else "transparent")

    # ------------------------------------------------------------------
    # My Tasks Tab
    # ------------------------------------------------------------------

    def _build_tasks_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._content, fg_color=C_BG, corner_radius=0)
        ctk.CTkLabel(frame, text="My Assigned Tasks",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=20, pady=(16, 8))
        self._tasks_scroll = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._tasks_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        return frame

    def _refresh_tasks(self) -> None:
        for w in self._tasks_scroll.winfo_children():
            w.destroy()
        if not self._db or not self._db.is_connected:
            ctk.CTkLabel(self._tasks_scroll, text="Database offline.", text_color=C_MUTED).pack(pady=20)
            return
        try:
            col = self._db.get_collection("tasks")
            if not col:
                return
            tasks = list(col.find({"employee_id": self._user_id}, {"_id": 0}).sort("assigned_at", -1).limit(20))
            if not tasks:
                ctk.CTkLabel(self._tasks_scroll, text="No tasks assigned yet.", text_color=C_MUTED).pack(pady=20)
                return

            new_ids = {t["task_id"] for t in tasks if "task_id" in t}
            new_tasks = new_ids - self._known_task_ids
            if self._known_task_ids and new_tasks:
                self.after(0, lambda: ToastNotification(self, "You have a new task assigned!", C_TEAL))
            self._known_task_ids = new_ids

            for t in tasks:
                card = TaskCard(self._tasks_scroll, t, self._db, self._user_id)
                card.pack(fill="x", pady=6)
        except Exception as exc:
            ctk.CTkLabel(self._tasks_scroll, text=str(exc), text_color=C_RED).pack()

    # ------------------------------------------------------------------
    # My Status Tab
    # ------------------------------------------------------------------

    def _build_status_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._content, fg_color=C_BG, corner_radius=0)

        session_card = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=14)
        session_card.pack(fill="x", padx=20, pady=(16, 12))
        ctk.CTkLabel(session_card, text="Session Info", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))

        self._session_dur_lbl = ctk.CTkLabel(session_card, text="Duration: —",
                                              font=ctk.CTkFont(size=12), text_color=C_MUTED)
        self._session_dur_lbl.pack(anchor="w", padx=16, pady=2)
        self._tick_session_timer(session_card)

        # Productivity
        prod_card = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=14)
        prod_card.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(prod_card, text="Productivity Score", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        self._prod_lbl = ctk.CTkLabel(prod_card, text="—", font=ctk.CTkFont(size=24, weight="bold"), text_color=C_GREEN)
        self._prod_lbl.pack(anchor="w", padx=16)
        self._prod_bar = ctk.CTkProgressBar(prod_card, height=10, progress_color=C_GREEN, fg_color=C_BORDER)
        self._prod_bar.set(0)
        self._prod_bar.pack(fill="x", padx=16, pady=(4, 14))

        # Break schedule
        break_card = ctk.CTkFrame(frame, fg_color=C_CARD, corner_radius=14)
        break_card.pack(fill="x", padx=20, pady=(0, 12))
        brow = ctk.CTkFrame(break_card, fg_color="transparent")
        brow.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(brow, text="Break Schedule", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkButton(brow, text="Set My Break Times", width=140, height=28, fg_color=C_BORDER, hover_color=C_BLUE,
                      font=ctk.CTkFont(size=11),
                      command=lambda: BreakConfigPopup(self, self._user_id, self._db)).pack(side="right")

        self._breaks_display_frame = ctk.CTkFrame(break_card, fg_color="transparent")
        self._breaks_display_frame.pack(fill="x", padx=16, pady=(0, 12))

        # Next break countdown
        self._next_break_lbl = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=13), text_color=C_TEAL)
        self._next_break_lbl.pack(anchor="w", padx=24, pady=4)

        return frame

    def _tick_session_timer(self, parent) -> None:
        elapsed = time.time() - self._session_start
        self._session_dur_lbl.configure(text=f"Duration: {_fmt_duration(elapsed)}")
        self.after(1000, lambda: self._tick_session_timer(parent))

    def _refresh_status(self) -> None:
        if not self._db or not self._db.is_connected:
            return
        # Productivity from last activity log
        try:
            col = self._db.get_collection("activity_logs")
            if col:
                doc = col.find_one({"user_id": self._user_id}, sort=[("timestamp", -1)])
                if doc:
                    prod = doc.get("productivity_score", 0.0)
                    self._prod_lbl.configure(text=f"{prod:.0f} / 100")
                    self._prod_bar.set(prod / 100.0)
        except Exception:
            pass

        # Refresh break schedule display
        try:
            from C3_activity_monitoring.src.break_manager import BreakManager
            bm = BreakManager()
            breaks = bm.load_breaks()
            for w in self._breaks_display_frame.winfo_children():
                w.destroy()
            for key, cfg in breaks.items():
                label = key.replace("_", " ").title()
                ctk.CTkLabel(self._breaks_display_frame,
                             text=f"{label}: {cfg['start']}  ({cfg['duration_minutes']} min)",
                             font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(anchor="w", pady=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # My Attendance Tab
    # ------------------------------------------------------------------

    def _build_attendance_tab(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._content, fg_color=C_BG, corner_radius=0)
        ctk.CTkLabel(frame, text="My Attendance (Last 30 Days)",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=20, pady=(16, 8))

        hdr = ctk.CTkFrame(frame, fg_color=C_SIDEBAR, corner_radius=8, height=34)
        hdr.pack(fill="x", padx=20, pady=(0, 2))
        for col in ["Date", "Sign-in", "Sign-out", "Duration", "Status"]:
            ctk.CTkLabel(hdr, text=col, font=ctk.CTkFont(size=11), text_color=C_MUTED, anchor="w").pack(side="left", padx=16, pady=8, expand=True)

        self._att_scroll = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._att_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        return frame

    def _refresh_attendance(self) -> None:
        for w in self._att_scroll.winfo_children():
            w.destroy()
        if not self._db or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("attendance_logs")
            if col:
                docs = list(col.find({"employee_id": self._user_id}, {"_id": 0}).sort("date", -1).limit(30))
                for d in docs:
                    s_color = {"On Time": C_GREEN, "Late": C_AMBER, "Early Departure": C_RED}.get(d.get("status", ""), C_MUTED)
                    row = ctk.CTkFrame(self._att_scroll, fg_color=C_CARD, corner_radius=8, height=40)
                    row.pack(fill="x", pady=2)
                    row.pack_propagate(False)
                    for val in [d.get("date",""), d.get("signin","—"), d.get("signout","—"), d.get("duration","—")]:
                        ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=16, expand=True)
                    ctk.CTkLabel(row, text=d.get("status","—"), text_color=s_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)
        except Exception as exc:
            ctk.CTkLabel(self._att_scroll, text=str(exc), text_color=C_RED).pack()

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def _update_clock(self) -> None:
        self._time_lbl.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self._update_clock)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        threading.Thread(target=self._refresh_tasks, daemon=True).start()
        threading.Thread(target=self._refresh_status, daemon=True).start()
        threading.Thread(target=self._refresh_attendance, daemon=True).start()

    def _start_polling(self) -> None:
        self.after(POLL_TASKS_MS, self._poll)

    def _poll(self) -> None:
        self._refresh_all()
        self.after(POLL_TASKS_MS, self._poll)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Launch helper
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def launch_employee_panel(parent, employee: dict, db: MongoDBClient, session_id: str = None) -> EmployeePanel:
    """Open the employee panel window."""
    return EmployeePanel(parent, employee, db, session_id=session_id)
