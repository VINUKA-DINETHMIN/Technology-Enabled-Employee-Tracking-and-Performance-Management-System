"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/offline_queue.py

Persistent offline queue for events that cannot be uploaded to MongoDB
because the network is unavailable.

Saves to a local JSON-lines file and replays on reconnect.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE_FILE = Path(__file__).resolve().parent.parent.parent / "logs" / "offline_queue.jsonl"


class OfflineQueue:
    """
    Thread-safe JSON-lines based offline event queue.

    Usage
    ─────
    >>> q = OfflineQueue()
    >>> q.push({"user_id": "EMP001", "event": "keystroke"})
    >>> q.flush(db_collection)   # uploads all queued events
    """

    def __init__(self, queue_file: Path | None = None) -> None:
        self._file = Path(queue_file or _DEFAULT_QUEUE_FILE)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def push(self, document: dict[str, Any]) -> None:
        """Append *document* to the offline queue file."""
        with self._lock:
            try:
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(document, ensure_ascii=False) + "\n")
            except Exception as exc:
                logger.error("OfflineQueue write error: %s", exc)

    def flush(self, db_collection) -> int:
        """
        Upload all queued documents to *db_collection* and clear the file.

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
                    lines = f.readlines()
            except Exception as exc:
                logger.error("OfflineQueue read error: %s", exc)
                return 0

            docs = []
            for line in lines:
                try:
                    docs.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass

            if not docs:
                return 0

            try:
                result = db_collection.insert_many(docs, ordered=False)
                uploaded = len(result.inserted_ids)
                # Clear the file on success
                open(self._file, "w").close()
                logger.info("OfflineQueue: flushed %d documents.", uploaded)
                return uploaded
            except Exception as exc:
                logger.error("OfflineQueue flush error: %s", exc)
                return 0

    @property
    def size(self) -> int:
        """Return the approximate number of queued documents."""
        if not self._file.exists():
            return 0
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0
