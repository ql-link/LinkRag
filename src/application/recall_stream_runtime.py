"""召回 SSE 流式执行 runtime。

对外 RAG 问答流端点 ``/api/v1/rag/stream``（``routes/rag.py``）的召回融合 +
LLM 流式生成执行与事件序列化的**单一来源**。

- ``recall_event``：序列化单帧 SSE 事件；
- ``recall_event_stream``：流内执行 pipeline，把结果/异常映射为 SSE 终态事件。

hits 序列化抽至 ``recall_serialization``：本 runtime 用 ``serialize_reranked_hits``
（含 rerank 字段），纯召回 JSON 端点用 ``serialize_hits``（仅 RRF 字段）。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator

from loguru import logger

from src.application.recall_errors import (
    CODE_ALL_SOURCES_FAILED,
    CODE_EMBEDDING_CONFIG_MISSING,
    CODE_GENERATION_FAILED,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_MODEL_CONFIG_MISSING,
    CODE_TIMEOUT,
)
from src.application.recall_serialization import serialize_reranked_hits
from src.config import settings
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.user_model_resolver import aresolve_user_model
from src.core.pipeline.recall import (
    RecallError,
    RecallFatalError,
    RecallHit,
    RecallPipeline,
    RecallRequest,
    RecallValidationError,
)
from src.core.pipeline.recall.generation import assemble_context, fetch_chunk_contents
from src.core.pipeline.rerank import (
    PostRecallReranker,
    RerankedHit,
    RerankRequest,
    degrade_to_rrf_order,
)
from src.core.prompts import RAG_GENERATION_SYSTEM_PROMPT, build_rag_user_prompt


def recall_event(name: str, payload: dict) -> str:
    """序列化为单帧 SSE 事件（``data`` 为单行 JSON）。"""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def recall_event_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
    config_id: int,
    reranker: PostRecallReranker,
) -> AsyncGenerator[str, None]:
    """流内执行召回 + 重排 + 生成，把结果/异常映射为 SSE 终态事件。

    先按 ``(user_id, CHAT, config_id)`` 前置校验用户模型——不可用即 ``error``
    MODEL_CONFIG_MISSING、**不进入召回**；通过后执行召回融合，一次性回填片段正文（供
    rerank 与生成共用），对 RRF 候选做 rerank 精排（不可用即降级为 RRF 顺序，见
    ``_rerank_hits``；与召回共享同一条流超时预算），用重排后的最终候选按 token 预算拼装
    上下文，用该模型流式生成——逐 token ``answer_delta``、结束 ``answer_done``（附最终候选
    元信息与 ``rerank_applied``）。生成阶段失败 → ``error`` GENERATION_FAILED（整请求失败）。
    0 命中 / 全部片段缺正文 → ``recall_done``（不生成）。

    通用失败终态：必备前置缺失（用户无默认 EMBEDDING 配置）→ ``error`` EMBEDDING_CONFIG_MISSING；
    全路失败 → ``error`` ALL_SOURCES_FAILED；超时 → ``error`` TIMEOUT；客户端断连 → 停止发送并向上
    传播取消；未预期异常 → ``error`` INTERNAL_ERROR。message 不含内部堆栈。
    """
    timeout_seconds = settings.RECALL_STREAM_TIMEOUT_MS / 1000
    try:
        # 召回前置校验用户模型；不可用即硬失败、不进入召回。
        try:
            resolved = await aresolve_user_model(
                user_id=recall_req.user_id,
                capability="CHAT",
                config_id=config_id,
                allow_system_fallback=False,
            )
        except (UserModelConfigMissingError, ValueError) as exc:
            logger.warning(
                "[recall] model config unavailable request_id={} config_id={}: {}",
                request_id,
                config_id,
                exc,
            )
            yield recall_event(
                "error",
                {
                    "code": CODE_MODEL_CONFIG_MISSING,
                    "message": "selected model is not configured or unavailable",
                },
            )
            return

        recall_started = time.monotonic()
        response = await asyncio.wait_for(pipeline.execute(recall_req), timeout=timeout_seconds)

        # 正文回填一次：rerank 与生成共用同一份正文，避免对同批 chunk 重复查库。
        contents = (
            await fetch_chunk_contents([h.chunk_id for h in response.hits], recall_req.user_id)
            if response.hits
            else {}
        )

        # RRF 候选 → rerank 精排（不可用即降级为 RRF 顺序，截断 top_n）。
        # rerank 与召回共享同一条流超时预算：只把剩余预算交给 rerank，不让两段各占满整窗。
        rerank_budget = timeout_seconds - (time.monotonic() - recall_started)
        reranked_hits, rerank_applied = await _rerank_hits(
            reranker, recall_req, response.hits, contents, rerank_budget, request_id
        )

        # 空命中 / 上下文拼装 / 流式生成（用 rerank 后的最终候选与已回填正文）。
        async for event in _generate_answer(
            resolved,
            reranked_hits,
            rerank_applied,
            contents,
            response.failed_sources,
            recall_req,
            request_id,
        ):
            yield event
    except RecallValidationError as exc:
        # 正常已在握手前拦截；此处为 pipeline 自身安全网的兜底。
        logger.info("[recall] validation error request_id={}: {}", request_id, exc)
        yield recall_event("error", {"code": CODE_INVALID_REQUEST, "message": str(exc)})
    except RecallFatalError as exc:
        # 必备前置缺失（当前：发起用户无默认 EMBEDDING 配置，dense 路无法编码 query）。
        # 须置于 RecallError 之前——RecallFatalError 是其子类。整请求硬失败，不做宽松降级。
        logger.warning("[recall] embedding config missing request_id={}: {}", request_id, exc)
        yield recall_event(
            "error",
            {"code": CODE_EMBEDDING_CONFIG_MISSING, "message": "user embedding config missing"},
        )
    except RecallError as exc:
        logger.warning("[recall] all sources failed request_id={}: {}", request_id, exc)
        yield recall_event(
            "error", {"code": CODE_ALL_SOURCES_FAILED, "message": "all retrievers failed"}
        )
    except asyncio.TimeoutError:
        logger.warning("[recall] timeout request_id={}", request_id)
        yield recall_event("error", {"code": CODE_TIMEOUT, "message": "recall timeout"})
    except asyncio.CancelledError:
        # 客户端断连：停止发送事件，向上传播取消，让 pipeline 协程随之结束。
        logger.info("[recall] client disconnected, cancelling request_id={}", request_id)
        raise
    except Exception:  # noqa: BLE001 - 兜底，避免未预期异常泄露堆栈给调用方
        logger.exception("[recall] unexpected error request_id={}", request_id)
        yield recall_event("error", {"code": CODE_INTERNAL_ERROR, "message": "internal error"})


async def _rerank_hits(
    reranker: PostRecallReranker,
    recall_req: RecallRequest,
    rrf_hits: list[RecallHit],
    contents: dict[str, str],
    timeout_s: float,
    request_id: str,
) -> tuple[list[RerankedHit], bool]:
    """对 RRF 候选执行 rerank 精排，返回 ``(最终候选, rerank_applied)``。

    rerank 是 best-effort 增强：**已知不可用情形降级为 RRF 顺序**，保证 ``rag/stream``
    不因 rerank 不可用而整条失败——「没有 rerank 就用 RRF」。降级口径与 reranker 软降级
    一致：复用 ``degrade_to_rrf_order`` 对**有正文候选**截断到 ``RERANK_DEFAULT_TOP_N``，
    确保无论走哪条降级路，喂给下游的片段集合与数量一致。

    降级覆盖：
    - 软降级（模型调用失败 / 返回不可用）：reranker 内部已返回 RRF 顺序候选且
      ``rerank_applied=False``，原样透出；
    - 硬失败（未配 RERANK 模型 → ``UserModelConfigMissingError`` / provider 不支持 →
      ``ValueError``）、rerank 超时、预算耗尽：此处兜底降级。

    只 catch 已知运维失败；其它未预期异常**向上抛**，由顶层收敛为 ``INTERNAL_ERROR``
    （带堆栈），不被静默吞成"降级"而掩盖真实缺陷。``CancelledError``（客户端断连）向上传播。
    """
    top_n = settings.RERANK_DEFAULT_TOP_N

    def _degrade() -> tuple[list[RerankedHit], bool]:
        scored = [h for h in rrf_hits if contents.get(h.chunk_id)]
        return degrade_to_rrf_order(scored, top_n), False

    # 预算（共享流超时的剩余部分）已耗尽：不再发起 rerank，直接降级。
    if timeout_s <= 0:
        logger.info(
            "[recall] no budget left for rerank, fallback to RRF order request_id={}", request_id
        )
        return _degrade()

    try:
        resp = await asyncio.wait_for(
            reranker.rerank(
                RerankRequest(
                    query=recall_req.query,
                    user_id=recall_req.user_id,
                    hits=rrf_hits,
                    contents=contents,
                )
            ),
            timeout=timeout_s,
        )
        return resp.hits, resp.rerank_applied
    except asyncio.CancelledError:
        raise
    except (UserModelConfigMissingError, ValueError, asyncio.TimeoutError) as exc:
        logger.info(
            "[recall] rerank unavailable, fallback to RRF order request_id={}: {}",
            request_id,
            exc,
        )
        return _degrade()


async def _generate_answer(
    resolved,
    hits: list[RerankedHit],
    rerank_applied: bool,
    contents: dict[str, str],
    failed_sources: list[str],
    recall_req: RecallRequest,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """生成模式后续：空命中判定 → 上下文拼装 → 流式生成。

    入参 ``hits`` 是 rerank 后的最终候选（降级时为 RRF 顺序），``contents`` 是上游一次性
    回填的正文（rerank 与生成共用，不在此重复查库）。上下文拼装与 ``answer_done`` /
    ``recall_done`` 回报均以 ``hits`` 为准；``rerank_applied`` 原样透出。

    - 0 命中 / 全部片段缺正文 → ``recall_done``（不发起生成）；
    - 否则用已解析的用户模型流式生成：逐 token ``answer_delta``、结束 ``answer_done``；
    - 生成阶段任何异常 → ``error`` GENERATION_FAILED（整请求失败，不返回部分召回片段为成功终态）。

    客户端断连的 ``CancelledError`` 向上传播，由顶层处理。
    """
    # 空命中：不进入生成。
    if not hits:
        yield recall_event(
            "recall_done",
            {"hits": [], "rerank_applied": rerank_applied, "failed_sources": failed_sources},
        )
        return

    # 上下文拼装（正文已在上游一次性回填，按 rerank 后顺序纳入）。
    assembled = assemble_context(
        hits, contents, settings.RECALL_GENERATION_CONTEXT_TOKEN_BUDGET
    )
    logger.info(
        "[recall] generation context request_id={} rerank_applied={} hits={} blocks={} skipped_no_content={} truncated={}",
        request_id,
        rerank_applied,
        len(hits),
        len(assembled.blocks),
        assembled.skipped_no_content,
        assembled.truncated,
    )

    # 全部片段缺正文：按空命中处理，不生成。
    if not assembled.blocks:
        yield recall_event(
            "recall_done",
            {
                "hits": serialize_reranked_hits(hits),
                "rerank_applied": rerank_applied,
                "failed_sources": failed_sources,
            },
        )
        return

    # 流式生成：生成阶段失败即整请求失败。
    try:
        user_prompt = build_rag_user_prompt(recall_req.query, assembled.context_text)
        answer_parts: list[str] = []
        async for chunk in resolved.provider.stream(
            prompt=user_prompt,
            system_prompt=RAG_GENERATION_SYSTEM_PROMPT,
        ):
            if chunk.delta:
                answer_parts.append(chunk.delta)
                yield recall_event("answer_delta", {"text": chunk.delta})
        yield recall_event(
            "answer_done",
            {
                "answer": "".join(answer_parts),
                "hits": serialize_reranked_hits(hits),
                "rerank_applied": rerank_applied,
                "failed_sources": failed_sources,
            },
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 生成失败统一收敛为 GENERATION_FAILED
        logger.warning("[recall] generation failed request_id={}: {}", request_id, exc)
        yield recall_event(
            "error",
            {"code": CODE_GENERATION_FAILED, "message": "answer generation failed"},
        )
