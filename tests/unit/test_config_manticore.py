"""Manticore 运行时配置的 fail-fast 校验。"""

from __future__ import annotations

import pytest

from src.config import Settings


@pytest.mark.parametrize("backend", ["qdrant", "manticore", " MANTICORE "])
def test_bm25_backend_accepts_only_registered_values(backend: str) -> None:
    configured = Settings(_env_file=None, BM25_BACKEND=backend)

    assert configured.BM25_BACKEND == backend.strip().lower()


def test_bm25_backend_rejects_typo() -> None:
    with pytest.raises(ValueError, match="BM25_BACKEND must be one of"):
        Settings(_env_file=None, BM25_BACKEND="mantcore")


def test_bm25_backend_rejects_removed_elasticsearch_backend() -> None:
    with pytest.raises(ValueError, match="BM25_BACKEND must be one of"):
        Settings(_env_file=None, BM25_BACKEND="es")


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


def test_migration_config_accepts_dual_write_and_shadow_read() -> None:
    configured = Settings(
        _env_file=None,
        BM25_BACKEND="qdrant",
        BM25_WRITE_BACKENDS="qdrant, manticore, qdrant",
        BM25_SHADOW_BACKEND="manticore",
        BM25_SHADOW_SAMPLE_RATE=0.05,
    )

    assert configured.BM25_WRITE_BACKENDS == "qdrant,manticore"
    assert configured.BM25_SHADOW_BACKEND == "manticore"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"BM25_BACKEND": "qdrant", "BM25_WRITE_BACKENDS": "manticore"},
            "BM25_BACKEND must be included",
        ),
        (
            {"BM25_BACKEND": "qdrant", "BM25_SHADOW_BACKEND": "qdrant"},
            "must differ",
        ),
        (
            {
                "BM25_BACKEND": "qdrant",
                "BM25_WRITE_BACKENDS": "qdrant",
                "BM25_SHADOW_BACKEND": "manticore",
            },
            "SHADOW_BACKEND must be included",
        ),
        ({"BM25_SHADOW_SAMPLE_RATE": 1.1}, "between 0 and 1"),
        ({"MANTICORE_SSL_CERT": "/tmp/client.pem"}, "must be configured together"),
    ],
)
def test_migration_config_rejects_unsafe_cutover(values: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, **values)
