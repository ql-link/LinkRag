"""纯召回 JSON 执行 runtime。

对外纯召回端点 ``/api/v1/recall``（``routes/recall.py``）的召回执行与异常映射的
**单一来源**。与 SSE 流式端点的关键区别：不调 CHAT 模型、不回填正文、不建 SSE，
执行期异常映射为 ``RecallApiError``（由 ``src/main.py`` 全局 handler 转 HTTP 状态码），
而非 SSE ``error`` 终态帧。错误码常量与 ``recall_stream_runtime`` 对齐，仅载体不同。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from src.api.internal_auth import (
    CODE_ALL_SOURCES_FAILED,
    CODE_EMBEDDING_CONFIG_MISSING,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_TIMEOUT,
    RecallApiError,
)
from src.api.recall_serialization import serialize_hits
from src.config import settings
from src.core.pipeline.recall import (
    RecallError,
    RecallFatalError,
    RecallPipeline,
    RecallRequest,
    RecallValidationError,
)


async def run_recall_json(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
) -> dict:
    """执行纯召回，返回与 SSE ``recall_done`` 帧同构的 ``{hits, failed_sources}``。

    执行期异常映射为 ``RecallApiError``（HTTP 状态码与错误码）：

    - ``RecallFatalError`` → 422 EMBEDDING_CONFIG_MISSING（发起用户无默认 EMBEDDING 配置，
      dense 路无法编码 query）；**须置于 RecallError 之前**——它是其子类；
    - ``RecallError`` → 500 ALL_SOURCES_FAILED（全部召回路失败）；
    - ``asyncio.TimeoutError`` → 504 TIMEOUT；
    - ``RecallValidationError`` → 422 INVALID_REQUEST（正常已在握手前拦截，此处为安全网）；
    - 其它异常 → 500 INTERNAL_ERROR，message 不含内部堆栈。

    超时上限复用 ``RECALL_STREAM_TIMEOUT_MS``（语义为召回执行超时，与 SSE 端点一致）。
    """
    timeout_seconds = settings.RECALL_STREAM_TIMEOUT_MS / 1000
    try:
        response = await asyncio.wait_for(pipeline.execute(recall_req), timeout=timeout_seconds)
    except RecallValidationError as exc:
        logger.info("[recall-json] validation error request_id={}: {}", request_id, exc)
        raise RecallApiError(422, CODE_INVALID_REQUEST, str(exc))
    except RecallFatalError as exc:
        logger.warning("[recall-json] embedding config missing request_id={}: {}", request_id, exc)
        raise RecallApiError(422, CODE_EMBEDDING_CONFIG_MISSING, "user embedding config missing")
    except RecallError as exc:
        logger.warning("[recall-json] all sources failed request_id={}: {}", request_id, exc)
        raise RecallApiError(500, CODE_ALL_SOURCES_FAILED, "all retrievers failed")
    except asyncio.TimeoutError:
        logger.warning("[recall-json] timeout request_id={}", request_id)
        raise RecallApiError(504, CODE_TIMEOUT, "recall timeout")
    except Exception:  # noqa: BLE001 - 兜底，避免未预期异常泄露堆栈给调用方
        logger.exception("[recall-json] unexpected error request_id={}", request_id)
        raise RecallApiError(500, CODE_INTERNAL_ERROR, "internal error")

    return {
        "hits": serialize_hits(response),
        "failed_sources": response.failed_sources,
    }
