"""
toLink-RAG API 服务入口
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.config import settings
from src.api.routes import llm, internal, parse, mq
from src.cache.redis_client import redis_client
from src.database import init_database, close_database

# 引入文档解析模块的数据库依赖
from src.core.database import engine
from src.models.parse_task import Base

# MQ 工厂（生命周期管理）
from src.core.mq.factory import MQFactory
from src.core.mq.topic_admin import ensure_topics
from src.core.mq.consumers.parse_task_consumer import start_parse_consumer
# 解析任务临时落盘目录治理：启动时清空 PARSE_TEMP_DIR，回收上次异常退出残留的临时文件。
from src.core.pipeline.parse_task import temp_workspace


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理

    启动时初始化：
    - Redis 连接
    - MySQL 连接池

    关闭时清理：
    - MQ 连接
    - Redis 连接
    - MySQL 连接池
    """
    # 启动时初始化
    await redis_client.initialize()
    await init_database()
    # 在拉起消费者之前清空临时落盘目录：兜底回收上次进程异常退出残留的源文件副本，
    # 失败让 worker 启动失败暴露问题，避免后续 download_to_path 永远失败但运维无感知。
    temp_workspace.ensure_clean_on_startup(Path(settings.PARSE_TEMP_DIR))
    if settings.MQ_VENDOR.lower() == "kafka" and settings.INIT_KAFKA_TOPICS_ON_STARTUP:
        ensure_topics()
    await start_parse_consumer()
    yield
    # 关闭时清理（MQ 连接优先关闭，避免消息丢失）
    try:
        mq_factory = MQFactory()
        await mq_factory.close_all()
    except Exception:
        pass
    await redis_client.close()
    await close_database()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="RAG 系统服务",
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

# 注册所有模块路由
app.include_router(llm.router)
app.include_router(internal.router)
app.include_router(parse.router)  # 挂载文档解析路由
app.include_router(mq.router)    # 挂载 MQ 消息中台路由



@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok", 
        "app": settings.APP_NAME,
        "services": ["llm", "document_parser"]
    }


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
