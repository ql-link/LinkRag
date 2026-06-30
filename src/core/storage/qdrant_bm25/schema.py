"""Qdrant BM25 后端的命名常量。

BM25 这一路是**新增的另一条 sparse 向量命名空间**，与现有 BGE-M3 learned sparse
（named vector ``sparse_text``，无 IDF modifier）并存、互不干扰：
- ``bm25_text`` 带 ``Modifier.IDF``，装 coarse+fine 双段 BM25 统计权重（纯字面精准匹配）。
- ``sparse_text`` 不带 modifier，装的是模型学出来的语义权重。

payload 字段名与 ES 后端对齐，便于召回侧多租户 filter 与 Formula 类型加权
按相同语义引用。
"""

from __future__ import annotations

# BM25 专用 named sparse vector（带 Modifier.IDF）。coarse 与 fine 两段 token 编进
# 同一向量的隔离 hash 维度空间（见 encoder），单次点积即 coarse+fine 双路 BM25。
DEFAULT_BM25_VECTOR_NAME = "bm25_text"

# payload 字段（与 es/document_factory 对齐）。
PAYLOAD_CHUNK_ID = "chunk_id"
PAYLOAD_DOC_ID = "doc_id"
PAYLOAD_USER_ID = "user_id"
PAYLOAD_DATASET_ID = "dataset_id"
PAYLOAD_CHUNK_TYPE = "chunk_type"
