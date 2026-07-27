from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import mysql

from src.core.storage.wiki_tree.repository import WikiTreeRepository
from src.core.wiki.models import (
    EffectiveWikiScope,
    WikiChunkRecord,
    WikiChunkRefDraft,
    WikiHeadingDraft,
    WikiHeadingRecord,
    WikiTreeDraft,
)


class _Rows:
    """为仓储单元测试提供最小 SQLAlchemy 行结果接口。"""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


def _scope() -> EffectiveWikiScope:
    return EffectiveWikiScope(user_id=123, dataset_ids=(10,), doc_ids=None, doc_ids_by_dataset={})


def _heading(node_id: int = 1) -> WikiHeadingRecord:
    return WikiHeadingRecord(
        id=node_id,
        heading_key=f"{node_id:064x}",
        doc_id=10001,
        dataset_id=10,
        original_filename="guide.md",
        parent_id=None,
        title="Guide",
        heading_level=1,
        sort_order=0,
    )


def _compiled_sql(statement: object) -> str:
    """按真实 MySQL 方言展开绑定值，便于锁定索引友好的 SQL 形态。"""

    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,title", [("exact", "gUiDe"), ("prefix", r"Guide%_")])
async def test_heading_query_keeps_title_column_bare_for_composite_index(mode, title):
    repository = WikiTreeRepository()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Rows([]))

    await repository.find_heading_page(
        session,
        mode=mode,
        normalized_title=title,
        scope=_scope(),
        after=None,
        limit=15,
    )

    sql = _compiled_sql(session.execute.await_args.args[0])
    assert "lower(" not in sql
    assert "wiki_tree_node.title = 'guide'" in sql or "wiki_tree_node.title like 'guide" in sql
    if mode == "prefix":
        assert "escape" in sql


@pytest.mark.asyncio
async def test_heading_preview_counts_all_refs_but_transfers_only_first_row():
    repository = WikiTreeRepository()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Rows([(1, 101, 0, "C1", 5000)]))

    preview = await repository.load_heading_previews(session, (_heading(),), scope=_scope())

    sql = _compiled_sql(session.execute.await_args.args[0])
    assert "count(*) over" in sql
    assert "row_number() over" in sql
    assert "position_rank = 1" in sql
    assert preview[1].direct_chunk_count == 5000
    assert preview[1].chunk_id == "C1"


@pytest.mark.asyncio
@pytest.mark.parametrize("position_count", [10, 11, 5000])
async def test_chunk_locations_apply_position_limit_before_parent_path_hydration(
    monkeypatch, position_count
):
    repository = WikiTreeRepository()
    chunk = WikiChunkRecord("C1", 10001, 10, "content", "paragraph", 1, 2)
    monkeypatch.setattr(repository, "load_chunks", AsyncMock(return_value=(chunk,)))
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_Rows(
            [
                ("C1", heading_id, position_count, heading_id)
                for heading_id in range(1, min(position_count, 10) + 1)
            ]
        )
    )

    locations = await repository.load_chunk_locations(
        session,
        ("C1",),
        scope=_scope(),
        max_positions=10,
    )

    sql = _compiled_sql(session.execute.await_args.args[0])
    assert "count(*) over" in sql
    assert "row_number() over" in sql
    assert "position_rank <= 10" in sql
    assert locations[0].heading_ids == tuple(range(1, min(position_count, 10) + 1))
    assert locations[0].position_count == position_count


@pytest.mark.asyncio
async def test_tree_replacement_flushes_once_per_heading_level_and_once_for_refs(monkeypatch):
    repository = WikiTreeRepository()
    monkeypatch.setattr(repository, "delete_by_doc_id", AsyncMock(return_value=3))
    session = MagicMock()
    session.flush = AsyncMock()
    next_id = 10000
    batches: list[list[object]] = []

    def add_all(records):
        nonlocal next_id
        batch = list(records)
        batches.append(batch)
        for record in batch:
            if record.id is None:
                next_id += 1
                record.id = next_id

    session.add_all.side_effect = add_all
    headings: list[WikiHeadingDraft] = []
    previous = {"a": None, "b": None}
    for level in range(1, 7):
        for branch in ("a", "b"):
            key = f"{level * 2 + (branch == 'b'):064x}"
            headings.append(
                WikiHeadingDraft(
                    heading_key=key,
                    title=f"{branch.upper()}{level}",
                    heading_level=level,
                    parent_heading_key=previous[branch],
                    sort_order=0 if branch == "a" else 1,
                )
            )
            previous[branch] = key
    tree = WikiTreeDraft(
        headings=tuple(reversed(headings)),
        chunk_refs=(WikiChunkRefDraft("C1", previous["a"], 0),),
    )

    result = await repository.replace_document_tree(session, 10001, tree)

    assert result.deleted_count == 3
    assert result.heading_count == 12
    assert session.flush.await_count == 7
    assert [len(batch) for batch in batches] == [2, 2, 2, 2, 2, 2, 1]
    deepest_a = next(record for record in batches[-2] if record.title == "A6")
    assert batches[-1][0].parent_id == deepest_a.id
