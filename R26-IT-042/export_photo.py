import base64
from common.database import MongoDBClient
from config.settings import settings

def export_reg_photo():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()
    col = db.get_collection("employees")
    emp = col.find_one({"full_name": {"$regex": "Prathapa", "$options": "i"}})
    if emp and emp.get("face_images"):
        img_data = base64.b64decode(emp["face_images"][0])
        with open("registration_photo.jpg", "wb") as f:
            f.write(img_data)
        print("Exported registration_photo.jpg")
    else:
        print("No photo found.")

if __name__ == "__main__":
    export_reg_photo()
