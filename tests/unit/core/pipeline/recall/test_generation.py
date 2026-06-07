"""``assemble_context`` 上下文拼装逻辑单测：跳过缺正文、超预算截尾、排序保持。"""

from __future__ import annotations

from src.core.llm.tokenizer import Tokenizer
from src.core.pipeline.recall.generation import assemble_context
from src.core.pipeline.recall.models import RecallHit


def _hit(cid: str) -> RecallHit:
    return RecallHit(cid, 10, 1, 1.0, {})


def test_skips_chunks_without_content():
    hits = [_hit(f"c{i}") for i in range(5)]
    contents = {"c0": "a", "c1": "b", "c3": "d"}
    result = assemble_context(hits, contents, token_budget=10_000)
    assert [b.chunk_id for b in result.blocks] == ["c0", "c1", "c3"]
    assert result.skipped_no_content == 2
    assert result.truncated == 0


def test_all_missing_content_yields_no_blocks():
    hits = [_hit(f"c{i}") for i in range(3)]
    result = assemble_context(hits, {}, token_budget=10_000)
    assert result.blocks == []
    assert result.skipped_no_content == 3


def test_truncates_tail_when_over_budget():
    tok = Tokenizer()
    contents = {f"c{i}": "数据内容片段示例" + str(i) * 5 for i in range(4)}
    hits = [_hit(f"c{i}") for i in range(4)]
    budget = sum(tok.count_tokens(contents[f"c{i}"]) for i in range(3))
    result = assemble_context(hits, contents, token_budget=budget, tokenizer=tok)
    assert [b.chunk_id for b in result.blocks] == ["c0", "c1", "c2"]
    assert result.truncated == 1


def test_preserves_fusion_order_and_numbers_blocks():
    hits = [_hit("c1"), _hit("c2")]
    contents = {"c1": "alpha", "c2": "beta"}
    result = assemble_context(hits, contents, token_budget=10_000)
    assert "[片段1] alpha" in result.context_text
    assert "[片段2] beta" in result.context_text
    assert result.context_text.index("片段1") < result.context_text.index("片段2")


def test_always_includes_first_chunk_even_if_over_budget():
    hits = [_hit("c1"), _hit("c2")]
    contents = {"c1": "很长的正文" * 50, "c2": "短"}
    result = assemble_context(hits, contents, token_budget=1)
    # 至少纳入第一个有正文片段，避免空上下文；其余超预算截断。
    assert result.blocks[0].chunk_id == "c1"
    assert result.truncated == 1
