"""LambdaMART 模型单例装配；加载失败时由调用方保持 weighted-score 基线。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from loguru import logger

from src.config import PROJECT_ROOT, settings
from src.core.pipeline.ltr import LambdaMartRanker, load_lambda_mart_ranker
from src.observability.logging import safe_exception_stack, truncate_log_value


@lru_cache(maxsize=1)
def get_ltr_ranker() -> LambdaMartRanker | None:
    if settings.RECALL_LTR_MODE in {"off", "baseline"}:
        return None
    try:
        model_dir = Path(settings.RECALL_LTR_MODEL_DIR)
        if not model_dir.is_absolute():
            model_dir = Path(PROJECT_ROOT) / model_dir
        ranker = load_lambda_mart_ranker(model_dir)
    except Exception as exc:  # 启动/首次请求校验失败不击穿服务，active 由 runtime 回退 baseline
        logger.bind(
            event="recall_ltr_startup_fallback",
            outcome="degraded",
            mode=settings.RECALL_LTR_MODE,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).error("[recall] LambdaMART bundle unavailable; weighted-score fallback active")
        return None
    logger.bind(
        event="recall_ltr_model_loaded",
        outcome="succeeded",
        mode=settings.RECALL_LTR_MODE,
        model_version=ranker.model_version,
        feature_version=ranker.manifest["feature_version"],
        feature_signature=ranker.manifest["feature_signature"],
    ).info("[recall] LambdaMART model loaded")
    return ranker
