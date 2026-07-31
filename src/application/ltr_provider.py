"""LambdaMART 模型单例装配；加载失败时由调用方保持 weighted-score 基线。"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path

from loguru import logger

from src.config import PROJECT_ROOT, settings
from src.core.pipeline.ltr import LambdaMartRanker, load_lambda_mart_ranker
from src.observability.logging import safe_exception_stack, truncate_log_value

_loaded_ranker: LambdaMartRanker | None = None
_last_load_error: str | None = None
_preload_completed = False


@lru_cache(maxsize=1)
def get_ltr_ranker() -> LambdaMartRanker | None:
    """加载并缓存模型；仅供构建校验与应用启动预加载调用。"""
    global _last_load_error, _loaded_ranker
    if settings.RECALL_LTR_MODE in {"off", "baseline"}:
        return None
    try:
        model_dir = Path(settings.RECALL_LTR_MODEL_DIR)
        if not model_dir.is_absolute():
            model_dir = Path(PROJECT_ROOT) / model_dir
        ranker = load_lambda_mart_ranker(model_dir)
    except Exception as exc:  # 启动校验失败不击穿服务，active 由 runtime 回退 baseline
        _loaded_ranker = None
        _last_load_error = type(exc).__name__
        logger.bind(
            event="recall_ltr_startup_fallback",
            outcome="degraded",
            mode=settings.RECALL_LTR_MODE,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).error("[recall] LambdaMART bundle unavailable; weighted-score fallback active")
        return None
    _loaded_ranker = ranker
    _last_load_error = None
    logger.bind(
        event="recall_ltr_model_loaded",
        outcome="succeeded",
        mode=settings.RECALL_LTR_MODE,
        model_version=ranker.model_version,
        feature_version=ranker.manifest["feature_version"],
        feature_signature=ranker.manifest["feature_signature"],
        candidate_contract_version=ranker.serving_contract["candidate_contract"]["version"],
        candidate_contract_signature=ranker.serving_contract["candidate_contract_signature"],
    ).info("[recall] LambdaMART model loaded")
    return ranker


async def preload_ltr_ranker() -> LambdaMartRanker | None:
    """在 FastAPI startup 阶段通过 worker thread 完成模型加载与全部契约自测。"""
    global _preload_completed
    try:
        return await asyncio.to_thread(get_ltr_ranker)
    finally:
        _preload_completed = True


def get_initialized_ltr_ranker() -> LambdaMartRanker | None:
    """请求期只读 startup 结果，绝不触发文件读取、LightGBM 导入或模型构造。"""
    if settings.RECALL_LTR_MODE in {"off", "baseline"}:
        return None
    return _loaded_ranker


def get_ltr_runtime_status() -> dict:
    """返回无外部调用的进程内 LTR 状态，供健康检查和监控采集。"""
    ranker = _loaded_ranker
    mode = settings.RECALL_LTR_MODE
    if mode == "active":
        serving_strategy = "lambdamart" if ranker is not None else "weighted_score"
    elif mode == "baseline":
        serving_strategy = "weighted_score"
    else:
        serving_strategy = "legacy_rerank"
    return {
        "configured_mode": mode,
        "serving_strategy": serving_strategy,
        "preload_completed": _preload_completed,
        "loaded": ranker is not None,
        "model_version": ranker.model_version if ranker is not None else None,
        "candidate_contract_version": (
            ranker.serving_contract["candidate_contract"]["version"] if ranker is not None else None
        ),
        "last_load_error": _last_load_error,
        "monitor": (
            ranker.runtime_snapshot()
            if ranker is not None and hasattr(ranker, "runtime_snapshot")
            else ranker.monitor.snapshot() if ranker is not None else None
        ),
    }


def shutdown_ltr_ranker() -> None:
    """关闭专用推理 executor；进程退出后不再接受新的本地排序任务。"""
    global _loaded_ranker
    if _loaded_ranker is not None:
        _loaded_ranker.close()
        _loaded_ranker = None
    get_ltr_ranker.cache_clear()
