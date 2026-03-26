"""
R26-IT-042 — WorkPlus  |  Employee Activity Monitoring System
main.py

Application entry point.

Startup sequence
────────────────
1. Load config (config/settings.py)
2. Connect to MongoDB Atlas (common/database.py)
3. Show CustomTkinter Login Window (Employee ID + OTP)
4. On successful credential validation →
   a. Run C2 facial liveness check
   b. On pass → initialise C3 activity monitoring (background threads)
   c. Initialise C1 user interaction profiling
   d. Initialise C4 productivity prediction logger
5. Show minimised status window / system tray indicator
6. On logout / shutdown → graceful teardown of all threads + flush logs

Cross-platform notes
────────────────────
• sys.platform == "win32"  → Windows (pynput keyboard hook OK)
• sys.platform == "darwin" → macOS (prompt user to grant Accessibility +
                             Camera permissions in System Preferences)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so sibling packages resolve correctly
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Internal imports (all relative to project root)
# ---------------------------------------------------------------------------
from config.settings import settings
from common.database import MongoDBClient
from common.logger import SecureLogger
from common.alerts import AlertSender

# ---------------------------------------------------------------------------
# Logging bootstrap (stdlib) — SecureLogger is initialised after config loads
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")

# ---------------------------------------------------------------------------
# CustomTkinter global appearance
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ---------------------------------------------------------------------------
# Asset paths — supports .jfif / .jpg / .png automatically
# ---------------------------------------------------------------------------
ASSETS_DIR = _PROJECT_ROOT / "assets"

def _find_logo() -> Path:
    """Return the first logo file found in assets/, regardless of extension."""
    for name in ("logo.jfif", "logo.png", "logo.jpg", "logo.jpeg"):
        p = ASSETS_DIR / name
        if p.exists():
            return p
    return ASSETS_DIR / "logo.png"   # fallback (will raise, caught by except)

LOGO_PATH = _find_logo()


# ===========================================================================
# Login Window
# ===========================================================================

class LoginWindow(ctk.CTk):
    """
    CustomTkinter login window.

    Shows:
    • Company logo
    • Employee ID input
    • OTP input (6-digit)
    • Login button
    • Status / error label
    """

    def __init__(self, on_success_callback) -> None:
        super().__init__()

        self._on_success = on_success_callback

        # Window settings
        self.title(f"{settings.APP_NAME}  v{settings.VERSION} — Login")
        self.geometry("460x600")
        self.resizable(False, False)
        self.configure(fg_color="#0f1117")

        # Centre on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 460) // 2
        y = (self.winfo_screenheight() - 600) // 2
        self.geometry(f"460x600+{x}+{y}")

        self._build_ui()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Logo ─────────────────────────────────────────────────────────
        try:
            raw = Image.open(LOGO_PATH).convert("RGBA")   # JFIF/PNG/JPG all handled
            raw = raw.resize((120, 120), Image.LANCZOS)
            self._logo_img = ctk.CTkImage(light_image=raw, dark_image=raw, size=(120, 120))
            logo_label = ctk.CTkLabel(self, image=self._logo_img, text="")
        except Exception as _logo_err:
            log.warning("Could not load logo (%s) — using emoji fallback.", _logo_err)
            logo_label = ctk.CTkLabel(
                self, text="💼", font=ctk.CTkFont(size=72), text_color="#4f9eff"
            )
        logo_label.pack(pady=(40, 10))

        # ── App title ─────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text=settings.APP_NAME,
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#e2e8f0",
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            self,
            text="Employee Activity Monitoring System  ·  R26-IT-042",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
        ).pack(pady=(0, 30))

        # ── Form frame ────────────────────────────────────────────────────
        form = ctk.CTkFrame(self, fg_color="#1a1d27", corner_radius=16)
        form.pack(padx=40, fill="x")

        # Employee ID
        ctk.CTkLabel(
            form, text="Employee ID", font=ctk.CTkFont(size=12),
            text_color="#94a3b8", anchor="w",
        ).pack(padx=24, pady=(24, 4), fill="x")

        self._emp_id_var = ctk.StringVar()
        self._emp_id_entry = ctk.CTkEntry(
            form,
            textvariable=self._emp_id_var,
            placeholder_text="e.g.  EMP-001",
            height=44,
            font=ctk.CTkFont(size=14),
            border_color="#2d3748",
            fg_color="#0f1117",
        )
        self._emp_id_entry.pack(padx=24, fill="x")

        # OTP
        ctk.CTkLabel(
            form, text="One-Time Password (6 digits)", font=ctk.CTkFont(size=12),
            text_color="#94a3b8", anchor="w",
        ).pack(padx=24, pady=(16, 4), fill="x")

        self._otp_var = ctk.StringVar()
        self._otp_entry = ctk.CTkEntry(
            form,
            textvariable=self._otp_var,
            placeholder_text="● ● ● ● ● ●",
            show="●",
            height=44,
            font=ctk.CTkFont(size=14),
            border_color="#2d3748",
            fg_color="#0f1117",
        )
        self._otp_entry.pack(padx=24, fill="x")

        # Status label
        self._status_var = ctk.StringVar(value="")
        self._status_label = ctk.CTkLabel(
            form,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=12),
            text_color="#ef4444",
        )
        self._status_label.pack(pady=(8, 0))

        # Login button
        self._login_btn = ctk.CTkButton(
            form,
            text="Login",
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#3b82f6",
            hover_color="#2563eb",
            corner_radius=10,
            command=self._on_login_click,
        )
        self._login_btn.pack(padx=24, pady=(16, 24), fill="x")

        # Enter key binding
        self.bind("<Return>", lambda _: self._on_login_click())

    # -----------------------------------------------------------------------
    # Login logic
    # -----------------------------------------------------------------------

    def _on_login_click(self) -> None:
        emp_id = self._emp_id_var.get().strip()
        otp = self._otp_var.get().strip()

        self._set_status("")

        if not emp_id:
            self._set_status("Employee ID is required.")
            return

        if len(otp) != 6 or not otp.isdigit():
            self._set_status("OTP must be exactly 6 digits.")
            return

        # Disable button while processing
        self._login_btn.configure(state="disabled", text="Verifying…")
        self.update()

        # Run verification in a background thread to keep GUI responsive
        threading.Thread(
            target=self._verify_credentials,
            args=(emp_id, otp),
            daemon=True,
        ).start()

    def _verify_credentials(self, emp_id: str, otp: str) -> None:
        """Background thread: validate OTP then call success callback."""
        try:
            success = _validate_otp(emp_id, otp)
        except Exception as exc:
            log.error("OTP validation error: %s", exc)
            self.after(0, lambda: self._login_failed("Verification service unavailable."))
            return

        if success:
            self.after(0, lambda: self._login_succeeded(emp_id))
        else:
            self.after(0, lambda: self._login_failed("Invalid credentials.  Please try again."))

    def _login_succeeded(self, emp_id: str) -> None:
        self._set_status("✓ Credentials verified.", colour="#22c55e")
        self.after(500, lambda: self._on_success(emp_id))

    def _login_failed(self, reason: str) -> None:
        self._set_status(reason)
        self._login_btn.configure(state="normal", text="Login")

    def _set_status(self, msg: str, colour: str = "#ef4444") -> None:
        self._status_var.set(msg)
        self._status_label.configure(text_color=colour)


# ===========================================================================
# Status Window (shown after login)
# ===========================================================================

class StatusWindow(ctk.CTkToplevel):
    """
    Small floating status window shown while monitoring is active.
    Displays the currently monitored employee and monitoring state.
    """

    def __init__(self, master, user_id: str) -> None:
        super().__init__(master)

        self.title("Monitoring Active")
        self.geometry("320x200")
        self.resizable(False, False)
        self.configure(fg_color="#0f1117")

        ctk.CTkLabel(
            self,
            text="🟢  Monitoring Active",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#22c55e",
        ).pack(pady=(30, 8))

        ctk.CTkLabel(
            self,
            text=f"Employee: {user_id}",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
        ).pack(pady=4)

        self._status_label = ctk.CTkLabel(
            self,
            text="All trackers running.",
            font=ctk.CTkFont(size=12),
            text_color="#64748b",
        )
        self._status_label.pack(pady=4)

        ctk.CTkButton(
            self,
            text="Logout",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._on_logout,
        ).pack(pady=(20, 0), padx=40, fill="x")

    def update_status(self, msg: str) -> None:
        self._status_label.configure(text=msg)

    def _on_logout(self) -> None:
        if messagebox.askyesno("Logout", "Stop monitoring and log out?"):
            self.master.event_generate("<<AppShutdown>>")


# ===========================================================================
# Application Controller
# ===========================================================================

class Application:
    """
    Top-level application controller.  Owns all resources and orchestrates
    the startup / shutdown lifecycle.
    """

    def __init__(self) -> None:
        self._db_client: Optional[MongoDBClient] = None
        self._secure_logger: Optional[SecureLogger] = None
        self._alert_sender: Optional[AlertSender] = None
        self._user_id: Optional[str] = None
        self._monitor_threads: list[threading.Thread] = []
        self._shutdown_event = threading.Event()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main entry point — runs until the user logs out or closes the app."""
        self._check_platform()
        self._load_config()
        self._connect_db()
        self._init_logger()

        # Show login window
        login = LoginWindow(on_success_callback=self._on_login_success)
        login.bind("<<AppShutdown>>", lambda _: self._shutdown())
        login.protocol("WM_DELETE_WINDOW", self._shutdown)
        login.mainloop()

    def _check_platform(self) -> None:
        """Log platform and show macOS permission hint."""
        log.info("Platform: %s", sys.platform)
        if sys.platform == "darwin":
            messagebox.showinfo(
                "macOS Permissions Required",
                "This application requires:\n\n"
                "• Camera access (facial liveness)\n"
                "• Accessibility access (keyboard / mouse tracking)\n\n"
                "Grant these in System Preferences → Privacy & Security.",
            )

    def _load_config(self) -> None:
        """Validate settings; warn if any are missing."""
        missing = settings.validate()
        if missing:
            messagebox.showwarning(
                "Configuration Warning",
                f"The following environment variables are not set:\n\n"
                + "\n".join(f"  • {k}" for k in missing)
                + "\n\nSome features may be unavailable.  "
                "Edit the .env file and restart.",
            )
        log.info("Settings loaded: %s", settings)

    def _connect_db(self) -> None:
        """Attempt MongoDB Atlas connection (non-fatal if it fails)."""
        self._db_client = MongoDBClient(
            uri=settings.MONGO_URI,
            db_name=settings.MONGO_DB_NAME,
        )
        ok = self._db_client.connect()
        if not ok:
            log.warning("MongoDB offline — running in offline mode.")

    def _init_logger(self) -> None:
        self._secure_logger = SecureLogger(user_id="SYSTEM")
        self._alert_sender = AlertSender(
            ws_url=settings.WEBSOCKET_URL,
            fallback_logger=self._secure_logger,
        )

    # ------------------------------------------------------------------
    # Post-login flow
    # ------------------------------------------------------------------

    def _on_login_success(self, emp_id: str) -> None:
        """Called by LoginWindow after credentials pass."""
        self._user_id = emp_id
        log.info("Login success for user: %s", emp_id)

        # Update logger user context
        if self._secure_logger:
            self._secure_logger._user_id = emp_id

        # ── Step 1: Facial liveness check ────────────────────────
        if not self._run_face_liveness(emp_id):
            messagebox.showerror(
                "Face Verification Failed",
                "Facial liveness check did not pass.\n"
                "Please ensure your face is clearly visible and try again.",
            )
            return

        # ── Step 2: Start monitoring components ──────────────────
        self._init_monitoring(emp_id)

        # ── Step 3: Show status window ────────────────────────────
        self._show_status_window(emp_id)

    def _run_face_liveness(self, emp_id: str) -> bool:
        """
        Call C2_facial_liveness.  Returns True if the check passes.

        The actual implementation lives in C2_facial_liveness/src/.
        This stub imports it dynamically to avoid hard coupling.
        """
        try:
            from C2_facial_liveness.src import run_liveness_check  # type: ignore
            return run_liveness_check(user_id=emp_id)
        except ImportError:
            log.warning("C2_facial_liveness not yet implemented — bypassing face check.")
            return True  # Remove this default once C2 is ready
        except Exception as exc:
            log.error("Face liveness check error: %s", exc)
            return False

    def _init_monitoring(self, emp_id: str) -> None:
        """
        Initialise all three monitoring components in background threads.
        Each component's init function is imported dynamically.
        """
        # C3: Activity monitoring
        self._start_component_thread(
            name="C3-ActivityMonitoring",
            target=self._start_c3,
            args=(emp_id,),
        )
        # C1: User interaction profiling
        self._start_component_thread(
            name="C1-UserInteraction",
            target=self._start_c1,
            args=(emp_id,),
        )
        # C4: Productivity prediction
        self._start_component_thread(
            name="C4-ProductivityPrediction",
            target=self._start_c4,
            args=(emp_id,),
        )

    def _start_component_thread(self, name: str, target, args: tuple) -> None:
        t = threading.Thread(target=target, args=args, name=name, daemon=True)
        t.start()
        self._monitor_threads.append(t)
        log.info("Thread started: %s", name)

    def _start_c3(self, emp_id: str) -> None:
        try:
            from C3_activity_monitoring.src.initialize_monitoring import start_monitoring  # type: ignore
            start_monitoring(
                user_id=emp_id,
                db_client=self._db_client,
                alert_sender=self._alert_sender,
                shutdown_event=self._shutdown_event,
            )
        except ImportError:
            log.warning("C3_activity_monitoring not yet implemented — skipping.")
        except Exception as exc:
            log.error("C3 crashed: %s", exc)

    def _start_c1(self, emp_id: str) -> None:
        try:
            from C1_user_interaction.src import start_interaction_profiling  # type: ignore
            start_interaction_profiling(
                user_id=emp_id,
                shutdown_event=self._shutdown_event,
            )
        except ImportError:
            log.warning("C1_user_interaction not yet implemented — skipping.")
        except Exception as exc:
            log.error("C1 crashed: %s", exc)

    def _start_c4(self, emp_id: str) -> None:
        try:
            from C4_productivity_prediction.src import start_productivity_logger  # type: ignore
            start_productivity_logger(
                user_id=emp_id,
                db_client=self._db_client,
                shutdown_event=self._shutdown_event,
            )
        except ImportError:
            log.warning("C4_productivity_prediction not yet implemented — skipping.")
        except Exception as exc:
            log.error("C4 crashed: %s", exc)

    # ------------------------------------------------------------------
    # Status window
    # ------------------------------------------------------------------

    def _show_status_window(self, emp_id: str) -> None:
        # We need a root CTk window for the Toplevel; re-use the hidden login
        # root or create one.
        root = ctk.CTk()
        root.withdraw()  # hidden root keeps Tkinter alive
        root.bind("<<AppShutdown>>", lambda _: self._shutdown())

        status = StatusWindow(root, emp_id)
        status.protocol("WM_DELETE_WINDOW", self._shutdown)
        status.bind("<<AppShutdown>>", lambda _: self._shutdown())

        root.mainloop()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """Graceful teardown: stop threads, flush queues, close DB."""
        log.info("Shutting down — signalling all monitor threads.")
        self._shutdown_event.set()

        # Wait up to 5 s for threads to finish
        for t in self._monitor_threads:
            t.join(timeout=5.0)
            if t.is_alive():
                log.warning("Thread %s did not stop cleanly.", t.name)

        # Flush offline log queue
        if self._secure_logger and self._db_client and self._db_client.is_connected:
            col = self._db_client.get_collection("sessions")
            flushed = self._secure_logger.flush_queue(col)
            log.info("Flushed %d offline log entries.", flushed)

        # Close database
        if self._db_client:
            self._db_client.close()

        log.info("Shutdown complete. Goodbye.")
        sys.exit(0)


