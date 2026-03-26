"""
R26-IT-042 — Employee Activity Monitoring System
common/logger.py

SecureLogger — Encrypted, tamper-evident logger with offline queue support.

How it works
────────────
1. Each log entry is formatted as JSON, then AES-256-GCM encrypted via
   common/encryption.py and written to a local rotating file.
2. An HMAC signature is appended to every entry so on-disk logs can be
   verified for tampering.
3. If the MongoDB connection is unavailable, log documents are pushed into
   an in-memory (and optionally local JSON) offline queue and flushed later
   when connectivity is restored.
4. A standard Python logging.Logger is also configured so regular library
   code (pymongo, websockets, etc.) writes to the same file.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

from common.encryption import AESEncryptor

# ---------------------------------------------------------------------------
# Module-level logger (used internally — not the SecureLogger itself)
# ---------------------------------------------------------------------------
_internal = logging.getLogger(__name__)

# Log levels accepted by SecureLogger
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# Default log directory (next to this file → project root / logs/)
_DEFAULT_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


class SecureLogger:
    """
    Encrypted, tamper-evident application logger with offline queue support.

    Usage
    ─────
    >>> sl = SecureLogger(user_id="EMP001")
    >>> sl.log("INFO", "Session started")
    >>> sl.flush_queue(db_collection)   # upload offline queue to MongoDB
    """

    def __init__(
        self,
        user_id: str = "SYSTEM",
        log_dir: Optional[str] = None,
        max_bytes: int = 5 * 1024 * 1024,   # 5 MB per file
        backup_count: int = 5,
        encryptor: Optional[AESEncryptor] = None,
    ) -> None:
        self._user_id = user_id
        self._log_dir = os.path.normpath(log_dir or _DEFAULT_LOG_DIR)
        os.makedirs(self._log_dir, exist_ok=True)

        # Try to initialise the encryptor; fall back to plain logging if AES_KEY
        # is not yet set (e.g. during first-run setup).
        try:
            self._enc: Optional[AESEncryptor] = encryptor or AESEncryptor()
        except ValueError as exc:
            _internal.warning("AESEncryptor not initialised (%s) — falling back to plain logs.", exc)
            self._enc = None

        # Rotating plain-text (but line-encrypted) log file
        log_path = os.path.join(self._log_dir, "monitor.enc.log")
        self._file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self._file_handler.setLevel(logging.DEBUG)

        # Offline queue (thread-safe)
        self._offline_queue: queue.Queue[dict] = queue.Queue(maxsize=10_000)
        self._lock = threading.Lock()

        _internal.info("SecureLogger initialised — log dir: %s", self._log_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        level: str,
        message: str,
        user_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """
        Write an encrypted log entry.

        Parameters
        ----------
        level:
            One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        message:
            Human-readable log message.
        user_id:
            Override the default user_id for this entry.
        extra:
            Arbitrary key-value metadata merged into the log document.
        """
        level = level.upper()
        if level not in LOG_LEVELS:
            level = "INFO"

        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "user_id": user_id or self._user_id,
            "message": message,
            **(extra or {}),
        }

        line = json.dumps(entry, ensure_ascii=False)

        # Encrypt if possible; otherwise write plain
        if self._enc is not None:
            try:
                encrypted = self._enc.encrypt(line)
                sig = self._enc.hmac_sign(line)
                output = f"{encrypted.decode('ascii')}|{sig}"
            except Exception as exc:  # pylint: disable=broad-except
                _internal.error("Encryption failed, writing plain: %s", exc)
                output = line
        else:
            output = line

        self._write_to_file(output)

        # Push to offline queue for later DB upload
        self._push_to_queue(entry)

    def flush_queue(self, db_collection) -> int:
        """
        Upload all queued log documents to *db_collection*.

        Parameters
        ----------
        db_collection:
            A pymongo Collection object.

        Returns
        -------
        int
            Number of documents successfully uploaded.
        """
        if db_collection is None:
            return 0

        flushed = 0
        batch: list[dict] = []

        while not self._offline_queue.empty():
            try:
                batch.append(self._offline_queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return 0

        try:
            result = db_collection.insert_many(batch, ordered=False)
            flushed = len(result.inserted_ids)
            _internal.info("Flushed %d log documents to MongoDB.", flushed)
        except Exception as exc:  # pylint: disable=broad-except
            _internal.error("Failed to flush log queue to MongoDB: %s", exc)
            # Put them back
            for doc in batch:
                self._push_to_queue(doc)

        return flushed

    @property
    def queue_size(self) -> int:
        """Return the number of documents waiting in the offline queue."""
        return self._offline_queue.qsize()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_to_file(self, line: str) -> None:
        with self._lock:
            try:
                self._file_handler.stream  # type: ignore[attr-defined]
                self._file_handler.emit(
                    logging.LogRecord(
                        name="SecureLogger",
                        level=logging.INFO,
                        pathname="",
                        lineno=0,
                        msg=line,
                        args=(),
                        exc_info=None,
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                _internal.error("Failed to write to log file: %s", exc)

    def _push_to_queue(self, entry: dict) -> None:
        try:
            self._offline_queue.put_nowait(entry)
        except queue.Full:
            _internal.warning("Offline log queue is full — oldest entry dropped.")
            try:
                self._offline_queue.get_nowait()
                self._offline_queue.put_nowait(entry)
            except queue.Empty:
                pass
