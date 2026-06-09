"""召回 API 的共享错误类型与错误码。

外部用户态 Recall API 归属 Java（复用 Sa-Token + dataset/doc 归属校验）；Python 暴露
对外 RAG 问答流 ``/api/v1/rag/stream`` 与纯召回 JSON ``/api/v1/recall``（鉴权见
``recall_session_auth``）。本模块提供两条召回链路共用的：

- ``RecallApiError``：握手前错误的统一类型，由 ``src/main.py`` 注册的异常处理器
  序列化为 ``{code, message, data}`` JSON + 对应 HTTP 状态。
- ``CODE_*``：错误码常量，与 docs/api/error_codes.md 保持一致。
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request

# 错误码常量：与 docs/api/error_codes.md 保持一致。
CODE_SCOPE_FORBIDDEN = "RECALL_SCOPE_FORBIDDEN"
CODE_INVALID_REQUEST = "RECALL_INVALID_REQUEST"
CODE_ALL_SOURCES_FAILED = "RECALL_ALL_SOURCES_FAILED"
CODE_TIMEOUT = "RECALL_TIMEOUT"
CODE_INTERNAL_ERROR = "RECALL_INTERNAL_ERROR"
# 发起用户无默认 EMBEDDING 配置：dense 召回无法编码 query，整请求硬失败。
CODE_EMBEDDING_CONFIG_MISSING = "RECALL_EMBEDDING_CONFIG_MISSING"
# 对外直连 SSE（LINK-40）专属错误码。
CODE_SESSION_UNAUTHORIZED = "RECALL_SESSION_UNAUTHORIZED"
CODE_RATE_LIMITED = "RECALL_RATE_LIMITED"
# 召回后 LLM 生成（recall-answer-generation）：
# 前置模型校验失败——所选 config_id 不属于本用户 / 非 CHAT 能力 / 已停用 / 不存在；
# 模型不可用，整请求前置硬失败、不进入召回。
CODE_MODEL_CONFIG_MISSING = "RECALL_MODEL_CONFIG_MISSING"
# 生成阶段 LLM 调用失败（超时/报错/限流）：生成是召回固有部分，生成失败即整请求失败。
CODE_GENERATION_FAILED = "RECALL_GENERATION_FAILED"


class RecallApiError(Exception):
    """握手前错误：携带 HTTP 状态与业务错误码。

    路由与鉴权依赖只抛本异常，由全局异常处理器统一转 JSON 响应，避免散落的
    ``HTTPException`` 破坏 ``{code, message, data}`` 响应体约定。
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _request_id(request: Request) -> str:
    """取请求 ``X-Request-Id``，缺省时生成；两条召回链路共用。"""
    return request.headers.get("X-Request-Id") or uuid4().hex
