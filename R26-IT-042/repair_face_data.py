import base64
import io
import cv2
import numpy as np
from PIL import Image
from common.database import MongoDBClient
from config.settings import settings

def fix_all_face_data():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    if not db.connect():
        print("Failed to connect to MongoDB")
        return

    col = db.get_collection("employees")
    emps = list(col.find({}))
    
    print(f"Repairing face data for {len(emps)} employees...")

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    for emp in emps:
        images_b64 = emp.get("face_images", [])
        if not images_b64:
            continue

        valid_embeddings = []
        for b64_str in images_b64:
            try:
                img_data = base64.b64decode(b64_str)
                img = Image.open(io.BytesIO(img_data)).convert('RGB')
                frame = np.array(img)
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                
                faces = cascade.detectMultiScale(gray, 1.1, 5)
                if len(faces) > 0:
                    (x, y, w, h) = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
                    face_roi = gray[y:y+h, x:x+w]
                    face_roi = cv2.equalizeHist(face_roi) # Normalize lightning
                    hist = cv2.calcHist([face_roi], [0], None, [128], [0, 256])
                    valid_embeddings.append([float(v[0]) for v in hist])
            except Exception:
                pass

        if valid_embeddings:
            num_bins = len(valid_embeddings[0])
            avg_emb = [sum(emb[i] for emb in valid_embeddings)/len(valid_embeddings) for i in range(num_bins)]
            col.update_one({"_id": emp["_id"]}, {"$set": {"face_embedding": avg_emb}})
            print(f"  ✓ Repaired: {emp['full_name']}")
        else:
            print(f"  ✗ Failed: {emp['full_name']} (No faces detected in photos)")

if __name__ == "__main__":
    fix_all_face_data()
