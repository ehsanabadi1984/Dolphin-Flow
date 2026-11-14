from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet():
    key = getattr(settings, "SMS_CREDENTIALS_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured(
            "SMS_CREDENTIALS_ENCRYPTION_KEY must be configured."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured(
            "SMS_CREDENTIALS_ENCRYPTION_KEY is invalid."
        ) from exc


def encrypt_credentials(credentials):
    import json

    payload = json.dumps(
        credentials, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_credentials(ciphertext):
    import json

    try:
        payload = _fernet().decrypt(ciphertext.encode("ascii"))
        result = json.loads(payload.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, UnicodeError) as exc:
        raise ImproperlyConfigured(
            "SMS provider credentials could not be decrypted."
        ) from exc

    if not isinstance(result, dict):
        raise ImproperlyConfigured("Decrypted SMS credentials are invalid.")
    return result
