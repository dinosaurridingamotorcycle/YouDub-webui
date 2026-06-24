from __future__ import annotations

import os

import pytest

from backend.app import secrets


@pytest.fixture
def key_env(monkeypatch, tmp_path):
    """Force the secrets module to use a throwaway key file under tmp_path."""
    monkeypatch.setattr(secrets, "_key_path", lambda: tmp_path / "secret.key")
    monkeypatch.delenv("YOUDUB_SECRET_KEY", raising=False)
    # Clear any cached state by re-importing fresh module behavior.
    return tmp_path


def test_encrypt_decrypt_roundtrip(key_env):
    plaintext = "sk-test-1234567890"
    token = secrets.encrypt_secret(plaintext)
    assert token != plaintext  # actually encrypted
    assert secrets.decrypt_secret(token) == plaintext


def test_encrypt_empty_stays_empty(key_env):
    assert secrets.encrypt_secret("") == ""
    assert secrets.decrypt_secret("") == ""


def test_decrypt_legacy_plaintext_is_returned_as_is(key_env):
    # Values stored before encryption was enabled (plain text) must remain
    # readable instead of being dropped.
    assert secrets.decrypt_secret("sk-legacy-plaintext") == "sk-legacy-plaintext"


def test_decrypt_with_wrong_key_falls_back_to_plaintext(monkeypatch, tmp_path):
    # Encrypt with one key...
    monkeypatch.setattr(secrets, "_key_path", lambda: tmp_path / "k1.key")
    monkeypatch.delenv("YOUDUB_SECRET_KEY", raising=False)
    token = secrets.encrypt_secret("sk-secret")

    # ...then switch to a different key. Decryption must not crash; it falls
    # back to returning the stored token verbatim (fail-safe, not silent loss).
    monkeypatch.setattr(secrets, "_key_path", lambda: tmp_path / "k2.key")
    assert secrets.decrypt_secret(token) == token


def test_env_key_takes_precedence(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("YOUDUB_SECRET_KEY", env_key)
    monkeypatch.setattr(secrets, "_key_path", lambda: tmp_path / "unused.key")
    token = secrets.encrypt_secret("sk-test")
    assert secrets.decrypt_secret(token) == "sk-test"
    # Env-key path must not touch the file system.
    assert not (tmp_path / "unused.key").exists()


def test_no_crypto_falls_back_to_plaintext(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets, "_key_path", lambda: tmp_path / "secret.key")
    monkeypatch.delenv("YOUDUB_SECRET_KEY", raising=False)
    monkeypatch.setattr(secrets, "_HAS_CRYPTO", False)

    assert secrets.encrypt_secret("sk-plain") == "sk-plain"
    assert secrets.decrypt_secret("sk-plain") == "sk-plain"
