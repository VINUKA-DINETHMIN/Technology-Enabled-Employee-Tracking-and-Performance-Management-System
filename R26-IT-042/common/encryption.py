"""
R26-IT-042 — Employee Activity Monitoring System
common/encryption.py

AESEncryptor — AES-256-GCM symmetric encryption + HMAC-SHA256 log integrity
signing, used across all four components.

Design decisions
────────────────
• AES-256-GCM is authenticated encryption — it provides both confidentiality
  and integrity without a separate HMAC layer for ciphertext.  We still expose
  an hmac_sign / hmac_verify pair so that plain log lines (not encrypted) can
  be signed for tamper-evidence.
• A fresh 96-bit nonce (IV) is generated for every encrypt() call and
  prepended to the returned bytes so decrypt() can recover it without storing
  state.
• The AES key is derived from a hex string stored in AES_KEY (env var).
  It must be exactly 32 bytes (64 hex characters) for AES-256.
"""

from __future__ import annotations

import hmac
import hashlib
import os
import base64
import logging
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# Nonce size for AES-GCM (96 bits recommended by NIST)
_NONCE_BYTES = 12


class AESEncryptor:
    """
    AES-256-GCM encryptor / decryptor.

    Usage
    ─────
    >>> enc = AESEncryptor()           # reads AES_KEY from env
    >>> token = enc.encrypt("hello")
    >>> plain = enc.decrypt(token)
    >>> assert plain == "hello"
    """

    def __init__(self, hex_key: Optional[str] = None) -> None:
        """
        Parameters
        ----------
        hex_key:
            64-character hex string representing a 32-byte AES key.
            Defaults to the ``AES_KEY`` environment variable.

        Raises
        ------
        ValueError
            If the key is missing or not the correct length.
        """
        raw_hex = hex_key or os.environ.get("AES_KEY", "")
        if not raw_hex:
            raise ValueError(
                "AES_KEY is not set.  "
                "Add a 64-char hex key to your .env file.  "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(raw_hex) != 64:
            raise ValueError(
                f"AES_KEY must be exactly 64 hex characters (32 bytes). "
                f"Got {len(raw_hex)} characters."
            )

        try:
            self._key: bytes = bytes.fromhex(raw_hex)
        except ValueError as exc:
            raise ValueError(f"AES_KEY contains non-hex characters: {exc}") from exc

        self._aesgcm = AESGCM(self._key)

    # ------------------------------------------------------------------
    # Encryption / decryption
    # ------------------------------------------------------------------

    def encrypt(self, data: str, associated_data: Optional[bytes] = None) -> bytes:
        """
        Encrypt *data* with AES-256-GCM.

        Parameters
        ----------
        data:
            Plain-text string to encrypt.
        associated_data:
            Optional authenticated-but-not-encrypted context (e.g. user_id).

        Returns
        -------
        bytes
            ``nonce (12 B) || ciphertext+tag`` encoded as base64.
        """
        nonce: bytes = os.urandom(_NONCE_BYTES)
        plaintext: bytes = data.encode("utf-8")
        ciphertext: bytes = self._aesgcm.encrypt(nonce, plaintext, associated_data)
        raw: bytes = nonce + ciphertext
        return base64.b64encode(raw)

    def decrypt(self, token: bytes, associated_data: Optional[bytes] = None) -> str:
        """
        Decrypt *token* produced by :meth:`encrypt`.

        Parameters
        ----------
        token:
            Base64-encoded ``nonce || ciphertext+tag``.
        associated_data:
            Must match the value used during encryption.

        Returns
        -------
        str
            The original plain-text string.

        Raises
        ------
        ValueError
            On decryption failure (wrong key, tampered ciphertext, etc.)
        """
        try:
            raw: bytes = base64.b64decode(token)
            nonce: bytes = raw[:_NONCE_BYTES]
            ciphertext: bytes = raw[_NONCE_BYTES:]
            plaintext: bytes = self._aesgcm.decrypt(nonce, ciphertext, associated_data)
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Decryption failed — data may be corrupt or tampered: {exc}") from exc

    # ------------------------------------------------------------------
    # HMAC helpers for log integrity (signs plain text, not encrypted)
    # ------------------------------------------------------------------

    def hmac_sign(self, message: str) -> str:
        """
        Return a hex HMAC-SHA256 signature for *message*.

        Parameters
        ----------
        message:
            Plain-text log line or payload string.

        Returns
        -------
        str
            Hex digest of the HMAC.
        """
        sig = hmac.new(self._key, message.encode("utf-8"), hashlib.sha256)
        return sig.hexdigest()

    def hmac_verify(self, message: str, signature: str) -> bool:
        """
        Verify that *signature* is a valid HMAC for *message*.

        Parameters
        ----------
        message:
            The original message string.
        signature:
            Hex HMAC to verify.

        Returns
        -------
        bool
            ``True`` if the signature is valid, ``False`` otherwise.
        """
        expected = self.hmac_sign(message)
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Convenience: encrypt / decrypt arbitrary bytes (e.g. screenshots)
    # ------------------------------------------------------------------

    def encrypt_bytes(self, data: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """Encrypt raw bytes and return base64-encoded ciphertext."""
        nonce: bytes = os.urandom(_NONCE_BYTES)
        ciphertext: bytes = self._aesgcm.encrypt(nonce, data, associated_data)
        return base64.b64encode(nonce + ciphertext)

    def decrypt_bytes(self, token: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """Decrypt bytes produced by :meth:`encrypt_bytes`."""
        try:
            raw: bytes = base64.b64decode(token)
            nonce: bytes = raw[:_NONCE_BYTES]
            ciphertext: bytes = raw[_NONCE_BYTES:]
            return self._aesgcm.decrypt(nonce, ciphertext, associated_data)
        except Exception as exc:
            raise ValueError(f"Byte decryption failed: {exc}") from exc
