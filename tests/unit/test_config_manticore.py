"""Manticore 运行时配置的 fail-fast 校验。"""

from __future__ import annotations

import pytest

from src.config import Settings


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"MANTICORE_POOL_MINSIZE": 3, "MANTICORE_POOL_MAXSIZE": 2}, "POOL_MINSIZE"),
        ({"MANTICORE_WRITE_BATCH_SIZE": 0}, "WRITE_BATCH_SIZE"),
        ({"MANTICORE_TIMEOUT_SECONDS": 0}, "timeout values"),
        (
            {"MANTICORE_MAX_DOCUMENT_BYTES": 200, "MANTICORE_WRITE_BATCH_BYTES": 100},
            "MAX_DOCUMENT_BYTES",
        ),
    ],
)
def test_manticore_rejects_unsafe_resource_limits(values: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, **values)


def test_manticore_rejects_unpaired_client_certificate() -> None:
    with pytest.raises(ValueError, match="must be configured together"):
        Settings(_env_file=None, MANTICORE_SSL_CERT="/tmp/client.pem")
