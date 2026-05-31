from __future__ import annotations

from src.config import Settings


def test_should_enable_sparse_vector_by_default():
    settings = Settings(_env_file=None)

    assert settings.SPARSE_VECTOR_ENABLED is True


def test_should_not_expose_sparse_vector_use_fp16_config():
    settings = Settings(_env_file=None)

    assert not hasattr(settings, "SPARSE_VECTOR_USE_FP16")
