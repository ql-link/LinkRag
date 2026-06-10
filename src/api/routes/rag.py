"""对外 RAG 问答流 SSE 路由（LINK-131）。

端点：``POST /api/v1/rag/stream``（面向**浏览器前端**）。前端凭 Java 签发的短期
session token 直连，绕过 Java 中转。承接完整 RAG 行为：召回 → RRF 融合 → 正文回填 →
上下文组装 → CHAT 模型流式生成。

由旧端点 ``POST /api/v1/recall/stream``（``routes/recall_direct.py``）改名搬迁而来：
「召回 = stream」的旧契约语义不再扩散，SSE 的合理性来自 LLM 生成阶段。

握手顺序（全部在建流前，失败走 HTTP JSON）：
1. ``verify_session_token`` 依赖：独立密钥验签 + iss/aud/scope/exp；
2. 解析并校验请求体（``extra=forbid``，无 ``user_id``，``config_id`` 必填）；query 空白 → 400；
3. scope：body ``dataset_ids`` 必须是 claims 授权范围子集（省略 = 全量授权范围）；
4. 并发 acquire：按 ``user_id`` 限并发流数，超限 → 429。

通过后建流，SSE 执行复用 ``recall_stream_runtime``。
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
    RecallApiError,
)
from src.api.recall_pipeline_provider import aresolve_recall_config, get_recall_pipeline
from src.api.recall_session_auth import (
    SessionAuthContext,
    acquire_stream_slot,
    release_stream_slot,
    resolve_dataset_scope,
    verify_session_token,
)
from src.api.recall_stream_runtime import recall_event_stream
from src.core.pipeline.recall import RecallPipeline, RecallRequest

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class RagStreamRequest(BaseModel):
    """RAG 问答流请求体。

    接受 ``query``（必填）、``config_id``（必填，本次生成所用 CHAT 模型配置 id）与可选
    ``dataset_ids``（本人授权范围内的子集选择）。**不含 ``user_id``**——身份只取 token
    claims；body 出现 ``user_id`` / ``top_k`` / ``sources`` / ``strict`` / ``doc_ids``
    等任何未知字段，``extra=forbid`` 触发 422；缺 ``config_id`` 同样触发 422。
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    config_id: int
    dataset_ids: list[int] | None = None


async def _parse_and_validate_body(request: Request) -> RagStreamRequest:
    """解析 JSON 并做形状/业务校验。失败抛 ``RecallApiError``（握手前 JSON 错误）。"""
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise RecallApiError(422, CODE_INVALID_REQUEST, "request body is not valid JSON")

    try:
        body = RagStreamRequest.model_validate(payload)
    except ValidationError as exc:
        raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid request: {exc.errors()}")

    if not body.query.strip():
        raise RecallApiError(400, CODE_INVALID_REQUEST, "query is empty or blank")
    return body


async def _guarded_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
    user_id: int,
    config_id: int,
    token_budget: int,
) -> AsyncGenerator[str, None]:
    """包裹召回事件流，确保并发名额在任何收尾路径都被释放。

    ``finally`` 覆盖正常关流、SSE error、以及前端断连触发的 ``CancelledError``
    （Starlette 会对响应体生成器调用 ``aclose``），避免名额泄漏。
    """
    try:
        async for event in recall_event_stream(
            pipeline, recall_req, request_id, config_id=config_id, token_budget=token_budget
        ):
            yield event
    finally:
        await release_stream_slot(user_id)


@router.post("/stream")
async def rag_stream(
    request: Request,
    ctx: SessionAuthContext = Depends(verify_session_token),
    pipeline: RecallPipeline = Depends(get_recall_pipeline),
) -> StreamingResponse:
    """对外 RAG 问答流 SSE 入口。"""
    body = await _parse_and_validate_body(request)
    dataset_ids = resolve_dataset_scope(body.dataset_ids, ctx)

    # 数据集级 recall 配置在建流前读出（短 session），把 top_k / 阈值 / token 预算固化为
    # 普通值带进流，避免 SSE 生成器执行期再触 DB。
    recall_cfg = await aresolve_recall_config(ctx.user_id, dataset_ids)

    # 并发 acquire 在建流前：超限直接 429（握手前 JSON），不建流、不触发 pipeline。
    if not await acquire_stream_slot(ctx.user_id):
        raise RecallApiError(429, CODE_RATE_LIMITED, "too many concurrent recall streams")

    recall_req = RecallRequest(
        query=body.query,
        user_id=ctx.user_id,  # 身份以凭证 claims 为准，不信任 body
        dataset_ids=dataset_ids,
        doc_ids=None,
        top_k=recall_cfg.recall_result_limit,
        sparse_score_threshold_override=recall_cfg.sparse_score_threshold,
        dense_score_threshold_override=recall_cfg.dense_score_threshold,
    )

    return StreamingResponse(
        _guarded_stream(
            pipeline,
            recall_req,
            ctx.request_id,
            ctx.user_id,
            body.config_id,
            recall_cfg.recall_context_token_budget,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭网关响应缓冲，保证 SSE 实时
            "X-Request-Id": ctx.request_id,
        },
    )
