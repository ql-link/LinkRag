"""内部多路召回 SSE 流式路由。

端点：``POST /api/v1/internal/recall/stream``（仅供 Java Recall Gateway 内部调用）。

链路（方案 A：建流在前）：
1. 依赖 ``verify_internal_jwt`` 校验内部 JWT，产出可信 ``InternalAuthContext``；
2. 解析并校验请求体（``extra=forbid``，拒绝非首版字段）；query 空白 → 400；
3. scope 校验：``body.user_id`` 必须等于 claims ``sub``；``body.dataset_ids`` 必须是
   claims 授权范围子集；
4. 以上握手前错误统一走 HTTP JSON；建流后 pipeline 的成功/失败/超时统一走 SSE 终态事件。

不返回 chunk 正文；``top_k`` / ``sources`` / ``strict`` 由服务端配置控制。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.internal_auth import (
    CODE_ALL_SOURCES_FAILED,
    CODE_EMBEDDING_CONFIG_MISSING,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_SCOPE_FORBIDDEN,
    CODE_TIMEOUT,
    CODE_USER_MISMATCH,
    InternalAuthContext,
    RecallApiError,
    verify_internal_jwt,
)
from src.api.recall_pipeline_provider import get_recall_pipeline
from src.config import settings
from src.core.pipeline.recall import (
    RecallError,
    RecallFatalError,
    RecallPipeline,
    RecallRequest,
    RecallResponse,
    RecallValidationError,
)

router = APIRouter(prefix="/api/v1/internal/recall", tags=["internal-recall"])


class RecallStreamRequest(BaseModel):
    """内部召回请求体。

    仅接受 ``query`` / ``user_id`` / ``dataset_ids``；出现 ``top_k`` / ``sources`` /
    ``strict`` / ``include_content`` / ``doc_ids`` 等非首版字段时 ``extra=forbid`` 触发
    校验失败 → 422，避免调用方误以为这些策略生效。``user_id`` 仅用于与凭证 ``sub``
    一致性校验，真正下传 pipeline 的身份以 claims 为准。
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    user_id: int
    dataset_ids: list[int]


async def _parse_and_validate_body(request: Request) -> RecallStreamRequest:
    """解析 JSON 并做形状/业务校验。失败抛 ``RecallApiError``（握手前 JSON 错误）。"""
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise RecallApiError(422, CODE_INVALID_REQUEST, "request body is not valid JSON")

    try:
        body = RecallStreamRequest.model_validate(payload)
    except ValidationError as exc:
        raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid request: {exc.errors()}")

    if not body.query.strip():
        raise RecallApiError(400, CODE_INVALID_REQUEST, "query is empty or blank")
    return body


def _check_scope(body: RecallStreamRequest, ctx: InternalAuthContext) -> None:
    """身份与授权范围一致性校验。

    - ``body.user_id`` 必须等于 claims ``sub``，否则 403 USER_MISMATCH；
    - claims 带 ``dataset_ids`` 时，``body.dataset_ids`` 必须是其子集，否则 403
      SCOPE_FORBIDDEN；claims 为空/None 表示全库授权，不限制 body 范围。
    """
    if body.user_id != ctx.user_id:
        raise RecallApiError(403, CODE_USER_MISMATCH, "user_id does not match credential")

    if ctx.dataset_ids:
        if not set(body.dataset_ids) <= set(ctx.dataset_ids):
            raise RecallApiError(
                403, CODE_SCOPE_FORBIDDEN, "dataset_ids exceed authorized scope"
            )


def _event(name: str, payload: dict) -> str:
    """序列化为单帧 SSE 事件（``data`` 为单行 JSON）。"""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _serialize_hits(response: RecallResponse) -> list[dict]:
    return [
        {
            "chunk_id": str(h.chunk_id),
            "doc_id": h.doc_id,
            "dataset_id": h.dataset_id,
            "fused_score": h.fused_score,
            "scores": h.scores,
        }
        for h in response.hits
    ]


async def _recall_event_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """流内执行 pipeline，把结果/异常映射为 SSE 终态事件。

    成功（含宽松降级）→ ``recall_done``；全路失败 → ``error`` ALL_SOURCES_FAILED；
    超时 → ``error`` TIMEOUT；客户端断连 → 停止发送并向上传播取消（pipeline 协程随之
    取消）；未预期异常 → ``error`` INTERNAL_ERROR。错误 message 不含内部堆栈。
    """
    timeout_seconds = settings.RECALL_STREAM_TIMEOUT_MS / 1000
    try:
        response = await asyncio.wait_for(
            pipeline.execute(recall_req), timeout=timeout_seconds
        )
        yield _event(
            "recall_done",
            {"hits": _serialize_hits(response), "failed_sources": response.failed_sources},
        )
    except RecallValidationError as exc:
        # 正常已在握手前拦截；此处为 pipeline 自身安全网的兜底。
        logger.info("[recall] validation error request_id={}: {}", request_id, exc)
        yield _event("error", {"code": CODE_INVALID_REQUEST, "message": str(exc)})
    except RecallFatalError as exc:
        # 必备前置缺失（当前：发起用户无默认 EMBEDDING 配置，dense 路无法编码 query）。
        # 须置于 RecallError 之前——RecallFatalError 是其子类。整请求硬失败，不做宽松降级。
        logger.warning("[recall] embedding config missing request_id={}: {}", request_id, exc)
        yield _event(
            "error",
            {"code": CODE_EMBEDDING_CONFIG_MISSING, "message": "user embedding config missing"},
        )
    except RecallError as exc:
        logger.warning("[recall] all sources failed request_id={}: {}", request_id, exc)
        yield _event(
            "error", {"code": CODE_ALL_SOURCES_FAILED, "message": "all retrievers failed"}
        )
    except asyncio.TimeoutError:
        logger.warning("[recall] timeout request_id={}", request_id)
        yield _event("error", {"code": CODE_TIMEOUT, "message": "recall timeout"})
    except asyncio.CancelledError:
        # 客户端（Java）断连：停止发送事件，向上传播取消，让 pipeline 协程随之结束。
        logger.info("[recall] client disconnected, cancelling request_id={}", request_id)
        raise
    except Exception:  # noqa: BLE001 - 兜底，避免未预期异常泄露堆栈给调用方
        logger.exception("[recall] unexpected error request_id={}", request_id)
        yield _event("error", {"code": CODE_INTERNAL_ERROR, "message": "internal error"})


@router.post("/stream")
async def recall_stream(
    request: Request,
    ctx: InternalAuthContext = Depends(verify_internal_jwt),
    pipeline: RecallPipeline = Depends(get_recall_pipeline),
) -> StreamingResponse:
    """内部多路召回 SSE 流式入口。"""
    body = await _parse_and_validate_body(request)
    _check_scope(body, ctx)

    recall_req = RecallRequest(
        query=body.query,
        user_id=ctx.user_id,  # 身份以凭证 claims 为准，不信任 body
        dataset_ids=body.dataset_ids,
        doc_ids=None,
        top_k=settings.RECALL_RESULT_LIMIT,
    )

    return StreamingResponse(
        _recall_event_stream(pipeline, recall_req, ctx.request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭网关响应缓冲，保证 SSE 实时
            "X-Request-Id": ctx.request_id,
        },
    )
