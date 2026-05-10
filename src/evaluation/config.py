# -*- coding: utf-8 -*-
"""
EvalConfig — 评估专用配置，与 src/config.Settings 完全解耦。

使用独立的 .env.eval 文件，避免污染业务环境配置。
"""
from __future__ import annotations

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalConfig(BaseSettings):
    """评估框架运行配置。

    所有字段均有合理默认值，可在 .env.eval 中覆盖。
    字段分组：数据集 / 报告 / 运行控制 / LLM 裁判 / 资源隔离 / 存储 / 质量门禁 / Pipeline。
    """

    # ── 数据集 ─────────────────────────────────────────────────────────────────
    EVAL_DATASET_DIR: str = "./tests/evaluation_datasets"

    # ── 报告 ───────────────────────────────────────────────────────────────────
    EVAL_REPORT_DIR: str = "./docs/evaluation_reports"

    # ── 运行控制 ───────────────────────────────────────────────────────────────
    EVAL_RUNS_PER_SAMPLE: int = 1
    EVAL_TIMEOUT_PER_SAMPLE_S: int = 120
    EVAL_MAX_MEMORY_MB: int = 2048
    EVAL_PARALLELISM: int = 4
    EVAL_RETRY_EVAL_ERRORS: int = 2

    # ── LLM 裁判（默认关闭）───────────────────────────────────────────────────
    EVAL_JUDGE_ENABLED: bool = False
    EVAL_JUDGE_MODEL: Optional[str] = None
    EVAL_JUDGE_CACHE_DIR: str = "./.eval_cache/judge"
    EVAL_JUDGE_CACHE_TTL_H: int = 168   # 缓存有效期 7 天

    # ── 资源隔离 ───────────────────────────────────────────────────────────────
    EVAL_QDRANT_COLLECTION_PREFIX: str = "eval_"
    EVAL_ES_INDEX_PREFIX: str = "eval_"

    # ── 存储后端 ───────────────────────────────────────────────────────────────
    EVAL_STORE_BACKEND: str = "filesystem"   # filesystem | mysql
    EVAL_STORE_DIR: str = "./.eval_store"
    EVAL_MYSQL_DSN: Optional[str] = None     # 独立连接，不复用业务 DB session

    # ── 质量门禁（CI 场景）────────────────────────────────────────────────────
    EVAL_GATE_ENABLED: bool = False
    EVAL_GATE_THRESHOLD_FILE: Optional[str] = None   # JSON: {metric_id: {min/max}}

    # ── Pipeline ───────────────────────────────────────────────────────────────
    EVAL_PIPELINE_CONFIG: str = "configs/eval/full_parse_chunk.yaml"

    model_config = SettingsConfigDict(
        env_file=".env.eval",       # 评估专用 env，与 .env 分离
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 进程级单例
eval_config = EvalConfig()
