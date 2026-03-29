from common.database import MongoDBClient
from config.settings import settings

client = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
client.connect()
col = client.get_collection("employees")
if col is not None:
    docs = list(col.find({}, {"employee_id": 1, "_id": 0}))
    for d in docs:
        print(f"'{d.get('employee_id')}'")
client.close()
