
import sys
import os
from pathlib import Path

# Bootstrap path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import settings
from common.database import MongoDBClient
import json

db = MongoDBClient()
db.connect()

print("--- COMMANDS ---")
cmds_col = db.get_collection("commands")
if cmds_col is not None:
    for doc in cmds_col.find().sort("timestamp", -1).limit(5):
        print(json.dumps(doc, indent=2, default=str))

print("\n--- CAMERA STREAMS ---")
cam_col = db.get_collection("camera_streams")
if cam_col is not None:
    for doc in cam_col.find():
        # Don't print the huge base64
        if "image_base64" in doc:
            doc["image_base64_len"] = len(doc["image_base64"])
            del doc["image_base64"]
        print(json.dumps(doc, indent=2, default=str))

db.close()
