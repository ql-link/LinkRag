# ruff: noqa: E402
# NLTK 与日志必须先于业务模块初始化，因此本文件有意在初始化调用后继续导入。

"""
toLink-RAG API 服务入口
"""

# NLTK 数据路径必须在引入任何会用到 NLTK 的依赖（如 infinity-sdk）之前配置，
# 确保运行时优先命中项目内 nltk_data，而非用户家目录 ~/nltk_data。
from src.bootstrap import configure_nltk_data_path

configure_nltk_data_path()

# 显式初始化日志：装好 Loguru sink 与标准库 logging 桥接（InterceptHandler），
# 放在其余 src 导入之前，确保后续模块导入期产生的日志也被统一捕获，
# 而非依赖某个 core 模块被 import 时的副作用触发。
from src.observability.logging import (
    logger,
    safe_exception_stack,
    setup_logger,
    truncate_log_value,
)

setup_logger()

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.java_access_auth import validate_java_access_jwt_configuration
from src.api.management_auth import (
    ManagementAuthenticator,
    SqlUserAuthorizationRepository,
    build_access_token_verifier,
)
from src.api.routes import (
    admin_model_catalog,
    admin_model_configs,
    admin_model_sync,
    admin_operations,
    apps,
    blog,
    chat,
    datasets,
    document_files,
    feedback,
    identity_users,
    internal,
    internal_document_files,
    llm,
    model_configs,
    mq,
    object_uploads,
    parse,
    rag,
    recall,
    usage,
    wiki,
)
from src.application.document_deletion import replay_pending_deletions
from src.application.document_uploads import DocumentUploadExecutor, fail_stuck_uploads
from src.application.identity_session import AccessTokenIssuer, build_session_state
from src.application.ltr_provider import (
    get_ltr_runtime_status,
    preload_ltr_ranker,
    shutdown_ltr_ranker,
)
from src.application.ltr_shadow_executor import (
    get_ltr_shadow_executor,
    initialize_ltr_shadow_executor,
    shutdown_ltr_shadow_executor,
)
from src.application.management_outbox import publish_due
from src.application.recall_errors import RecallApiError
from src.cache.redis_client import redis_client
from src.config import settings
from src.core.mq.consumers.document_delete_consumer import (
    DOCUMENT_DELETE_GROUP,
    DOCUMENT_DELETE_TOPIC,
    handle_document_delete,
)
from src.core.mq.consumers.parse_task_consumer import (
    PARSE_TASK_GROUP,
    PARSE_TASK_TOPIC,
    handle_parse_task,
)

# MQ 工厂（生命周期管理）
from src.core.mq.factory import MQFactory
from src.core.mq.topic_admin import ensure_topics

# 解析任务临时落盘目录治理：启动时清空 PARSE_TEMP_DIR，回收上次异常退出残留的临时文件。
from src.core.pipeline.parse_task import temp_workspace
from src.database import close_database, get_db_context, init_database
from src.observability.middleware import TraceContextMiddleware
from src.services.mq_service import MQService
from src.services.storage.factory import StorageFactory


async def _start_mq_consumers() -> None:
    """组合根装配：用 MQService 订阅各业务 handler 并启动消费。

    core 层消费者模块只暴露 handler 与 topic/group 常量，订阅装配在此完成，
    避免 core 反向依赖 services。各消费者用独立 group_id，offset 互不干扰。
    """
    mq_service = MQService()
    await mq_service.subscribe(
        topic=PARSE_TASK_TOPIC,
        group_id=PARSE_TASK_GROUP,
        callback=handle_parse_task,
    )
    await mq_service.subscribe(
        topic=DOCUMENT_DELETE_TOPIC,
        group_id=DOCUMENT_DELETE_GROUP,
        callback=handle_document_delete,
    )
    await mq_service.start_consuming()
    logger.info(
        f"[MQConsumers] 消费者已启动: "
        f"parse_task(topic={PARSE_TASK_TOPIC}, group={PARSE_TASK_GROUP}), "
        f"document_delete(topic={DOCUMENT_DELETE_TOPIC}, group={DOCUMENT_DELETE_GROUP})"
    )


async def _replay_delete_notifications() -> None:
    """Repair post-commit publish failures without a second MQ consumer group."""
    while True:
        await asyncio.sleep(300)
        try:
            await replay_pending_deletions()
        except Exception as exc:
            logger.bind(event="document_delete_replay_failed", error_type=type(exc).__name__).error(
                "删除通知对账失败"
            )


async def _publish_management_outbox() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await publish_due()
        except Exception as exc:
            logger.bind(
                event="management_outbox_publish_failed", error_type=type(exc).__name__
            ).error("管理端消息补发失败")


