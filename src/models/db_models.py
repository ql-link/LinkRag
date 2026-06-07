"""
SQLAlchemy ORM 模型
对应 MySQL 数据库表结构
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
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
    api_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
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
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
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
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    )


class UserLLMConfigDB(Base):
    """用户级 LLM 配置

    表：llm_user_config

    系统预设与用户自配统一汇入本表，Python 按
    (user_id, capability, is_default, is_active) 读取生效配置。
    """

    __tablename__ = "llm_user_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_system_provider.id"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    api_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
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
    config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_user_config.id"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    fallback_config_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    # 关系
    config: Mapped["UserLLMConfigDB"] = relationship("UserLLMConfigDB", back_populates="usage_logs")

    __table_args__ = (
        Index("idx_user_date", "user_id", "created_at"),
        Index("idx_config_date", "config_id", "created_at"),
        Index("idx_conversation_id", "conversation_id"),
    )
