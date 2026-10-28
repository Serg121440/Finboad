"""Encryption of marketplace API keys at rest (Fernet, key derived from APP_SECRET)."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from core import config


class SecretMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not config.APP_SECRET:
        raise SecretMissing("APP_SECRET не задан: без него ключи кабинетов нельзя сохранить")
    key = base64.urlsafe_b64encode(hashlib.sha256(config.APP_SECRET.encode()).digest())
    return Fernet(key)


def encrypt(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise SecretMissing("Ключи зашифрованы другим APP_SECRET") from e


def mask(value: str) -> str:
    """Show only the tail of a secret in the UI."""
    value = value or ""
    return "•" * 6 + value[-4:] if len(value) > 4 else "•" * len(value)
