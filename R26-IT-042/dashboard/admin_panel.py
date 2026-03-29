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
        self.geometry("780x700")
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

        # Currently Active Task & Top App
        if risk_doc:
            status_frame = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
            status_frame.pack(fill="x", pady=(0, 12))
            
            top_app = risk_doc.get("top_app") or "None"
            is_unproductive = top_app.lower() in ["youtube", "netflix", "facebook", "instagram", "tiktok", "gaming", "steam"]
            app_color = C_RED if is_unproductive else C_GREEN
            
            ctk.CTkLabel(status_frame, text="Current App Focus:", font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(anchor="w", padx=16, pady=(12, 0))
            ctk.CTkLabel(status_frame, text=top_app.upper(), font=ctk.CTkFont(size=14, weight="bold"), text_color=app_color).pack(anchor="w", padx=16)

            active_task = risk_doc.get("active_task_title", "No Active Task")
            ctk.CTkLabel(status_frame, text="Active Working Task:", font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(anchor="w", padx=16, pady=(8, 0))
            ctk.CTkLabel(status_frame, text=active_task, font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(0, 12))
            
            prod = risk_doc.get("productivity_score", 0.0)
            ctk.CTkLabel(status_frame, text="Current Productivity:", font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(anchor="w", padx=16)
            ctk.CTkLabel(status_frame, text=f"{prod:.0f}%", font=ctk.CTkFont(size=18, weight="bold"), text_color=_risk_color(100-prod)).pack(anchor="w", padx=16, pady=(0, 12))

        # Contributing factors
        if risk_doc:
            factors = risk_doc.get("contributing_factors", [])
            if factors:
                ff = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
                ff.pack(fill="x", pady=(0, 12))
                ctk.CTkLabel(ff, text="Anomaly Factors", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))
                for f in factors:
                    f_name = f.replace('_', ' ').title()
                    f_color = C_RED if "unproductive" in f or "off_task" in f else C_AMBER
                    ctk.CTkLabel(ff, text=f"  • {f_name}", font=ctk.CTkFont(size=12, weight="bold" if f_color==C_RED else "normal"), text_color=f_color).pack(anchor="w", padx=16)
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
            status_color = {"pending": C_MUTED, "in_progress": C_AMBER, "completed": C_GREEN, "paused": C_RED}.get(t.get("status", ""), C_MUTED)
            ctk.CTkLabel(row, text=t.get("title", "?"), text_color=C_TEXT, font=ctk.CTkFont(size=11)).pack(side="left", padx=8, pady=6)
            ctk.CTkLabel(row, text=t.get("status", "").replace("_", " ").title(), text_color=status_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=8)
        ctk.CTkFrame(tf, fg_color="transparent", height=8).pack()

        # Screenshots list
        ssf = ctk.CTkFrame(body, fg_color=C_CARD, corner_radius=12)
        ssf.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(ssf, text="Recent Screenshots", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        screens = self._get_screenshots(emp_id)
        if not screens:
            ctk.CTkLabel(ssf, text="No screenshots captured yet.", font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(anchor="w", padx=16, pady=(0, 12))
        else:
            for s in screens[:5]:
                row = ctk.CTkFrame(ssf, fg_color=C_BORDER, corner_radius=8)
                row.pack(fill="x", padx=16, pady=3)
                reason = s.get("trigger_reason", "manual").title()
                risk = s.get("risk_score_at_capture", 0.0)
                ctk.CTkLabel(row, text=f"📸 {reason}", text_color=C_TEXT, font=ctk.CTkFont(size=11)).pack(side="left", padx=8, pady=6)
                ctk.CTkLabel(row, text=f"Risk: {risk:.0f}", text_color=_risk_color(risk), font=ctk.CTkFont(size=11)).pack(side="left", padx=12)
                
                # Buttons to view
                b64 = s.get("image_base64")
                path = s.get("file_path", "")
                
                # Cloud Viewer (Primary)
                if b64:
                    ctk.CTkButton(row, text="View Cloud", width=70, height=24, fg_color=C_TEAL, hover_color=C_TEAL_D, 
                                  font=ctk.CTkFont(size=10), command=lambda b=b64: ScreenshotViewer(self, b)).pack(side="right", padx=4)
                
                # Local Viewer (Secondary - Decrypts high-res)
                if path and os.path.exists(path):
                    ctk.CTkButton(row, text="View Local", width=70, height=24, fg_color=C_BLUE, hover_color="#2563eb", 
                                  font=ctk.CTkFont(size=10), command=lambda p=path: ScreenshotViewer(self, p, is_path=True, user_id=emp_id)).pack(side="right", padx=4)
                
                # Folder Opener
                if path:
                    ctk.CTkButton(row, text="📁", width=28, height=24, fg_color=C_SIDEBAR, hover_color=C_BORDER, 
                                  font=ctk.CTkFont(size=10), command=lambda p=path: self._open_file(p)).pack(side="right", padx=2)
                
                ctk.CTkLabel(row, text=_fmt_time(s.get("timestamp", "")), text_color=C_MUTED, font=ctk.CTkFont(size=11)).pack(side="right")
            ctk.CTkFrame(ssf, fg_color="transparent", height=8).pack()

        # Action Buttons
        ctrl_frame = ctk.CTkFrame(body, fg_color="transparent")
        ctrl_frame.pack(fill="x", pady=20)
        
        ctk.CTkButton(ctrl_frame, text="Resend MFA Email", fg_color=C_TEAL, hover_color=C_TEAL_D, height=38, 
                      command=self._resend_mfa).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(ctrl_frame, text="Force Screenshot", fg_color="#7c3aed", hover_color="#6d28d9", height=38, 
                      command=lambda: self._force_screenshot(emp_id)).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(ctrl_frame, text="Live Camera", fg_color=C_RED, hover_color="#b91c1c", height=38, 
                      command=lambda: LiveCamViewer(self, emp_id, self._db)).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(ctrl_frame, text="Live Screen", fg_color="#3b82f6", hover_color="#2563eb", height=38, 
                      command=lambda: LiveScreenViewer(self, emp_id, self._db)).pack(side="left", expand=True, padx=4)

    def _force_screenshot(self, emp_id: str) -> None:
        if not self._db or not self._db.is_connected: return
        import uuid
        try:
            col = self._db.get_collection("commands")
            if col is not None:
                now = datetime.utcnow()
                expires = (now + timedelta(minutes=5)).isoformat()
                col.insert_one({
                    "command_id": str(uuid.uuid4()),
                    "target_user_id": emp_id,
                    "command_type": "force_screenshot",
                    "status": "pending",
                    "timestamp": now.isoformat(),
                    "expires_at": expires
                })
        except Exception: pass

    def _resend_mfa(self) -> None:
        from common.email_utils import send_mfa_setup_email
        email = self._emp.get("email")
        name = self._emp.get("full_name")
        mfa_secret = self._emp.get("mfa_secret")
        if not email or not mfa_secret:
            messagebox.showerror("Error", "Missing email or MFA secret.")
            return
        if send_mfa_setup_email(email, name, mfa_secret):
            messagebox.showinfo("Success", f"MFA email sent to {email}.")
        else:
            messagebox.showerror("Failed", "Check SMTP settings in .env.")

    def _latest_activity(self, emp_id: str) -> Optional[dict]:
        try:
            col = self._db.get_collection("activity_logs")
            if col is not None:
                return col.find_one({"user_id": emp_id}, sort=[("timestamp", -1)])
        except Exception: pass
        return None

    def _get_alerts(self, emp_id: str) -> list:
        try:
            col = self._db.get_collection("alerts")
            if col is not None:
                return list(col.find({"user_id": emp_id}, {"_id": 0}).sort("timestamp", -1).limit(10))
        except Exception: pass
        return []

    def _get_tasks(self, emp_id: str) -> list:
        try:
            col = self._db.get_collection("tasks")
            if col is not None:
                return list(col.find({"employee_id": emp_id}, {"_id": 0}).sort("assigned_at", -1).limit(10))
        except Exception: pass
        return []

    def _get_screenshots(self, emp_id: str) -> list:
        try:
            col = self._db.get_collection("screenshots")
            if col is not None:
                return list(col.find({"user_id": emp_id}, {"_id": 0}).sort("timestamp", -1).limit(10))
        except Exception: pass
        return []

    def _open_file(self, path: str) -> None:
        try:
            if not path: return
            dir_path = os.path.dirname(path)
            if sys.platform == "win32": os.startfile(dir_path)
            else:
                import subprocess
                subprocess.call(["open", dir_path])
        except Exception as exc: messagebox.showerror("Error", str(exc))

    def _force_screenshot(self, emp_id: str) -> None:
        """
        Send a remote command to the employee's app to trigger a screenshot.
        """
        try:
            col = self._db.get_collection("commands")
            if col is not None:
                cmd = {
                    "command_id": str(uuid.uuid4()),
                    "target_user_id": emp_id,
                    "command_type": "force_screenshot",
                    "status": "pending",
                    "created_at": datetime.utcnow().isoformat(),
                    "expires_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat()
                }
                col.insert_one(cmd)
                messagebox.showinfo("Command Sent", f"Force Screenshot command queued for {emp_id}.\nIt will be captured on their next heartbeat.")
            else:
                messagebox.showerror("Error", "Command collection unavailable.")
        except Exception as exc: 
            messagebox.showerror("Error", f"Failed to send command: {exc}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Screenshot Viewer Window
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ScreenshotViewer(ctk.CTkToplevel):
    def __init__(self, parent, data: str, title: str = "Screenshot Viewer", is_path: bool = False, user_id: str = ""):
        super().__init__(parent)
        self.title(title)
        self.geometry("900x650")
        self.attributes("-topmost", True)
        self.configure(fg_color=C_BG)

        import base64
        import io
        from PIL import Image
        from common.encryption import AESEncryptor

        try:
            if is_path:
                p = Path(data)
                if not p.exists():
                    raise FileNotFoundError(f"File not found: {p}")
                
                raw_bytes = p.read_bytes()
                
                # PNG Signature check for legacy/unencrypted files
                if raw_bytes.startswith(b"\x89PNG") or raw_bytes.startswith(b"\xff\xd8"):
                    img_bytes = raw_bytes
                    source_text = "Viewing Local File (Unencrypted)"
                elif p.suffix == ".enc":
                    # Decrypt high-quality local image
                    enc = AESEncryptor()
                    # Use user_id as associated data if available (matches ScreenshotTrigger logic)
                    assoc = user_id.encode() if user_id else None
                    img_bytes = enc.decrypt_bytes(raw_bytes, associated_data=assoc)
                    source_text = "Viewing Local File (Secure Decrypted)"
                else:
                    img_bytes = raw_bytes
                    source_text = "Viewing Local File"
            else:
                img_bytes = base64.b64decode(data)
                source_text = "Viewing Cloud Preview (Optimized)"

            img = Image.open(io.BytesIO(img_bytes))
            
            # Resize
            display_w, display_h = 860, 540
            img.thumbnail((display_w, display_h))
            
            self._photo = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._lbl = ctk.CTkLabel(self, image=self._photo, text="")
            self._lbl.pack(expand=True, padx=20, pady=20)
            
            ctk.CTkLabel(self, text=source_text, font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=(0, 10))
            
        except Exception as exc:
            ctk.CTkLabel(self, text=f"Failed to load image: {exc}", text_color=C_RED, wraplength=400).pack(expand=True)

class LiveCamViewer(ctk.CTkToplevel):
    """
    Real-time camera feed viewer that polls MongoDB for latest snapshots.
    """
    def __init__(self, parent, user_id: str, db: Optional[MongoDBClient]):
        super().__init__(parent)
        self.user_id = user_id
        self._db = db
        self.title(f"Live Cam — {user_id}")
        self.geometry("680x560")
        self.attributes("-topmost", True)
        self.configure(fg_color=C_BG)

        self._lbl = ctk.CTkLabel(self, text="Initializing Stream...", font=ctk.CTkFont(size=14), text_color=C_MUTED)
        self._lbl.pack(expand=True, fill="both", padx=20, pady=20)

        self._status_lbl = ctk.CTkLabel(self, text="Connecting to remote device...", font=ctk.CTkFont(size=11), text_color=C_AMBER)
        self._status_lbl.pack(pady=(0, 10))

        # Send command to start streaming
        self._send_command("start_live_cam")
        
        self._closed = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_loop()

    def _send_command(self, cmd_type: str):
        if not self._db or not self._db.is_connected: return
        import uuid
        try:
            col = self._db.get_collection("commands")
            if col is not None:
                now = datetime.utcnow()
                expires = (now + timedelta(minutes=5)).isoformat()
                col.insert_one({
                    "command_id": str(uuid.uuid4()),
                    "target_user_id": self.user_id,
                    "command_type": cmd_type,
                    "status": "pending",
                    "timestamp": now.isoformat(),
                    "expires_at": expires
                })
        except Exception: pass

    def _update_loop(self):
        if self._closed or not self.winfo_exists(): return
        if not self._db or not self._db.is_connected: 
            self.after(1000, self._update_loop)
            return
        
        try:
            import base64, io
            from PIL import Image
            
            col = self._db.get_collection("camera_streams")
            if col is not None:
                doc = col.find_one({"user_id": self.user_id})
                if doc:
                    status = doc.get("status")
                    if status == "streaming":
                        b64 = doc.get("image_base64")
                        if b64:
                            img_bytes = base64.b64decode(b64)
                            img = Image.open(io.BytesIO(img_bytes))
                            # Display
                            photo = ctk.CTkImage(light_image=img, dark_image=img, size=(640, 480))
                            self._lbl.configure(image=photo, text="")
                            self._lbl._image = photo # Keep reference
                            self._status_lbl.configure(text=f"Live • Last Update: {doc.get('timestamp','?')[-8:]}", text_color=C_GREEN)
                    elif status == "off":
                        err = doc.get("error", "Stream stopped by employee system.")
                        self._status_lbl.configure(text=err, text_color=C_RED)
                else:
                    self._status_lbl.configure(text="Waiting for remote device to respond...", text_color=C_AMBER)
        except Exception as e:
            if self.winfo_exists():
                self._status_lbl.configure(text=f"Update failed: {e}", text_color=C_RED)
        
        if self.winfo_exists():
            self.after(1000, self._update_loop)

    def _on_close(self):
        self._closed = True
        self._send_command("stop_live_cam")
        self.destroy()

class LiveScreenViewer(ctk.CTkToplevel):
    """
    Real-time screen feed viewer that polls MongoDB for latest snapshots.
    """
    def __init__(self, parent, user_id: str, db: Optional[MongoDBClient]):
        super().__init__(parent)
        self.user_id = user_id
        self._db = db
        self.title(f"Live Screen — {user_id}")
        self.geometry("820x600")
        self.attributes("-topmost", True)
        self.configure(fg_color=C_BG)

        self._lbl = ctk.CTkLabel(self, text="Initializing Stream...", font=ctk.CTkFont(size=14), text_color=C_MUTED)
        self._lbl.pack(expand=True, fill="both", padx=20, pady=20)

        self._status_lbl = ctk.CTkLabel(self, text="Connecting to remote device...", font=ctk.CTkFont(size=11), text_color=C_AMBER)
        self._status_lbl.pack(pady=(0, 10))

        # Send command to start streaming
        self._send_command("start_live_screen")
        
        self._closed = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_loop()

    def _send_command(self, cmd_type: str):
        if not self._db or not self._db.is_connected: return
        import uuid
        try:
            col = self._db.get_collection("commands")
            if col is not None:
                now = datetime.utcnow()
                expires = (now + timedelta(minutes=5)).isoformat()
                col.insert_one({
                    "command_id": str(uuid.uuid4()),
                    "target_user_id": self.user_id,
                    "command_type": cmd_type,
                    "status": "pending",
                    "timestamp": now.isoformat(),
                    "expires_at": expires
                })
        except Exception: pass

    def _update_loop(self):
        if self._closed or not self.winfo_exists(): return
        if not self._db or not self._db.is_connected: 
            self.after(1000, self._update_loop)
            return
        
        try:
            import base64, io
            from PIL import Image
            
            col = self._db.get_collection("screen_streams")
            if col is not None:
                doc = col.find_one({"user_id": self.user_id})
                if doc:
                    status = doc.get("status")
                    if status == "streaming":
                        b64 = doc.get("image_base64")
                        if b64:
                            img_bytes = base64.b64decode(b64)
                            img = Image.open(io.BytesIO(img_bytes))
                            # Display
                            photo = ctk.CTkImage(light_image=img, dark_image=img, size=(780, 440))
                            self._lbl.configure(image=photo, text="")
                            self._lbl._image = photo # Keep reference
                            self._status_lbl.configure(text=f"Live Screen • Last Update: {doc.get('timestamp','?')[-8:]}", text_color=C_GREEN)
                    elif status == "off":
                        err = doc.get("error", "Stream stopped by employee system.")
                        self._status_lbl.configure(text=err, text_color=C_RED)
                else:
                    self._status_lbl.configure(text="Waiting for remote screen capture...", text_color=C_AMBER)
        except Exception as e:
            if self.winfo_exists():
                self._status_lbl.configure(text=f"Update failed: {e}", text_color=C_RED)
        
        if self.winfo_exists():
            self.after(2000, self._update_loop)

    def _on_close(self):
        self._closed = True
        self._send_command("stop_live_screen")
        self.destroy()

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
            ("live_grid",  "  Live Monitor"),
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
            "live_grid":  self._tab_live_grid(),
            "alerts":     self._build_alerts_tab(),
            "tasks":      self._build_tasks_tab(),
            "attendance": self._build_attendance_tab(),
            "settings":   self._build_settings_tab(),
        }

    def _tab_live_grid(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self._tab_frame, fg_color="transparent")
        
        header = ctk.CTkFrame(frame, fg_color=C_CARD, height=60, corner_radius=12)
        header.pack(fill="x", pady=(0, 20))
        header.pack_propagate(False)
        
        ctk.CTkLabel(header, text="Live Screen Monitor Grid", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=20)
        
        self._grid_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._grid_scroll.pack(fill="both", expand=True)
        
        self._grid_items = {} # {user_id: {frame, label, status_label}}
        
        return frame

    def _refresh_live_grid(self) -> None:
        threading.Thread(target=self._fetch_live_grid, daemon=True).start()

    def _fetch_live_grid(self) -> None:
        if not self._db or not self._db.is_connected: return
        try:
            import base64, io
            from PIL import Image
            col = self._db.get_collection("screen_streams")
            if col is None: return
            streams = list(col.find({"status": "streaming"}))
            
            # Process images in background thread
            processed = []
            for s in streams:
                uid = s["user_id"]
                img = None
                b64 = s.get("image_base64")
                if b64:
                    try:
                        img_bytes = base64.b64decode(b64)
                        img = Image.open(io.BytesIO(img_bytes))
                    except Exception: pass
                processed.append({"user_id": uid, "image": img, "timestamp": s.get("timestamp", "?")})
            
            self.after(0, lambda: self._update_live_grid_ui(processed))
        except Exception: pass

    def _update_live_grid_ui(self, processed: list) -> None:
        current_ids = set(self._grid_items.keys())
        active_ids = {p["user_id"] for p in processed}
        
        # Remove dead
        for uid in current_ids - active_ids:
            if uid in self._grid_items:
                self._grid_items[uid]["frame"].destroy()
                del self._grid_items[uid]
                
        # Update/Add
        for i, p in enumerate(processed):
            uid = p["user_id"]
            if uid not in self._grid_items:
                tile = ctk.CTkFrame(self._grid_scroll, fg_color=C_CARD, corner_radius=12, width=380, height=240)
                tile.grid(row=len(self._grid_items)//3, column=len(self._grid_items)%3, padx=10, pady=10)
                tile.grid_propagate(False)
                n_lbl = ctk.CTkLabel(tile, text=f"Employee: {uid}", font=ctk.CTkFont(size=12, weight="bold"))
                n_lbl.pack(pady=(10, 5))
                s_lbl = ctk.CTkLabel(tile, text="Loading...", font=ctk.CTkFont(size=10), text_color=C_MUTED)
                s_lbl.pack(expand=True, fill="both", padx=10)
                st_lbl = ctk.CTkLabel(tile, text="Live • Capturing", font=ctk.CTkFont(size=9), text_color=C_GREEN)
                st_lbl.pack(pady=(0, 10))
                self._grid_items[uid] = {"frame": tile, "label": s_lbl, "status": st_lbl}

            if p["image"]:
                img = p["image"]
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(340, 180))
                self._grid_items[uid]["label"].configure(image=photo, text="")
                self._grid_items[uid]["label"]._image = photo
                self._grid_items[uid]["status"].configure(text=f"Live • Last sync: {p['timestamp'][-8:]}")

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
            online_cnt = sessions_col.count_documents({"status": "active"}) if sessions_col is not None else 0
            self.after(0, lambda v=online_cnt: self._card_online.set_value(str(v)))

            # Alerts today
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            alerts_today = alerts_col.count_documents({"timestamp": {"$gte": today_start.isoformat()}}) if alerts_col is not None else 0
            self.after(0, lambda v=alerts_today: self._card_alerts.set_value(str(v)))

            # High risk
            high_risk = activity_col.count_documents({"composite_risk_score": {"$gte": 75}}) if activity_col is not None else 0
            self.after(0, lambda v=high_risk: self._card_highrisk.set_value(str(v)))

            # Avg productivity (last hour)
            pipeline = [{"$group": {"_id": None, "avg": {"$avg": "$productivity_score"}}}]
            avg_result = list(activity_col.aggregate(pipeline)) if activity_col is not None else []
            avg_prod = avg_result[0]["avg"] if avg_result else 0.0
            self._card_avg_prod.set_value(f"{avg_prod:.0f}%")

            # Employee rows
            # Employee rows (exclude heavy fields but keep enough for details)
            employees = list(emps_col.find({}, {"_id": 0, "password_hash": 0, "face_images": 0, "face_embedding": 0}).limit(50)) if emps_col is not None else []
            
            # Pre-fetch all active sessions for fast lookup
            active_sessions = {}
            if sessions_col is not None:
                # Get all active sessions at once to avoid separate queries per row
                for sess in sessions_col.find({"status": "active"}):
                    eid = sess.get("employee_id")
                    if eid:
                        active_sessions[eid] = sess

            self._update_employee_list(employees, activity_col, active_sessions)

        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Dashboard refresh error: %s", exc)

    def _update_employee_list(self, employees: list, activity_col, active_sessions: dict) -> None:
        if not hasattr(self, "_emp_rows"):
            self._emp_rows = {} # {emp_id: {"frame": frame, "labels": {name: label}}}

        # Sync IDs
        new_ids = {e.get("employee_id") for e in employees if e.get("employee_id")}
        old_ids = set(self._emp_rows.keys())

        # 1. Remove rows
        for eid in (old_ids - new_ids):
            try:
                self._emp_rows[eid]["frame"].pack_forget()
                self._emp_rows[eid]["frame"].destroy()
            except Exception: pass
            del self._emp_rows[eid]

        # 2. Update or Create
        for emp in employees:
            eid = emp.get("employee_id")
            if not eid: continue
            
            act = None
            try:
                if activity_col:
                    act = activity_col.find_one({"user_id": eid}, sort=[("timestamp", -1)])
            except Exception: pass

            risk = act.get("composite_risk_score", 0.0) if act else 0.0
            risk_color = _risk_color(risk)
            status = "Break" if (act and act.get("in_break")) else ("Idle" if risk == 0 else "Active")
            
            # Use activity log location or fallback to session metadata (city)
            sess = active_sessions.get(eid)
            is_online = (sess is not None)
            
            loc = "—"
            if act and act.get("location_mode"):
                loc = act.get("location_mode").title()
            elif sess:
                # If no activity log yet, pull from session
                city = sess.get("city")
                loc = city if (city and city != "Unknown") else (sess.get("location_mode") or "—").title()
            
            last_seen = _fmt_time(act.get("timestamp", "")) if act else "—"
            name = emp.get("full_name", eid)

            is_online = False
            try:
                if sessions_col:
                    sess = sessions_col.find_one({"employee_id": eid, "status": "active"})
                    if sess: is_online = True
            except Exception: pass

            status_text = status
            status_color = C_TEXT
            if is_online:
                status_text = f"⬤ {status}"
                status_color = C_GREEN
            elif status == "Break":
                status_text = f"○ {status}"
                status_color = C_AMBER
            else:
                status_text = f"✖ Offline"
                status_color = C_RED

            if eid in self._emp_rows:
                # Update
                labels = self._emp_rows[eid]["labels"]
                labels["name"].configure(text=name)
                labels["risk"].configure(text=f"{risk:.0f}", text_color=risk_color)
                labels["loc"].configure(text=loc)
                labels["status"].configure(text=status_text, text_color=status_color)
                labels["seen"].configure(text=last_seen)
            else:
                # Create
                row = ctk.CTkFrame(self._emp_list_frame, fg_color=C_CARD, corner_radius=10, height=44)
                row.pack(fill="x", pady=3)
                row.pack_propagate(False)

                l_name = ctk.CTkLabel(row, text=name, text_color=C_TEXT, font=ctk.CTkFont(size=12, weight="bold"), width=180, anchor="w")
                l_name.pack(side="left", padx=8)
                l_id = ctk.CTkLabel(row, text=eid, text_color=C_MUTED, font=ctk.CTkFont(size=11), width=90, anchor="w")
                l_id.pack(side="left")
                l_risk = ctk.CTkLabel(row, text=f"{risk:.0f}", text_color=risk_color, font=ctk.CTkFont(size=12, weight="bold"), width=80, anchor="w")
                l_risk.pack(side="left")
                l_loc = ctk.CTkLabel(row, text=loc, text_color=C_MUTED, font=ctk.CTkFont(size=11), width=90, anchor="w")
                l_loc.pack(side="left")
                l_status = ctk.CTkLabel(row, text=status_text, text_color=status_color, font=ctk.CTkFont(size=11), width=90, anchor="w")
                l_status.pack(side="left")
                l_seen = ctk.CTkLabel(row, text=last_seen, text_color=C_MUTED, font=ctk.CTkFont(size=11), width=90, anchor="w")
                l_seen.pack(side="left")

                ctk.CTkButton(
                    row, text="Details", width=72, height=28, fg_color=C_BORDER, hover_color=C_BLUE,
                    font=ctk.CTkFont(size=11), command=lambda e=emp: EmployeeDetailWindow(self, e, self._db)
                ).pack(side="right", padx=8)

                self._emp_rows[eid] = {
                    "frame": row,
                    "labels": {"name": l_name, "id": l_id, "risk": l_risk, "loc": l_loc, "status": l_status, "seen": l_seen}
                }

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
            if col is None:
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
            if col is not None:
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
            if col is not None:
                col.insert_one(task_doc)
                messagebox.showinfo("Success", f"Task '{title}' assigned to {emp_id}.")
                self._task_title_var.set("")
                self._task_desc_box.delete("1.0", "end")
                self._refresh_task_list()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _fetch_tasks(self) -> None:
        if not self._db or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("tasks")
            if col is None: return
            tasks = list(col.find({}, {"_id": 0}).sort("assigned_at", -1).limit(40))
            self.after(0, lambda: self._update_task_ui(tasks))
        except Exception as exc:
            self.after(0, lambda: self._update_task_ui([], error=str(exc)))

    def _update_task_ui(self, tasks: list, error: str = "") -> None:
        for w in self._task_list_frame.winfo_children():
            w.destroy()
        if error:
            ctk.CTkLabel(self._task_list_frame, text=error, text_color=C_RED).pack()
            return
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

    def _refresh_task_list(self) -> None:
        threading.Thread(target=self._fetch_tasks, daemon=True).start()

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
        for col in ["Name", "ID", "Date", "Sign-in", "Sign-out", "Location", "Status"]:
            ctk.CTkLabel(hdr, text=col, font=ctk.CTkFont(size=11), text_color=C_MUTED, anchor="w").pack(side="left", padx=12, pady=8, expand=True)

        self._att_list_frame = ctk.CTkScrollableFrame(frame, fg_color=C_BG)
        self._att_list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        return frame

    def _refresh_attendance(self) -> None:
        if _HAS_CALENDAR:
            date_str = self._att_date.get_date().isoformat()
        else:
            date_str = self._att_date_var.get()
        emp_filter = self._att_emp_var.get().strip()
        threading.Thread(target=self._fetch_attendance, args=(date_str, emp_filter), daemon=True).start()

    def _fetch_attendance(self, date_str: str, emp_filter: str) -> None:
        if not self._db or not self._db.is_connected:
            return
        try:
            col = self._db.get_collection("attendance_logs")
            if col is None: return
            query = {}
            if date_str: query["date"] = date_str
            if emp_filter and emp_filter != "All Employees": query["employee_id"] = emp_filter
            docs = list(col.find(query, {"_id": 0}).limit(50))
            active_sessions = set()
            try:
                scol = self._db.get_collection("sessions")
                if scol: active_sessions = {s.get("employee_id") for s in scol.find({"status": "active"})}
            except Exception: pass
            self.after(0, lambda: self._update_attendance_ui(docs, active_sessions))
        except Exception as exc:
            self.after(0, lambda: self._update_attendance_ui([], set(), error=str(exc)))

    def _update_attendance_ui(self, docs: list, active_sessions: set, error: str = "") -> None:
        for w in self._att_list_frame.winfo_children():
            w.destroy()
        if error:
            ctk.CTkLabel(self._att_list_frame, text=error, text_color=C_RED).pack()
            return
        for d in docs:
            eid = d.get("employee_id")
            status = d.get("status", "—")
            if eid in active_sessions: status = "Online"
            elif status in ["On Time", "Late", "Overtime"]: status = "Offline"
            s_color = {"Online": C_GREEN, "On Time": C_GREEN, "Late": C_AMBER, "Early Departure": C_RED, "Overtime": C_BLUE, "Offline": C_RED}.get(status, C_MUTED)
            row = ctk.CTkFrame(self._att_list_frame, fg_color=C_CARD, corner_radius=8, height=40)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            row_vals = [d.get("full_name","?"), eid, d.get("date",""), d.get("signin","—"), d.get("signout","—"), d.get("duration","—")]
            for val in row_vals:
                ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=12, expand=True)
            ctk.CTkLabel(row, text=status, text_color=s_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)

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
        elif self._active_tab == "live_grid":
            threading.Thread(target=self._refresh_live_grid, daemon=True).start()
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
