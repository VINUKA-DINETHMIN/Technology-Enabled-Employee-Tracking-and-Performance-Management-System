"""
R26-IT-042 — Component 3: Activity Monitoring
C3_activity_monitoring/src/initialize_monitoring.py

Orchestrates all C3 sub-trackers: keyboard, mouse, app usage,
idle detection, anomaly engine, screenshot trigger, and break manager.

Called by main.py in a background thread.  Runs until shutdown_event is set.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


def start_monitoring(
    user_id: str,
    db_client=None,
    alert_sender=None,
    shutdown_event: Optional[threading.Event] = None,
) -> None:
    """
    Start all C3 activity monitoring sub-components.

    Parameters
    ----------
    user_id:
        Employee identifier.
    db_client:
        MongoDBClient instance from common/database.py.
    alert_sender:
        AlertSender instance from common/alerts.py.
    shutdown_event:
        threading.Event — monitored to exit all loops cleanly.
    """
    logger.info("C3 activity monitoring starting for user: %s", user_id)

    if shutdown_event is None:
        shutdown_event = threading.Event()

    # TODO: start sub-trackers here (keyboard, mouse, app, idle, anomaly, screenshot, break)

    # Block until shutdown is signalled
    shutdown_event.wait()
    logger.info("C3 activity monitoring stopped for user: %s", user_id)
