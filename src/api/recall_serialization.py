"""召回命中序列化的单一来源。

SSE 流式端点（``recall_stream_runtime``）与纯召回 JSON 端点（``recall_json_runtime``）
共用本模块，确保两种载体（SSE 帧 / HTTP JSON）输出的 hits 结构一致，避免双链路漂移。
"""

from __future__ import annotations

from src.core.pipeline.recall import RecallResponse
from src.core.pipeline.rerank import RerankedHit


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


def serialize_reranked_hits(hits: list[RerankedHit]) -> list[dict]:
    """把重排后命中裁剪为最小候选；在 RRF 字段基础上补 rerank 分与名次，不含 chunk 正文。

    ``rerank_score`` / ``rerank_rank`` 在 rerank 未生效（降级）或某候选未拿到 rerank
    分时为 ``None``——降级与「rerank 生效但该候选落入无分 tail」都用 ``None`` 表达，
    调用方据顶层 ``rerank_applied`` 区分二者。
    """
    return [
        {
            "chunk_id": str(h.chunk_id),
            "doc_id": h.doc_id,
            "dataset_id": h.dataset_id,
            "fused_score": h.fused_score,
            "scores": h.scores,
            "rerank_score": h.rerank_score,
            "rerank_rank": h.rerank_rank,
        }
        for h in hits
    ]
