"""对外 RAG 问答流 SSE 路由（LINK-131）。

端点：``POST /api/v1/rag/stream``（面向**浏览器前端**）。前端凭 Java 签发的短期
session token 直连，绕过 Java 中转。承接完整 RAG 行为：召回 → RRF 融合 → rerank 精排
（不可用即降级 RRF 顺序）→ 正文回填 → 上下文组装 → CHAT 模型流式生成。

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

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.recall_session_auth import (
    SessionAuthContext,
    acquire_stream_slot,
    release_stream_slot,
    resolve_dataset_scope,
    verify_session_token,
)
from src.application.recall_errors import (
    CODE_INVALID_REQUEST,
    CODE_RATE_LIMITED,
    RecallApiError,
)
from src.application.recall_pipeline_provider import (
    aresolve_recall_config,
    build_recall_request_from_config,
    get_recall_pipeline,
    get_reranker,
)
from src.application.recall_stream_runtime import recall_event_stream
from src.core.pipeline.recall import RecallPipeline, RecallRequest
from src.core.pipeline.rerank import PostRecallReranker

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class RagStreamRequest(BaseModel):
    """RAG 问答流请求体。

    接受 ``query``（必填）、``config_id``（必填，本次生成所用 CHAT 模型配置 id）、
    ``conversation_id``（必填，本轮所属对话 id，作为落库挂载锚点）、可选
    ``is_first_turn``（会话首条用户消息标记，触发基于 query 的标题生成）与可选
    ``dataset_ids``（本人授权范围内的子集选择）。**不含 ``user_id``**——身份只取 token
    claims；body 出现 ``user_id`` / ``top_k`` / ``sources`` / ``strict`` / ``doc_ids``
    等任何未知字段，``extra=forbid`` 触发 422；缺 ``config_id`` / ``conversation_id``
    同样触发 422（缺会话 id 不进入召回生成、不发对话轮次消息）。
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    config_id: int
    conversation_id: int
    # turn_id：前端每轮生成的稳定 UUID，断连重连不变，作落库幂等键（贯穿 GENERATING 起点与
    # 终态，Java 据此 upsert 同一行）。必填——缺失 → 422 RECALL_INVALID_REQUEST。
    turn_id: str
    # is_first_turn：是否会话首条用户消息。前端在新建会话首问时置 true，触发 Python 基于
    # query 生成会话标题（随 chat_turn.title 上报 + SSE conversation_title 即时回前端）。
    # 仅作生成开关；省不省钱由它决定，正确性由 Java「空/默认才写」兜底。默认 false 兼容老前端。
    is_first_turn: bool = False
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


# 在途生产者任务的强引用注册表：asyncio 只持弱引用，无此集合任务可能被 GC 中断。
# 任务结束（含异常/超时）由 done_callback 移除。
_INFLIGHT_TASKS: set[asyncio.Task] = set()


@dataclass
class _StreamChannel:
    """生产者后台任务与消费者 SSE 响应之间的解耦载体。

    生产者把 SSE 事件 ``put`` 进 ``queue``，``None`` 为关流哨兵；消费者从中读取转发。
    客户端断连时消费者置位 ``consumer_gone``，生产者据此停止入队（但**继续生成与落库**），
    避免无人读取时队列无限增长——这是「断连不取消、后台续跑」的内存兜底。
    """

    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    consumer_gone: asyncio.Event = field(default_factory=asyncio.Event)


