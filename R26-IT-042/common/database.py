"""
R26-IT-042 — Employee Activity Monitoring System
common/database.py

MongoDBClient — Manages the MongoDB Atlas connection shared by all four
components.  The connection string is loaded from the MONGO_URI environment
variable (see config/settings.py).

Collections used across the project
────────────────────────────────────
  sessions              Active / historical employee sessions
  alerts                Risk alerts sent to the dashboard
  screenshots           Encrypted screenshot metadata
  behavioral_baselines  Per-user ML baseline documents
  auth_events           Login / OTP / face-liveness events
  productivity_scores   C4 predictions per session window
"""

from __future__ import annotations

import os
import logging
from typing import Optional

import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    ConnectionFailure,
    ConfigurationError,
    ServerSelectionTimeoutError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known collection names — used to pre-validate caller requests
# ---------------------------------------------------------------------------
KNOWN_COLLECTIONS: set[str] = {
    "sessions",
    "alerts",
    "screenshots",
    "behavioral_baselines",
    "auth_events",
    "productivity_scores",
    # New collections added by full system build
    "employees",
    "tasks",
    "task_logs",
    "activity_logs",
    "attendance_logs",
    "policy_violations",
}


class MongoDBClient:
    """
    Singleton-style MongoDB Atlas client shared across all components.

    Usage
    ─────
    >>> client = MongoDBClient()
    >>> client.connect()
    >>> col = client.get_collection("sessions")
    >>> client.close()
    """

    def __init__(self, uri: Optional[str] = None, db_name: str = "employee_monitor") -> None:
        """
        Parameters
        ----------
        uri:
            MongoDB connection URI.  Defaults to the MONGO_URI env variable.
        db_name:
            Database name to use.  Defaults to ``employee_monitor``.
        """
        self._uri: str = uri or os.environ.get("MONGO_URI", "")
        self._db_name: str = db_name
        self._client: Optional[MongoClient] = None
        self._db: Optional[Database] = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish a connection to MongoDB Atlas.

        Returns
        -------
        bool
            ``True`` on success, ``False`` on failure.
        """
        if not self._uri:
            logger.error(
                "MONGO_URI is not set.  "
                "Add it to your .env file before starting the application."
            )
            return False

        try:
            self._client = MongoClient(
                self._uri,
                serverSelectionTimeoutMS=5_000,
                connectTimeoutMS=10_000,
                socketTimeoutMS=30_000,
                maxPoolSize=10,
                retryWrites=True,
            )
            # Force an immediate handshake so we catch auth errors early
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            self._connected = True
            logger.info("MongoDB Atlas connected — database: %s", self._db_name)
            self._ensure_indexes()
            return True

        except ConfigurationError as exc:
            logger.error("MongoDB configuration error: %s", exc)
        except ServerSelectionTimeoutError as exc:
            logger.error("MongoDB server selection timeout: %s", exc)
        except ConnectionFailure as exc:
            logger.error("MongoDB connection failure: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unexpected MongoDB error: %s", exc)

        self._connected = False
        return False

    def get_collection(self, name: str) -> Optional[Collection]:
        """
        Return a pymongo ``Collection`` object.

        Parameters
        ----------
        name:
            Collection name.  Should be one of ``KNOWN_COLLECTIONS``.

        Returns
        -------
        Collection | None
            The collection, or ``None`` if the client is not connected.
        """
        if not self._connected or self._db is None:
            logger.warning(
                "Attempted to get collection '%s' but the database is not connected.", name
            )
            return None

        if name not in KNOWN_COLLECTIONS:
            logger.warning(
                "Collection '%s' is not in the known-collection list — "
                "proceeding anyway but check for typos.",
                name,
            )

        return self._db[name]

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the client is currently connected."""
        return self._connected

    def close(self) -> None:
        """Gracefully close the MongoDB connection."""
        if self._client is not None:
            self._client.close()
            self._connected = False
            logger.info("MongoDB connection closed.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """Create commonly used indexes if they do not already exist."""
        if self._db is None:
            return

        try:
            # sessions — sort / filter by user + start time
            self._db["sessions"].create_index(
                [("user_id", pymongo.ASCENDING), ("start_time", pymongo.DESCENDING)],
                name="user_session_time",
                background=True,
            )
            # alerts — retrieve latest alerts per user
            self._db["alerts"].create_index(
                [("user_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="user_alert_time",
                background=True,
            )
            # productivity_scores — query by session
            self._db["productivity_scores"].create_index(
                [("session_id", pymongo.ASCENDING)],
                name="session_score",
                background=True,
            )
            logger.debug("MongoDB indexes verified / created.")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not ensure MongoDB indexes: %s", exc)
