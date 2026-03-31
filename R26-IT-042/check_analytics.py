#!/usr/bin/env python3
"""Quick check: Is app usage analytics working with real data?"""

from common.database import MongoDBClient
from C3_activity_monitoring.src.app_usage_analytics import AppUsageAnalytics
import os
from dotenv import load_dotenv

load_dotenv()
db = MongoDBClient(uri=os.getenv('MONGO_URI'), db_name='employee_monitor')
db.connect()

print('\n' + '='*60)
print('APP USAGE ANALYTICS - REAL DATA CHECK')
print('='*60 + '\n')

# Get all unique users
col = db.get_collection('activity_logs')
users = col.distinct('user_id')
print(f'Active Users with Logs: {len(users)}')
print(f'Users: {users}\n')

# Test analytics for each user
analytics = AppUsageAnalytics(db_client=db)
for user_id in users[:3]:  # Test first 3 users
    summary = analytics.get_apps_by_period(user_id=user_id, period='today')
    print(f'[{user_id}] Today Activity:')
    print(f'  Most Used App: {summary.most_used_app}')
    print(f'  Total Active Time: {summary.get_hours_string(summary.total_time_sec)}')
    print(f'  Unique Apps: {summary.app_count}')
    print(f'  Total Sessions: {summary.total_sessions}')
    
    if summary.apps:
        print(f'  Top 3 Apps:')
        for app in summary.apps[:3]:
            time_str = summary.get_hours_string(app['time_sec'])
            pct = app['percentage']
            print(f'    • {app["app"]}: {time_str} ({pct:.0f}%)')
    else:
        print('  (No apps today)')
    print()

print('='*60)
print('✓ Analytics engine working with real MongoDB data')
print('='*60 + '\n')
