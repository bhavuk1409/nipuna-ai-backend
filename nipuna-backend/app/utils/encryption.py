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
