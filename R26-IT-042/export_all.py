import base64
from common.database import MongoDBClient
from config.settings import settings

def export_all_photos():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()
    col = db.get_collection("employees")
    emps = col.find({})
    for e in emps:
        if e.get("face_images"):
            name = e["full_name"].replace(" ", "_")
            img_data = base64.b64decode(e["face_images"][0])
            with open(f"photo_{name}.jpg", "wb") as f:
                f.write(img_data)
            print(f"Exported photo_{name}.jpg")

if __name__ == "__main__":
    export_all_photos()
