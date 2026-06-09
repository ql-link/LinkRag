"""对外纯召回 JSON 路由（LINK-131）。

端点：``POST /api/v1/recall``（面向**浏览器前端**）。一次性返回纯召回结果，
**不调 CHAT 模型、不回填 chunk 正文、不建立 SSE、不做并发限流**。当前阶段为接口
预留实现，前端暂不真正接入。

与 RAG 问答流（``routes/rag.py``）共用 session token 鉴权与 dataset scope 校验；
关键差异：不要求 ``config_id``、出现 ``config_id`` 即 422、返回 ``application/json``、
执行期错误走 HTTP 状态码（由 ``recall_json_runtime`` 抛 ``RecallApiError``）而非 SSE error 帧。

握手顺序（全部失败走 HTTP JSON）：
1. ``verify_session_token`` 依赖：独立密钥验签 + iss/aud/scope/exp；
2. 解析并校验请求体（``extra=forbid``，仅 ``query`` + 可选 ``dataset_ids``）；query 空白 → 400；
3. scope：body ``dataset_ids`` 必须是 claims 授权范围子集（省略 = 全量授权范围）。

身份只取 claims，前端自报一律不信任；``top_k`` / ``sources`` / ``strict`` 由服务端配置控制。
返回 hits 结构与 RAG 流的 ``recall_done`` 帧 payload 同构。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.internal_auth import CODE_INVALID_REQUEST, RecallApiError
from src.api.recall_json_runtime import run_recall_json
from src.api.recall_pipeline_provider import get_recall_pipeline
from src.api.recall_session_auth import (
    SessionAuthContext,
    resolve_dataset_scope,
    verify_session_token,
)
from src.config import settings
from src.core.pipeline.recall import RecallPipeline, RecallRequest

router = APIRouter(prefix="/api/v1/recall", tags=["recall"])


class RecallJsonRequest(BaseModel):
    """对外纯召回请求体。

    仅接受 ``query``（必填）与可选 ``dataset_ids``（本人授权范围内的子集选择）。
    **不要求 ``config_id``**——纯召回不调 CHAT 模型；body 出现 ``config_id`` /
    ``user_id`` / ``top_k`` / ``sources`` / ``strict`` / ``doc_ids`` 等任何未知字段，
    ``extra=forbid`` 触发 422，避免调用方误以为这些策略生效。
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    dataset_ids: list[int] | None = None


async def _parse_and_validate_body(request: Request) -> RecallJsonRequest:
    """解析 JSON 并做形状/业务校验。失败抛 ``RecallApiError``（握手前 JSON 错误）。"""
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise RecallApiError(422, CODE_INVALID_REQUEST, "request body is not valid JSON")

    try:
        body = RecallJsonRequest.model_validate(payload)
    except ValidationError as exc:
        raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid request: {exc.errors()}")

    if not body.query.strip():
        raise RecallApiError(400, CODE_INVALID_REQUEST, "query is empty or blank")
    return body


@router.post("")
async def recall_json(
    request: Request,
    ctx: SessionAuthContext = Depends(verify_session_token),
    pipeline: RecallPipeline = Depends(get_recall_pipeline),
) -> JSONResponse:
    """对外纯召回 JSON 入口。"""
    body = await _parse_and_validate_body(request)
    dataset_ids = resolve_dataset_scope(body.dataset_ids, ctx)

    recall_req = RecallRequest(
        query=body.query,
        user_id=ctx.user_id,  # 身份以凭证 claims 为准，不信任 body
        dataset_ids=dataset_ids,
        doc_ids=None,
        top_k=settings.RECALL_RESULT_LIMIT,
    )

    payload = await run_recall_json(pipeline, recall_req, ctx.request_id)
    return JSONResponse(content=payload, headers={"X-Request-Id": ctx.request_id})
