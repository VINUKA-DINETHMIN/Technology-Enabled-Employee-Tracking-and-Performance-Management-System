# C3 — Activity Monitoring & Anomaly Detection

Tracks keyboard, mouse, app usage, idle time, and flags behavioural anomalies.

## Owner
Team Member 3

## Dependencies
```
pynput, pyautogui, psutil, scikit-learn, numpy, pandas, pymongo, websockets
```

## Interfaces
- `start_monitoring(user_id, db_client, alert_sender, shutdown_event)`

## Module Map
| Module | Purpose |
|--------|---------|
| `initialize_monitoring.py` | Orchestrates all sub-trackers |
| `keyboard_tracker.py` | Records keystroke events + WPM |
| `mouse_tracker.py` | Tracks velocity, clicks, scroll |
| `app_usage_monitor.py` | Logs active window titles |
| `idle_detector.py` | Detects and reports idle periods |
| `feature_extractor.py` | Rolls raw events into ML features |
| `anomaly_engine.py` | IsolationForest anomaly scoring |
| `screenshot_trigger.py` | Captures screen on high risk score |
| `break_manager.py` | Suppresses alerts during breaks |
| `geo_context.py` | Adds geolocation context |
| `offline_queue.py` | Buffers events when DB offline |
| `websocket_alerter.py` | Sends alerts to dashboard |
