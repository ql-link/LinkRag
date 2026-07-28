"""BM25 召回的后端无关异常。"""

from __future__ import annotations

import asyncio

_TRANSIENT_MYSQL_ERRNOS = {2002, 2003, 2006, 2013, 2055}


def _http_status(exc: BaseException) -> int | None:
    """从异常本身或其响应对象中提取可用的 HTTP 状态码。"""

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def is_transient_bm25_error(exc: BaseException) -> bool:
    """沿异常链识别可安全重试的 BM25 读取故障，不解析不稳定的错误文本。"""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
            return True
        if _http_status(current) in {502, 503, 504}:
            return True
        module = type(current).__module__
        name = type(current).__name__
        if (
            module.startswith(("pymysql", "aiomysql"))
            and name in {"OperationalError", "InterfaceError"}
            and current.args
            and isinstance(current.args[0], int)
            and current.args[0] in _TRANSIENT_MYSQL_ERRNOS
        ):
            return True
        if module.startswith("httpx") and name in {
            "TimeoutException",
            "ConnectError",
            "ReadError",
            "WriteError",
            "CloseError",
            "PoolTimeout",
            "NetworkError",
        }:
            return True
        if module.startswith("aiohttp") and name in {
            "ClientConnectionError",
            "ServerConnectionError",
            "ServerDisconnectedError",
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


class Bm25RecallValidationError(ValueError):
    """BM25 召回请求参数不合法。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            message
            if message.startswith("bm25_recall_validation:")
            else f"bm25_recall_validation: {message}"
        )


class Bm25RetrievalError(Exception):
    """BM25 后端查询失败。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            message if message.startswith("bm25_retrieval:") else f"bm25_retrieval: {message}"
        )
