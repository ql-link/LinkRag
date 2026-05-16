"""add document_post_process_pipeline table

修复历史 schema 漂移 (commit 283c834, 2026-05-10)：
新增 document_post_process_pipeline 表只写在了 scripts/db/init.sql 里，
存量库不会自动 CREATE。本迁移补建该表，DDL 与 init.sql 保持一致。

幂等保护：使用 CREATE TABLE IF NOT EXISTS 语义（通过 information_schema 检测）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = :name"
        ),
        {"name": table_name},
    ).scalar()
    return bool(row)


CREATE_SQL = """
CREATE TABLE document_post_process_pipeline (
    id                         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '解析后处理流程主键',
    document_parsed_log_id      BIGINT UNSIGNED NOT NULL COMMENT '解析日志主键，对应 document_parsed_log.id',
    task_id                    VARCHAR(36) NOT NULL COMMENT '解析任务业务唯一标识，对应 document_parsed_log.task_id',
    document_original_file_id   BIGINT UNSIGNED NOT NULL COMMENT '原文件主键，对应 document_original_file.id',
    document_parse_file_id      BIGINT UNSIGNED DEFAULT NULL COMMENT '文件解析表主键，对应 document_parse_file.id',

    pipeline_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '流程状态: PENDING/PROCESSING/SUCCESS/FAILED',
    chunking_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '分片状态: PENDING/SUCCESS/FAILED',
    vectorizing_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '向量化状态: PENDING/SUCCESS/FAILED',
    es_indexing_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'ES入库状态: PENDING/SUCCESS/FAILED',

    failed_stage                VARCHAR(20) DEFAULT NULL COMMENT '失败阶段: CHUNKING/VECTORIZING/ES_INDEXING',
    recover_from_stage          VARCHAR(20) DEFAULT NULL COMMENT '下次恢复阶段: CHUNKING/VECTORIZING/ES_INDEXING',
    failure_reason              VARCHAR(512) DEFAULT NULL COMMENT '最近一次失败原因摘要',

    chunk_count                 INT NOT NULL DEFAULT 0 COMMENT '本次分片数量',
    retry_count                 INT NOT NULL DEFAULT 0 COMMENT '已重试次数',
    last_retry_at               DATETIME DEFAULT NULL COMMENT '最近一次重试时间',

    chunking_duration_ms        BIGINT DEFAULT NULL COMMENT '分片耗时，单位毫秒',
    vectorizing_duration_ms     BIGINT DEFAULT NULL COMMENT '向量化耗时，单位毫秒',
    es_indexing_duration_ms     BIGINT DEFAULT NULL COMMENT 'ES入库耗时，单位毫秒',
    total_duration_ms           BIGINT DEFAULT NULL COMMENT '后处理流程总耗时，单位毫秒',

    started_at                  DATETIME DEFAULT NULL COMMENT '后处理开始时间',
    finished_at                 DATETIME DEFAULT NULL COMMENT '后处理结束时间',
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_post_pipeline_parsed_log (document_parsed_log_id),
    KEY idx_post_pipeline_task_id (task_id),
    KEY idx_post_pipeline_parse_file (document_parse_file_id, updated_at),
    KEY idx_post_pipeline_status (pipeline_status, updated_at),
    KEY idx_post_pipeline_retry (pipeline_status, recover_from_stage, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '文件级解析后处理流程状态表'
"""


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "document_post_process_pipeline"):
        op.execute(sa.text(CREATE_SQL))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "document_post_process_pipeline"):
        op.execute(sa.text("DROP TABLE document_post_process_pipeline"))
