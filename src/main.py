"""
toLink-RAG API 服务入口
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.api.routes import llm, internal
from src.cache.redis_client import redis_client
from src.database import init_database, close_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理

    启动时初始化：
    - Redis 连接
    - MySQL 连接池

    关闭时清理：
    - Redis 连接
    - MySQL 连接池
    """
    # 启动时初始化
    await redis_client.initialize()
    await init_database()
    yield
    # 关闭时清理
    await redis_client.close()
    await close_database()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="RAG 系统 LLM 调用接口",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(llm.router)
app.include_router(internal.router)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "app": settings.APP_NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )