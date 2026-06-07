"""对外直连多路召回 SSE 流式路由（LINK-40）。

端点：``POST /api/v1/recall/stream``（面向**浏览器前端**，区别于 internal-only 的
``/api/v1/internal/recall/stream``）。前端凭 Java 签发的短期 session token 直连，绕过
Java 中转。

握手顺序（全部在建流前，失败走 HTTP JSON）：
1. ``verify_session_token`` 依赖：独立密钥验签 + iss/aud/scope/exp；
2. 解析并校验请求体（``extra=forbid``，无 ``user_id``）；query 空白 → 400；
3. scope：body ``dataset_ids`` 必须是 claims 授权范围子集（省略 = 全量授权范围）；
4. 并发 acquire：按 ``user_id`` 限并发流数，超限 → 429。

通过后建流，SSE 执行复用 ``recall_stream_runtime``（与内部端点同一实现）。
身份只取 claims，前端自报一律不信任；``top_k`` / ``sources`` / ``strict`` 由服务端配置控制。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.internal_auth import (
    CODE_INVALID_REQUEST,
    CODE_RATE_LIMITED,
    CODE_SCOPE_FORBIDDEN,
    RecallApiError,
)
from src.api.recall_pipeline_provider import get_recall_pipeline
from src.api.recall_session_auth import (
    SessionAuthContext,
    acquire_stream_slot,
    release_stream_slot,
    verify_session_token,
)
from src.api.recall_stream_runtime import recall_event_stream
from src.config import settings
from src.core.pipeline.recall import RecallPipeline, RecallRequest

router = APIRouter(prefix="/api/v1/recall", tags=["recall-direct"])


class RecallDirectStreamRequest(BaseModel):
    """对外直连召回请求体。

    接受 ``query``（必填）、``config_id``（必填，本次生成所用 CHAT 模型配置 id）与可选
    ``dataset_ids``（本人授权范围内的子集选择）。**不含 ``user_id``**——身份只取 token
    claims；body 出现 ``user_id`` / ``top_k`` / ``sources`` / ``strict`` / ``doc_ids``
    等任何未知字段，``extra=forbid`` 触发 422；缺 ``config_id`` 同样触发 422。
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    config_id: int
    dataset_ids: list[int] | None = None


async def _parse_and_validate_body(request: Request) -> RecallDirectStreamRequest:
    """解析 JSON 并做形状/业务校验。失败抛 ``RecallApiError``（握手前 JSON 错误）。"""
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise RecallApiError(422, CODE_INVALID_REQUEST, "request body is not valid JSON")

    try:
        body = RecallDirectStreamRequest.model_validate(payload)
    except ValidationError as exc:
        raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid request: {exc.errors()}")

    if not body.query.strip():
        raise RecallApiError(400, CODE_INVALID_REQUEST, "query is empty or blank")
    return body


def _resolve_dataset_ids(
    body: RecallDirectStreamRequest, ctx: SessionAuthContext
) -> list[int]:
    """解析本次召回的最终数据集范围。

    - body 省略 / 空 ``dataset_ids`` → 用 claims 全量授权范围（claims 也空表示 Java
      已授权全库，返回空列表交由 pipeline 做全库召回）；
    - body 指定子集 → 必须 ⊆ claims 授权范围，否则 403 SCOPE_FORBIDDEN；claims 为空
      （全库授权）时不限制 body。
    """
    if not body.dataset_ids:
        return ctx.dataset_ids or []

    if ctx.dataset_ids and not set(body.dataset_ids) <= set(ctx.dataset_ids):
        raise RecallApiError(
            403, CODE_SCOPE_FORBIDDEN, "dataset_ids exceed authorized scope"
        )
    return body.dataset_ids


async def _guarded_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
    user_id: int,
    config_id: int,
) -> AsyncGenerator[str, None]:
    """包裹召回事件流，确保并发名额在任何收尾路径都被释放。

    ``finally`` 覆盖正常关流、SSE error、以及前端断连触发的 ``CancelledError``
    （Starlette 会对响应体生成器调用 ``aclose``），避免名额泄漏。
    """
    try:
        async for event in recall_event_stream(
            pipeline, recall_req, request_id, config_id=config_id
        ):
            yield event
    finally:
        await release_stream_slot(user_id)


@router.post("/stream")
async def recall_stream_direct(
    request: Request,
    ctx: SessionAuthContext = Depends(verify_session_token),
    pipeline: RecallPipeline = Depends(get_recall_pipeline),
) -> StreamingResponse:
    """对外直连多路召回 SSE 流式入口。"""
    body = await _parse_and_validate_body(request)
    dataset_ids = _resolve_dataset_ids(body, ctx)

    # 并发 acquire 在建流前：超限直接 429（握手前 JSON），不建流、不触发 pipeline。
    if not await acquire_stream_slot(ctx.user_id):
        raise RecallApiError(429, CODE_RATE_LIMITED, "too many concurrent recall streams")

    recall_req = RecallRequest(
        query=body.query,
        user_id=ctx.user_id,  # 身份以凭证 claims 为准，不信任 body
        dataset_ids=dataset_ids,
        doc_ids=None,
        top_k=settings.RECALL_RESULT_LIMIT,
    )

    return StreamingResponse(
        _guarded_stream(pipeline, recall_req, ctx.request_id, ctx.user_id, body.config_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭网关响应缓冲，保证 SSE 实时
            "X-Request-Id": ctx.request_id,
        },
    )
