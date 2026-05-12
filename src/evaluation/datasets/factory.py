# -*- coding: utf-8 -*-
"""Evaluation dataset factory."""
from __future__ import annotations

import os

from src.evaluation.config import EvalConfig, eval_config
from src.evaluation.datasets.loader import FileSystemDataset, MinioDataset
from src.evaluation.storage.minio_object_storage import MinioEvaluationObjectStorage


class DatasetFactory:
    """Build evaluation datasets from EvalConfig and CLI overrides."""

    @staticmethod
    def create(
        dataset_name: str,
        version: str | None = None,
        split: str | None = None,
        config: EvalConfig | None = None,
        object_storage=None,
        dataset_dir: str | None = None,
    ):
        cfg = config or eval_config
        backend = cfg.EVAL_DATASET_BACKEND.lower()

        if backend == "minio":
            storage = object_storage or MinioEvaluationObjectStorage.from_config(cfg)
            return MinioDataset(
                dataset_name=dataset_name,
                version=version or cfg.EVAL_DATASET_DEFAULT_VERSION,
                split=split or cfg.EVAL_DATASET_SPLIT,
                object_storage=storage,
                bucket=cfg.EVAL_DATASET_BUCKET,
                prefix=cfg.EVAL_DATASET_PREFIX,
            )

        if backend == "filesystem":
            root = dataset_dir or cfg.EVAL_DATASET_DIR
            manifest_path = os.path.join(root, dataset_name, "manifest.yaml")
            return FileSystemDataset(manifest_path)

        raise ValueError(f"不支持的 evaluation dataset backend: {backend}")
