from __future__ import annotations

import math

import pytest

from src.config import SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS, Settings
from src.core.dataset_config.models import ChunkingConfig


def test_should_enable_sparse_vector_by_default():
    settings = Settings(_env_file=None)

    assert settings.SPARSE_VECTOR_ENABLED is True


def test_recall_fusion_defaults():
    settings = Settings(_env_file=None)

    assert settings.RECALL_FUSION_BM25_WEIGHT == 0.2
    assert settings.RECALL_FUSION_SPARSE_WEIGHT == 0.3
    assert settings.RECALL_FUSION_DENSE_WEIGHT == 0.5


def test_recall_fusion_weights_allow_zero():
    settings = Settings(
        _env_file=None,
        RECALL_FUSION_BM25_WEIGHT=0.0,
        RECALL_FUSION_SPARSE_WEIGHT=0.0,
        RECALL_FUSION_DENSE_WEIGHT=1.0,
    )

    assert settings.RECALL_FUSION_BM25_WEIGHT == 0.0
    assert settings.RECALL_FUSION_SPARSE_WEIGHT == 0.0
    assert settings.RECALL_FUSION_DENSE_WEIGHT == 1.0


def test_recall_ltr_mode_and_shadow_rate_are_validated():
    settings = Settings(
        _env_file=None,
        RECALL_LTR_MODE=" Shadow ",
        RECALL_LTR_SHADOW_SAMPLE_RATE=0.25,
    )

    assert settings.RECALL_LTR_MODE == "shadow"
    assert settings.RECALL_LTR_SHADOW_SAMPLE_RATE == 0.25


def test_recall_ltr_is_active_by_default():
    assert Settings.model_fields["RECALL_LTR_MODE"].default == "active"


def test_recall_ltr_rejects_invalid_rollout_config():
    with pytest.raises(ValueError, match="RECALL_LTR_MODE"):
        Settings(_env_file=None, RECALL_LTR_MODE="canary")
    with pytest.raises(ValueError, match="RECALL_LTR_SHADOW_SAMPLE_RATE"):
        Settings(_env_file=None, RECALL_LTR_SHADOW_SAMPLE_RATE=1.1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("RECALL_FUSION_BM25_WEIGHT", -0.1),
        ("RECALL_FUSION_SPARSE_WEIGHT", math.nan),
        ("RECALL_FUSION_DENSE_WEIGHT", math.inf),
    ],
)
def test_recall_fusion_rejects_invalid_weights(field: str, value: float):
    with pytest.raises(ValueError, match=field):
        Settings(_env_file=None, **{field: value})


def test_should_normalize_chunking_stage_algorithm_names():
    settings = Settings(
        _env_file=None,
        CHUNKING_STAGE_ONE_ALGORITHM=" Candidate_Boundary ",
        CHUNKING_STAGE_TWO_ALGORITHM=" Noop ",
    )

    assert settings.CHUNKING_STAGE_ONE_ALGORITHM == "candidate_boundary"
    assert settings.CHUNKING_STAGE_TWO_ALGORITHM == "noop"


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
            "CHUNKING_STAGE_TWO_ALGORITHM must be one of the registered Stage 2 algorithms"
        ) in str(exc)
        assert "semantic_depth_window" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_should_register_semantic_depth_stage_two_but_keep_noop_default():
    settings = Settings(_env_file=None)

    assert settings.CHUNKING_STAGE_TWO_ALGORITHM == "noop"
    assert "semantic_depth_window" in SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS
    assert (
        Settings(
            _env_file=None, CHUNKING_STAGE_TWO_ALGORITHM=" semantic_depth_window "
        ).CHUNKING_STAGE_TWO_ALGORITHM
        == "semantic_depth_window"
    )


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


