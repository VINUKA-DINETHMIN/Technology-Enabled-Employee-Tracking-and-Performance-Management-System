"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/offline_queue.py

OfflineQueue — Persistent encrypted offline buffer for activity_logs
documents that cannot be uploaded to MongoDB due to network issues.

• Documents are AES-256 encrypted before being written to disk.
• On reconnect, the queue is flushed to MongoDB in insertion order.
• Thread-safe via threading.Lock.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default queue file path
_DEFAULT_QUEUE_FILE = (
    Path(__file__).resolve().parent.parent.parent / "logs" / "offline_queue.json"
)

# How long (seconds) between connectivity checks
_CONNECTIVITY_CHECK_INTERVAL = 30.0


class OfflineQueue:
    """
    Thread-safe encrypted offline event queue.

    On enqueue, the document is serialised to JSON, encrypted with
    AES-256-GCM via common/encryption.py, then appended to the local
    queue file as a base64 line.

    On flush (when connectivity returns), all stored documents are
    decrypted, deserialized, and bulk-inserted into MongoDB.

    Usage
    ─────
    >>> q = OfflineQueue()
    >>> q.enqueue({"user_id": "EMP001", "event": "keystroke"})
    >>> if q.is_online():
    ...     q.flush(db_collection)
    """

    def __init__(
        self,
        queue_file: Optional[Path] = None,
        mongo_host: str = "8.8.8.8",
        mongo_port: int = 53,
    ) -> None:
        """
        Parameters
        ----------
        queue_file:
            Path to the local encrypted queue file.
            Defaults to ``logs/offline_queue.json``.
        mongo_host / mongo_port:
            Host and port used for connectivity check (DNS ping).
        """
        self._file = Path(queue_file or _DEFAULT_QUEUE_FILE)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._mongo_host = mongo_host
        self._mongo_port = mongo_port
        self._last_online: Optional[bool] = None

        # Lazy-load encryptor to avoid crashing if AES_KEY not set at import
        self._encryptor = None

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        """
        Check internet connectivity by attempting a socket connection.

        Returns
        -------
        bool
            True if a network route is available.
        """
        try:
            socket.setdefaulttimeout(3)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
                (self._mongo_host, self._mongo_port)
            )
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------

    def enqueue(self, doc: dict[str, Any]) -> None:
        """
        Encrypt *doc* and append it to the local queue file.

        Parameters
        ----------
        doc:
            The activity_log document to store offline.
        """
        enc = self._get_encryptor()
        try:
            raw_json = json.dumps(doc, ensure_ascii=False, default=str)
            if enc is not None:
                encrypted_line = enc.encrypt(raw_json).decode("utf-8")
            else:
                # Fallback: plain JSON if encryption not available
                encrypted_line = "PLAIN:" + raw_json

            with self._lock:
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(encrypted_line + "\n")

        except Exception as exc:
            logger.error("OfflineQueue.enqueue error: %s", exc)

    def flush(self, db_collection) -> int:
        """
        Decrypt and upload all queued documents to *db_collection*.

        Parameters
        ----------
        db_collection:
            pymongo Collection to insert documents into.

        Returns
        -------
        int
            Number of documents successfully uploaded.
        """
        if db_collection is None:
            return 0

        with self._lock:
            if not self._file.exists():
                return 0

            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
            except Exception as exc:
                logger.error("OfflineQueue.flush read error: %s", exc)
                return 0

            if not lines:
                return 0

            enc = self._get_encryptor()
            docs = []
            for line in lines:
                try:
                    if line.startswith("PLAIN:"):
                        docs.append(json.loads(line[6:]))
                    elif enc is not None:
                        decrypted = enc.decrypt(line.encode("utf-8"))
                        docs.append(json.loads(decrypted))
                    else:
                        docs.append(json.loads(line))
                except Exception as exc:
                    logger.warning("OfflineQueue: could not decode line: %s", exc)

            if not docs:
                return 0

            try:
                result = db_collection.insert_many(docs, ordered=False)
                uploaded = len(result.inserted_ids)
                # Clear queue file on success
                with open(self._file, "w", encoding="utf-8") as f:
                    pass
                logger.info("OfflineQueue: flushed %d documents to MongoDB.", uploaded)
                return uploaded
            except Exception as exc:
                logger.error("OfflineQueue.flush MongoDB error: %s", exc)
                return 0

    # ------------------------------------------------------------------
    # Legacy push() alias (backward compat with existing code)
    # ------------------------------------------------------------------

    def push(self, document: dict[str, Any]) -> None:
        """Alias for enqueue() — kept for backward compatibility."""
        self.enqueue(document)

    @property
    def size(self) -> int:
        """Return the approximate number of queued documents."""
        if not self._file.exists():
            return 0
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_encryptor(self):
        """Lazy-load AESEncryptor; returns None if AES_KEY not set."""
        if self._encryptor is not None:
            return self._encryptor
        try:
            from common.encryption import AESEncryptor
            self._encryptor = AESEncryptor()
            return self._encryptor
        except Exception as exc:
            logger.warning("AESEncryptor unavailable for OfflineQueue: %s", exc)
            return None
