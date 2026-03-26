"""
R26-IT-042 — WorkPlus  |  Employee Activity Monitoring System
main.py

Application entry point.

Startup sequence
────────────────
1. Load config (config/settings.py)
2. Connect to MongoDB Atlas (common/database.py)
3. Show 3-Step Login (app/login.py): Password → MFA → Face + Liveness
4. On successful login →
   a. Open employee dashboard (dashboard/employee_panel.py)
   b. Start C3 activity monitoring in background (initialize_monitoring.py)
   c. Start C1 user interaction profiling
   d. Start C4 productivity prediction logger
5. On logout / shutdown → graceful teardown of all threads + flush logs

Admin panel:
   Run: python dashboard/admin_panel.py  (separate process)
   Or:  python main.py --admin

Cross-platform notes
────────────────────
• sys.platform == "win32"  → Windows (pynput keyboard hook OK)
• sys.platform == "darwin" → macOS (prompt user to grant Accessibility +
                             Camera permissions in System Preferences)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

# ── Path bootstrap ────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Internal imports ──────────────────────────────────────────────────────
from config.settings import settings
from common.database import MongoDBClient
from common.logger import SecureLogger
from common.alerts import AlertSender

# ── Logging bootstrap ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")

# ── Global appearance ─────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Application Controller
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Application:
    """
    Top-level application controller.
    Owns all resources and orchestrates the startup / shutdown lifecycle.
    """

    def __init__(self) -> None:
        self._db_client: Optional[MongoDBClient] = None
        self._secure_logger: Optional[SecureLogger] = None
        self._alert_sender: Optional[AlertSender] = None
        self._user_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._employee: Optional[dict] = None
        self._monitor_threads: list[threading.Thread] = []
        self._shutdown_event = threading.Event()
        self._root: Optional[ctk.CTk] = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def run(self, admin_mode: bool = False) -> None:
        """Main entry point — runs until logout or window close."""
        self._check_platform()
        self._load_config()
        self._connect_db()
        self._init_services()

        if admin_mode:
            self._launch_admin_panel()
        else:
            self._launch_login()

    def _check_platform(self) -> None:
        log.info("Platform: %s", sys.platform)
        if sys.platform == "darwin":
            from tkinter import messagebox
            messagebox.showinfo(
                "macOS Permissions Required",
                "This application requires:\n\n"
                "• Camera access (facial liveness)\n"
                "• Accessibility access (keyboard / mouse tracking)\n\n"
                "Grant these in System Preferences → Privacy & Security.",
            )

    def _load_config(self) -> None:
        missing = settings.validate()
        if missing:
            from tkinter import messagebox
            messagebox.showwarning(
                "Configuration Warning",
                f"Missing environment variables:\n\n"
                + "\n".join(f"  • {k}" for k in missing)
                + "\n\nEdit .env and restart.",
            )
        log.info("Settings loaded: %s", settings)

    def _connect_db(self) -> None:
        self._db_client = MongoDBClient(
            uri=settings.MONGO_URI,
            db_name=settings.MONGO_DB_NAME,
        )
        ok = self._db_client.connect()
        if ok:
            # Ensure all required collections are indexed
            self._ensure_extra_indexes()
        else:
            log.warning("MongoDB offline — running in offline mode.")

    def _ensure_extra_indexes(self) -> None:
        """Create indexes for collections added by the full system."""
        if not self._db_client or not self._db_client.is_connected:
            return
        try:
            import pymongo
            db = self._db_client._db  # internal reference
            if db is None:
                return
            db["activity_logs"].create_index(
                [("user_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="user_activity_time", background=True,
            )
            db["employees"].create_index(
                [("employee_id", pymongo.ASCENDING)],
                name="employee_id_unique", unique=True, background=True,
            )
            db["tasks"].create_index(
                [("employee_id", pymongo.ASCENDING), ("assigned_at", pymongo.DESCENDING)],
                name="employee_tasks", background=True,
            )
            db["attendance_logs"].create_index(
                [("employee_id", pymongo.ASCENDING), ("date", pymongo.DESCENDING)],
                name="employee_attendance", background=True,
            )
            db["policy_violations"].create_index(
                [("user_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="user_violations", background=True,
            )
            log.debug("Extra MongoDB indexes ensured.")
        except Exception as exc:
            log.warning("Could not ensure extra indexes: %s", exc)

    def _init_services(self) -> None:
        self._secure_logger = SecureLogger(user_id="SYSTEM")
        self._alert_sender = AlertSender(
            ws_url=settings.WEBSOCKET_URL,
            fallback_logger=self._secure_logger,
        )

    # ------------------------------------------------------------------
    # Login (employee mode)
    # ------------------------------------------------------------------

    def _launch_login(self) -> None:
        from app.login import LoginWindow

        win = LoginWindow(
            db=self._db_client,
            on_success=self._on_login_success,
            alert_sender=self._alert_sender,
        )
        win.protocol("WM_DELETE_WINDOW", self._shutdown)
        self._root = win
        win.mainloop()

    def _on_login_success(self, employee: dict, session_id: str) -> None:
        """Called by LoginWindow after all 3 steps pass."""
        self._employee = employee
        self._user_id = employee.get("employee_id", "?")
        self._session_id = session_id
        log.info("Login success: %s session=%s", self._user_id, session_id)

        if self._secure_logger:
            self._secure_logger._user_id = self._user_id

        # Close login window
        if self._root:
            try:
                self._root.withdraw()
            except Exception:
                pass

        # Start monitoring threads
        self._init_monitoring()

        # Open employee panel
        self._open_employee_panel()

    def _open_employee_panel(self) -> None:
        from dashboard.employee_panel import EmployeePanel

        # Need a CTk root for Toplevel
        root = ctk.CTk()
        root.withdraw()
        root.protocol("WM_DELETE_WINDOW", self._shutdown)
        self._root = root

        panel = EmployeePanel(
            parent=root,
            employee=self._employee,
            db=self._db_client,
            session_id=self._session_id,
        )
        panel.protocol("WM_DELETE_WINDOW", self._shutdown)

        # Log attendance sign-in
        self._log_attendance_signin()

        root.mainloop()

    def _log_attendance_signin(self) -> None:
        try:
            from datetime import datetime, timezone
            col = self._db_client.get_collection("attendance_logs")
            if col:
                today = datetime.now().strftime("%Y-%m-%d")
                existing = col.find_one({"employee_id": self._user_id, "date": today})
                if not existing:
                    col.insert_one({
                        "employee_id": self._user_id,
                        "full_name": self._employee.get("full_name", ""),
                        "date": today,
                        "signin": datetime.now().strftime("%H:%M:%S"),
                        "signout": None,
                        "duration": None,
                        "status": "On Time",
                    })
        except Exception as exc:
            log.warning("Attendance signin log error: %s", exc)

    # ------------------------------------------------------------------
    # Monitoring (C1, C3, C4)
    # ------------------------------------------------------------------

    def _init_monitoring(self) -> None:
        # C3: Activity monitoring
        self._start_thread("C3-ActivityMonitoring", self._start_c3)
        # C1: User interaction
        self._start_thread("C1-UserInteraction", self._start_c1)
        # C4: Productivity prediction
        self._start_thread("C4-ProductivityPrediction", self._start_c4)

    def _start_thread(self, name: str, target) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._monitor_threads.append(t)
        log.info("Thread started: %s", name)

    def _start_c3(self) -> None:
        try:
            from C3_activity_monitoring.src.initialize_monitoring import start_monitoring
            start_monitoring(
                user_id=self._user_id,
                db_client=self._db_client,
                alert_sender=self._alert_sender,
                shutdown_event=self._shutdown_event,
                session_id=self._session_id,
                location_mode="unknown",
                wifi_ssid_match=False,
                face_liveness_score=1.0,
            )
        except ImportError:
            log.warning("C3 not available — skipping activity monitoring.")
        except Exception as exc:
            log.error("C3 crashed: %s", exc)

    def _start_c1(self) -> None:
        try:
            from C1_user_interaction.src import start_interaction_profiling
            start_interaction_profiling(
                user_id=self._user_id,
                shutdown_event=self._shutdown_event,
            )
        except ImportError:
            log.warning("C1 not available — skipping.")
        except Exception as exc:
            log.error("C1 crashed: %s", exc)

    def _start_c4(self) -> None:
        try:
            from C4_productivity_prediction.src import start_productivity_logger
            start_productivity_logger(
                user_id=self._user_id,
                db_client=self._db_client,
                shutdown_event=self._shutdown_event,
            )
        except ImportError:
            log.warning("C4 not available — skipping.")
        except Exception as exc:
            log.error("C4 crashed: %s", exc)

    # ------------------------------------------------------------------
    # Admin panel mode
    # ------------------------------------------------------------------

    def _launch_admin_panel(self) -> None:
        from dashboard.admin_panel import AdminPanel
        panel = AdminPanel(db=self._db_client)
        panel.protocol("WM_DELETE_WINDOW", self._shutdown)
        panel.mainloop()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        log.info("Shutting down — signalling all monitor threads.")
        self._shutdown_event.set()

        # Log attendance sign-out
        try:
            if self._user_id and self._db_client and self._db_client.is_connected:
                from datetime import datetime
                col = self._db_client.get_collection("attendance_logs")
                today = datetime.now().strftime("%Y-%m-%d")
                if col:
                    col.update_one(
                        {"employee_id": self._user_id, "date": today},
                        {"$set": {"signout": datetime.now().strftime("%H:%M:%S")}},
                    )
        except Exception:
            pass

        # Update session status
        try:
            if self._session_id and self._db_client and self._db_client.is_connected:
                from datetime import datetime
                col = self._db_client.get_collection("sessions")
                if col:
                    col.update_one(
                        {"session_id": self._session_id},
                        {"$set": {"status": "ended", "logout_at": datetime.utcnow().isoformat()}},
                    )
        except Exception:
            pass

        # Wait up to 5 s for threads
        for t in self._monitor_threads:
            t.join(timeout=5.0)

        # Final offline flush
        try:
            if self._secure_logger and self._db_client and self._db_client.is_connected:
                col = self._db_client.get_collection("sessions")
                if col:
                    self._secure_logger.flush_queue(col)
        except Exception:
            pass

        if self._db_client:
            self._db_client.close()

        log.info("Shutdown complete.")
        sys.exit(0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main() -> None:
    parser = argparse.ArgumentParser(description="WorkPlus Employee Monitoring System")
    parser.add_argument("--admin", action="store_true", help="Open the admin panel directly")
    args = parser.parse_args()

    try:
        app = Application()
        app.run(admin_mode=args.admin)
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        log.critical("Unhandled exception: %s", exc, exc_info=True)
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "Fatal Error",
                f"An unexpected error occurred:\n\n{exc}\n\nThe application will close.",
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
