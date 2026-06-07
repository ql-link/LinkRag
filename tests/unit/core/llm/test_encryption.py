import pytest

from src.config import settings
from src.core.llm.encryption import decrypt_api_key, encrypt_api_key


def test_encrypt_decrypt_api_key_with_java_compatible_hex_secret(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_SECRET", "01" * 32)

    encrypted = encrypt_api_key("sk-test-value")

    assert encrypted != "sk-test-value"
    assert decrypt_api_key(encrypted) == "sk-test-value"


def test_encryption_secret_must_be_64_hex_chars(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_SECRET", "default-secret")

    with pytest.raises(ValueError, match="64-character hex"):
        encrypt_api_key("sk-test-value")