# ===========================================================================
# OTP Validation Helper
# ===========================================================================

def _validate_otp(emp_id: str, otp: str) -> bool:
    """
    Validate the TOTP code for *emp_id*.

    In production this queries MongoDB for the employee's TOTP secret and
    verifies the code using pyotp.  During development / before C1 is
    wired up, it accepts any 6-digit code for any valid employee ID.

    Parameters
    ----------
    emp_id:
        Employee identifier string.
    otp:
        6-digit OTP string.

    Returns
    -------
    bool
        True if the OTP is valid for the current time window.
    """
    try:
        import pyotp

        # TODO: Replace with real DB lookup
        # secret = db.get_collection("auth_events").find_one({"user_id": emp_id})["totp_secret"]
        # totp = pyotp.TOTP(secret)
        # return totp.verify(otp)

        # ── Development stub ──────────────────────────────────────────────
        log.debug("Dev mode: accepting OTP for %s (OTP validation not yet wired to DB)", emp_id)
        return len(otp) == 6 and otp.isdigit() and bool(emp_id)

    except ImportError:
        log.warning("pyotp not installed — accepting any 6-digit OTP.")
        return len(otp) == 6 and otp.isdigit()


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    try:
        app = Application()
        app.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        log.critical("Unhandled exception in main: %s", exc, exc_info=True)
        try:
            messagebox.showerror(
                "Fatal Error",
                f"An unexpected error occurred:\n\n{exc}\n\nThe application will close.",
            )
        except Exception:
            pass
        sys.exit(1)
