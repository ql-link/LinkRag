import asyncio
import threading
import time
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT
from src.core.pipeline.ltr import load_lambda_mart_ranker

MODEL_DIR = Path(PROJECT_ROOT) / "models" / "ltr" / "candidate-difference-v3-20260728-final33"


def test_versioned_bundle_loads_and_passes_contract_vectors():
    ranker = load_lambda_mart_ranker(MODEL_DIR)

    assert ranker.model_version == "candidate-difference-v3-20260728-final33"
    assert ranker.manifest["alias_enabled"] is False
    assert ranker.manifest["feature_version"] == "candidate_difference_v3"
    assert (
        ranker.serving_contract["candidate_contract"]["version"] == "blind_v5_candidate_routing_v1"
    )


def test_tampered_manifest_is_rejected(tmp_path):
    target = tmp_path / "model"
    target.mkdir()
    for source in MODEL_DIR.iterdir():
        (target / source.name).write_bytes(source.read_bytes())
    manifest = target / "manifest.json"
    manifest.write_text(manifest.read_text().replace("candidate_difference_v3", "bad", 1))

    with pytest.raises(ValueError, match="feature version mismatch"):
        load_lambda_mart_ranker(target)


def test_tampered_candidate_serving_contract_is_rejected(tmp_path):
    target = tmp_path / "model"
    target.mkdir()
    for source in MODEL_DIR.iterdir():
        (target / source.name).write_bytes(source.read_bytes())
    contract = target / "serving_contract.json"
    contract.write_text(contract.read_text().replace('"output_top_n": 10', '"output_top_n": 8'))

    with pytest.raises(ValueError, match="candidate serving contract mismatch"):
        load_lambda_mart_ranker(target)


@pytest.mark.asyncio
async def test_inference_timeout_keeps_executor_queue_bounded(monkeypatch):
    ranker = load_lambda_mart_ranker(MODEL_DIR)
    release = threading.Event()
    started = 0
    lock = threading.Lock()

    def blocked_predict(*args):
        nonlocal started
        with lock:
            started += 1
        release.wait(timeout=2)
        return [], [], [], 1.0

    monkeypatch.setattr(ranker, "_predict", blocked_predict)
    monkeypatch.setitem(ranker.manifest, "timeout_ms", 20)
    try:
        results = await asyncio.gather(
            *[ranker.rank(query="q", routes={}, candidate_contents={}) for _ in range(20)]
        )

        assert all(result.mode == "fallback_timeout" for result in results)
        assert started <= ranker.runtime_snapshot()["inference_capacity"]
        assert ranker.runtime_snapshot()["inference_running"] == started
    finally:
        release.set()
        await asyncio.sleep(0.05)
        ranker.close()


@pytest.mark.asyncio
async def test_inference_within_timeout_but_over_latency_budget_uses_fallback(monkeypatch):
    """TIM-002: a completed prediction may still violate the serving latency budget."""

    ranker = load_lambda_mart_ranker(MODEL_DIR)
    monkeypatch.setitem(ranker.manifest, "timeout_ms", 200)
    monkeypatch.setitem(ranker.manifest, "latency_budget_ms", 1)

    def slow_predict(*args):
        time.sleep(0.02)
        return ["dense", "bm25"], ["bm25", "dense"], ["dense", "bm25"], 1.0

    monkeypatch.setattr(ranker, "_predict", slow_predict)
    try:
        result = await ranker.rank(query="q", routes={}, candidate_contents={})
        assert result.mode == "fallback_budget_exceeded"
        assert result.ranked_chunk_ids == ["dense", "bm25"]
        assert result.elapsed_ms >= 1
    finally:
        ranker.close()


@pytest.mark.asyncio
async def test_burst_inference_does_not_block_event_loop(monkeypatch):
    """TIM-007: bounded worker inference must leave the asyncio loop responsive."""

    ranker = load_lambda_mart_ranker(MODEL_DIR)
    monkeypatch.setitem(ranker.manifest, "timeout_ms", 500)
    monkeypatch.setitem(ranker.manifest, "latency_budget_ms", 500)

    def slow_predict(*args):
        time.sleep(0.05)
        return [], [], [], 1.0

    monkeypatch.setattr(ranker, "_predict", slow_predict)
    heartbeat_ticks = 0

    async def heartbeat():
        nonlocal heartbeat_ticks
        deadline = asyncio.get_running_loop().time() + 0.04
        while asyncio.get_running_loop().time() < deadline:
            heartbeat_ticks += 1
            await asyncio.sleep(0.001)

    try:
        results, _ = await asyncio.gather(
            asyncio.gather(
                *[ranker.rank(query="q", routes={}, candidate_contents={}) for _ in range(8)]
            ),
            heartbeat(),
        )

        assert len(results) == 8
        assert heartbeat_ticks >= 10
        assert ranker.runtime_snapshot()["inference_capacity"] == 4
    finally:
        ranker.close()
