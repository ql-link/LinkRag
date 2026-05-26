"""consolidate task status authority into a renamed parse pipeline table

把整体任务状态权威收敛到一张表，并把"文件级解析后处理流程状态表"重命名为
"文件解析流程状态表"——因为加入解析+上传阶段后，本表已覆盖端到端的全部
解析过程，不再是"后处理"。

- ``document_parsed_log`` 退化为"文件解析产物快照表"：删除 ``task_status`` /
  ``failure_reason``，相应索引按"去掉 task_status 引用"重建。
- ``document_post_process_pipeline`` → ``document_parse_pipeline``：表名重命名；
  新增 ``cleaning_status`` / ``cleaning_duration_ms``（先前的"解析+上传"语义
  下沉为"文档清洗"阶段），删除 ``chunk_count`` / ``retry_count`` /
  ``last_retry_at`` 以及 ``idx_post_pipeline_retry``；其余索引同步改名。

数据迁移：
- 老 ``log.task_status='success'`` → ``pipeline.cleaning_status='SUCCESS'``；
- 老 ``log.task_status='failed'``  → ``pipeline.cleaning_status='FAILED'``，
  并把 ``log.failure_reason`` 回填到 ``pipeline.failure_reason``（仅当后者为空），
  ``failed_stage`` 取 ``CLEANING``；
- 其余（``created`` 或缺失 pipeline 行）保持默认 ``PENDING``。

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-26
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 表重命名：post_process → parse pipeline ----
    op.rename_table("document_post_process_pipeline", "document_parse_pipeline")

    # ---- document_parse_pipeline: 新增 cleaning_* 字段 ----
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "cleaning_status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
            comment="文档清洗（解析+上传）阶段状态: PENDING/SUCCESS/FAILED",
        ),
    )
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "cleaning_duration_ms",
            sa.BigInteger(),
            nullable=True,
            comment="文档清洗阶段耗时，单位毫秒",
        ),
    )

    # ---- 数据迁移：从 log 把 success/failed 终态回填到 pipeline ----
    op.execute(
        """
        UPDATE document_parse_pipeline pp
        JOIN document_parsed_log log
          ON log.id = pp.document_parsed_log_id
        SET pp.cleaning_status = CASE log.task_status
                WHEN 'success' THEN 'SUCCESS'
                WHEN 'failed'  THEN 'FAILED'
                ELSE 'PENDING'
            END,
            pp.cleaning_duration_ms = log.parse_duration_ms,
            pp.pipeline_status = CASE
                WHEN log.task_status = 'failed' AND pp.pipeline_status = 'PENDING'
                    THEN 'FAILED'
                ELSE pp.pipeline_status
            END,
            pp.failure_reason = CASE
                WHEN log.task_status = 'failed' AND pp.failure_reason IS NULL
                    THEN log.failure_reason
                ELSE pp.failure_reason
            END,
            pp.failed_stage = CASE
                WHEN log.task_status = 'failed' AND pp.failed_stage IS NULL
                    THEN 'CLEANING'
                ELSE pp.failed_stage
            END
        WHERE log.task_status IN ('success', 'failed')
        """
    )

    # ---- document_parse_pipeline: 删除冗余字段与索引 ----
    op.drop_index(
        "idx_post_pipeline_retry",
        table_name="document_parse_pipeline",
    )
    op.drop_column("document_parse_pipeline", "chunk_count")
    op.drop_column("document_parse_pipeline", "retry_count")
    op.drop_column("document_parse_pipeline", "last_retry_at")

    # ---- 索引改名：post_pipeline → parse_pipeline ----
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX uk_post_pipeline_parsed_log TO uk_parse_pipeline_parsed_log"
    )
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX idx_post_pipeline_task_id TO idx_parse_pipeline_task_id"
    )
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX idx_post_pipeline_parse_file TO idx_parse_pipeline_parse_file"
    )
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX idx_post_pipeline_status TO idx_parse_pipeline_status"
    )

    # ---- document_parse_pipeline: 表注释升格 ----
    op.execute(
        "ALTER TABLE document_parse_pipeline COMMENT '文件解析流程状态表'"
    )

    # ---- document_parsed_log: 删除 task_status / failure_reason 相关索引与字段 ----
    op.drop_index(
        "idx_parsed_log_original_status",
        table_name="document_parsed_log",
    )
    op.drop_index(
        "idx_parsed_log_parse_task_status",
        table_name="document_parsed_log",
    )
    op.drop_column("document_parsed_log", "task_status")
    op.drop_column("document_parsed_log", "failure_reason")

    op.create_index(
        "idx_parsed_log_original_file",
        "document_parsed_log",
        ["document_original_file_id", "updated_at"],
    )
    op.create_index(
        "idx_parsed_log_parse_file",
        "document_parsed_log",
        ["document_parse_file_id", "updated_at"],
    )

    op.execute(
        "ALTER TABLE document_parsed_log COMMENT '文件解析产物快照表'"
    )


def downgrade() -> None:
    # ---- document_parsed_log: 回滚 task_status / failure_reason ----
    op.drop_index("idx_parsed_log_parse_file", table_name="document_parsed_log")
    op.drop_index("idx_parsed_log_original_file", table_name="document_parsed_log")

    op.add_column(
        "document_parsed_log",
        sa.Column(
            "failure_reason",
            sa.String(length=512),
            nullable=True,
            comment="解析失败原因",
        ),
    )
    op.add_column(
        "document_parsed_log",
        sa.Column(
            "task_status",
            sa.String(length=16),
            nullable=False,
            server_default="created",
            comment="任务状态: created/success/failed",
        ),
    )

    # 反向回填：从 pipeline.cleaning_status 推回 log.task_status。
    op.execute(
        """
        UPDATE document_parsed_log log
        JOIN document_parse_pipeline pp
          ON pp.document_parsed_log_id = log.id
        SET log.task_status = CASE pp.cleaning_status
                WHEN 'SUCCESS' THEN 'success'
                WHEN 'FAILED'  THEN 'failed'
                ELSE 'created'
            END,
            log.failure_reason = CASE
                WHEN pp.cleaning_status = 'FAILED' THEN pp.failure_reason
                ELSE NULL
            END
        """
    )

    op.create_index(
        "idx_parsed_log_original_status",
        "document_parsed_log",
        ["document_original_file_id", "task_status", "updated_at"],
    )
    op.create_index(
        "idx_parsed_log_parse_task_status",
        "document_parsed_log",
        ["document_parse_file_id", "task_status", "updated_at"],
    )

    op.execute(
        "ALTER TABLE document_parsed_log COMMENT '文件解析任务日志表'"
    )

    # ---- document_parse_pipeline: 索引改名回滚 ----
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX idx_parse_pipeline_status TO idx_post_pipeline_status"
    )
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX idx_parse_pipeline_parse_file TO idx_post_pipeline_parse_file"
    )
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX idx_parse_pipeline_task_id TO idx_post_pipeline_task_id"
    )
    op.execute(
        "ALTER TABLE document_parse_pipeline "
        "RENAME INDEX uk_parse_pipeline_parsed_log TO uk_post_pipeline_parsed_log"
    )

    # ---- document_parse_pipeline: 回滚字段与索引 ----
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "last_retry_at",
            sa.DateTime(),
            nullable=True,
            comment="用户侧最近一次重试时间",
        ),
    )
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="用户侧重试次数",
        ),
    )
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "chunk_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="本次分片数量",
        ),
    )
    op.create_index(
        "idx_post_pipeline_retry",
        "document_parse_pipeline",
        ["pipeline_status", "recover_from_stage", "updated_at"],
    )

    op.drop_column("document_parse_pipeline", "cleaning_duration_ms")
    op.drop_column("document_parse_pipeline", "cleaning_status")

    op.execute(
        "ALTER TABLE document_parse_pipeline COMMENT '文件级解析后处理流程状态表'"
    )

    # ---- 表重命名回滚：parse_pipeline → post_process ----
    op.rename_table("document_parse_pipeline", "document_post_process_pipeline")
