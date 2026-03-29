from common.database import MongoDBClient
from config.settings import settings
from datetime import datetime

# Bootstrap
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

db = MongoDBClient(settings.MONGO_URI, settings.MONGO_DB_NAME)
db.connect()

if db.is_connected:
    att_col = db.get_collection("attendance_logs")
    sess_col = db.get_collection("sessions")
    today = datetime.now().strftime("%Y-%m-%d")
    
    print("\n--- Attendance Logs for Emp003 Today ---")
    log = att_col.find_one({"employee_id": "Emp003", "date": today})
    print(log)
    
    print("\n--- Active Sessions for Emp003 ---")
    sess = list(sess_col.find({"employee_id": "Emp003", "status": "active"}))
    print(sess)
    
db.close()
