from __future__ import annotations

from src.config import Settings


def test_should_enable_sparse_vector_by_default():
    settings = Settings(_env_file=None)

    assert settings.SPARSE_VECTOR_ENABLED is True


def test_should_normalize_chunking_semantic_unit():
    settings = Settings(_env_file=None, CHUNKING_SEMANTIC_UNIT=" Paragraph ")

    assert settings.CHUNKING_SEMANTIC_UNIT == "paragraph"


def test_should_reject_invalid_chunking_semantic_unit():
    try:
        Settings(_env_file=None, CHUNKING_SEMANTIC_UNIT="section")
    except ValueError as exc:
        assert "CHUNKING_SEMANTIC_UNIT must be 'sentence' or 'paragraph'" in str(exc)
    else:
        raise AssertionError("expected ValueError")
