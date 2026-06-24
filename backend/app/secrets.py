from __future__ import annotations

import logging
import os

from .config import DATA_DIR, ensure_runtime_dirs

log = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet

    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover - depends on environment
    Fernet = None  # type: ignore[assignment]
    _HAS_CRYPTO = False


def _key_path():
    return DATA_DIR / "secret.key"


def _load_or_create_key() -> bytes:
    env_key = os.getenv("YOUDUB_SECRET_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")
    path = _key_path()
    if path.exists():
        return path.read_bytes()
    ensure_runtime_dirs()
    key = Fernet.generate_key()
    path.write_bytes(key)
    log.info("Generated new secret key at %s", path)
    return key


def _fernet() -> "Fernet":
    if not _HAS_CRYPTO:
        raise RuntimeError("cryptography package is not installed")
    return Fernet(_load_or_create_key())


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for at-rest storage. Falls back to plaintext if the
    cryptography package is unavailable (with a warning), so the app stays
    usable. Empty input stays empty."""
    if not plaintext:
        return ""
    if not _HAS_CRYPTO:
        log.warning("cryptography not installed; storing secret in plaintext")
        return plaintext
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret. If decryption fails (e.g. legacy plaintext
    value from before encryption was enabled, or a changed key), the original
    value is returned so existing data remains readable."""
    if not token:
        return ""
    if not _HAS_CRYPTO:
        return token
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:
        return token
