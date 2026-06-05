from __future__ import annotations

from src.config import Settings


def test_should_enable_sparse_vector_by_default():
    settings = Settings(_env_file=None)

    assert settings.SPARSE_VECTOR_ENABLED is True
