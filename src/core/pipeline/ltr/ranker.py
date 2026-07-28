"""版本化 LambdaMART 在线推理、契约校验与 weighted-score 降级。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.pipeline.ltr.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    ROUTES,
    build_online_features,
    feature_signature,
    weighted_baseline_order,
    weighted_fallback_order,
)
from src.core.pipeline.recall.models import RetrieverHit


@dataclass(frozen=True)
class LtrRankResult:
    ranked_chunk_ids: list[str]
    mode: str
    model_version: str
    elapsed_ms: float
    reason: str | None = None


@dataclass
class RankerMonitor:
    counters: Counter[str] = field(default_factory=Counter)
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=10_000))

    def record(self, mode: str, elapsed_ms: float) -> None:
        self.counters[mode] += 1
        self.latencies_ms.append(elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        values = sorted(self.latencies_ms)

        def percentile(q: float) -> float:
            if not values:
                return 0.0
            return values[min(len(values) - 1, math.ceil(len(values) * q) - 1)]

        return {
            "counters": dict(self.counters),
            "latency_p50_ms": percentile(0.50),
            "latency_p95_ms": percentile(0.95),
            "latency_p99_ms": percentile(0.99),
        }


class LambdaMartRanker:
    """进程内只读模型；推理放入 worker thread，超时或异常返回 weighted-score 顺序。"""

    def __init__(self, model_dir: str | Path) -> None:
        self.model_dir = Path(model_dir)
        self.manifest = _load_manifest(self.model_dir)
        self.short_fallback = _load_short_fallback(self.model_dir, self.manifest)
        self.model = _load_booster(self.model_dir, self.manifest)
        self.monitor = RankerMonitor()
        _validate_bundle(self.model_dir, self.manifest, self.model)

    async def rank(
        self,
        *,
        query: str,
        routes: dict[str, list[RetrieverHit]],
        candidate_contents: dict[str, str],
    ) -> LtrRankResult:
        started = time.perf_counter()
        fallback = weighted_baseline_order(routes)
        try:
            chunk_ids, ranked, fallback, confidence = await asyncio.wait_for(
                asyncio.to_thread(
                    self._predict,
                    query,
                    routes,
                    candidate_contents,
                ),
                timeout=self.timeout_ms / 1000,
            )
            if not chunk_ids:
                return LtrRankResult([], "fallback_empty", self.model_version, 0.0)
            compact_length = len("".join(query.split()))
            short_fallback = compact_length <= int(
                self.short_fallback["max_query_chars"]
            ) and confidence < float(self.short_fallback["confidence_threshold"])
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms > self.latency_budget_ms:
                ranked = fallback
                mode = "fallback_budget_exceeded"
            elif short_fallback:
                ranked = fallback
                mode = "hybrid_short_low_confidence"
            else:
                mode = "ltr"
            self.monitor.record(mode, elapsed_ms)
            return LtrRankResult(ranked, mode, self.model_version, elapsed_ms)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 本地模型失败必须降级，不能击穿问答流
            elapsed_ms = (time.perf_counter() - started) * 1000
            mode = "fallback_timeout" if isinstance(exc, asyncio.TimeoutError) else "fallback_error"
            self.monitor.record(mode, elapsed_ms)
            return LtrRankResult(
                fallback,
                mode,
                self.model_version,
                elapsed_ms,
                reason=type(exc).__name__,
            )

    def _predict(
        self,
        query: str,
        routes: dict[str, list[RetrieverHit]],
        candidate_contents: dict[str, str],
    ) -> tuple[list[str], list[str], list[str], float]:
        chunk_ids, features = build_online_features(
            query=query,
            routes=routes,
            candidate_contents=candidate_contents,
        )
        fallback = weighted_fallback_order(chunk_ids, features)
        if not chunk_ids:
            return chunk_ids, [], fallback, 1.0
        scores = self.model.predict(features, num_threads=1)
        return chunk_ids, _rank(chunk_ids, scores), fallback, _top12_margin(scores)

    @property
    def model_version(self) -> str:
        return str(self.manifest["model_version"])

    @property
    def timeout_ms(self) -> int:
        return int(self.manifest["timeout_ms"])

    @property
    def latency_budget_ms(self) -> int:
        return int(self.manifest["latency_budget_ms"])


def load_lambda_mart_ranker(model_dir: str | Path) -> LambdaMartRanker:
    """加载并运行 bundle 自测；任何契约不匹配均抛错，由装配层保持 baseline。"""
    return LambdaMartRanker(model_dir)


def _load_manifest(model_dir: Path) -> dict[str, Any]:
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("feature_version") != FEATURE_VERSION:
        raise ValueError("LambdaMART feature version mismatch")
    if manifest.get("feature_signature") != feature_signature():
        raise ValueError("LambdaMART feature signature mismatch")
    if manifest.get("feature_names") != FEATURE_NAMES:
        raise ValueError("LambdaMART feature order mismatch")
    if manifest.get("model_format") != "lightgbm_text_v1":
        raise ValueError("unsupported LambdaMART model format")
    if manifest.get("alias_enabled") is not False:
        raise ValueError("production LambdaMART bundle must keep Alias disabled")
    if int(manifest.get("timeout_ms") or 0) <= 0:
        raise ValueError("LambdaMART timeout must be positive")
    if int(manifest.get("latency_budget_ms") or 0) <= 0:
        raise ValueError("LambdaMART latency budget must be positive")
    expected_model_sha = str(manifest.get("model_file_sha256") or "")
    actual_model_sha = hashlib.sha256((model_dir / "model.txt").read_bytes()).hexdigest()
    if expected_model_sha != actual_model_sha:
        raise ValueError("LambdaMART model checksum mismatch")
    return manifest


def _load_short_fallback(model_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path = model_dir / "short_fallback.json"
    expected = str(manifest.get("short_fallback_sha256") or "")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("short fallback checksum mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != manifest.get("short_fallback_version"):
        raise ValueError("short fallback version mismatch")
    if payload.get("fallback") != "hybrid":
        raise ValueError("unsupported short-query fallback")
    return payload


def _load_booster(model_dir: Path, manifest: dict[str, Any]):
    import lightgbm
    from lightgbm import Booster

    if lightgbm.__version__ != manifest.get("lightgbm_version"):
        raise ValueError(
            "LightGBM runtime version mismatch: "
            f"expected={manifest.get('lightgbm_version')} actual={lightgbm.__version__}"
        )
    return Booster(model_file=str(model_dir / "model.txt"))


def _validate_bundle(model_dir: Path, manifest: dict[str, Any], model: Any) -> None:
    sums: dict[str, str] = {}
    for line in (model_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name.strip()] = digest
    for name, expected in sums.items():
        if hashlib.sha256((model_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"production bundle checksum mismatch: {name}")
    contract = json.loads((model_dir / "feature_contract.json").read_text(encoding="utf-8"))
    if contract.get("feature_signature") != manifest["feature_signature"]:
        raise ValueError("production feature contract signature mismatch")
    if contract.get("alias_enabled") is not False:
        raise ValueError("production feature contract enables Alias")
    vectors = json.loads((model_dir / "test_vectors.json").read_text(encoding="utf-8")).get(
        "vectors"
    )
    if not vectors:
        raise ValueError("production bundle test vectors are empty")
    for vector in vectors:
        payload = vector["input"]
        routes = {
            source: [
                RetrieverHit(source=source, **hit) for hit in payload["routes"].get(source, [])
            ]
            for source in ROUTES
        }
        chunk_ids, features = build_online_features(
            query=payload["query"],
            routes=routes,
            candidate_contents=payload["candidate_contents"],
        )
        expected = vector["expected"]
        if chunk_ids != expected["candidate_chunk_ids"]:
            raise ValueError(f"candidate order mismatch: {vector['id']}")
        if hashlib.sha256(features.tobytes()).hexdigest() != expected["feature_matrix_sha256"]:
            raise ValueError(f"feature vector mismatch: {vector['id']}")
        if (
            _rank(chunk_ids, model.predict(features, num_threads=1))
            != expected["ltr_ranked_chunk_ids"]
        ):
            raise ValueError(f"LambdaMART ranking mismatch: {vector['id']}")
        if (
            weighted_fallback_order(chunk_ids, features)
            != expected["weighted_score_ranked_chunk_ids"]
        ):
            raise ValueError(f"weighted fallback mismatch: {vector['id']}")


def _rank(chunk_ids: list[str], scores: Any) -> list[str]:
    return [
        item[0]
        for item in sorted(zip(chunk_ids, scores), key=lambda item: (-float(item[1]), item[0]))
    ]


def _top12_margin(scores: Any) -> float:
    ordered = sorted((float(value) for value in scores), reverse=True)
    if len(ordered) < 2:
        return 1.0
    scale = max(abs(ordered[0]), abs(ordered[1]), 1e-9)
    return max(0.0, ordered[0] - ordered[1]) / scale
