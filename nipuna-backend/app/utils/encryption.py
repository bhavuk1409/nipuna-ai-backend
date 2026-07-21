import base64

from cryptography.fernet import Fernet

from app.config import get_settings


def _get_fernet() -> Fernet:
    settings = get_settings()
    key_hex = settings.encryption_key
    if not key_hex or len(key_hex) != 64:
        raise RuntimeError(
            "ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes)"
        )
    key_bytes = bytes.fromhex(key_hex)
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt(plaintext: str) -> str:
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    f = _get_fernet()
    return f.decrypt(token.encode()).decode()


def encrypt_bytes(plaintext: str) -> bytes:
    """Return the Fernet token as raw bytes — for storage in
    ``LargeBinary`` columns (e.g. ``user_memories.value_encrypted``,
    ``messages.content_encrypted``). The on-disk form is the
    url-safe base64 string but stored as bytes so a database dump
    doesn't render it as readable text.
    """
    return encrypt(plaintext).encode("utf-8")


def decrypt_bytes(token: bytes) -> str:
    """Inverse of :func:`encrypt_bytes` — accepts the ``LargeBinary``
    bytes form, returns the plaintext.
    """
    if isinstance(token, (bytes, bytearray)):
        token = token.decode("utf-8", errors="replace")
    return decrypt(token)
