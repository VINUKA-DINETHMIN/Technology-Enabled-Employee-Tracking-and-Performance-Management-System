from common.database import MongoDBClient
from config.settings import settings
import logging

def check_prathapa():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()
    col = db.get_collection("employees")
    emps = col.find({"full_name": {"$regex": "Prathapa", "$options": "i"}})
    for emp in emps:
        print(f"Name: {emp['full_name']}, Email: '{emp['email']}'")

if __name__ == "__main__":
    check_prathapa()
