"""
R26-IT-042 — Component 3: Activity Monitoring
C3_activity_monitoring/src/__init__.py
"""


def start_monitoring(user_id, db_client=None, alert_sender=None, shutdown_event=None):
    """
    Entry point called by main.py.
    Delegates to initialize_monitoring.start_monitoring().
    """
    from C3_activity_monitoring.src.initialize_monitoring import start_monitoring as _start
    _start(
        user_id=user_id,
        db_client=db_client,
        alert_sender=alert_sender,
        shutdown_event=shutdown_event,
    )