async def _scan_stuck_uploads() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            count = await fail_stuck_uploads()
            if count:
                logger.warning("已将 {} 条超时上传记录置为失败", count)
        except Exception as exc:
            logger.bind(
                event="document_upload_stuck_scan_failed", error_type=type(exc).__name__
            ).error("超时上传扫描失败")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理

    启动时初始化：
    - LambdaMART 模型或明确 baseline 状态
    - Redis 连接
    - MySQL 连接池

    关闭时清理：
    - MQ 连接
    - Redis 连接
    - MySQL 连接池
    """
    # 鉴权公钥属于启动契约：启用新 access JWT 却缺少/损坏公钥时禁止带病接流量。
    validate_java_access_jwt_configuration()
    if settings.B5_FILE_WRITES_ENABLED and (
        not settings.B5_INTERNAL_FILE_SERVICE_TOKEN or not settings.B5_INTERNAL_FILE_BASE_URL
    ):
        raise RuntimeError("B5 文件写入需要内部文件服务 token 与可访问的 base URL")
    # 在连接外部依赖前拒绝尚未实现的存储 provider。
    StorageFactory.validate_provider()
    # 启动时初始化
    # LTR 文件读取、LightGBM 导入、Booster 构造与测试向量校验全部在 worker thread
    # 预加载；失败会固化为本进程 baseline 状态，不把首次初始化成本留给真实请求。
    await preload_ltr_ranker()
    initialize_ltr_shadow_executor()
    await redis_client.initialize()
    await init_database()
    if (
        settings.B3_CONTROL_WRITES_ENABLED
        or settings.B5_FILE_WRITES_ENABLED
        or settings.B5_DELETE_WRITES_ENABLED
    ):
        async with get_db_context() as db:
            if settings.B3_CONTROL_WRITES_ENABLED:
                await db.execute(text("SELECT id FROM llm_provider_model_sync_job LIMIT 0"))
                await db.execute(text("SELECT id FROM llm_provider_model_sync_candidate LIMIT 0"))
            if settings.B5_FILE_WRITES_ENABLED or settings.B5_DELETE_WRITES_ENABLED:
                await db.execute(text("SELECT id FROM management_mq_outbox LIMIT 0"))
    if settings.B1_PYTHON_ISSUER_ENABLED:
        # 启用签发时在接流量前验证阶段门槛及密钥配对。
        probe, _ = AccessTokenIssuer.from_settings().sign(1, "USER")
        build_access_token_verifier().verify(probe)
    app.state.identity_sessions = build_session_state()
    app.state.management_authenticator = (
        ManagementAuthenticator(
            build_access_token_verifier(),
            app.state.identity_sessions,
            SqlUserAuthorizationRepository(),
        )
        if settings.JAVA_ACCESS_JWT_ENABLED
        else None
    )
    # 在拉起消费者之前清空临时落盘目录：兜底回收上次进程异常退出残留的源文件副本，
    # 失败让 worker 启动失败暴露问题，避免后续 download_to_path 永远失败但运维无感知。
    temp_workspace.ensure_clean_on_startup(Path(settings.PARSE_TEMP_DIR))
    if settings.MQ_VENDOR.lower() == "kafka" and settings.INIT_KAFKA_TOPICS_ON_STARTUP:
        ensure_topics()
    await _start_mq_consumers()
    app.state.document_upload_executor = None
    upload_scan_task = None
    if settings.B5_FILE_WRITES_ENABLED:
        app.state.document_upload_executor = DocumentUploadExecutor()
        app.state.document_upload_executor.start()
        upload_scan_task = asyncio.create_task(_scan_stuck_uploads())
    delete_replay_task = (
        asyncio.create_task(_replay_delete_notifications())
        if settings.B5_DELETE_WRITES_ENABLED
        else None
    )
    outbox_task = (
        asyncio.create_task(_publish_management_outbox())
        if settings.B5_FILE_WRITES_ENABLED or settings.B5_DELETE_WRITES_ENABLED
        else None
    )
    try:
        yield
    finally:
        if upload_scan_task is not None:
            upload_scan_task.cancel()
            try:
                await upload_scan_task
            except asyncio.CancelledError:
                pass
        if app.state.document_upload_executor is not None:
            await app.state.document_upload_executor.close()
        if delete_replay_task is not None:
            delete_replay_task.cancel()
            try:
                await delete_replay_task
            except asyncio.CancelledError:
                pass
        if outbox_task is not None:
            outbox_task.cancel()
            try:
                await outbox_task
            except asyncio.CancelledError:
                pass
    # 关闭时清理（MQ 连接优先关闭，避免消息丢失）
    try:
        mq_factory = MQFactory()
        await mq_factory.close_all()
    except Exception:
        pass
    await app.state.identity_sessions.close()
    await redis_client.close()
    from src.core.storage.manticore_bm25 import close_manticore_bm25_store

    await close_manticore_bm25_store()
    await close_database()
    await shutdown_ltr_shadow_executor()
    shutdown_ltr_ranker()
    # 等待 enqueue 异步队列里的日志全部落盘，避免退出时丢失尾部日志。
    await logger.complete()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="RAG 系统服务",
    lifespan=lifespan,
)

# CORS 配置
# 注意：CORS 是全局中间件，对所有路由生效。对外端点（/api/v1/rag/stream、/api/v1/recall）
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
app.add_middleware(TraceContextMiddleware)

# 注册所有模块路由
app.include_router(llm.router)
app.include_router(internal.router)
app.include_router(parse.router)  # 挂载文档解析路由
app.include_router(mq.router)  # 挂载 MQ 消息中台路由
app.include_router(rag.router)  # 挂载对外 RAG 问答流 SSE 路由（LINK-131）
app.include_router(recall.router)  # 挂载对外纯召回 JSON 路由（LINK-131）
app.include_router(recall.session_router)  # 本地统一后端兼容浏览器召回握手
app.include_router(wiki.router)  # 挂载 Wiki 标题树对外读取路由
app.include_router(identity_users.auth_router)
app.include_router(identity_users.user_router)
app.include_router(identity_users.admin_router)
app.include_router(chat.router)
app.include_router(chat.chunk_router)
app.include_router(usage.router)
app.include_router(admin_operations.router)
app.include_router(feedback.public_router)
app.include_router(feedback.admin_router)
app.include_router(blog.admin_router)
app.include_router(blog.public_router)
app.include_router(object_uploads.router)
app.include_router(model_configs.router)
app.include_router(admin_model_configs.router)
app.include_router(admin_model_catalog.router)
app.include_router(admin_model_sync.router)
app.include_router(datasets.router)
app.include_router(document_files.router)
app.include_router(internal_document_files.router)
app.include_router(apps.router)  # 接入应用服务端 API（APPS_API_ENABLED）


@app.exception_handler(RecallApiError)
async def recall_api_error_handler(request: Request, exc: RecallApiError) -> JSONResponse:
    """召回握手前错误统一响应：{code, message, data} + 对应 HTTP 状态。"""
    # 握手失败（鉴权 / 入参 / 限流等）记 warning：便于排查对接问题与发现异常调用。
    logger.warning(
        f"召回握手失败 {request.method} {request.url.path}: "
        f"code={exc.code} status={exc.status_code} msg={exc.message}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底未捕获异常：带请求上下文记录完整堆栈，再返回统一 500 响应。

    框架层异常虽已由 InterceptHandler 桥接的 uvicorn logger 记录，但缺业务上下文；
    此处补记请求方法 / 路径，便于排障，并保证对外错误体格式统一。
    """
    logger.bind(
        event="http_unhandled_exception",
        outcome="failed",
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
        error_message=truncate_log_value(exc),
        stack_trace=safe_exception_stack(exc),
    ).error("未捕获 HTTP 异常: method={} path={}", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误", "data": None},
    )


