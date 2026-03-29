from common.database import MongoDBClient
from config.settings import settings
import logging

def check_face_data():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()
    col = db.get_collection("employees")
    # Finding the user 'Prathapa'
    emp = col.find_one({"full_name": {"$regex": "Prathapa", "$options": "i"}})
    
    if not emp:
        print("Employee 'Prathapa' not found.")
        return

    face_images = emp.get("face_images", [])
    face_embedding = emp.get("face_embedding", [])
    
    print(f"Employee: {emp['full_name']}")
    print(f"Number of face images saved: {len(face_images)}")
    if face_images:
        print(f"First image size (chars): {len(face_images[0])}")
        print(f"First image snippet: {face_images[0][:50]}...")
    
    print(f"Embedding size: {len(face_embedding)}")
    if face_embedding:
        print(f"Embedding snippet: {face_embedding[:5]}")

if __name__ == "__main__":
    check_face_data()
