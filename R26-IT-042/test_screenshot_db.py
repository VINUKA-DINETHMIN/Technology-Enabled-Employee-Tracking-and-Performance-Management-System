import sys
import os
from pathlib import Path

# Add project root to sys.path
root = Path(r"d:\sliit\Y4S1\rp\vinuka\Technology-Enabled-Employee-Tracking-and-Performance-Management-System\R26-IT-042")
sys.path.append(str(root))

from C3_activity_monitoring.src.screenshot_trigger import ScreenshotTrigger
from common.database import MongoDBClient
from dotenv import load_dotenv

load_dotenv()

def test_screenshot():
    print("Testing screenshot capture with DB storage...")
    db = MongoDBClient()
    if not db.connect():
        print("Failed to connect to MongoDB.")
        return
    st = ScreenshotTrigger(db_client=db)
    
    path = st.capture(user_id="test_admin", session_id="test_session", risk_score=5.0, trigger_reason="manual_test")
    if path:
        print(f"Success! Screenshot saved to {path} and MongoDB.")
    else:
        print("Capture failed.")

if __name__ == "__main__":
    test_screenshot()
