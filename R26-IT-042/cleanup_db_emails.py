from common.database import MongoDBClient
from config.settings import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_emails():
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    if not db.connect():
        logger.error("Failed to connect to MongoDB")
        return

    col = db.get_collection("employees")
    if col is None:
        logger.error("Collection 'employees' not found")
        return

    # Find emails that contain characters they shouldn't (like trailing slashes or spaces)
    cursor = col.find({})
    count = 0
    fixed = 0

    for emp in cursor:
        count += 1
        original_email = emp.get("email", "")
        clean_email = original_email.strip().strip("/").lower()
        
        if original_email != clean_email:
            logger.info(f"Fixing email for {emp.get('full_name')}: '{original_email}' -> '{clean_email}'")
            col.update_one({"_id": emp["_id"]}, {"$set": {"email": clean_email}})
            fixed += 1

    logger.info(f"Checked {count} employees. Fixed {fixed} email addresses.")

if __name__ == "__main__":
    cleanup_emails()
