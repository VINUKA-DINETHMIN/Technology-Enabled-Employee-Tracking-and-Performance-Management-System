"""
R26-IT-042 — Component 4: Productivity Prediction
C4_productivity_prediction/src/__init__.py

Public interface for C4.  main.py calls start_productivity_logger().
"""

# TODO (C4 owner): implement productivity model inference and SHAP/LIME explanations


def start_productivity_logger(user_id: str, db_client=None, shutdown_event=None) -> None:
    """
    Entry point called by main.py to start the productivity prediction loop.

    Parameters
    ----------
    user_id:
        Employee identifier.
    db_client:
        MongoDBClient instance.
    shutdown_event:
        threading.Event — set by main.py on logout.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info("C4 productivity prediction starting for user: %s", user_id)

    if shutdown_event:
        shutdown_event.wait()

    logger.info("C4 productivity prediction stopped for user: %s", user_id)