@app.get("/health")
async def health_check():
    """进程存活检查；不访问外部依赖。"""
    ltr_status = get_ltr_runtime_status()
    ltr_status["shadow"] = get_ltr_shadow_executor().snapshot()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "services": ["llm", "document_parser"],
        "ltr": ltr_status,
    }


@app.get("/ready")
async def readiness_check():
    """流量就绪检查；验证服务请求路径依赖，不与纯进程存活混淆。"""

    import asyncio

    from sqlalchemy import text

    from src.database import get_async_engine

    failures: list[str] = []

    try:
        async with get_async_engine().connect() as connection:
            await asyncio.wait_for(connection.execute(text("SELECT 1")), timeout=5)
    except Exception:
        failures.append("mysql")

    if not await redis_client.ping():
        failures.append("redis")

    from src.core.storage.manticore_bm25 import get_manticore_bm25_store

    try:
        await get_manticore_bm25_store().ping()
    except Exception as exc:
        logger.bind(
            event="manticore_readiness_failed",
            outcome="degraded",
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning("Manticore readiness check failed")
        failures.append("manticore")

    if settings.VECTOR_STORE_TYPE.lower() == "qdrant":
        from src.core.storage.qdrant import QdrantIndexStore

        qdrant_store = QdrantIndexStore(timeout=5)
        try:
            client = await qdrant_store._get_client()
            await asyncio.wait_for(client.get_collections(), timeout=5)
        except Exception:
            failures.append("qdrant")
        finally:
            await qdrant_store.close()

    if failures:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "app": settings.APP_NAME,
                "failed_dependencies": failures,
                "bm25_backend": "manticore",
            },
        )

    ltr_status = get_ltr_runtime_status()
    degraded_components = []
    if settings.RECALL_LTR_MODE == "active" and not ltr_status["loaded"]:
        degraded_components.append("ltr")
    return {
        "status": "degraded" if degraded_components else "ready",
        "app": settings.APP_NAME,
        "bm25_backend": "manticore",
        "degraded_components": degraded_components,
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
