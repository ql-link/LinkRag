"""
SQLAlchemy ORM 模型
对应 MySQL 数据库表结构
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""

    pass


class SystemProviderDB(Base):
    """系统级厂商配置

    表：llm_system_provider
    """

    __tablename__ = "llm_system_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 默认 API 地址（模板值，不参与运行决策；运行入口以模型能力层事实为准）
    api_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # 默认协议（模板值，新增模型能力时预填用，不参与运行决策）
    default_protocol: Mapped[str] = mapped_column(String(32), default="openai", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    user_configs: Mapped[List["UserLLMConfigDB"]] = relationship(
        "UserLLMConfigDB", back_populates="provider"
    )
    provider_models: Mapped[List["ProviderModelDB"]] = relationship(
        "ProviderModelDB", back_populates="provider"
    )
    system_presets: Mapped[List["SystemPresetDB"]] = relationship(
        "SystemPresetDB", back_populates="provider"
    )


class ProviderModelDB(Base):
    """厂商模型能力目录

    表：llm_provider_model
    """

    __tablename__ = "llm_provider_model"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_system_provider.id"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    # 调用协议（事实来源；Java 服务层保证非空，待历史数据回填后收紧 NOT NULL）
    protocol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 调用入口完整端点 URL（事实来源；Python adapter 直打；google 例外存 base）
    api_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    provider: Mapped["SystemProviderDB"] = relationship(
        "SystemProviderDB", back_populates="provider_models"
    )

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "model_name",
            "capability",
            name="uk_provider_model_cap",
        ),
        Index("idx_provider_cap", "provider_id", "capability"),
    )


class SystemPresetDB(Base):
    """系统预设模板

    表：llm_system_preset
    """

    __tablename__ = "llm_system_preset"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_system_provider.id"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    # 厂商类型（与用户配置对齐，镜像免 join）
    provider_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 调用协议（创建预设时复制自模型能力层）
    protocol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 调用入口完整端点 URL（复制自模型能力层）
    api_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    provider: Mapped["SystemProviderDB"] = relationship(
        "SystemProviderDB", back_populates="system_presets"
    )

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "model_name",
            "capability",
            name="uk_preset_provider_model_cap",
        ),
        Index(
            "idx_preset_provider_cap_default",
            "provider_type",
            "capability",
            "is_active",
            "is_default",
        ),
    )


class UserLLMConfigDB(Base):
    """用户级 LLM 配置

    表：llm_user_config

    本表仅保存用户自己的配置。历史系统预设镜像行通过 is_system_preset 保留兼容，
    Python 读取用户默认配置时排除该类历史行。
    """

    __tablename__ = "llm_user_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_system_provider.id"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 实际生效地址：复制自模型能力层事实（不 fallback 厂商默认）
    api_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # 调用协议快照：复制自模型能力层，下游按 protocol+capability 选 adapter
    protocol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    capability: Mapped[str] = mapped_column(String(32), default="CHAT", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_system_preset: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    provider: Mapped["SystemProviderDB"] = relationship(
        "SystemProviderDB", back_populates="user_configs"
    )
    usage_logs: Mapped[List["UsageLogDB"]] = relationship("UsageLogDB", back_populates="config")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider_id",
            "model_name",
            "capability",
            "is_system_preset",
            name="uk_user_provider_model_capability",
        ),
        Index("idx_user_active_default", "user_id", "is_active", "is_default"),
        Index("idx_user_provider_cap", "user_id", "provider_type", "capability"),
    )


class UsageLogDB(Base):
    """LLM 用量日志

    表：llm_usage_log
    """

    __tablename__ = "llm_usage_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # config_id 放开为可空：对话 / 解析写入侧走用户配置（有 config_id），但召回 query 编码
    # 等走系统配置的调用没有 per-user 配置行，全链路用量上报时该列可能缺省。
    config_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("llm_user_config.id"), nullable=True
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # stage / operation：归属维度，区分一条用量出自哪个阶段、哪种模型调用。
    # stage: parse / recall / chat；operation: embed / sparse / rerank / vision / table / generate。
    # 全部阶段（chat generate / parse embed·vision·table / recall embed·rerank）的用量统一由
    # Python 通过 TokenUsageMessage 上报、Java 消费落库（LINK-191）。可空以兼容存量行。
    stage: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    operation: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    # 关系
    config: Mapped[Optional["UserLLMConfigDB"]] = relationship(
        "UserLLMConfigDB", back_populates="usage_logs"
    )

    __table_args__ = (
        Index("idx_user_date", "user_id", "created_at"),
        Index("idx_config_date", "config_id", "created_at"),
        # 用量分析常按「用户 × 阶段 × 时间」聚合，复合索引覆盖该访问路径。
        Index("idx_user_stage_date", "user_id", "stage", "created_at"),
    )


class ChatConversationDB(Base):
    """对话表

    表：chat_conversation

    所有权：表结构由 Python 侧 Alembic 迁移管理；行数据的增删改由 Java 侧负责
    （建对话、生成标题、每轮更新 last_config_id/last_model_name/updated_at）。
    Python 侧不写本表，仅保留 ORM 映射作为 schema 权威源。
    """

    __tablename__ = "chat_conversation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_config_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_model_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_chat_conversation_user_pinned_updated",
            "user_id",
            "is_pinned",
            "updated_at",
        ),
        Index("idx_chat_conversation_dataset_updated", "dataset_id", "updated_at"),
    )


class ChatMessageDB(Base):
    """对话消息表（一行一轮：query + answer 同行）

    表：chat_message

    一行同时承载用户提问、LLM 回答、召回引用（仅 chunk_id，不含正文）与本轮状态。
    所有权同 chat_conversation：结构归 Python，行数据由 Java 在消费 ChatTurnMessage
    时写入；Python 侧不写本表（chat-message-persistence）。
    """

    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # query 设为可空：本列由 add_column 加到既有（Java 管理）表，MEDIUMTEXT 在 MySQL 下
    # 无法带 DEFAULT 兜底既有行，NOT NULL 会导致迁移在非空表上失败。Java 落库时总会写入，
    # 业务上不出现 NULL（chat-message-persistence）。
    query: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT, nullable=True)
    answer: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    references: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # turn_id：前端每轮稳定 UUID，落库幂等键。Java 据此 upsert 同一行——起点 GENERATING 行
    # 与终态 COMPLETED/FAILED 行同 turn_id，断连续跑/重连不重复插入。唯一索引允许多 NULL，
    # 既有历史行（turn_id 为 NULL）不受约束（chat-stream-resilient-persist）。
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 轮次状态：GENERATING（起点）/COMPLETED（成功或空命中占位）/FAILED（任意失败）。
    # 旧 success/partial/failed 已退役；default 仅作 ORM 层兜底，行数据由 Java 写。
    status: Mapped[str] = mapped_column(String(16), default="GENERATING", nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_conversation_created", "conversation_id", "created_at"),
        Index("uk_chat_message_turn_id", "turn_id", unique=True),
    )


class BlogPostDB(Base):
    """博客文章元数据

    表：blog_post
    """

    __tablename__ = "blog_post"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    content_object_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cover_asset_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("slug", "deleted_seq", name="uk_blog_post_slug_seq"),
        Index("idx_blog_post_public_list", "status", "published_at", "id"),
        Index("idx_blog_post_admin_list", "is_deleted", "updated_at", "id"),
    )


class BlogAssetDB(Base):
    """博客文章资源元数据

    表：blog_asset
    """

    __tablename__ = "blog_asset"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    public_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("object_key", name="uk_blog_asset_object_key"),
        Index("idx_blog_asset_post_type", "post_id", "asset_type", "is_deleted", "created_at"),
    )


class UserFeedbackDB(Base):
    """匿名用户反馈

    表：user_feedback
    """

    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32), default="OTHER", nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_object_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    admin_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_feedback_created", "created_at"),
        Index("idx_feedback_status_priority", "status", "priority", "created_at"),
        Index("idx_feedback_type_created", "type", "created_at"),
    )
