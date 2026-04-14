"""
数据库连接管理
提供异步 MySQL 连接池和 Session 管理
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import settings


def _get_async_database_url() -> str:
    """将 pymysql URL 转换为 aiomysql URL

    mysql+pymysql:// -> mysql+aiomysql://
    """
    db_url = settings.DATABASE_URL or ""
    if "mysql+pymysql://" in db_url:
        return db_url.replace("mysql+pymysql://", "mysql+aiomysql://")
    elif db_url.startswith("mysql://") or db_url.startswith("("):
        # Handle cases where it's just mysql:// or wrapped in quotes/parens
        return db_url
    return db_url


# 创建异步引擎
_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    """获取或创建异步引擎单例"""
    global _async_engine
    if _async_engine is None:
        async_url = _get_async_database_url()
        _async_engine = create_async_engine(
            async_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取或创建 Session 工厂单例"""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取数据库 Session"""
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """上下文管理器：获取数据库 Session（用于后台任务）"""
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_database() -> None:
    """初始化数据库连接池"""
    engine = get_async_engine()
    # 测试连接
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def close_database() -> None:
    """关闭数据库连接池"""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None