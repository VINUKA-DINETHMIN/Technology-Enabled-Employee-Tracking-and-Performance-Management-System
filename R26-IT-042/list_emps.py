from common.database import MongoDBClient
from config.settings import settings

def list_all_emps():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()
    col = db.get_collection("employees")
    emps = col.find({}, {"full_name": 1, "employee_id": 1, "_id": 0})
    for e in emps:
        print(f"Name: {e['full_name']}, ID: {e['employee_id']}")

if __name__ == "__main__":
    list_all_emps()
