"""标准 ``/rerank`` 调用助手（多 provider 共享）。

Jina / Cohere / 硅基流动(SiliconFlow) 等厂商提供同构的 ``POST /rerank`` 端点：
请求体 ``{model, query, documents, top_n?, return_documents}``，响应体
``{results:[{index, relevance_score, document}], tokens|usage}``。各 OpenAI 兼容 provider
（openai/qwen/glm/deepseek）的 HTTP 客户端都暴露同一个 ``_post(endpoint, json)`` 协程，本模块把这套
契约与解析收敛到一处，由各 provider 的 ``rerank()`` 复用，统一产出
:class:`~src.core.llm.response.RerankResult`，避免在每个 provider 里重复实现与解析漂移。
"""
from __future__ import annotations

from typing import Awaitable, Callable, List, Optional

from src.core.llm.response import RerankItem, RerankResult, UsageInfo

# provider client 的 ``_post(endpoint, json) -> dict`` 协程签名。
PostFn = Callable[[str, dict], Awaitable[dict]]


def build_rerank_payload(
    query: str,
    documents: List[str],
    model: str,
    top_n: Optional[int],
    extra: Optional[dict] = None,
) -> dict:
    """构造标准 ``/rerank`` 请求体。

    ``top_n=None`` 时不写入 ``top_n`` 字段——表示对全部 ``documents`` 打分、不在 provider 侧截断，
    截断与取 Top-K 交由调用方（如 LINK-130 的 ``PostRecallReranker``）自行处理。
    """
    payload: dict = {
        "model": model,
        "query": query,
        "documents": documents,
        "return_documents": True,
    }
    if top_n is not None:
        payload["top_n"] = top_n
    if extra:
        payload.update(extra)
    return payload


def _extract_text(item: dict, documents: List[str]) -> str:
    """取重排项对应的文档正文。

    优先用 provider 回填的 ``document``（dict 形如 ``{"text": ...}`` 或直接是字符串）；
    未回填时按 ``index`` 从入参 ``documents`` 取回（契约保证 index 对齐入参顺序）。
    """
    doc = item.get("document")
    if isinstance(doc, dict):
        text = doc.get("text")
        if text is not None:
            return text
    elif isinstance(doc, str):
        return doc

    index = item.get("index")
    if isinstance(index, int) and 0 <= index < len(documents):
        return documents[index]
    return ""


def _extract_usage(data: dict) -> UsageInfo:
    """解析用量。

    各厂商字段不一：硅基流动用 ``tokens{input_tokens,output_tokens}``，标准 OpenAI 风格用
    ``usage{prompt_tokens,total_tokens}``。两者都缺时退化为 0，不因用量缺失而失败。
    """
    tokens = data.get("tokens") or {}
    usage = data.get("usage") or {}
    prompt = tokens.get("input_tokens") or usage.get("prompt_tokens") or 0
    completion = tokens.get("output_tokens") or usage.get("completion_tokens") or 0
    total = usage.get("total_tokens") or (prompt + completion)
    return UsageInfo(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def parse_rerank_response(data: dict, model: str, documents: List[str]) -> RerankResult:
    """把标准 ``/rerank`` 响应解析为 :class:`RerankResult`。"""
    raw_results = data.get("results") or []
    items = [
        RerankItem(
            index=item.get("index", 0),
            score=float(item.get("relevance_score", item.get("score", 0.0))),
            text=_extract_text(item, documents),
        )
        for item in raw_results
    ]
    return RerankResult(
        model=data.get("model", model),
        results=items,
        usage=_extract_usage(data),
    )


async def standard_rerank(
    post: PostFn,
    *,
    query: str,
    documents: List[str],
    model: str,
    top_n: Optional[int] = None,
    endpoint: str = "/rerank",
    **kwargs,
) -> RerankResult:
    """对 OpenAI 兼容 provider 发起标准 ``/rerank`` 调用并解析。

    Args:
        post: provider client 的 ``_post(endpoint, json)`` 协程。
        query: 查询串。
        documents: 待重排文档正文列表。``documents`` 为空时直接返回空结果，不发起请求。
        model: rerank 模型名（必填，无内置默认 rerank 模型）。
        top_n: ``None`` 表示对全部 ``documents`` 打分、不在 provider 侧截断。
        endpoint: rerank 端点路径，默认 ``/rerank``。
        **kwargs: 透传到请求体的额外字段。

    Returns:
        RerankResult: ``results`` 按 provider 返回顺序（通常按分数降序）排列。
    """
    if not documents:
        return RerankResult(model=model, results=[], usage=UsageInfo())

    payload = build_rerank_payload(query, documents, model, top_n, extra=kwargs or None)
    data = await post(endpoint, payload)
    return parse_rerank_response(data, model, documents)
