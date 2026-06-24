"""Workflow engine ORM models.

These tables are generic workflow runtime state. They do not replace existing
parse-task tables; the parse workflow demo only writes here when explicitly
using ``MySQLWorkflowStore``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.db_models import Base


class WorkflowRunDB(Base):
    """One workflow run.

    表：workflow_run
    """

    __tablename__ = "workflow_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    definition_name: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    previous_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_phase: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("run_id", name="uk_workflow_run_id"),
        Index("idx_workflow_run_biz_key", "biz_key"),
        Index("idx_workflow_run_previous", "previous_run_id"),
        Index("idx_workflow_run_definition_status", "definition_name", "status", "updated_at"),
    )


class WorkflowNodeRunDB(Base):
    """One node in one workflow run.

    表：workflow_node_run
    """

    __tablename__ = "workflow_node_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requires: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    provides: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    output_ref: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    allow_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tolerated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_phase: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    inherited_from_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("run_id", "node_key", name="uk_workflow_node_run"),
        Index("idx_workflow_node_run_run", "run_id"),
        Index("idx_workflow_node_run_status", "status", "updated_at"),
        Index("idx_workflow_node_run_inherited", "inherited_from_run_id"),
    )
