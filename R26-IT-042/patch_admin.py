import sys

path = r"d:\sliit\Y4S1\rp\vinuka\Technology-Enabled-Employee-Tracking-and-Performance-Management-System\R26-IT-042\dashboard\admin_panel.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target = """            docs = list(col.find(query, {"_id": 0}).limit(50))
            for d in docs:
                status_color = {"On Time": C_GREEN, "Late": C_AMBER, "Early Departure": C_RED, "Overtime": C_BLUE, "Offline": C_RED}.get(d.get("status", ""), C_MUTED)
                row = ctk.CTkFrame(self._att_list_frame, fg_color=C_CARD, corner_radius=8, height=40)
                row.pack(fill="x", pady=2)
                row.pack_propagate(False)
                for val in [d.get("full_name","?"), d.get("employee_id","?"), d.get("date",""), d.get("signin","\u2014"), d.get("signout","\u2014"), d.get("duration","\u2014")]:
                    ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=12, expand=True)
                ctk.CTkLabel(row, text=d.get("status","\u2014"), text_color=status_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)"""

replacement = """            docs = list(col.find(query, {"_id": 0}).limit(50))
            active_sessions = set()
            try:
                scol = self._db.get_collection("sessions")
                if scol:
                    active_sessions = {s.get("employee_id") for s in scol.find({"status": "active"})}
            except Exception: pass

            for d in docs:
                eid = d.get("employee_id")
                status = d.get("status", "\u2014")
                if eid in active_sessions:
                    status = "Online"
                elif status in ["On Time", "Late", "Overtime"]:
                    status = "Offline"
                
                s_color = {"Online": C_GREEN, "On Time": C_GREEN, "Late": C_AMBER, "Early Departure": C_RED, "Overtime": C_BLUE, "Offline": C_RED}.get(status, C_MUTED)
                row = ctk.CTkFrame(self._att_list_frame, fg_color=C_CARD, corner_radius=8, height=40)
                row.pack(fill="x", pady=2)
                row.pack_propagate(False)
                row_vals = [d.get("full_name","?"), eid, d.get("date",""), d.get("signin","\u2014"), d.get("signout","\u2014"), d.get("duration","\u2014")]
                for val in row_vals:
                    ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=12, expand=True)
                ctk.CTkLabel(row, text=status, text_color=s_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)"""

if target in content:
    new_content = content.replace(target, replacement)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully updated admin_panel.py")
else:
    print("Target not found in content")
    # Debug: showing the content of the target area
    import re
    m = re.search(r'docs = list\(col\.find\(query.*?\n.*?except Exception as exc:', content, re.DOTALL)
    if m:
        print("Found surrounding context:")
        print(m.group(0))
