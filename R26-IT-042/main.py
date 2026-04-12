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
import subprocess
import sys
import threading
import time
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from typing import Optional

import customtkinter as ctk

# Keep TensorFlow/MediaPipe runtime logs quieter in console output.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

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
        self._employee_panel = None
        self._shutdown_event = threading.Event()
        self._root: Optional[ctk.CTk] = None
        self._liveness_score = 1.0
        self._cam_streaming = False
        self._screen_streaming = False
        self._location_mode = "unknown"
        self._current_city = "Unknown"
        self._location_context: dict = {}

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
        log.info("Python executable: %s", sys.executable)
        try:
            mp_version = version("mediapipe")
            log.info("MediaPipe package version=%s", mp_version)
        except PackageNotFoundError:
            log.warning("MediaPipe package is not installed in this interpreter.")
        except Exception as exc:
            log.warning("MediaPipe package check failed: %s", exc)
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
            db["antispoofing_checks"].create_index(
                [("user_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="user_antispoofing_checks", background=True,
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
        self._liveness_score = employee.get("face_liveness_score", 1.0)
        self._location_mode = str(employee.get("location_mode") or "unknown").lower()
        self._current_city = employee.get("geo_city") or "Unknown"
        self._location_context = {
            "city": employee.get("geo_city") or "Unknown",
            "region": employee.get("geo_region") or "Unknown",
            "country": employee.get("geo_country") or "Unknown",
            "timezone": employee.get("geo_timezone") or "Unknown",
            "isp": employee.get("geo_isp") or "Unknown",
            "org": employee.get("geo_org") or "Unknown",
            "asn": employee.get("geo_asn") or "Unknown",
            "geo_source": employee.get("geo_source") or "unknown",
            "lat": employee.get("geo_lat"),
            "lon": employee.get("geo_lon"),
            "confidence": float(employee.get("geo_confidence") or 0.0),
            "location_hint": employee.get("geo_hint") or "Unknown",
            "vpn_proxy_detected": bool(employee.get("vpn_proxy_detected", False)),
            "hosting_detected": bool(employee.get("hosting_detected", False)),
            "geolocation_deviation": employee.get("geolocation_deviation"),
            "inside_office_geofence": employee.get("inside_office_geofence"),
            "geolocation_resolved": bool(employee.get("geolocation_resolved", False)),
            "office_radius_km": float(employee.get("office_radius_km") or 0.0),
            "location_trust_score": float(employee.get("location_trust_score") or 0.0),
        }
        log.info("Login success: %s session=%s liveness=%.2f", self._user_id, session_id, self._liveness_score)

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
            break_manager=getattr(self, "_break_manager", None)
        )
        self._employee_panel = panel
        # Add a helper to the root so panel can call it
        root.show_login = self._restart_at_login
        panel.protocol("WM_DELETE_WINDOW", self._shutdown)

        # Log attendance sign-in
        self._log_attendance_signin()

        root.mainloop()

    def _log_attendance_signin(self) -> None:
        try:
            from datetime import datetime, timezone
            col = self._db_client.get_collection("attendance_logs")
            if col is not None:
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
                        "location": getattr(self, "_current_city", "Unknown"),
                        "status": "On Time",
                    })
                else:
                    # Relog on the same day — clear signout/duration so they show as online
                    col.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {"signout": None, "duration": None, "status": "On Time"}}
                    )
        except Exception as exc:
            log.warning("Attendance signin log error: %s", exc)

    def _log_attendance_signout(self) -> None:
        try:
            from datetime import datetime
            col = self._db_client.get_collection("attendance_logs")
            if col is not None:
                today = datetime.now().strftime("%Y-%m-%d")
                now_str = datetime.now().strftime("%H:%M:%S")
                
                # Update today's record
                doc = col.find_one({"employee_id": self._user_id, "date": today})
                if doc and doc.get("signin"):
                    # Calculate duration
                    s_t = datetime.strptime(doc["signin"], "%H:%M:%S")
                    e_t = datetime.strptime(now_str, "%H:%M:%S")
                    diff = e_t - s_t
                    duration = str(diff).split(".")[0] # HH:MM:SS
                    
                    col.update_one(
                        {"employee_id": self._user_id, "date": today},
                        {"$set": {
                            "signout": now_str,
                            "duration": duration,
                            "status": "Offline"
                        }}
                    )
        except Exception as exc:
            log.warning("Attendance signout log error: %s", exc)

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
        # REMOTE COMMANDS: Admin-to-Employee instructions
        self._start_thread("COMMANDS", self._start_command_poller)

    def _restart_at_login(self) -> None:
        """Called on logout to return to the login screen."""
        log.info("Restarting at login...")
        self._log_attendance_signout()
        self._shutdown_monitoring()
        if self._root:
            self._root.destroy()
        self._launch_login()

    def _shutdown_monitoring(self) -> None:
        self._shutdown_event.set()
        for t in self._monitor_threads:
            t.join(timeout=1.0)
        self._monitor_threads = []
        self._shutdown_event.clear()

    def _start_thread(self, name: str, target) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._monitor_threads.append(t)
        log.info("Thread started: %s", name)

    def _start_c3(self) -> None:
        try:
            from C3_activity_monitoring.src.initialize_monitoring import start_monitoring
            self._break_manager = start_monitoring(
                user_id=self._user_id,
                db_client=self._db_client,
                alert_sender=self._alert_sender,
                shutdown_event=self._shutdown_event,
                session_id=self._session_id,
                location_mode=self._location_mode,
                location_context=self._location_context,
                wifi_ssid_match=False,
                face_liveness_score=self._liveness_score,
            )
            try:
                panel = getattr(self, "_employee_panel", None)
                if panel is not None and hasattr(panel, "set_break_manager"):
                    panel.set_break_manager(self._break_manager)
            except Exception:
                pass
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

    def _start_command_poller(self) -> None:
        """
        Background thread that listens for instructions from the admin panel
        (e.g., force screenshot, lock workstation, display message).
        """
        try:
            from common.commands import CommandPoller
            from C3_activity_monitoring.src.screenshot_trigger import ScreenshotTrigger
            from common.encryption import AESEncryptor
            import cv2
            import base64
            from datetime import datetime

            poller = CommandPoller(
                user_id=self._user_id,
                db_client=self._db_client,
                shutdown_event=self._shutdown_event,
                interval_sec=10
            )

            # --- Handler: Remote Screenshot ---
            def handle_screenshot(cmd: dict):
                log.info("Executing remote command: force_screenshot")
                try:
                    enc = AESEncryptor()
                    st = ScreenshotTrigger(db_client=self._db_client, encryptor=enc)
                    st.capture(
                        user_id=self._user_id,
                        session_id=self._session_id or "admin_remote",
                        risk_score=cmd.get("risk_score", 0.0),
                        trigger_reason="admin_remote_force"
                    )
                except Exception as e:
                    log.error("Remote screenshot execution failed: %s", e)
                    raise

            # --- Handler: Live Cam & Screen ---
            self._cam_streaming = False
            self._screen_streaming = False
            
            def handle_start_cam(cmd: dict):
                if self._cam_streaming: return
                log.info("Starting live camera stream for admin")
                self._cam_streaming = True
                
                def stream_loop():
                    col = self._db_client.get_collection("camera_streams")
                    cap = cv2.VideoCapture(0)
                    if not cap.isOpened():
                        log.error("LIVE CAM: Could not open camera.")
                        if col is not None:
                            col.update_one({"user_id": self._user_id}, {"$set": {"status": "off", "error": "Camera unavailable"}}, upsert=True)
                        self._cam_streaming = False
                        return

                    log.info("LIVE CAM: Camera stream started.")
                    try:
                        while self._cam_streaming and not self._shutdown_event.is_set():
                            ret, frame = cap.read()
                            if ret:
                                # Resize and encode
                                frame = cv2.resize(frame, (320, 240))
                                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                                b64 = base64.b64encode(buffer).decode('utf-8')
                                
                                if col is not None:
                                    col.update_one(
                                        {"user_id": self._user_id},
                                        {"$set": {
                                            "image_base64": b64,
                                            "timestamp": datetime.utcnow().isoformat(),
                                            "status": "streaming"
                                        }},
                                        upsert=True
                                    )
                            else:
                                log.warning("LIVE CAM: Failed to capture frame.")
                            time.sleep(1.0)
                    except Exception as e:
                        log.error("LIVE CAM: Loop error: %s", e)
                    finally:
                        cap.release()
                        if col is not None:
                            col.update_one({"user_id": self._user_id}, {"$set": {"status": "off"}})
                        self._cam_streaming = False
                        log.info("LIVE CAM: Camera stream stopped.")

                threading.Thread(target=stream_loop, daemon=True).start()

            def handle_stop_cam(cmd: dict):
                log.info("Stopping live camera stream")
                self._cam_streaming = False

            def handle_start_screen(cmd: dict):
                if self._screen_streaming: return
                log.info("Starting live screen stream for admin")
                self._screen_streaming = True
                
                def screen_loop():
                    import pyautogui, io
                    col = self._db_client.get_collection("screen_streams")
                    try:
                        while self._screen_streaming and not self._shutdown_event.is_set():
                            # Capture
                            img = pyautogui.screenshot()
                            # Resize to reasonable size
                            img = img.resize((640, 360))
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=40)
                            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                            
                            if col is not None:
                                col.update_one(
                                    {"user_id": self._user_id},
                                    {"$set": {
                                        "image_base64": b64,
                                        "timestamp": datetime.utcnow().isoformat(),
                                        "status": "streaming"
                                    }},
                                    upsert=True
                                )
                            time.sleep(2.0) # Slightly slower for screen
                    except Exception as e:
                        log.error("LIVE SCREEN: Loop error: %s", e)
                    finally:
                        if col is not None:
                            col.update_one({"user_id": self._user_id}, {"$set": {"status": "off"}})
                        self._screen_streaming = False
                        log.info("LIVE SCREEN: Screen stream stopped.")

                threading.Thread(target=screen_loop, daemon=True).start()

            def handle_stop_screen(cmd: dict):
                log.info("Stopping live screen stream")
                self._screen_streaming = False

            def handle_antispoofing_check(cmd: dict):
                """
                Remote anti-spoofing check initiated by admin.
                Runs ResNet50 model on live camera frames and stores results.
                """
                log.info("Executing remote command: antispoofing_check")
                try:
                    from C2_Anti_Spoofing_Detection.src.antispoofing_detector import AntiSpoofingDetector
                    from common.antispoofing_utils import store_antispoofing_result
                    import time as time_module
                    
                    detector = AntiSpoofingDetector()
                    if not detector.load_model():
                        log.error("Anti-spoofing model failed to load.")
                        return
                    
                    import cv2
                    cap = cv2.VideoCapture(0)
                    if not cap.isOpened():
                        log.warning("Camera not available for anti-spoofing check.")
                        detector.close()
                        return
                    
                    # Run check: collect predictions over ~10 seconds
                    predictions = []
                    scores = []
                    start_time = time_module.time()
                    timeout_sec = 10.0
                    
                    while (time_module.time() - start_time) < timeout_sec:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        
                        is_real, confidence, _ = detector.predict(frame)
                        predictions.append(is_real)
                        scores.append(1.0 - confidence if is_real else confidence)
                    
                    cap.release()
                    detector.close()
                    
                    if not predictions:
                        log.warning("No frames captured for anti-spoofing check.")
                        return
                    
                    # Average results
                    duration = time_module.time() - start_time
                    avg_is_real = sum(predictions) / len(predictions) >= 0.5
                    avg_confidence = sum(confidence for confidence in scores) / len(scores) if scores else 0.0
                    avg_score = sum(scores) / len(scores) if scores else 0.5
                    
                    # Store to database
                    success = store_antispoofing_result(
                        db_client=self._db_client,
                        user_id=self._user_id,
                        is_real=avg_is_real,
                        confidence=avg_confidence,
                        frame_count=len(predictions),
                        avg_score=avg_score,
                        duration_sec=duration,
                    )
                    
                    if success:
                        log.info(
                            "Anti-spoofing check completed: user=%s verdict=%s confidence=%.2f frames=%d",
                            self._user_id,
                            "REAL" if avg_is_real else "FAKE",
                            avg_confidence,
                            len(predictions),
                        )
                    
                except Exception as e:
                    log.error("Anti-spoofing check execution failed: %s", e)
            
            poller.register_handler("force_screenshot", handle_screenshot)
            poller.register_handler("start_live_cam", handle_start_cam)
            poller.register_handler("stop_live_cam", handle_stop_cam)
            poller.register_handler("start_live_screen", handle_start_screen)
            poller.register_handler("stop_live_screen", handle_stop_screen)
            poller.register_handler("start_antispoofing_check", handle_antispoofing_check)
            
            # Start polling
            poller.start()

        except Exception as exc:
            log.error("Command poller initialization failed: %s", exc)

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
                if col is not None:
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
                if col is not None:
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

def _select_venv_python() -> Optional[Path]:
    """Return local venv python path if it exists."""
    venv_py = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return venv_py if venv_py.exists() else None


def _ensure_venv_interpreter() -> None:
    """Relaunch with local venv interpreter when started from system Python."""
    if os.environ.get("WORKPLUS_SKIP_VENV_REEXEC") == "1":
        return

    venv_py = _select_venv_python()
    if venv_py is None:
        return

    current = str(Path(sys.executable).resolve()).lower()
    target = str(venv_py.resolve()).lower()
    if current == target:
        return

    os.environ["WORKPLUS_SKIP_VENV_REEXEC"] = "1"
    print(f"[WorkPlus] Switching interpreter to venv: {venv_py}")
    env = os.environ.copy()
    env["WORKPLUS_SKIP_VENV_REEXEC"] = "1"
    subprocess.Popen([str(venv_py), *sys.argv], cwd=str(_PROJECT_ROOT), env=env)
    raise SystemExit(0)

def main() -> None:
    _ensure_venv_interpreter()

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
