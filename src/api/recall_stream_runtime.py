"""召回 SSE 流式执行 runtime（内部端点与对外直连端点共享）。

从 ``routes/recall.py`` 抽取，作为召回流式执行与事件序列化的**单一来源**：
内部端点 ``/api/v1/internal/recall/stream`` 与对外直连端点 ``/api/v1/recall/stream``
都复用本模块，确保两条链路的 SSE 事件协议、降级与失败终态语义不发生漂移。

- ``recall_event``：序列化单帧 SSE 事件；
- ``serialize_hits``：把 ``RecallResponse`` 命中裁剪为最小候选（不含正文）；
- ``recall_event_stream``：流内执行 pipeline，把结果/异常映射为 SSE 终态事件。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from loguru import logger

from src.api.internal_auth import (
    CODE_ALL_SOURCES_FAILED,
    CODE_EMBEDDING_CONFIG_MISSING,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_TIMEOUT,
)
from src.config import settings
from src.core.pipeline.recall import (
    RecallError,
    RecallFatalError,
    RecallPipeline,
    RecallRequest,
    RecallResponse,
    RecallValidationError,
)


def recall_event(name: str, payload: dict) -> str:
    """序列化为单帧 SSE 事件（``data`` 为单行 JSON）。"""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def serialize_hits(response: RecallResponse) -> list[dict]:
    """把融合命中裁剪为最小候选；不含 chunk 正文。"""
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


async def recall_event_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """流内执行 pipeline，把结果/异常映射为 SSE 终态事件。

    成功（含宽松降级）→ ``recall_done``；必备前置缺失（用户无默认 EMBEDDING 配置）→
    ``error`` EMBEDDING_CONFIG_MISSING（硬失败，不降级）；全路失败 → ``error``
    ALL_SOURCES_FAILED；超时 → ``error`` TIMEOUT；客户端断连 → 停止发送并向上传播取消
    （pipeline 协程随之取消）；未预期异常 → ``error`` INTERNAL_ERROR。message 不含内部堆栈。
    """
    timeout_seconds = settings.RECALL_STREAM_TIMEOUT_MS / 1000
    try:
        response = await asyncio.wait_for(
            pipeline.execute(recall_req), timeout=timeout_seconds
        )
        yield recall_event(
            "recall_done",
            {"hits": serialize_hits(response), "failed_sources": response.failed_sources},
        )
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
