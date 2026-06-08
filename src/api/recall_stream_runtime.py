"""召回 SSE 流式执行 runtime。

对外 RAG 问答流端点 ``/api/v1/rag/stream``（``routes/rag.py``）的召回融合 +
LLM 流式生成执行与事件序列化的**单一来源**。

- ``recall_event``：序列化单帧 SSE 事件；
- ``recall_event_stream``：流内执行 pipeline，把结果/异常映射为 SSE 终态事件。

hits 序列化（``serialize_hits``）抽至 ``recall_serialization``，与纯召回 JSON 端点共用。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from loguru import logger

from src.api.internal_auth import (
    CODE_ALL_SOURCES_FAILED,
    CODE_EMBEDDING_CONFIG_MISSING,
    CODE_GENERATION_FAILED,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_MODEL_CONFIG_MISSING,
    CODE_TIMEOUT,
)
from src.api.recall_serialization import serialize_hits
from src.config import settings
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.user_model_resolver import aresolve_user_model
from src.core.pipeline.recall import (
    RecallError,
    RecallFatalError,
    RecallPipeline,
    RecallRequest,
    RecallResponse,
    RecallValidationError,
)
from src.core.pipeline.recall.generation import assemble_context, fetch_chunk_contents
from src.core.prompts import RAG_GENERATION_SYSTEM_PROMPT, build_rag_user_prompt


def recall_event(name: str, payload: dict) -> str:
    """序列化为单帧 SSE 事件（``data`` 为单行 JSON）。"""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def recall_event_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
    config_id: int,
) -> AsyncGenerator[str, None]:
    """流内执行召回 + 生成，把结果/异常映射为 SSE 终态事件。

    先按 ``(user_id, CHAT, config_id)`` 前置校验用户模型——不可用即 ``error``
    MODEL_CONFIG_MISSING、**不进入召回**；通过后执行召回融合，回填片段正文、按 token
    预算拼装上下文，用该模型流式生成——逐 token ``answer_delta``、结束 ``answer_done``
    （附召回片段元信息）。生成阶段失败 → ``error`` GENERATION_FAILED（整请求失败）。
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

        response = await asyncio.wait_for(pipeline.execute(recall_req), timeout=timeout_seconds)

        # 空命中 / 正文回填 / 流式生成。
        async for event in _generate_answer(resolved, response, recall_req, request_id):
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


async def _generate_answer(
    resolved,
    response: RecallResponse,
    recall_req: RecallRequest,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """生成模式后续：空命中判定 → 正文回填 → 上下文拼装 → 流式生成。

    - 0 命中 / 全部片段缺正文 → ``recall_done``（不发起生成）；
    - 否则用已解析的用户模型流式生成：逐 token ``answer_delta``、结束 ``answer_done``；
    - 生成阶段任何异常 → ``error`` GENERATION_FAILED（整请求失败，不返回部分召回片段为成功终态）。

    客户端断连的 ``CancelledError`` 向上传播，由顶层处理。
    """
    # 空命中：不进入生成。
    if not response.hits:
        yield recall_event(
            "recall_done",
            {"hits": [], "failed_sources": response.failed_sources},
        )
        return

    # 正文回填 + 上下文拼装。
    contents = await fetch_chunk_contents([h.chunk_id for h in response.hits], recall_req.user_id)
    assembled = assemble_context(
        response.hits, contents, settings.RECALL_GENERATION_CONTEXT_TOKEN_BUDGET
    )
    logger.info(
        "[recall] generation context request_id={} hits={} blocks={} skipped_no_content={} truncated={}",
        request_id,
        len(response.hits),
        len(assembled.blocks),
        assembled.skipped_no_content,
        assembled.truncated,
    )

    # 全部片段缺正文：按空命中处理，不生成。
    if not assembled.blocks:
        yield recall_event(
            "recall_done",
            {"hits": serialize_hits(response), "failed_sources": response.failed_sources},
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
                "hits": serialize_hits(response),
                "failed_sources": response.failed_sources,
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