async def _run_chat_turn_producer(
    channel: _StreamChannel,
    pipeline: RecallPipeline,
    reranker: PostRecallReranker,
    recall_req: RecallRequest,
    request_id: str,
    user_id: int,
    config_id: int,
    conversation_id: int,
    turn_id: str,
    is_first_turn: bool,
    token_budget: int,
    rerank_top_n: int,
) -> None:
    """后台生产者任务：跑完整召回+生成+落库，独立于 HTTP 连接生命周期。

    客户端断连只取消消费者，本任务不受影响（R1）。名额在此任务 ``finally`` 释放（R6）——
    绑任务而非连接，避免断连即还名额、任务仍在烧 token 却不计数。
    """
    try:
        async for event in recall_event_stream(
            pipeline,
            recall_req,
            request_id,
            config_id=config_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            is_first_turn=is_first_turn,
            reranker=reranker,
            token_budget=token_budget,
            rerank_top_n=rerank_top_n,
        ):
            # 消费者尚在则入队；已断连则跳过入队，但生成与落库继续跑完。
            if not channel.consumer_gone.is_set():
                await channel.queue.put(event)
    except asyncio.CancelledError:
        # 仅进程关闭等会取消本任务；客户端断连不会。向上传播，finally 仍释放名额。
        logger.info("[rag-stream] producer cancelled request_id={}", request_id)
        raise
    except Exception:  # noqa: BLE001 - runtime 内部已收敛各失败为终态落库，这里兜底防任务静默死亡
        logger.exception("[rag-stream] producer crashed request_id={}", request_id)
    finally:
        await channel.queue.put(None)  # 关流哨兵：消费者在场时正常结束
        await release_stream_slot(user_id)


async def _sse_consumer(channel: _StreamChannel) -> AsyncGenerator[str, None]:
    """SSE 响应体：从 channel 读事件转发给前端，**不驱动生成**。

    客户端断连时 Starlette 取消响应协程，``CancelledError`` 打到下面的 ``await get()``。
    用 ``finally`` 置位 ``consumer_gone``（覆盖取消 / GeneratorExit / 正常关流三条退出路径，
    不依赖具体异常类型）让生产者停止入队，随后停止转发——但**不取消生产者任务**，
    生成在后台续跑到落库。正常关流时置位为 no-op（生产者已结束）。
    """
    try:
        while True:
            event = await channel.queue.get()
            if event is None:  # 生产者关流哨兵
                break
            yield event
    finally:
        channel.consumer_gone.set()


@router.post("/stream")
async def rag_stream(
    request: Request,
    ctx: SessionAuthContext = Depends(verify_session_token),
    pipeline: RecallPipeline = Depends(get_recall_pipeline),
    reranker: PostRecallReranker = Depends(get_reranker),
) -> StreamingResponse:
    """对外 RAG 问答流 SSE 入口。"""
    body = await _parse_and_validate_body(request)
    dataset_ids = resolve_dataset_scope(body.dataset_ids, ctx)

    # 数据集级 recall 配置在建流前读出（短 session），把 RRF 候选池 / per-route top_k /
    # 阈值 / token 预算固化为普通值带进流，避免 SSE 生成器执行期再触 DB。
    recall_cfg = await aresolve_recall_config(ctx.user_id, dataset_ids)

    # 并发 acquire 在建流前：超限直接 429（握手前 JSON），不建流、不触发 pipeline。
    if not await acquire_stream_slot(ctx.user_id):
        raise RecallApiError(429, CODE_RATE_LIMITED, "too many concurrent recall streams")

    recall_req = build_recall_request_from_config(
        query=body.query,
        user_id=ctx.user_id,  # 身份以凭证 claims 为准，不信任 body
        dataset_ids=dataset_ids,
        recall_cfg=recall_cfg,
    )

    # 解耦：生成跑在独立后台任务（生产者），SSE 响应只是观察通道（消费者）。客户端断连
    # 取消消费者但不取消生产者——任务续跑到完成并落库（R1）。名额由生产者 finally 释放（R6）。
    channel = _StreamChannel()
    try:
        task = asyncio.create_task(
            _run_chat_turn_producer(
                channel,
                pipeline,
                reranker,
                recall_req,
                ctx.request_id,
                ctx.user_id,
                body.config_id,
                body.conversation_id,
                body.turn_id,
                body.is_first_turn,
                recall_cfg.recall_context_token_budget,
                recall_cfg.rerank_top_n,
            )
        )
    except Exception:
        # 建任务失败：回退已占用的名额，避免泄漏。
        await release_stream_slot(ctx.user_id)
        raise
    _INFLIGHT_TASKS.add(task)
    task.add_done_callback(_INFLIGHT_TASKS.discard)

    return StreamingResponse(
        _sse_consumer(channel),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭网关响应缓冲，保证 SSE 实时
            "X-Request-Id": ctx.request_id,
        },
    )
