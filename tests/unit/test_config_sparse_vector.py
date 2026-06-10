from __future__ import annotations

from src.config import Settings


def test_should_enable_sparse_vector_by_default():
    settings = Settings(_env_file=None)

    assert settings.SPARSE_VECTOR_ENABLED is True


def test_should_normalize_chunking_stage_algorithm_names():
    settings = Settings(
        _env_file=None,
        CHUNKING_STAGE_ONE_ALGORITHM=" Candidate_Boundary ",
        CHUNKING_STAGE_TWO_ALGORITHM=" Noop ",
    )

    assert settings.CHUNKING_STAGE_ONE_ALGORITHM == "candidate_boundary"
    assert settings.CHUNKING_STAGE_TWO_ALGORITHM == "noop"
    assert not hasattr(settings, "CHUNKING_ENABLE_ADVANCED_PIPELINE")


def test_should_reject_invalid_chunking_stage_algorithm_names():
    try:
        Settings(_env_file=None, CHUNKING_STAGE_ONE_ALGORITHM="unknown")
    except ValueError as exc:
        assert "CHUNKING_STAGE_ONE_ALGORITHM must be 'candidate_boundary'" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    try:
        Settings(_env_file=None, CHUNKING_STAGE_TWO_ALGORITHM="unknown")
    except ValueError as exc:
        assert (
            "CHUNKING_STAGE_TWO_ALGORITHM must be one of the registered " "Stage 2 algorithms: noop"
        ) in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_should_allow_chunking_overlap_token_bounds():
    disabled = Settings(_env_file=None, CHUNKING_OVERLAP_TOKENS=0)
    upper_bound = Settings(_env_file=None, CHUNKING_OVERLAP_TOKENS=64)

    assert disabled.CHUNKING_OVERLAP_TOKENS == 0
    assert upper_bound.CHUNKING_OVERLAP_TOKENS == 64


def test_should_reject_invalid_chunking_overlap_tokens():
    for value in (-1, 65):
        try:
            Settings(_env_file=None, CHUNKING_OVERLAP_TOKENS=value)
        except ValueError as exc:
            assert "CHUNKING_OVERLAP_TOKENS must be between 0 and 64" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_should_allow_min_candidate_chunk_token_bounds():
    lower_bound = Settings(_env_file=None, CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS=128)
    upper_bound = Settings(_env_file=None, CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS=256)

    assert lower_bound.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS == 128
    assert upper_bound.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS == 256


def test_should_reject_invalid_min_candidate_chunk_tokens():
    for value in (127, 257):
        try:
            Settings(_env_file=None, CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS=value)
        except ValueError as exc:
            assert "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS must be between 128 and 256" in str(exc)
        else:
            raise AssertionError("expected ValueError")
