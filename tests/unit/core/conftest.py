"""Shared test fixtures for src/core/* unit tests.

提供跨模块复用的 chunk 真值构造器，让 dense / sparse / repository / parse_task
等模块的测试用同一套方式构造 ``ChunkRecordDB``：仅传必要字段，其它字段给合理默认。

放在 ``tests/unit/core/conftest.py`` 而非 ``tests/conftest.py``，是为了把作用范围
限定在 core 业务模块的单测（API / service 层不需要 ORM 行真值）。
"""

from __future__ import annotations

from typing import Any

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_PENDING,
    ES_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.models.chunk_record import ChunkRecordDB


def make_chunk_record(
    chunk_id: str,
    *,
    doc_id: int = 10001,
    user_id: int = 10002,
    set_id: int = 10003,
    bucket_id: int = 0,
    content: str = "alpha",
    content_hash: str = "sha-fake",
    chunk_type: str = "text",
    start_line: int = 1,
    end_line: int = 10,
    chunk_index: int = 0,
    dense: str = CHUNK_STATUS_PENDING,
    sparse: str = SPARSE_VECTOR_STATUS_PENDING,
    es: str = ES_STATUS_PENDING,
    dense_model: str | None = None,
    sparse_model: str | None = None,
    **extra: Any,
) -> ChunkRecordDB:
    """构造一个 ``ChunkRecordDB`` 实例供单测使用。

    设计原则：
    - 必填只有 ``chunk_id``；其它字段给合理默认，调用方仅覆盖关心的字段。
    - 状态字段（dense / sparse / es）使用短名 ``dense`` / ``sparse`` / ``es``，
      让"按状态构造混合批次"的测试代码尽量短：
      ``make_chunk_record("c1", dense="SUCCESS", sparse="PENDING")``。
    - 不主动构造 ``id`` / ``create_time`` / ``update_time``——交给 SQLAlchemy 默认值。
    - ``**extra`` 用于偶发的边缘字段覆盖；正常测试不应使用。
    """

    return ChunkRecordDB(
        chunk_id=chunk_id,
        doc_id=doc_id,
        user_id=user_id,
        set_id=set_id,
        bucket_id=bucket_id,
        content=content,
        content_hash=content_hash,
        chunk_type=chunk_type,
        start_line=start_line,
        end_line=end_line,
        chunk_index=chunk_index,
        dense_vector_status=dense,
        dense_vector_model=dense_model,
        sparse_vector_status=sparse,
        sparse_vector_model=sparse_model,
        es_status=es,
        **extra,
    )
