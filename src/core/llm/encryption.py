"""
API Key 加密工具
使用 AES-256-GCM 对用户 API Key 进行加密存储
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import settings


def _get_aes_key() -> bytes:
    """读取 Java 对齐的 64 位 hex AES-256 key。"""
    secret = settings.API_KEY_ENCRYPTION_SECRET.strip()
    try:
        key = bytes.fromhex(secret)
    except ValueError as exc:
        raise ValueError("API_KEY_ENCRYPTION_SECRET must be a 64-character hex string") from exc
    if len(key) != 32:
        raise ValueError("API_KEY_ENCRYPTION_SECRET must decode to 32 bytes")
    return key


def encrypt_api_key(api_key: str) -> str:
    """加密 API Key

    Args:
        api_key: 明文 API Key

    Returns:
        Base64 编码的加密字符串 (IV + ciphertext)
    """
    aesgcm = AESGCM(_get_aes_key())
    iv = os.urandom(12)  # 96-bit IV for GCM
    ciphertext = aesgcm.encrypt(iv, api_key.encode(), None)
    # 拼接 IV + ciphertext
    encrypted = base64.b64encode(iv + ciphertext).decode()
    return encrypted


def decrypt_api_key(encrypted: str) -> str:
    """解密 API Key

    Args:
        encrypted: Base64 编码的加密字符串

    Returns:
        明文 API Key
    """
    aesgcm = AESGCM(_get_aes_key())
    data = base64.b64decode(encrypted.encode())
    iv = data[:12]
    ciphertext = data[12:]
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return plaintext.decode()


def mask_api_key(api_key: str) -> str:
    """掩码 API Key，只显示前4后4位

    Args:
        api_key: 原始 API Key

    Returns:
        掩码后的字符串，如 sk-****....****1234
    """
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****....****{api_key[-4:]}"
