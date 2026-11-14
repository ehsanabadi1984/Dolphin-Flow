"""Encryption helpers for SMS provider credentials.

The encryption key is intentionally independent from Django SECRET_KEY.
A missing or invalid key fails closed; credentials are never stored in plaintext.
"""
import json
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SMSCredentialEncryptionError(Exception):
    """Raised when SMS credentials cannot safely be encrypted or decrypted."""


def _fernet():
    key = getattr(settings, "SMS_CREDENTIALS_ENCRYPTION_KEY", "")
    if not isinstance(key, str) or not key.strip():
        raise ImproperlyConfigured(
            "SMS_CREDENTIALS_ENCRYPTION_KEY must be configured independently "
            "from Django SECRET_KEY."
        )
    try:
        return Fernet(key.strip().encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured(
            "SMS_CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_sms_credentials(credentials):
    """Encrypt a mapping of provider credentials into an opaque Fernet token."""
    if not isinstance(credentials, Mapping):
        raise TypeError("SMS provider credentials must be a mapping.")
    try:
        payload = json.dumps(
            dict(credentials),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SMSCredentialEncryptionError(
            "SMS provider credentials must contain JSON-serializable values."
        ) from exc
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_sms_credentials(ciphertext):
    """Decrypt a Fernet token and return its JSON object without logging secrets."""
    if not isinstance(ciphertext, str) or not ciphertext.strip():
        raise SMSCredentialEncryptionError("Encrypted SMS credentials are empty.")
    try:
        payload = _fernet().decrypt(ciphertext.encode("ascii"))
        credentials = json.loads(payload.decode("utf-8"))
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError, ValueError) as exc:
        raise SMSCredentialEncryptionError(
            "SMS credentials could not be decrypted with the configured key."
        ) from exc
    if not isinstance(credentials, dict):
        raise SMSCredentialEncryptionError(
            "Decrypted SMS credentials must be a JSON object."
        )
    return credentials
