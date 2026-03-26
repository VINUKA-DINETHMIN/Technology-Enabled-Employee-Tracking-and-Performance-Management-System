"""
R26-IT-042 — Employee Activity Monitoring System
app/login.py

3-Step Login Flow:
  Step 1 — Employee ID + Password (bcrypt verify, lockout after 3 fails)
  Step 2 — TOTP MFA (pyotp, 6-digit Google Authenticator code)
  Step 3 — Face Verification + Liveness Check (OpenCV DNN + C2 liveness)

On full success:
  - Creates session document in MongoDB "sessions" collection
  - Logs auth event to "auth_events"
  - Starts C3 activity trackers
  - Opens employee_panel.py

Lockout:
  - Password: 5 minutes after 3 failed attempts
  - Face:     15 minutes after 3 failed attempts → CRITICAL alert
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import numpy as np

from common.database import MongoDBClient
from common.alerts import AlertSender
from config.settings import settings

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Color palette ─────────────────────────────────────────────────────────
C_BG    = "#0b0e17"
C_CARD  = "#151b2d"
C_BORDER= "#1e2a40"
C_TEAL  = "#14b8a6"
C_TEAL_D= "#0d9488"
C_RED   = "#ef4444"
C_GREEN = "#22c55e"
C_BLUE  = "#3b82f6"
C_TEXT  = "#e2e8f0"
C_MUTED = "#64748b"

# Lockout constants
_PW_LOCKOUT_MINUTES = 5
_FACE_LOCKOUT_MINUTES = 15
_MAX_ATTEMPTS = 3

# Face similarity threshold (cosine similarity of histogram embeddings)
_FACE_THRESHOLD = 0.80

LOGO_PATH = _ROOT / "assets" / "logo.png"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step Indicator Widget
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class StepIndicator(ctk.CTkFrame):
    """Three-step progress indicator at the top of the login window."""

    STEP_LABELS = ["Password", "MFA Code", "Face Check"]

    def __init__(self, parent, **kw) -> None:
        super().__init__(parent, fg_color="transparent", **kw)
        self._circles: list[ctk.CTkLabel] = []
        self._step_labels: list[ctk.CTkLabel] = []

        for i, label in enumerate(self.STEP_LABELS):
            col = ctk.CTkFrame(self, fg_color="transparent")
            col.pack(side="left", expand=True)

            circle = ctk.CTkLabel(
                col, text=str(i + 1),
                width=36, height=36,
                corner_radius=18,
                fg_color=C_BORDER,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=C_MUTED,
            )
            circle.pack()

            lbl = ctk.CTkLabel(
                col, text=label,
                font=ctk.CTkFont(size=10),
                text_color=C_MUTED,
            )
            lbl.pack(pady=(4, 0))

            self._circles.append(circle)
            self._step_labels.append(lbl)

            # Connector line between steps
            if i < len(self.STEP_LABELS) - 1:
                line = ctk.CTkFrame(self, height=2, fg_color=C_BORDER, width=60)
                line.pack(side="left", pady=(0, 20))

        self.set_step(0)

    def set_step(self, active: int) -> None:
        """Highlight the active step (0-indexed)."""
        for i, (circle, lbl) in enumerate(zip(self._circles, self._step_labels)):
            if i < active:
                circle.configure(fg_color=C_GREEN, text_color="#fff", text="✓")
                lbl.configure(text_color=C_GREEN)
            elif i == active:
                circle.configure(fg_color=C_TEAL, text_color="#fff", text=str(i + 1))
                lbl.configure(text_color=C_TEAL)
            else:
                circle.configure(fg_color=C_BORDER, text_color=C_MUTED, text=str(i + 1))
                lbl.configure(text_color=C_MUTED)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Login Window
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LoginWindow(ctk.CTk):
    """
    3-Step login: Password → MFA → Face + Liveness.
    """

    def __init__(
        self,
        db: MongoDBClient,
        on_success: Callable[[dict, str], None],
        alert_sender: Optional[AlertSender] = None,
    ) -> None:
        super().__init__()
        self._db = db
        self._on_success = on_success
        self._alert_sender = alert_sender

        self._current_employee: Optional[dict] = None
        self._session_id = str(uuid.uuid4())
        self._step = 0
        self._pw_attempts = 0
        self._mfa_attempts = 0
        self._face_attempts = 0

        self.title(f"{settings.APP_NAME} — Login")
        self.geometry("480x680")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 480) // 2
        y = (self.winfo_screenheight() - 680) // 2
        self.geometry(f"480x680+{x}+{y}")

        self._build()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # Logo
        try:
            from PIL import Image
            raw = Image.open(LOGO_PATH).convert("RGBA").resize((90, 90), Image.LANCZOS)
            self._logo = ctk.CTkImage(light_image=raw, dark_image=raw, size=(90, 90))
            ctk.CTkLabel(self, image=self._logo, text="").pack(pady=(30, 4))
        except Exception:
            ctk.CTkLabel(self, text="WorkPlus", font=ctk.CTkFont(size=32, weight="bold"),
                         text_color=C_TEAL).pack(pady=(30, 4))

        ctk.CTkLabel(self, text=settings.APP_NAME,
                     font=ctk.CTkFont(size=18, weight="bold"), text_color=C_TEXT).pack()
        ctk.CTkLabel(self, text="Employee Activity Monitoring System",
                     font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=(0, 16))

        # Step indicator
        self._indicator = StepIndicator(self)
        self._indicator.pack(padx=40, fill="x")

        ctk.CTkFrame(self, height=1, fg_color=C_BORDER).pack(fill="x", padx=32, pady=12)

        # Step content container
        self._step_container = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=16)
        self._step_container.pack(fill="x", padx=32)

        # Status label (shared)
        self._status_var = ctk.StringVar()
        self._status_lbl = ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=ctk.CTkFont(size=11), text_color=C_RED, wraplength=380,
        )
        self._status_lbl.pack(pady=8)

        self._show_step_1()

    def _clear_step(self) -> None:
        for w in self._step_container.winfo_children():
            w.destroy()
        self._status_var.set("")

    # ------------------------------------------------------------------
    # Step 1 — Password
    # ------------------------------------------------------------------

    def _show_step_1(self) -> None:
        self._step = 0
        self._clear_step()
        self._indicator.set_step(0)

        ctk.CTkLabel(self._step_container, text="Sign In",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=C_TEXT).pack(padx=24, pady=(20, 8), anchor="w")

        ctk.CTkLabel(self._step_container, text="Employee ID",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(padx=24, fill="x")
        self._emp_id_var = ctk.StringVar()
        self._emp_id_entry = ctk.CTkEntry(
            self._step_container, textvariable=self._emp_id_var,
            placeholder_text="e.g. EMP-001", height=42,
            fg_color="#0f1117", border_color=C_BORDER,
        )
        self._emp_id_entry.pack(padx=24, fill="x", pady=(2, 10))

        ctk.CTkLabel(self._step_container, text="Password",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(padx=24, fill="x")

        pw_row = ctk.CTkFrame(self._step_container, fg_color="transparent")
        pw_row.pack(padx=24, fill="x", pady=(2, 10))
        self._pw_var = ctk.StringVar()
        self._pw_entry = ctk.CTkEntry(pw_row, textvariable=self._pw_var,
                                       show="•", height=42,
                                       fg_color="#0f1117", border_color=C_BORDER)
        self._pw_entry.pack(side="left", fill="x", expand=True)
        self._show_pw = False
        toggle_btn = ctk.CTkButton(pw_row, text="Show", width=56, height=42,
                                    fg_color=C_BORDER, hover_color="#374151",
                                    command=self._toggle_pw)
        toggle_btn.pack(side="left", padx=(4, 0))
        self._toggle_btn = toggle_btn

        self._login_btn = ctk.CTkButton(
            self._step_container, text="Continue",
            height=44, fg_color=C_TEAL, hover_color=C_TEAL_D,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_step1_submit,
        )
        self._login_btn.pack(padx=24, fill="x", pady=(4, 20))
        self.bind("<Return>", lambda _: self._on_step1_submit())
        self._emp_id_entry.focus()

    def _toggle_pw(self) -> None:
        self._show_pw = not self._show_pw
        self._pw_entry.configure(show="" if self._show_pw else "•")
        self._toggle_btn.configure(text="Hide" if self._show_pw else "Show")

    def _on_step1_submit(self) -> None:
        emp_id = self._emp_id_var.get().strip()
        password = self._pw_var.get()
        if not emp_id or not password:
            self._set_status("Please enter both Employee ID and password.")
            return
        self._login_btn.configure(state="disabled", text="Verifying…")
        threading.Thread(target=self._verify_password, args=(emp_id, password), daemon=True).start()

    def _verify_password(self, emp_id: str, password: str) -> None:
        try:
            col = self._db.get_collection("employees")
            if col is None:
                self.after(0, lambda: self._set_status("Database unavailable. Try again."))
                self.after(0, lambda: self._login_btn.configure(state="normal", text="Continue"))
                return

            emp = col.find_one({"employee_id": emp_id})
            if emp is None:
                self._pw_attempts += 1
                self.after(0, lambda: self._set_status(f"Employee ID not found. ({self._pw_attempts}/{_MAX_ATTEMPTS})"))
                self.after(0, lambda: self._login_btn.configure(state="normal", text="Continue"))
                return

            # Check lockout
            locked_until = emp.get("locked_until")
            if locked_until:
                try:
                    lu = datetime.fromisoformat(locked_until)
                    if datetime.utcnow() < lu.replace(tzinfo=None):
                        remaining = (lu.replace(tzinfo=None) - datetime.utcnow()).seconds // 60 + 1
                        self.after(0, lambda r=remaining: self._set_status(f"Account locked. Try again in {r} minute(s)."))
                        self.after(0, lambda: self._login_btn.configure(state="normal", text="Continue"))
                        return
                except Exception:
                    pass

            # Verify password
            import bcrypt
            pw_hash = emp.get("password_hash", "").encode()
            if not bcrypt.checkpw(password.encode(), pw_hash):
                self._pw_attempts += 1
                if self._pw_attempts >= _MAX_ATTEMPTS:
                    lock_until = (datetime.utcnow() + timedelta(minutes=_PW_LOCKOUT_MINUTES)).isoformat()
                    col.update_one({"employee_id": emp_id}, {"$set": {"locked_until": lock_until}})
                    self.after(0, lambda: self._set_status(f"Too many attempts. Account locked for {_PW_LOCKOUT_MINUTES} minutes."))
                else:
                    self.after(0, lambda a=self._pw_attempts: self._set_status(f"Incorrect password. ({a}/{_MAX_ATTEMPTS})"))
                self.after(0, lambda: self._login_btn.configure(state="normal", text="Continue"))
                return

            # Success — move to step 2
            self._current_employee = emp
            self._pw_attempts = 0
            self.after(0, self._show_step_2)

        except Exception as exc:
            logger.error("Password verify error: %s", exc)
            self.after(0, lambda: self._set_status("Verification error. Please try again."))
            self.after(0, lambda: self._login_btn.configure(state="normal", text="Continue"))

    # ------------------------------------------------------------------
    # Step 2 — MFA TOTP
    # ------------------------------------------------------------------

    def _show_step_2(self) -> None:
        self._step = 1
        self._clear_step()
        self._indicator.set_step(1)

        ctk.CTkLabel(self._step_container, text="Two-Factor Authentication",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=C_TEXT).pack(padx=24, pady=(20, 4), anchor="w")
        ctk.CTkLabel(self._step_container, text="Enter the 6-digit code from your authenticator app",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED, wraplength=380).pack(padx=24, anchor="w")

        self._otp_var = ctk.StringVar()
        otp_entry = ctk.CTkEntry(
            self._step_container, textvariable=self._otp_var,
            placeholder_text="● ● ● ● ● ●", height=52,
            font=ctk.CTkFont(size=22), justify="center",
            fg_color="#0f1117", border_color=C_BORDER,
        )
        otp_entry.pack(padx=24, fill="x", pady=(14, 4))
        otp_entry.focus()

        ctk.CTkLabel(self._step_container, text="Use Google Authenticator or compatible app",
                     font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(padx=24, anchor="w")

        self._mfa_btn = ctk.CTkButton(
            self._step_container, text="Verify Code",
            height=44, fg_color=C_TEAL, hover_color=C_TEAL_D,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_step2_submit,
        )
        self._mfa_btn.pack(padx=24, fill="x", pady=(14, 20))

        # Auto-submit when 6 digits entered
        self._otp_var.trace_add("write", lambda *_: self._otp_auto_submit())
        self.bind("<Return>", lambda _: self._on_step2_submit())

    def _otp_auto_submit(self) -> None:
        if len(self._otp_var.get()) == 6 and self._otp_var.get().isdigit():
            self.after(200, self._on_step2_submit)

    def _on_step2_submit(self) -> None:
        code = self._otp_var.get().strip()
        if len(code) != 6 or not code.isdigit():
            self._set_status("Enter a valid 6-digit code.")
            return
        self._mfa_btn.configure(state="disabled", text="Verifying…")
        threading.Thread(target=self._verify_mfa, args=(code,), daemon=True).start()

    def _verify_mfa(self, code: str) -> None:
        try:
            import pyotp
            secret = self._current_employee.get("mfa_secret", "")
            if not secret:
                # Dev bypass: accept any valid 6-digit code
                logger.warning("No MFA secret for employee — dev bypass active.")
                self.after(0, self._show_step_3)
                return

            totp = pyotp.TOTP(secret)
            if totp.verify(code, valid_window=1):
                self._mfa_attempts = 0
                self.after(0, self._show_step_3)
            else:
                self._mfa_attempts += 1
                if self._mfa_attempts >= _MAX_ATTEMPTS:
                    self.after(0, lambda: self._set_status("Too many invalid codes. Please restart login."))
                    self.after(2000, self._show_step_1)
                else:
                    self.after(0, lambda a=self._mfa_attempts: self._set_status(f"Invalid code. ({a}/{_MAX_ATTEMPTS})"))
                    self.after(0, lambda: self._mfa_btn.configure(state="normal", text="Verify Code"))
        except Exception as exc:
            logger.error("MFA verify error: %s", exc)
            self.after(0, lambda: self._set_status("MFA verification error."))
            self.after(0, lambda: self._mfa_btn.configure(state="normal", text="Verify Code"))

    # ------------------------------------------------------------------
    # Step 3 — Face Verification + Liveness
    # ------------------------------------------------------------------

    def _show_step_3(self) -> None:
        self._step = 2
        self._clear_step()
        self._indicator.set_step(2)

        ctk.CTkLabel(self._step_container, text="Face Verification",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=C_TEXT).pack(padx=24, pady=(20, 4), anchor="w")
        ctk.CTkLabel(self._step_container, text="Look directly at the camera and blink naturally",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(padx=24, anchor="w", pady=(0, 8))

        # macOS permission warning
        if sys.platform == "darwin":
            ctk.CTkLabel(self._step_container,
                         text="macOS: Grant camera access in System Preferences → Privacy.",
                         font=ctk.CTkFont(size=10), text_color=C_AMBER).pack(padx=24, anchor="w")

        # Camera canvas with rounded corners
        canvas_frame = ctk.CTkFrame(self._step_container, fg_color=C_BORDER, corner_radius=16)
        canvas_frame.pack(padx=24, pady=8)
        import tkinter as tk
        self._cam_canvas = tk.Canvas(canvas_frame, width=360, height=270,
                                      bg="#0b0e17", highlightthickness=0)
        self._cam_canvas.pack(padx=2, pady=2)

        self._face_status_var = ctk.StringVar(value="Look at the camera…")
        ctk.CTkLabel(self._step_container, textvariable=self._face_status_var,
                     font=ctk.CTkFont(size=12), text_color=C_MUTED).pack(pady=4)

        self._face_btn = ctk.CTkButton(
            self._step_container, text="Cancel",
            height=40, fg_color=C_BORDER, hover_color="#374151",
            command=self._cancel_face,
        )
        self._face_btn.pack(padx=24, fill="x", pady=(4, 16))

        # Start face check in background
        self._face_running = True
        threading.Thread(target=self._run_face_check, daemon=True).start()

    def _run_face_check(self) -> None:
        try:
            import cv2
            from C2_facial_liveness.src.liveness_detector import LivenessDetector
            from PIL import Image, ImageTk

            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self.after(0, lambda: self._face_status_var.set("Camera not available — check permissions."))
                self.after(0, self._on_face_fail)
                return

            detector = LivenessDetector()
            detector.initialize()

            stored_embedding = self._current_employee.get("face_embedding", [])
            verified_count = 0
            start_ts = time.time()
            max_duration = 40.0

            while self._face_running and (time.time() - start_ts) < max_duration:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                detector.process_frame(frame_rgb)

                # Draw face detection overlay
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                faces = cascade.detectMultiScale(gray, 1.1, 5)
                display = frame_rgb.copy()
                for (x, y, w_, h_) in faces:
                    cv2.rectangle(display, (x, y), (x + w_, y + h_), (20, 184, 166), 2)

                # Render to canvas
                try:
                    img = Image.fromarray(display).resize((360, 270))
                    photo = ImageTk.PhotoImage(img)
                    self._cam_canvas.after(0, lambda p=photo: self._draw_cam(p))
                except Exception:
                    pass

                # Face similarity check
                if len(faces) > 0 and stored_embedding:
                    current_emb = self._compute_embedding(gray)
                    sim = self._cosine_similarity(current_emb, stored_embedding)
                    if sim >= _FACE_THRESHOLD:
                        verified_count += 1
                    else:
                        verified_count = max(verified_count - 1, 0)

                liveness = detector.get_result()

                # Check pass conditions
                if verified_count >= 10 and liveness.passed:
                    cap.release()
                    detector.close()
                    self.after(0, lambda s=liveness.liveness_score: self._on_face_success(s))
                    return

                # Status updates
                if len(faces) == 0:
                    self.after(0, lambda: self._face_status_var.set("Look at the camera…"))
                elif not liveness.passed:
                    blinks = liveness.blink_count
                    self.after(0, lambda b=blinks: self._face_status_var.set(
                        f"Checking identity… Please blink naturally. (blinks: {b})"
                    ))
                elif verified_count < 10:
                    self.after(0, lambda: self._face_status_var.set("Checking identity…"))

                time.sleep(1 / 20)

            cap.release()
            detector.close()

            # Timed out or failed
            self.after(0, self._on_face_fail)

        except Exception as exc:
            logger.error("Face check error: %s", exc)
            self.after(0, self._on_face_fail)

    def _draw_cam(self, photo) -> None:
        try:
            self._cam_canvas._photo = photo
            self._cam_canvas.delete("all")
            self._cam_canvas.create_image(0, 0, anchor="nw", image=photo)
        except Exception:
            pass

    def _compute_embedding(self, gray_frame) -> list:
        try:
            import cv2
            hist = cv2.calcHist([gray_frame], [0], None, [128], [0, 256])
            return [float(v[0]) for v in hist]
        except Exception:
            return []

    def _cosine_similarity(self, a: list, b: list) -> float:
        try:
            va = np.array(a, dtype=np.float32)
            vb = np.array(b, dtype=np.float32)
            if len(va) != len(vb):
                # Pad/truncate to match
                min_len = min(len(va), len(vb))
                va, vb = va[:min_len], vb[:min_len]
            norm_a = np.linalg.norm(va)
            norm_b = np.linalg.norm(vb)
            if norm_a < 1e-6 or norm_b < 1e-6:
                return 0.0
            return float(np.dot(va, vb) / (norm_a * norm_b))
        except Exception:
            return 0.0

    def _on_face_success(self, liveness_score: float) -> None:
        self._face_running = False
        self._face_status_var.set("Identity verified!")
        self._status_lbl.configure(text_color=C_GREEN)
        self._set_status("Identity verified! Starting session…", color=C_GREEN)
        self.after(800, lambda: self._finalize_login(liveness_score))

    def _on_face_fail(self) -> None:
        self._face_running = False
        self._face_attempts += 1

        if self._face_attempts >= _MAX_ATTEMPTS:
            # Lock account for 15 minutes
            emp_id = self._current_employee.get("employee_id", "")
            lock_until = (datetime.utcnow() + timedelta(minutes=_FACE_LOCKOUT_MINUTES)).isoformat()
            try:
                col = self._db.get_collection("employees")
                if col:
                    col.update_one({"employee_id": emp_id}, {"$set": {"locked_until": lock_until}})
            except Exception:
                pass

            # Log CRITICAL security event
            self._log_auth_event("face_fail_lockout", emp_id, success=False)

            if self._alert_sender:
                try:
                    self._alert_sender.send_alert(
                        user_id=emp_id, risk_score=95.0,
                        factors=["face_verification_failed", f"attempts_{self._face_attempts}"],
                        level="CRITICAL",
                    )
                except Exception:
                    pass

            self._set_status(f"Face verification failed {_MAX_ATTEMPTS} times. Account locked for {_FACE_LOCKOUT_MINUTES} minutes.")
            self.after(3000, self._show_step_1)
        else:
            self._face_status_var.set("Face not recognized")
            self._set_status(f"Face not recognized. ({self._face_attempts}/{_MAX_ATTEMPTS}). Try again.")
            self._face_btn.configure(text="Retry", command=self._show_step_3)

    def _cancel_face(self) -> None:
        self._face_running = False
        self._show_step_1()

    # ------------------------------------------------------------------
    # Finalize login
    # ------------------------------------------------------------------

    def _finalize_login(self, liveness_score: float) -> None:
        emp_id = self._current_employee.get("employee_id", "")
        try:
            # Geo context
            location_mode = "unknown"
            wifi_ssid_hash = ""
            device_fingerprint = ""
            try:
                from C3_activity_monitoring.src.geo_context import get_geo_context
                geo = get_geo_context()
                location_mode = "office" if geo.get("city") else "unknown"
            except Exception:
                pass

            device_fingerprint = self._get_device_fp()

            # Create session document
            session_doc = {
                "session_id": self._session_id,
                "employee_id": emp_id,
                "login_at": datetime.now(timezone.utc).isoformat(),
                "location_mode": location_mode,
                "wifi_ssid_hash": wifi_ssid_hash,
                "device_fingerprint": device_fingerprint,
                "face_liveness_score": liveness_score,
                "mfa_verified": True,
                "status": "active",
            }

            col = self._db.get_collection("sessions")
            if col:
                col.insert_one(session_doc)

            # Log auth event
            self._log_auth_event("login_success", emp_id, success=True, extra={"liveness_score": liveness_score})

            # Clear face_attempts and locked_until
            emp_col = self._db.get_collection("employees")
            if emp_col:
                emp_col.update_one(
                    {"employee_id": emp_id},
                    {"$unset": {"locked_until": ""}, "$set": {"last_login": datetime.utcnow().isoformat()}},
                )

            # Call success callback
            self.after(0, lambda: self._on_success(self._current_employee, self._session_id))

        except Exception as exc:
            logger.error("Session creation error: %s", exc)
            self.after(0, lambda: self._on_success(self._current_employee, self._session_id))

    def _log_auth_event(self, event_type: str, emp_id: str, success: bool, extra: dict = None) -> None:
        try:
            col = self._db.get_collection("auth_events")
            if col:
                col.insert_one({
                    "event_type":  event_type,
                    "employee_id": emp_id,
                    "session_id":  self._session_id,
                    "timestamp":   datetime.utcnow().isoformat(),
                    "success":     success,
                    **(extra or {}),
                })
        except Exception as exc:
            logger.debug("Auth event log error: %s", exc)

    def _get_device_fp(self) -> str:
        import hashlib, platform, uuid as _uuid
        parts = [platform.node(), platform.machine(), str(_uuid.getnode())]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, color: str = C_RED) -> None:
        self._status_var.set(msg)
        self._status_lbl.configure(text_color=color)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Standalone runner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def launch_login(
    db: MongoDBClient,
    on_success: Callable[[dict, str], None],
    alert_sender: Optional[AlertSender] = None,
) -> LoginWindow:
    win = LoginWindow(db=db, on_success=on_success, alert_sender=alert_sender)
    return win


if __name__ == "__main__":
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()

    def _on_success(emp, session_id):
        print(f"Login SUCCESS: {emp['employee_id']} session={session_id}")

    win = launch_login(db, _on_success)
    win.mainloop()
