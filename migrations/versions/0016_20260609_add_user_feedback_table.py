"""add user feedback table

Java owns the feedback HTTP workflow, MinIO attachment upload, and admin
handling. Python only creates the shared database table through Alembic.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS user_feedback (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '反馈 ID',
                `type` VARCHAR(32) NOT NULL DEFAULT 'OTHER'
                    COMMENT '反馈类型：BUG=问题反馈，FEATURE=功能建议，EXPERIENCE=体验反馈，OTHER=其他',
                title VARCHAR(128) NOT NULL COMMENT '反馈标题',
                content TEXT NOT NULL COMMENT '反馈详细内容',
                attachment_object_key VARCHAR(512) NULL
                    COMMENT '附件 MinIO object_key，例如 feedback/2026/06/09/a.png',
                `status` VARCHAR(32) NOT NULL DEFAULT 'PENDING'
                    COMMENT '处理状态：PENDING=待处理，PROCESSING=处理中，RESOLVED=已解决，CLOSED=已关闭',
                priority TINYINT NOT NULL DEFAULT 3 COMMENT '处理优先级：1=高，2=中，3=低',
                admin_id BIGINT UNSIGNED NULL COMMENT '处理该反馈的管理员用户 ID',
                admin_reply TEXT NULL COMMENT '管理员处理回复或处理结论',
                processed_at DATETIME NULL COMMENT '管理员处理完成或最后一次处理该反馈的时间',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '反馈提交时间',
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    COMMENT '反馈更新时间',

                PRIMARY KEY (id),
                KEY idx_feedback_created (created_at),
                KEY idx_feedback_status_priority (`status`, priority, created_at),
                KEY idx_feedback_type_created (`type`, created_at)
            ) ENGINE=InnoDB
              DEFAULT CHARSET=utf8mb4
              COLLATE=utf8mb4_unicode_ci
              AUTO_INCREMENT=10000
              COMMENT='匿名用户反馈表'
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS user_feedback"))
