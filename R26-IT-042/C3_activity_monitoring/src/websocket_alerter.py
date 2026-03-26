"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/websocket_alerter.py

Component-level WebSocket alerter for C3.
Thin wrapper around common/alerts.py AlertSender, pre-configured
with the credentials from config/settings.py.

C3 team members should import this module rather than common/alerts
directly so settings are applied consistently.
"""

from __future__ import annotations

import logging
from typing import Optional

from common.alerts import AlertSender
from config.settings import settings

logger = logging.getLogger(__name__)


def get_alerter(fallback_logger=None) -> AlertSender:
    """
    Factory that returns an AlertSender configured from settings.

    Parameters
    ----------
    fallback_logger:
        SecureLogger instance used when WebSocket delivery fails.

    Returns
    -------
    AlertSender
    """
    return AlertSender(
        ws_url=settings.WEBSOCKET_URL,
        fallback_logger=fallback_logger,
    )


def send_c3_alert(
    user_id: str,
    risk_score: float,
    factors: list[str],
    session_id: Optional[str] = None,
    alerter: Optional[AlertSender] = None,
) -> bool:
    """
    Convenience wrapper for C3 to send an alert without manually
    instantiating AlertSender each time.

    Parameters
    ----------
    user_id:
        Employee identifier.
    risk_score:
        Numeric risk score 0–100.
    factors:
        Causal factors list (e.g. ["idle_spike", "after_hours"]).
    session_id:
        Optional session UUID.
    alerter:
        Pre-configured AlertSender.  If None, a new one is created.

    Returns
    -------
    bool
        True if delivered via WebSocket.
    """
    sender = alerter or get_alerter()
    return sender.send_alert(
        user_id=user_id,
        risk_score=risk_score,
        factors=factors,
        session_id=session_id,
    )
