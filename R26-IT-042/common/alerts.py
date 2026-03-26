"""
R26-IT-042 — Employee Activity Monitoring System
common/alerts.py

AlertSender — Risk alert delivery via WebSocket with local-log fallback.

Alert levels
────────────
  LOW      risk_score 0-24    — informational only
  MEDIUM   risk_score 25-49   — soft warning
  HIGH     risk_score 50-74   — notify manager
  CRITICAL risk_score 75-100  — immediate response required

The sender attempts to deliver the alert JSON over WebSocket to the
dashboard.  If the WebSocket handshake fails or the connection drops,
the alert is written to the SecureLogger offline queue for later delivery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

try:
    import websockets
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "websockets library not installed — AlertSender will use fallback logging only."
    )

logger = logging.getLogger(__name__)

# Risk score thresholds matching config/settings.py defaults
_LEVEL_THRESHOLDS: dict[str, int] = {
    "LOW": 25,
    "MEDIUM": 50,
    "HIGH": 75,
    "CRITICAL": 100,
}


def _score_to_level(risk_score: float) -> str:
    """Derive the alert level from a numeric risk score (0–100)."""
    if risk_score < 25:
        return "LOW"
    if risk_score < 50:
        return "MEDIUM"
    if risk_score < 75:
        return "HIGH"
    return "CRITICAL"


class AlertSender:
    """
    Delivers risk alerts to the dashboard WebSocket endpoint.

    Usage
    ─────
    >>> sender = AlertSender(ws_url="ws://localhost:8765")
    >>> sender.send_alert(
    ...     user_id="EMP001",
    ...     risk_score=82.5,
    ...     factors=["idle_spike", "after_hours_access"],
    ...     level="HIGH",
    ... )
    """

    def __init__(
        self,
        ws_url: Optional[str] = None,
        timeout: float = 5.0,
        fallback_logger=None,
    ) -> None:
        """
        Parameters
        ----------
        ws_url:
            WebSocket endpoint URL (e.g. ``ws://localhost:8765``).
            Defaults to the ``WEBSOCKET_URL`` environment variable loaded
            via config/settings.py.
        timeout:
            Seconds to wait for the WebSocket connection before giving up.
        fallback_logger:
            A ``SecureLogger`` instance used when WebSocket is unavailable.
        """
        import os
        self._ws_url: str = ws_url or os.environ.get("WEBSOCKET_URL", "ws://localhost:8765")
        self._timeout = timeout
        self._fallback_logger = fallback_logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(
        self,
        user_id: str,
        risk_score: float,
        factors: list[str],
        level: Optional[str] = None,
        session_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> bool:
        """
        Send a risk alert, synchronously (runs the async coroutine in its
        own thread-safe event loop so callers don't need to be async).

        Parameters
        ----------
        user_id:
            Employee identifier.
        risk_score:
            Numeric risk score 0–100.
        factors:
            List of contributing factor labels (e.g. ``["idle_spike"]``).
        level:
            Alert level override.  If ``None``, derived from *risk_score*.
        session_id:
            Optional current session identifier.
        extra:
            Additional metadata merged into the alert payload.

        Returns
        -------
        bool
            ``True`` if the alert was delivered via WebSocket.
        """
        effective_level = (level or _score_to_level(risk_score)).upper()

        payload: dict = {
            "type": "alert",
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "risk_score": round(float(risk_score), 2),
            "level": effective_level,
            "factors": factors,
            **(extra or {}),
        }

        logger.info(
            "Alert [%s] user=%s score=%.1f factors=%s",
            effective_level, user_id, risk_score, factors,
        )

        # Attempt WebSocket delivery
        delivered = self._send_via_websocket(payload)

        if not delivered:
            self._fallback_log(payload)

        return delivered

    def send_heartbeat(self, agent_id: str) -> bool:
        """Send a lightweight heartbeat to confirm the monitoring agent is alive."""
        payload = {
            "type": "heartbeat",
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return self._send_via_websocket(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_via_websocket(self, payload: dict) -> bool:
        """Run the async WebSocket send in a dedicated thread loop."""
        if not _WS_AVAILABLE:
            return False

        try:
            # Run coroutine in a new event loop (thread-safe)
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self._async_send(payload))
            loop.close()
            return result
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("WebSocket send failed: %s", exc)
            return False

    async def _async_send(self, payload: dict) -> bool:
        """Async coroutine that opens a short-lived WebSocket and sends one message."""
        try:
            async with websockets.connect(  # type: ignore[attr-defined]
                self._ws_url,
                open_timeout=self._timeout,
                close_timeout=2.0,
            ) as ws:
                await ws.send(json.dumps(payload))
                logger.debug("Alert delivered via WebSocket: %s", payload.get("type"))
                return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("WebSocket connection error: %s", exc)
            return False

    def _fallback_log(self, payload: dict) -> None:
        """Write undelivered alert to the SecureLogger or stdlib logging."""
        msg = f"UNDELIVERED ALERT: {json.dumps(payload)}"
        if self._fallback_logger is not None:
            self._fallback_logger.log(
                "WARNING",
                msg,
                user_id=payload.get("user_id", "UNKNOWN"),
                extra={"alert_payload": payload},
            )
        else:
            logger.warning(msg)
