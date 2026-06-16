"""add LLM protocol/api_base_url fact columns

Java and Python share the same MySQL database. Java now owns the LLM protocol
refactor (LINK-123 / LinkRag-Service#92): protocol and entry url are sunk into
the model-capability layer as the fact source, and copied into ``llm_user_config``
as a runtime snapshot. Downstream selects the adapter by ``(protocol, capability)``
instead of ``provider_type``. Bring the Python migration chain in line with that
shared contract.

New columns (all nullable except ``default_protocol`` which is a template default):

- ``llm_system_provider.default_protocol``  — 厂商默认协议模板（不参与运行决策）
- ``llm_provider_model.protocol`` / ``api_base_url`` — 事实来源（完整端点 URL；google 例外存 base）
- ``llm_system_preset.provider_type`` / ``protocol`` / ``api_base_url`` — 复制自模型能力层
- ``llm_user_config.protocol`` — 运行快照，下游按 protocol+capability 选 adapter

Model-capability and user-config ``api_base_url`` values are full endpoint URLs
that Python adapters call directly; ``google`` is the only exception and keeps
the base URL to ``/v1beta`` because Gemini encodes the model and stream mode in
the path.

Fact columns stay nullable for now; non-null is guaranteed by the Java service
layer (``validateProtocol`` + ``requireModelFact``) and will be tightened to
``NOT NULL`` after historical rows are backfilled.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 厂商层：默认协议模板（不参与运行决策）
    op.add_column(
        "llm_system_provider",
        sa.Column(
            "default_protocol",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'openai'"),
            comment="默认协议（模板值，新增模型能力预填用）",
        ),
    )
    op.alter_column(
        "llm_system_provider",
        "api_base_url",
        existing_type=sa.String(length=512),
        existing_nullable=False,
        comment="默认 API 地址（模板值，不参与运行决策）",
    )

    # 模型能力层：协议与入口事实来源（完整端点 URL；google 例外存 base）
    op.add_column(
        "llm_provider_model",
        sa.Column(
            "protocol",
            sa.String(length=32),
            nullable=True,
            comment="调用协议（事实来源；服务层保证非空，待回填后收紧 NOT NULL）",
        ),
    )
    op.add_column(
        "llm_provider_model",
        sa.Column(
            "api_base_url",
            sa.String(length=512),
            nullable=True,
            comment="调用入口完整端点 URL（事实来源，Python 直打不拼后缀；google 例外存 base）",
        ),
    )

    # 系统预设层：复制自模型能力层
    op.add_column(
        "llm_system_preset",
        sa.Column(
            "provider_type",
            sa.String(length=32),
            nullable=True,
            comment="厂商类型（与用户配置对齐，镜像免 join）",
        ),
    )
    op.add_column(
        "llm_system_preset",
        sa.Column(
            "protocol",
            sa.String(length=32),
            nullable=True,
            comment="调用协议（创建预设时复制自模型能力层）",
        ),
    )
    op.add_column(
        "llm_system_preset",
        sa.Column(
            "api_base_url",
            sa.String(length=512),
            nullable=True,
            comment="调用入口完整端点 URL（复制自模型能力层）",
        ),
    )

    # 用户配置层：运行快照（下游按 protocol+capability 选 adapter）
    op.add_column(
        "llm_user_config",
        sa.Column(
            "protocol",
            sa.String(length=32),
            nullable=True,
            comment="调用协议快照：复制自模型能力层，下游按 protocol+capability 选 adapter",
        ),
    )
    op.alter_column(
        "llm_user_config",
        "api_base_url",
        existing_type=sa.String(length=512),
        existing_nullable=True,
        comment="实际生效地址：完整端点 URL，复制自模型能力层事实（不 fallback 厂商默认），Python 直打",
    )


def downgrade() -> None:
    op.alter_column(
        "llm_user_config",
        "api_base_url",
        existing_type=sa.String(length=512),
        existing_nullable=True,
        comment="实际生效地址：用户自定义或厂商默认",
    )
    op.drop_column("llm_user_config", "protocol")

    op.drop_column("llm_system_preset", "api_base_url")
    op.drop_column("llm_system_preset", "protocol")
    op.drop_column("llm_system_preset", "provider_type")

    op.drop_column("llm_provider_model", "api_base_url")
    op.drop_column("llm_provider_model", "protocol")

    op.alter_column(
        "llm_system_provider",
        "api_base_url",
        existing_type=sa.String(length=512),
        existing_nullable=False,
        comment="官方默认 API 地址",
    )
    op.drop_column("llm_system_provider", "default_protocol")
