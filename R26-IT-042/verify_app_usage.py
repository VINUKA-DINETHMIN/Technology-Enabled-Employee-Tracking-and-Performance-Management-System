#!/usr/bin/env python3
"""
R26-IT-042 — Verification Script
Diagnose whether app usage tracking is working end-to-end
"""

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

print("\n" + "="*70)
print("APP USAGE TRACKING VERIFICATION SCRIPT")
print("="*70)

# TEST 1: Can we detect the active app?
print("\n[TEST 1] Testing Active App Detection...")
print("-" * 70)
try:
    from C3_activity_monitoring.src.app_usage_monitor import _get_active_app
    
    active = _get_active_app()
    print(f"✓ Active app detected: {active}")
    if active == "Unknown":
        print("  ⚠️  WARNING: Could not detect app. Check security permissions.")
    else:
        print(f"  ✓ Successfully detected: {active}")
except Exception as e:
    print(f"❌ Error: {e}")

# TEST 2: Can AppUsageMonitor track app switches?
print("\n[TEST 2] Testing AppUsageMonitor Tracking...")
print("-" * 70)
try:
    from C3_activity_monitoring.src.app_usage_monitor import AppUsageMonitor
    
    monitor = AppUsageMonitor(window_sec=10.0)
    monitor.start()
    
    print("✓ AppUsageMonitor started")
    print("  ACTION: Switch between 2-3 apps on your computer for 10 seconds...")
    print("  (e.g., Click on Chrome, then Word, then back to VS Code)")
    
    time.sleep(12)  # Let it collect data
    
    features = monitor.get_features()
    monitor.stop()
    
    print(f"\n✓ Captured features:")
    print(f"  - Top App: {features.get('top_app')}")
    print(f"  - Total Focus (seconds): {features.get('total_focus_duration'):.1f}s")
    print(f"  - App Switches: {features.get('app_switch_frequency'):.2f}/min")
    print(f"  - Focus Entropy: {features.get('active_app_entropy'):.4f}")
    
    if features.get('top_app') != 'Unknown':
        print(f"\n✓ Tracking is WORKING - detected app usage!")
    else:
        print(f"\n❌ Tracking FAILED - no app detected")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

# TEST 3: Check MongoDB connection
print("\n[TEST 3] Testing MongoDB Connection...")
print("-" * 70)
try:
    from common.database import MongoDBClient
    
    db = MongoDBClient(uri='mongodb://localhost:27017', db_name='employee_monitoring')
    connected = db.connect()
    
    if connected:
        print("✓ Connected to MongoDB")
        
        col = db.get_collection('activity_logs')
        if col:
            count = col.count_documents({})
            print(f"✓ activity_logs collection exists with {count} documents")
            
            if count > 0:
                latest = col.find_one(sort=[('timestamp', -1)])
                print(f"\nLatest activity log:")
                print(f"  - User: {latest.get('user_id')}")
                print(f"  - App: {latest.get('top_app')}")
                print(f"  - Time: {latest.get('timestamp')}")
                print(f"  - Risk Score: {latest.get('composite_risk_score')}")
        else:
            print("❌ activity_logs collection not found")
    else:
        print("❌ Cannot connect to MongoDB. Make sure:")
        print("   1. MongoDB is running (mongod.exe)")
        print("   2. MONGO_URI in .env is correct")
        print("   3. Network access is allowed")
        
except Exception as e:
    print(f"❌ Error: {e}")

# TEST 4: Test AppUsageAnalytics aggregation
print("\n[TEST 4] Testing Analytics Aggregation...")
print("-" * 70)
try:
    from common.database import MongoDBClient
    from C3_activity_monitoring.src.app_usage_analytics import AppUsageAnalytics
    
    db = MongoDBClient(uri='mongodb://localhost:27017', db_name='employee_monitoring')
    if db.connect():
        analytics = AppUsageAnalytics(db_client=db)
        
        # Get first user from activity_logs
        col = db.get_collection('activity_logs')
        if col and col.count_documents({}) > 0:
            sample_user = col.find_one()
            user_id = sample_user.get('user_id', 'UNKNOWN')
            
            summary = analytics.get_apps_by_period(user_id=user_id, period='today')
            
            print(f"✓ Aggregated data for {user_id}:")
            print(f"  - Most Used App: {summary.most_used_app}")
            print(f"  - Total Active Time: {summary.get_hours_string(summary.total_time_sec)}")
            print(f"  - Unique Apps: {summary.app_count}")
            print(f"  - Total Sessions: {summary.total_sessions}")
            
            if summary.apps:
                print(f"\n  App Breakdown:")
                for app_data in summary.apps[:5]:
                    print(f"    - {app_data['app']}: {summary.get_hours_string(app_data['time_sec'])} ({app_data['percentage']:.1f}%)")
                print("\n✓ Analytics aggregation WORKING")
            else:
                print("\n⚠️  No apps found in aggregation")
        else:
            print("⚠️  No activity logs found in database")
    else:
        print("❌ MongoDB not accessible")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("VERIFICATION COMPLETE")
print("="*70 + "\n")
