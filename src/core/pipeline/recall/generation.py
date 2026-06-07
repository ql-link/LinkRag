"""召回后生成阶段的上下文准备：片段正文回填 + 按 token 预算拼装上下文。

职责边界（与 pipeline 纯召回分离）：
- :func:`fetch_chunk_contents`：按 chunk_id 批量一次反查 MySQL ``kb_document_chunk``
  取正文（只取本用户、ACTIVE、非空正文）。召回结果按设计不含正文，正文留在 MySQL。
- :func:`assemble_context`：把命中片段按融合排序（调用方已降序）依次纳入，累计 token
  超预算则截断尾部低分片段；查不到正文的片段跳过。产出可直接注入 prompt 的上下文文本
  与可观测计数（纳入 / 跳过 / 截断）。

不做：query 预处理、向量化、reranker、调用 LLM——生成调用在 runtime 编排层。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from src.core.chunk_fact_storage.constants import CHUNK_LIFECYCLE_ACTIVE
from src.core.llm.tokenizer import Tokenizer
from src.core.pipeline.recall.models import RecallHit
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


@dataclass
class ContextBlock:
    """单个纳入上下文的片段。"""

    chunk_id: str
    content: str


@dataclass
class AssembledContext:
    """上下文拼装产物：注入 prompt 的文本 + 可观测计数。

    Attributes:
        blocks: 实际纳入上下文的片段（按融合排序，已通过预算）。
        context_text: 编号拼装后的上下文文本，可直接注入 user prompt。
        skipped_no_content: 因查不到正文被跳过的片段数。
        truncated: 因超 token 预算被截断的（有正文的）片段数。
    """

    blocks: list[ContextBlock] = field(default_factory=list)
    context_text: str = ""
    skipped_no_content: int = 0
    truncated: int = 0


def assemble_context(
    hits: list[RecallHit],
    contents: dict[str, str],
    token_budget: int,
    tokenizer: Tokenizer | None = None,
) -> AssembledContext:
    """按融合排序与 token 预算拼装上下文。

    规则：
    - hits 已按 fused_score 降序（调用方保证）；按此顺序依次纳入。
    - 查不到正文的片段跳过并计入 ``skipped_no_content``，不打断后续纳入。
    - 累计 token 超 ``token_budget`` 时停止纳入，其余有正文的片段计入 ``truncated``。
    - 至少纳入第一个有正文的片段（即便其单片超预算），避免空上下文。
    """
    tok = tokenizer or Tokenizer()
    result = AssembledContext()
    used_tokens = 0

    for hit in hits:
        content = contents.get(hit.chunk_id)
        if not content:
            result.skipped_no_content += 1
            continue

        cost = tok.count_tokens(content)
        # 预算判定：已纳入至少一个片段后，超预算则截断剩余有正文片段。
        if result.blocks and used_tokens + cost > token_budget:
            result.truncated += 1
            continue

        result.blocks.append(ContextBlock(chunk_id=hit.chunk_id, content=content))
        used_tokens += cost

    result.context_text = "\n\n".join(
        f"[片段{i}] {block.content}" for i, block in enumerate(result.blocks, start=1)
    )
    return result
