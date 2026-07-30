import asyncio
import threading
from types import SimpleNamespace

import pytest

from src.application import ltr_provider


def test_ltr_runtime_status_exposes_loaded_model_and_monitor(monkeypatch):
    ranker = SimpleNamespace(
        model_version="model-v1",
        serving_contract={"candidate_contract": {"version": "contract-v1"}},
        monitor=SimpleNamespace(snapshot=lambda: {"counters": {"ltr": 2}}),
    )
    monkeypatch.setattr(ltr_provider, "_loaded_ranker", ranker)
    monkeypatch.setattr(ltr_provider, "_last_load_error", None)
    monkeypatch.setattr(ltr_provider, "_preload_completed", True)
    monkeypatch.setattr(ltr_provider.settings, "RECALL_LTR_MODE", "active")

    assert ltr_provider.get_ltr_runtime_status() == {
        "configured_mode": "active",
        "serving_strategy": "lambdamart",
        "preload_completed": True,
        "loaded": True,
        "model_version": "model-v1",
        "candidate_contract_version": "contract-v1",
        "last_load_error": None,
        "monitor": {"counters": {"ltr": 2}},
    }


def test_ltr_runtime_status_keeps_load_error_without_triggering_load(monkeypatch):
    monkeypatch.setattr(ltr_provider, "_loaded_ranker", None)
    monkeypatch.setattr(ltr_provider, "_last_load_error", "ValueError")
    monkeypatch.setattr(ltr_provider, "_preload_completed", True)
    monkeypatch.setattr(ltr_provider.settings, "RECALL_LTR_MODE", "active")

    status = ltr_provider.get_ltr_runtime_status()

    assert status["loaded"] is False
    assert status["serving_strategy"] == "weighted_score"
    assert status["last_load_error"] == "ValueError"
    assert status["monitor"] is None


@pytest.mark.asyncio
async def test_preload_runs_loader_in_worker_and_request_path_only_reads_result(monkeypatch):
    ranker = SimpleNamespace(model_version="model-v1")
    loader_thread_ids: list[int] = []

    def _load():
        loader_thread_ids.append(threading.get_ident())
        monkeypatch.setattr(ltr_provider, "_loaded_ranker", ranker)
        return ranker

    monkeypatch.setattr(ltr_provider, "get_ltr_ranker", _load)
    monkeypatch.setattr(ltr_provider, "_loaded_ranker", None)
    monkeypatch.setattr(ltr_provider, "_preload_completed", False)
    monkeypatch.setattr(ltr_provider.settings, "RECALL_LTR_MODE", "active")

    loaded = await ltr_provider.preload_ltr_ranker()

    assert loaded is ranker
    assert loader_thread_ids and loader_thread_ids[0] != threading.get_ident()
    assert ltr_provider.get_initialized_ltr_ranker() is ranker
    assert ltr_provider._preload_completed is True


def test_request_path_never_calls_loader_when_preload_failed(monkeypatch):
    monkeypatch.setattr(ltr_provider, "_loaded_ranker", None)
    monkeypatch.setattr(ltr_provider.settings, "RECALL_LTR_MODE", "active")
    monkeypatch.setattr(
        ltr_provider,
        "get_ltr_ranker",
        lambda: (_ for _ in ()).throw(AssertionError("request path must not load model")),
    )

    assert ltr_provider.get_initialized_ltr_ranker() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "baseline"])
async def test_off_and_baseline_preload_never_load_bundle(monkeypatch, mode):
    """STA-003 / MOD-001 / MOD-007: no Booster construction in rollback modes."""

    def _unexpected_loader(*args, **kwargs):
        raise AssertionError("off/baseline must not load the LambdaMART bundle")

    ltr_provider.get_ltr_ranker.cache_clear()
    monkeypatch.setattr(ltr_provider, "_loaded_ranker", None)
    monkeypatch.setattr(ltr_provider, "_preload_completed", False)
    monkeypatch.setattr(ltr_provider.settings, "RECALL_LTR_MODE", mode)
    monkeypatch.setattr(ltr_provider, "load_lambda_mart_ranker", _unexpected_loader)

    assert await ltr_provider.preload_ltr_ranker() is None
    assert ltr_provider._preload_completed is True
    assert ltr_provider.get_initialized_ltr_ranker() is None


@pytest.mark.asyncio
async def test_concurrent_request_reads_do_not_trigger_duplicate_initialization(monkeypatch):
    """STA-004 / STA-006: concurrent first requests only read startup state."""

    ranker = SimpleNamespace(model_version="model-v1")
    loader_calls = 0

    def _unexpected_loader():
        nonlocal loader_calls
        loader_calls += 1
        raise AssertionError("request path must not initialize the model")

    monkeypatch.setattr(ltr_provider, "_loaded_ranker", ranker)
    monkeypatch.setattr(ltr_provider.settings, "RECALL_LTR_MODE", "active")
    monkeypatch.setattr(ltr_provider, "get_ltr_ranker", _unexpected_loader)

    results = await asyncio.gather(
        *[asyncio.to_thread(ltr_provider.get_initialized_ltr_ranker) for _ in range(32)]
    )

    assert results == [ranker] * 32
    assert loader_calls == 0
