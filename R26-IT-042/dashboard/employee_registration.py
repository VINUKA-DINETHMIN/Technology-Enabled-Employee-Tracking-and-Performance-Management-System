"""
R26-IT-042 — Employee Activity Monitoring System
dashboard/employee_registration.py

Two-part employee registration:
  Part 1 — Admin registration form (name, ID, email, dept, role, etc.)
  Part 2 — Face capture window (OpenCV + MediaPipe) with OpenCV DNN matching

On confirm:
  1. bcrypt password hash
  2. pyotp MFA secret → qrcode → smtplib email
  3. Save full employee document to MongoDB "employees" collection
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import smtplib
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import customtkinter as ctk
from tkinter import messagebox
import tkinter as tk

from common.database import MongoDBClient
from config.settings import settings
from common.email_utils import send_mfa_setup_email

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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

DEPARTMENTS = ["IT", "HR", "Finance", "Operations", "Management"]
ROLES       = ["Employee", "Senior Employee", "Team Lead"]
LOCATIONS   = ["Office", "Home", "Hybrid"]


def _validate_email(email: str) -> bool:
    """
    Stricter email validation. 
    Prevents common typos like trailing slashes or multiple dots.
    """
    # Strict regex for common email formats
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip().lower()))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Face Capture Window (Part 2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FaceCaptureWindow(ctk.CTkToplevel):
    """
    OpenCV + MediaPipe face capture window.
    Captures 5 photos automatically when a stable face is detected.
    """

    CAPTURE_COUNT = 5
    STABILITY_FRAMES = 8   # consecutive frames with face detected before auto-capture

    def __init__(self, parent, form_data: dict, db: MongoDBClient, admin_id: str = "ADMIN") -> None:
        super().__init__(parent)
        self._form = form_data
        self._db = db
        self._admin_id = admin_id
        self._captured_frames: list = []
        self._stable_count = 0
        self._running = False
        self._cap = None
        self._face_detection = None

        self.title("Face Capture — Step 2 of 2")
        self.geometry("700x620")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self._start_camera()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Face Enrollment",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=C_TEXT).pack(pady=(16, 2))
        ctk.CTkLabel(self, text="Look directly at the camera. Hold still when prompted.",
                     font=ctk.CTkFont(size=11), text_color=C_MUTED).pack()

        # Live frame canvas
        self._canvas = tk.Canvas(self, width=480, height=360, bg="#0b0e17", highlightthickness=0)
        self._canvas.pack(pady=12)

        self._status_lbl = ctk.CTkLabel(self, text="Initialising camera...",
                                         font=ctk.CTkFont(size=13), text_color=C_MUTED)
        self._status_lbl.pack()

        # Progress dots (5 captures)
        dot_row = ctk.CTkFrame(self, fg_color="transparent")
        dot_row.pack(pady=8)
        self._dots: list = []
        for _ in range(self.CAPTURE_COUNT):
            dot = ctk.CTkLabel(dot_row, text="○", font=ctk.CTkFont(size=20), text_color=C_BORDER)
            dot.pack(side="left", padx=6)
            self._dots.append(dot)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=12)
        ctk.CTkButton(btn_row, text="Retake", fg_color=C_BORDER, hover_color="#374151",
                      width=110, command=self._retake).pack(side="left", padx=8)
        self._confirm_btn = ctk.CTkButton(btn_row, text="Confirm and Register",
                                           fg_color=C_TEAL, hover_color=C_TEAL_D, width=160,
                                           state="disabled", command=self._on_confirm)
        self._confirm_btn.pack(side="left", padx=8)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _start_camera(self) -> None:
        try:
            import cv2
            self._cap = cv2.VideoCapture(0)
            if not self._cap.isOpened():
                raise RuntimeError("No webcam found.")

            # Load MediaPipe face detection
            try:
                import mediapipe as mp
                if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
                    self._face_detection = mp.solutions.face_detection.FaceDetection(
                        model_selection=0, min_detection_confidence=0.7
                    )
                else:
                    self._face_detection = None
            except Exception:
                self._face_detection = None

            self._running = True
            self._set_status("Position your face in the frame", C_MUTED)
            threading.Thread(target=self._camera_loop, daemon=True).start()
        except Exception as exc:
            self._set_status(f"Camera error: {exc}", C_RED)

    def _camera_loop(self) -> None:
        import cv2
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_detected = self._detect_face(frame_rgb, frame)

            if face_detected:
                self._stable_count += 1
            else:
                self._stable_count = 0

            # Auto-capture
            if (
                self._stable_count >= self.STABILITY_FRAMES
                and len(self._captured_frames) < self.CAPTURE_COUNT
            ):
                self._capture_frame(frame_rgb.copy())
                self._stable_count = 0

            # Render to canvas
            self._render_frame(frame_rgb, face_detected)
            time.sleep(1 / 30)

    def _detect_face(self, frame_rgb, frame_bgr) -> bool:
        import cv2
        try:
            if self._face_detection is not None:
                import mediapipe as mp
                results = self._face_detection.process(frame_rgb)
                if results.detections:
                    for detection in results.detections:
                        bboxC = detection.location_data.relative_bounding_box
                        h, w, _ = frame_bgr.shape
                        x = int(bboxC.xmin * w)
                        y = int(bboxC.ymin * h)
                        bw = int(bboxC.width * w)
                        bh = int(bboxC.height * h)
                        # Draw oval guide
                        cv2.ellipse(frame_bgr, (w // 2, h // 2), (120, 150), 0, 0, 360, (20, 184, 166), 3)
                        cv2.rectangle(frame_bgr, (x, y), (x + bw, y + bh), (20, 184, 166), 2)
                    return True
                return False
            else:
                # Fallback: Haar cascade
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                faces = cascade.detectMultiScale(gray, 1.1, 5)
                for (x, y, w_, h_) in faces:
                    cv2.rectangle(frame_bgr, (x, y), (x + w_, y + h_), (20, 184, 166), 2)
                return len(faces) > 0
        except Exception:
            return False

    def _render_frame(self, frame_rgb, face_ok: bool) -> None:
        try:
            from PIL import Image, ImageTk
            import numpy as np
            img = Image.fromarray(frame_rgb).resize((480, 360))
            photo = ImageTk.PhotoImage(img)
            self._canvas.after(0, lambda p=photo: self._draw_on_canvas(p))
        except Exception:
            pass

    def _draw_on_canvas(self, photo) -> None:
        try:
            self._canvas.delete("all")
            self._canvas._photo = photo  # prevent GC
            self._canvas.create_image(0, 0, anchor="nw", image=photo)
        except Exception:
            pass

    def _capture_frame(self, frame_rgb) -> None:
        self._captured_frames.append(frame_rgb)
        idx = len(self._captured_frames) - 1
        if idx < len(self._dots):
            self.after(0, lambda i=idx: self._dots[i].configure(text="●", text_color=C_TEAL))

        if len(self._captured_frames) >= self.CAPTURE_COUNT:
            self._running = False
            self.after(0, self._on_captures_complete)

    def _on_captures_complete(self) -> None:
        self._set_status(f"Captured! {self.CAPTURE_COUNT} photos saved.", C_GREEN)
        self._confirm_btn.configure(state="normal")

    def _retake(self) -> None:
        self._captured_frames.clear()
        self._stable_count = 0
        for dot in self._dots:
            dot.configure(text="○", text_color=C_BORDER)
        self._confirm_btn.configure(state="disabled")
        self._set_status("Position your face in the frame", C_MUTED)
        if not self._running:
            self._running = True
            threading.Thread(target=self._camera_loop, daemon=True).start()

    def _set_status(self, msg: str, color: str = C_MUTED) -> None:
        self.after(0, lambda: self._status_lbl.configure(text=msg, text_color=color))

    # ------------------------------------------------------------------
    # Confirm & Register
    # ------------------------------------------------------------------

    def _on_confirm(self) -> None:
        self._confirm_btn.configure(state="disabled", text="Registering...")
        threading.Thread(target=self._do_register, daemon=True).start()

    def _do_register(self) -> None:
        try:
            import cv2
            import numpy as np
            import base64
            
            face_b64s = []
            embeddings = []
            
            # Using 200x200 for storage
            FACE_SIZE = (200, 200)

            # Initialize face detection for cropping
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

            # Initialize FaceNet verifier for embedding extraction
            try:
                from C3_activity_monitoring.src.face_verifier import FaceVerifier
                verifier = FaceVerifier(model_path="models/face_recognition_sface.onnx")
            except (ImportError, FileNotFoundError, RuntimeError) as e:
                # Fallback if FaceNet not available
                print(f"⚠ FaceNet not available: {e}. Using histogram embeddings only.")
                verifier = None

            for frame in self._captured_frames:
                # Extract image for the FACE region
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                faces = cascade.detectMultiScale(gray, 1.1, 5)
                
                if len(faces) > 0:
                    # Take the largest face
                    (x, y, w, h) = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
                    face_roi = gray[y:y+h, x:x+w]
                    face_roi_color = cv2.cvtColor(face_roi, cv2.COLOR_GRAY2BGR)
                    
                    # Normalize lighting/contrast and resize
                    face_roi = cv2.equalizeHist(face_roi)
                    face_roi_resized = cv2.resize(face_roi, FACE_SIZE)
                    
                    # Convert to base64 for storage
                    _, buf = cv2.imencode(".jpg", face_roi_resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    face_b64s.append(base64.b64encode(buf).decode("utf-8"))
                    
                    # Extract FaceNet embedding
                    if verifier is not None:
                        try:
                            emb = verifier.get_embedding(face_roi_color)
                            if emb is not None:
                                embeddings.append(emb)
                        except Exception as e:
                            print(f"⚠ Embedding extraction failed: {e}")
            
            # Average the embeddings if multiple captures available
            if embeddings:
                avg_emb = np.mean(np.array(embeddings), axis=0).tolist()
            else:
                # Fallback if no embeddings computed
                avg_emb = []

            # 3. Hash password
            import bcrypt
            pw = self._form.get("password", "password123").encode()
            pw_hash = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()

            # 3. MFA secret
            import pyotp
            mfa_secret = pyotp.random_base32()

            # 4. Build document
            doc = {
                "employee_id":    self._form["employee_id"],
                "full_name":      self._form["full_name"],
                "email":          self._form["email"],
                "department":     self._form["department"],
                "role":           self._form["role"],
                "shift_start":    self._form["shift_start"],
                "shift_end":      self._form["shift_end"],
                "work_location":  self._form["work_location"],
                "password_hash":  pw_hash,
                "face_images":    face_b64s,
                "face_embedding": avg_emb,
                "registered_at":  datetime.now(timezone.utc).isoformat(),
                "registered_by":  self._admin_id,
                "status":         "active",
                "mfa_secret":     mfa_secret,
            }

            # 5. Save to MongoDB
            col = self._db.get_collection("employees")
            if col is None:
                raise RuntimeError("Database collection unavailable.")
            col.insert_one(doc)

            # 6. Send MFA email
            sent_ok = send_mfa_setup_email(self._form["email"], self._form["full_name"], mfa_secret)

            self.after(0, lambda: self._on_success(sent_ok))
        except Exception as exc:
            self.after(0, lambda e=exc: self._on_error(str(e)))

    def _compute_embedding(self, frame_rgb) -> Optional[list]:
        """Deprecated: Use face-aware cropping instead."""
        return None


    def _on_success(self, email_sent: bool = True) -> None:
        self._running = False
        msg = f"Employee '{self._form['full_name']}' registered successfully.\n\n"
        if email_sent:
            msg += "MFA setup email has been sent."
        else:
            msg += "⚠️ WARNING: MFA setup email could NOT be sent. Please check SMTP settings in .env."
            
        messagebox.showinfo("Registration Complete", msg)
        self.destroy()

    def _on_error(self, msg: str) -> None:
        messagebox.showerror("Registration Failed", msg)
        self._confirm_btn.configure(state="normal", text="Confirm and Register")

    def _on_close(self) -> None:
        self._running = False
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
        self.destroy()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Admin Registration Form (Part 1)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EmployeeRegistration(ctk.CTkToplevel):
    """Admin registration form — Part 1."""

    def __init__(self, parent, db: Optional[MongoDBClient] = None, admin_id: str = "ADMIN") -> None:
        super().__init__(parent)
        self._db = db or self._init_db()
        self._admin_id = admin_id
        self._errors: dict = {}

        self.title("Register New Employee — Step 1 of 2")
        self.geometry("520x720")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self.attributes("-topmost", True)

        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="#0f1420", corner_radius=0, height=56)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="New Employee Registration",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=C_TEXT).pack(side="left", padx=20, pady=14)

        form = ctk.CTkScrollableFrame(self, fg_color=C_BG)
        form.pack(fill="both", expand=True, padx=20)

        def field(parent, label: str, var: ctk.StringVar, placeholder: str = "",
                  show: str = "", row_key: str = "") -> None:
            ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=11), text_color=C_MUTED, anchor="w").pack(fill="x", pady=(10, 2))
            entry = ctk.CTkEntry(parent, textvariable=var, placeholder_text=placeholder,
                                  show=show, height=40, fg_color="#0f1117", border_color=C_BORDER)
            entry.pack(fill="x")
            err = ctk.CTkLabel(parent, text="", font=ctk.CTkFont(size=10), text_color=C_RED, anchor="w")
            err.pack(fill="x")
            if row_key:
                self._errors[row_key] = err

        def dropdown(parent, label: str, var: ctk.StringVar, values: list) -> None:
            ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=11), text_color=C_MUTED, anchor="w").pack(fill="x", pady=(10, 2))
            ctk.CTkOptionMenu(parent, variable=var, values=values, fg_color=C_BORDER, button_color=C_BORDER).pack(fill="x")

        # Form variables
        self._full_name   = ctk.StringVar()
        self._emp_id      = ctk.StringVar()
        self._email       = ctk.StringVar()
        self._department  = ctk.StringVar(value=DEPARTMENTS[0])
        self._role        = ctk.StringVar(value=ROLES[0])
        self._shift_start = ctk.StringVar(value="09:00")
        self._shift_end   = ctk.StringVar(value="18:00")
        self._work_loc    = ctk.StringVar(value=LOCATIONS[0])
        self._password    = ctk.StringVar()
        self._confirm_pw  = ctk.StringVar()

        field(form, "Full Name *",       self._full_name,   "Jane Doe",        row_key="full_name")
        field(form, "Employee ID *",     self._emp_id,      "EMP-001",         row_key="emp_id")
        field(form, "Email *",           self._email,       "jane@company.com",row_key="email")
        dropdown(form, "Department *",   self._department,  DEPARTMENTS)
        dropdown(form, "Role *",         self._role,        ROLES)
        field(form, "Shift Start (HH:MM)", self._shift_start, "09:00")
        field(form, "Shift End (HH:MM)",   self._shift_end,   "18:00")
        dropdown(form, "Work Location *",  self._work_loc,    LOCATIONS)
        field(form, "Password * (min 8 chars)", self._password, show="•", row_key="password")
        field(form, "Confirm Password *",       self._confirm_pw, show="•", row_key="confirm_pw")

        ctk.CTkButton(form, text="Next: Capture Face",
                       fg_color=C_TEAL, hover_color=C_TEAL_D, height=44,
                       font=ctk.CTkFont(size=14, weight="bold"),
                       command=self._on_next).pack(fill="x", pady=(16, 8))

    def _on_next(self) -> None:
        """Validate form and open face capture."""
        valid = True

        def set_err(key, msg):
            nonlocal valid
            valid = False
            if key in self._errors:
                self._errors[key].configure(text=msg)

        def clear_err(key):
            if key in self._errors:
                self._errors[key].configure(text="")

        clear_err("full_name")
        clear_err("emp_id")
        clear_err("email")
        clear_err("password")
        clear_err("confirm_pw")

        if not self._full_name.get().strip():
            set_err("full_name", "Full name is required.")
        if not self._emp_id.get().strip():
            set_err("emp_id", "Employee ID is required.")
        else:
            # Check uniqueness
            if self._db and self._db.is_connected:
                col = self._db.get_collection("employees")
                if col is not None and col.find_one({"employee_id": self._emp_id.get().strip()}):
                    set_err("emp_id", "Employee ID already exists.")
        if not _validate_email(self._email.get().strip()):
            set_err("email", "Invalid email address.")
        if len(self._password.get()) < 8:
            set_err("password", "Password must be at least 8 characters.")
        if self._password.get() != self._confirm_pw.get():
            set_err("confirm_pw", "Passwords do not match.")

        if not valid:
            messagebox.showwarning("Incomplete Form", "Please correct the errors in the form before proceeding.")
            return

        form_data = {
            "full_name":    self._full_name.get().strip(),
            "employee_id":  self._emp_id.get().strip(),
            "email":        self._email.get().strip(),
            "department":   self._department.get(),
            "role":         self._role.get(),
            "shift_start":  self._shift_start.get().strip(),
            "shift_end":    self._shift_end.get().strip(),
            "work_location":self._work_loc.get(),
            "password":     self._password.get(),
        }

        try:
            FaceCaptureWindow(self, form_data, self._db, self._admin_id)
            self.withdraw()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("FaceCaptureWindow error: %s", exc, exc_info=True)
            messagebox.showerror("Error", f"Failed to open face capture window:\n\n{exc}")

    def _init_db(self) -> MongoDBClient:
        db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
        db.connect()
        return db


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Standalone entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    root = ctk.CTk()
    root.withdraw()
    reg = EmployeeRegistration(root)
    reg.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
