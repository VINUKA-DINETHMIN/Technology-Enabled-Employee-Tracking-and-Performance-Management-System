from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
import sys

import customtkinter as ctk

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from common.database import MongoDBClient
from config.settings import settings
from C4_productivity_prediction.src.efficiency_service import EfficiencyPredictionService

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_BG = "#0b0e17"
C_CARD = "#151b2d"
C_BORDER = "#1e2a40"
C_TEXT = "#e2e8f0"
C_MUTED = "#64748b"
C_TEAL = "#14b8a6"
C_GREEN = "#22c55e"
C_AMBER = "#f59e0b"
C_RED = "#ef4444"
C_BLUE = "#3b82f6"


class EfficiencyWindow(ctk.CTk):
    """Standalone read-only window for per-employee efficiency prediction."""

    def __init__(self, db: MongoDBClient, refresh_ms: int = 60_000) -> None:
        super().__init__()
        self._db = db
        self._refresh_ms = refresh_ms
        self._service = EfficiencyPredictionService()

        self.title(f"{settings.APP_NAME} - Employee Efficiency Predictions")
        self.geometry("1280x760")
        self.minsize(1080, 680)
        self.configure(fg_color=C_BG)

        self._last_updated_var = ctk.StringVar(value="Last updated: -")
        self._status_var = ctk.StringVar(value="Loading model and reading data...")

        self._build()
        self.after(200, self._refresh)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            header,
            text="Individual Employee Efficiency",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Read-only C4 prediction view from existing employee/task/activity data",
            font=ctk.CTkFont(size=12),
            text_color=C_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        topbar = ctk.CTkFrame(self, fg_color="transparent")
        topbar.pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkLabel(topbar, textvariable=self._last_updated_var, text_color=C_MUTED).pack(side="left")

        ctk.CTkButton(
            topbar,
            text="Refresh Now",
            fg_color=C_TEAL,
            hover_color="#0d9488",
            command=self._refresh,
            width=130,
            height=34,
        ).pack(side="right")

        self._summary_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._summary_frame.pack(fill="x", padx=18, pady=(0, 10))

        self._cards = {
            "employees": self._make_card(self._summary_frame, "Employees", "0", C_BLUE),
            "high": self._make_card(self._summary_frame, "Predicted High", "0", C_GREEN),
            "medium": self._make_card(self._summary_frame, "Predicted Medium", "0", C_AMBER),
            "low": self._make_card(self._summary_frame, "Predicted Low", "0", C_RED),
            "avg_conf": self._make_card(self._summary_frame, "Avg Confidence", "0%", C_TEAL),
        }

        for i, key in enumerate(["employees", "high", "medium", "low", "avg_conf"]):
            self._cards[key].grid(row=0, column=i, sticky="nsew", padx=6)
            self._summary_frame.grid_columnconfigure(i, weight=1)

        body = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=12)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 16))

        ctk.CTkLabel(
            body,
            text="Predictions by Employee",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w", padx=14, pady=(12, 6))

        header_row = ctk.CTkFrame(body, fg_color="#10172b", corner_radius=8)
        header_row.pack(fill="x", padx=12, pady=(0, 8))
        for title, width in [
            ("Employee", 230),
            ("Prediction", 130),
            ("Confidence", 120),
            ("Input Productivity", 150),
            ("Workload", 110),
            ("Assigned", 90),
            ("Pending", 80),
            ("On Time", 90),
            ("Late", 80),
        ]:
            ctk.CTkLabel(
                header_row,
                text=title,
                width=width,
                text_color=C_MUTED,
                anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="left", padx=4, pady=8)

        self._table = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._table.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkLabel(footer, textvariable=self._status_var, text_color=C_MUTED).pack(anchor="w")

    def _make_card(self, parent, title: str, value: str, accent: str):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=12, border_width=1, border_color=C_BORDER)
        ctk.CTkLabel(card, text=title, text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(10, 2))
        val = ctk.CTkLabel(card, text=value, text_color=accent, font=ctk.CTkFont(size=20, weight="bold"))
        val.pack(anchor="w", padx=12, pady=(0, 10))
        card._value_label = val
        return card

    def _set_card(self, key: str, value: str) -> None:
        card = self._cards.get(key)
        if card is not None:
            card._value_label.configure(text=value)

    def _refresh(self) -> None:
        try:
            rows = self._service.predict_all(self._db)
            self._render_rows(rows)
            self._render_summary(rows)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_updated_var.set(f"Last updated: {now}")
            self._status_var.set(f"Read-only prediction completed for {len(rows)} employees.")
        except Exception as exc:
            logger.exception("Efficiency window refresh failed")
            self._status_var.set(f"Refresh failed: {exc}")

        self.after(self._refresh_ms, self._refresh)

    def _render_summary(self, rows) -> None:
        total = len(rows)
        high = sum(1 for r in rows if r.predicted_label.lower() == "high")
        medium = sum(1 for r in rows if r.predicted_label.lower() == "medium")
        low = sum(1 for r in rows if r.predicted_label.lower() == "low")
        avg_conf = (sum(r.confidence for r in rows) / total) if total else 0.0

        self._set_card("employees", str(total))
        self._set_card("high", str(high))
        self._set_card("medium", str(medium))
        self._set_card("low", str(low))
        self._set_card("avg_conf", f"{avg_conf * 100:.1f}%")

    def _render_rows(self, rows) -> None:
        for w in self._table.winfo_children():
            w.destroy()

        if not rows:
            ctk.CTkLabel(
                self._table,
                text="No employees available for prediction.",
                text_color=C_MUTED,
            ).pack(pady=20)
            return

        for r in rows:
            row = ctk.CTkFrame(self._table, fg_color="#10172b", corner_radius=8)
            row.pack(fill="x", pady=4)

            pred_color = {
                "high": C_GREEN,
                "medium": C_AMBER,
                "low": C_RED,
            }.get(r.predicted_label.lower(), C_TEXT)

            values = [
                (f"{r.full_name} ({r.employee_id})", 230, C_TEXT),
                (r.predicted_label, 130, pred_color),
                (f"{r.confidence * 100:.1f}%", 120, C_TEXT),
                (f"{r.productivity_score_input:.1f}", 150, C_TEXT),
                (f"{r.workload_score:.1f}", 110, C_TEXT),
                (str(r.total_tasks_assigned), 90, C_TEXT),
                (str(r.total_tasks_pending), 80, C_TEXT),
                (str(r.total_tasks_completed_on_time), 90, C_TEXT),
                (str(r.total_tasks_completed_late), 80, C_TEXT),
            ]

            for text, width, color in values:
                ctk.CTkLabel(
                    row,
                    text=text,
                    width=width,
                    anchor="w",
                    text_color=color,
                    font=ctk.CTkFont(size=12),
                ).pack(side="left", padx=4, pady=8)


def launch_efficiency_window(db: MongoDBClient | None = None) -> None:
    own_db = db is None
    db_client = db
    if db_client is None:
        db_client = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
        db_client.connect()

    app = EfficiencyWindow(db=db_client)
    app.mainloop()

    if own_db and db_client is not None:
        try:
            db_client.close()
        except Exception:
            pass
