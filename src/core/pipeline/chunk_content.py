"""chunk 正文回填：按 chunk_id 批量反查 MySQL 取本用户 ACTIVE 非空正文。

中立的数据访问 helper，供召回后多个下游消费方共享：

- :mod:`src.core.pipeline.rerank`：重排前按 RRF 候选回填正文喂给 rerank 模型；
- :mod:`src.core.pipeline.recall.generation`：生成阶段拼装上下文前回填正文。

放在 ``pipeline/`` 根下（而非 ``recall/`` 或 ``rerank/`` 内），让两个子包平级引用，
避免 rerank 反向依赖 generation。召回结果按设计不含正文，正文统一留在 MySQL 按需反查。
"""

from __future__ import annotations

from sqlalchemy import select

from src.core.chunk_fact_storage.constants import CHUNK_LIFECYCLE_ACTIVE
from src.database import get_async_session_factory
from src.models.chunk_record import ChunkRecordDB


async def fetch_chunk_contents(chunk_ids: list[str], user_id: int) -> dict[str, str]:
    """按 chunk_id 批量反查正文，返回 chunk_id -> 正文映射。

    只回填发起用户本人、生命周期 ACTIVE、正文非空的片段；查不到的 chunk_id 不出现在
    返回 dict 中（由调用方按「跳过」处理）。批量一次查询，不逐条，避免放大 DB 往返。
    """
    if not chunk_ids:
        return {}

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        stmt = select(ChunkRecordDB.chunk_id, ChunkRecordDB.content).where(
            ChunkRecordDB.chunk_id.in_(chunk_ids),
            ChunkRecordDB.user_id == user_id,
            ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
        )
        rows = (await session.execute(stmt)).all()

    return {chunk_id: content for chunk_id, content in rows if content and content.strip()}