def test_should_default_heading_llm_token_limits_for_default_chat_model():
    settings = Settings(_env_file=None)

    assert settings.MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET == 65536
    assert settings.MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS == 4096


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET", 2048),
        ("MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET", 262144),
        ("MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS", 512),
        ("MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS", 65536),
    ],
)
def test_should_allow_heading_llm_token_bounds(field: str, value: int):
    settings = Settings(_env_file=None, **{field: value})

    assert getattr(settings, field) == value


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET",
            2047,
            "between 2048 and 262144",
        ),
        (
            "MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET",
            262145,
            "between 2048 and 262144",
        ),
        (
            "MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS",
            511,
            "between 512 and 65536",
        ),
        (
            "MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS",
            65537,
            "between 512 and 65536",
        ),
    ],
)
def test_should_reject_invalid_heading_llm_token_bounds(
    field: str,
    value: int,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("CHUNKING_MAX_CHUNK_TOKENS", 256),
        ("CHUNKING_MAX_CHUNK_TOKENS", 512),
        ("CHUNKING_MAX_CHUNK_TOKENS", 2048),
        ("CHUNKING_HARD_MAX_TOKENS", 512),
        ("CHUNKING_HARD_MAX_TOKENS", 1024),
        ("CHUNKING_HARD_MAX_TOKENS", 8192),
    ],
)
def test_should_allow_chunking_stage_two_token_bounds(field: str, value: int):
    values = {
        "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS": 256,
        "CHUNKING_MAX_CHUNK_TOKENS": 512,
        "CHUNKING_HARD_MAX_TOKENS": 1024,
        field: value,
    }
    if field == "CHUNKING_MAX_CHUNK_TOKENS":
        values["CHUNKING_HARD_MAX_TOKENS"] = max(1024, value)
    settings = Settings(_env_file=None, **values)

    assert getattr(settings, field) == value


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("CHUNKING_MAX_CHUNK_TOKENS", 255, "between 256 and 2048"),
        ("CHUNKING_MAX_CHUNK_TOKENS", 2049, "between 256 and 2048"),
        ("CHUNKING_HARD_MAX_TOKENS", 511, "between 512 and 8192"),
        ("CHUNKING_HARD_MAX_TOKENS", 8193, "between 512 and 8192"),
    ],
)
def test_should_reject_invalid_chunking_stage_two_token_bounds(
    field: str,
    value: int,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, **{field: value})


def test_should_reject_cross_field_chunking_token_bounds():
    with pytest.raises(ValueError, match="CHUNKING_MAX_CHUNK_TOKENS must be >="):
        Settings(
            _env_file=None,
            CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS=256,
            CHUNKING_MAX_CHUNK_TOKENS=255,
        )

    with pytest.raises(ValueError, match="CHUNKING_HARD_MAX_TOKENS must be >="):
        Settings(
            _env_file=None,
            CHUNKING_MAX_CHUNK_TOKENS=1024,
            CHUNKING_HARD_MAX_TOKENS=512,
        )


def test_should_parse_env_string_chunking_token_bounds_and_prioritize_cross_field_errors():
    settings = Settings(
        _env_file=None,
        CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS="256",
        CHUNKING_MAX_CHUNK_TOKENS="512",
        CHUNKING_HARD_MAX_TOKENS="1024",
    )

    assert settings.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS == 256
    assert settings.CHUNKING_MAX_CHUNK_TOKENS == 512
    assert settings.CHUNKING_HARD_MAX_TOKENS == 1024

    with pytest.raises(ValueError, match="CHUNKING_MAX_CHUNK_TOKENS must be >="):
        Settings(
            _env_file=None,
            CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS="256",
            CHUNKING_MAX_CHUNK_TOKENS="255",
        )


def test_chunking_config_should_validate_stage_two_token_bounds():
    config = ChunkingConfig(
        min_candidate_chunk_tokens=256,
        max_chunk_tokens=512,
        hard_max_tokens=1024,
    )

    assert config.max_chunk_tokens == 512
    assert config.hard_max_tokens == 1024

    with pytest.raises(ValueError, match="hard_max_tokens must be >= max_chunk_tokens"):
        ChunkingConfig(max_chunk_tokens=1024, hard_max_tokens=512)
