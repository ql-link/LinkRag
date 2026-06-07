"""
toLink-RAG API 服务入口
"""
# NLTK 数据路径必须在引入任何会用到 NLTK 的依赖（deepdoc/infinity-sdk/langchain 等）之前配置，
# 确保运行时优先命中项目内 nltk_data，而非用户家目录 ~/nltk_data。
from src.nltk_bootstrap import configure_nltk_data_path

configure_nltk_data_path()

# 显式初始化日志：装好 Loguru sink 与标准库 logging 桥接（InterceptHandler），
# 放在其余 src 导入之前，确保后续模块导入期产生的日志也被统一捕获，
# 而非依赖某个 core 模块被 import 时的副作用触发。
from src.utils.logger import setup_logger

setup_logger()

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from src.config import settings
from src.api.routes import llm, internal, parse, mq, recall, recall_direct
from src.api.internal_auth import RecallApiError
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
    version="0.1.0",
    description="RAG 系统服务",
    lifespan=lifespan,
)

# CORS 配置
# 注意：CORS 是全局中间件，对所有路由生效。对外直连召回端点（/api/v1/recall/stream）
# 暴露给浏览器后，生产环境必须把 CORS_ORIGINS 由默认 ["*"] 收敛为前端可信域名清单
# （携带 Authorization 头的跨域请求需要显式 origin，"*" + allow_credentials 本就非法）。
# 内部路由是服务端调用，不依赖 CORS，收敛无副作用。
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
app.include_router(recall.router)  # 挂载内部多路召回 SSE 路由
app.include_router(recall_direct.router)  # 挂载对外直连召回 SSE 路由（LINK-40）


@app.exception_handler(RecallApiError)
async def recall_api_error_handler(request: Request, exc: RecallApiError) -> JSONResponse:
    """内部召回握手前错误统一响应：{code, message, data} + 对应 HTTP 状态。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )



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
        # 不让 uvicorn 安装自己的 dictConfig；日志交由 setup_logger 的
        # InterceptHandler 统一接管（CLI 启动路径同样在 import 期被接管覆盖）。
        log_config=None,
    )
