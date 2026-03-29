from common.database import MongoDBClient
from config.settings import settings
import json

client = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
client.connect()
db = client.get_collection("sessions") # Wait, get_collection returns a Collection or None
if db is not None:
    docs = list(db.find({"status": "active"}, {"_id": 0}).limit(10))
    print(json.dumps(docs, indent=2))
client.close()
