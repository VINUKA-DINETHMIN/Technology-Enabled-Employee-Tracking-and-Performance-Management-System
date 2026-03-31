#!/usr/bin/env python3
"""Inspect activity log document structure"""

from common.database import MongoDBClient
import os
from dotenv import load_dotenv
from pprint import pprint

load_dotenv()
db = MongoDBClient(uri=os.getenv('MONGO_URI'), db_name='employee_monitor')
db.connect()

col = db.get_collection('activity_logs')
sample = col.find_one({'user_id': 'EMP002'})

print('\n===== ACTIVITY LOG DOCUMENT STRUCTURE =====\n')
pprint(sample, width=60)
