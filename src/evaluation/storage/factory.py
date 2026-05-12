# -*- coding: utf-8 -*-
"""ResultStore factory for evaluation."""
from __future__ import annotations

from src.evaluation.config import EvalConfig, eval_config
from src.evaluation.storage.filesystem import FilesystemResultStore
from src.evaluation.storage.minio_object_storage import MinioEvaluationObjectStorage
from src.evaluation.storage.minio_result_store import MinioResultStore


class ResultStoreFactory:
    """Build ResultStore implementations from EvalConfig."""

    @staticmethod
    def create(config: EvalConfig | None = None, object_storage=None):
        cfg = config or eval_config
        backend = cfg.EVAL_STORE_BACKEND.lower()

        if backend == "minio":
            storage = object_storage or MinioEvaluationObjectStorage.from_config(cfg)
            return MinioResultStore(
                object_storage=storage,
                bucket=cfg.EVAL_RESULT_BUCKET,
                run_prefix=cfg.EVAL_RUN_PREFIX,
                report_prefix=cfg.EVAL_REPORT_PREFIX,
                baseline_prefix=cfg.EVAL_BASELINE_PREFIX,
            )

        if backend == "filesystem":
            return FilesystemResultStore(store_dir=cfg.EVAL_STORE_DIR)

        raise ValueError(f"不支持的 evaluation result store backend: {backend}")
