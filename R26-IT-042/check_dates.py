#!/usr/bin/env python3
"""Check what dates have activity data"""

from common.database import MongoDBClient
from C3_activity_monitoring.src.app_usage_analytics import AppUsageAnalytics
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
db = MongoDBClient(uri=os.getenv('MONGO_URI'), db_name='employee_monitor')
db.connect()

print('\n' + '='*60)
print('ACTIVITY LOG DATE RANGE CHECK')
print('='*60 + '\n')

col = db.get_collection('activity_logs')
users = col.distinct('user_id')

for user_id in users[:3]:
    logs = list(col.find({'user_id': user_id}).sort('timestamp', -1).limit(5))
    
    if logs:
        latest = logs[0]['timestamp']
        oldest = logs[-1]['timestamp']
        count = col.count_documents({'user_id': user_id})
        
        print(f'[{user_id}]')
        print(f'  Total Logs: {count}')
        print(f'  Latest: {latest}')
        print(f'  Oldest: {oldest}')
        
        # Get app data from latest log
        if 'top_app' in logs[0]:
            print(f'  Sample Apps: {logs[0].get("top_app")}')
        
        # Test with week/month
        analytics = AppUsageAnalytics(db_client=db)
        
        summary_week = analytics.get_apps_by_period(user_id=user_id, period='week')
        summary_month = analytics.get_apps_by_period(user_id=user_id, period='month')
        
        print(f'  This Week: {summary_week.most_used_app} ({summary_week.app_count} apps, {summary_week.get_hours_string(summary_week.total_time_sec)})')
        print(f'  This Month: {summary_month.most_used_app} ({summary_month.app_count} apps, {summary_month.get_hours_string(summary_month.total_time_sec)})')
        print()

print('='*60)
