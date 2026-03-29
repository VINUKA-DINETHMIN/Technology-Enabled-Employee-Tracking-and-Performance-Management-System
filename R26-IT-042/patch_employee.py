import sys

path = r"d:\sliit\Y4S1\rp\vinuka\Technology-Enabled-Employee-Tracking-and-Performance-Management-System\R26-IT-042\dashboard\employee_panel.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target = """                docs = list(col.find({"employee_id": self._user_id}, {"_id": 0}).sort("date", -1).limit(30))
                for d in docs:
                    s_color = {"On Time": C_GREEN, "Late": C_AMBER, "Early Departure": C_RED}.get(d.get("status", ""), C_MUTED)
                    row = ctk.CTkFrame(self._att_scroll, fg_color=C_CARD, corner_radius=8, height=40)
                    row.pack(fill="x", pady=2)
                    row.pack_propagate(False)
                    for val in [d.get("date",""), d.get("signin","\u2014"), d.get("signout","\u2014"), d.get("duration","\u2014")]:
                        ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=16, expand=True)
                    ctk.CTkLabel(row, text=d.get("status","\u2014"), text_color=s_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)"""

replacement = """                docs = list(col.find({"employee_id": self._user_id}, {"_id": 0}).sort("date", -1).limit(30))
                
                # Today's date for real-time status override
                from datetime import datetime
                today_str = datetime.now().strftime("%Y-%m-%d")

                for d in docs:
                    status = d.get("status", "\u2014")
                    row_date = d.get("date", "")
                    
                    # Real-time status override for CURRENT active session
                    if row_date == today_str:
                        status = "Online"

                    s_color = {
                        "Online": C_GREEN,
                        "On Time": C_GREEN, 
                        "Late": C_AMBER, 
                        "Early Departure": C_RED, 
                        "Offline": C_RED
                    }.get(status, C_MUTED)

                    row = ctk.CTkFrame(self._att_scroll, fg_color=C_CARD, corner_radius=8, height=40)
                    row.pack(fill="x", pady=2)
                    row.pack_propagate(False)
                    for val in [row_date, d.get("signin","\u2014"), d.get("signout","\u2014"), d.get("duration","\u2014")]:
                        ctk.CTkLabel(row, text=str(val), text_color=C_TEXT, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=16, expand=True)
                    ctk.CTkLabel(row, text=status, text_color=s_color, font=ctk.CTkFont(size=11)).pack(side="right", padx=12)"""

if target in content:
    new_content = content.replace(target, replacement)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully updated employee_panel.py")
else:
    print("Target not found in content")

