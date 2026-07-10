"""ManticoreBm25IndexingPipeline 单元测试：写入/删除逻辑（fake store/repo/db，不连 Manticore/DB）。

plan/chunk/meta 用 SimpleNamespace 鸭子构造——pipeline 只读属性、不强制真实类型。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.storage.manticore_bm25 import ManticoreBm25IndexingPipeline
from src.core.storage.manticore_bm25 import pipeline as pipeline_module


class _FakeStore:
    def __init__(self, *, unverified: set[str] | None = None) -> None:
        self.ensured: list[int] = []
        self.upserted: list = []
        self.deleted: list = []
        self.dropped: list[tuple[int, int]] = []
        # 模拟"REPLACE INTO 没抛异常，但回读校验查不到"的那部分 chunk_id。
        self._unverified = unverified or set()

    async def ensure_table(self, dataset_id: int) -> str:
        self.ensured.append(dataset_id)
        return f"bm25_ds_{dataset_id}"

    async def upsert_chunks(self, points) -> list[str]:
        self.upserted.extend(points)
        return [p.chunk_id for p in points if p.chunk_id not in self._unverified]

    async def delete_by_document(self, *, user_id, dataset_id, doc_id) -> int:
        self.deleted.append((user_id, dataset_id, doc_id))
        return 3  # 非零，用于验证 pipeline 层原样透传返回值、不做硬编码

    async def drop_table(self, dataset_id: int, *, user_id: int) -> None:
        self.dropped.append((user_id, dataset_id))


class _FakeRepo:
    def __init__(self) -> None:
        self.success: list = []
        self.failed: list = []

    async def mark_es_success(self, db, ids) -> None:
        self.success.extend(ids)

    async def mark_es_failed(self, db, ids, error_msg) -> None:
        self.failed.append((list(ids), error_msg))


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _chunk(cid, idx, ctype, coarse, fine):
    return SimpleNamespace(
        chunk_id=cid, chunk_index=idx, chunk_type=ctype, coarse_tokens=coarse, fine_tokens=fine
    )


def _plan(chunks, *, doc_id=1, user_id=1, dataset_id=2):
    return SimpleNamespace(
        chunks_with_tokens=chunks,
        file_meta=SimpleNamespace(doc_id=doc_id, user_id=user_id, dataset_id=dataset_id),
    )


def _pipeline(*, unverified: set[str] | None = None):
    store = _FakeStore(unverified=unverified)
    repo = _FakeRepo()
    pipe = ManticoreBm25IndexingPipeline(store=store, chunk_repository=repo)
    return pipe, store, repo


async def test_write_indexes_valid_chunks() -> None:
    pipe, store, repo = _pipeline()
    plan = _plan(
        [
            _chunk("c1", 0, "heading", "退费 流程", "退费 流程"),
            _chunk("c2", 1, "normal", "查询 系统", "查询 系统"),
        ]
    )
    res = await pipe.write_es_index(plan, db=_FakeDB())
    assert res.total_items == 2
    assert res.indexed_items == 2
    assert store.ensured == [2]
    assert {p.chunk_id for p in store.upserted} == {"c1", "c2"}
    p = store.upserted[0]
    assert (p.doc_id, p.user_id, p.dataset_id) == (1, 1, 2)
    assert p.coarse_tokens == "退费 流程"
    assert set(repo.success) == {"c1", "c2"}


async def test_write_marks_invalid_chunk_failed() -> None:
    pipe, store, repo = _pipeline()
    plan = _plan(
        [
            _chunk("ok", 0, "normal", "退费", "退费"),
            _chunk("bad", 1, "normal", "", ""),  # coarse 空 → 校验失败
        ]
    )
    res = await pipe.write_es_index(plan, db=_FakeDB())
    assert res.indexed_items == 1
    assert "bad" in res.failed_item_ids
    assert any("bad" in ids for ids, _ in repo.failed)
    assert {p.chunk_id for p in store.upserted} == {"ok"}


async def test_write_marks_chunk_failed_when_not_confirmed_by_readback() -> None:
    # REPLACE INTO 没抛异常（校验通过、进了 upserted），但批量回读没查到 "c2"——
    # 这条必须被标记为失败，不能因为整批没抛异常就被当成全部成功。
    pipe, store, repo = _pipeline(unverified={"c2"})
    plan = _plan(
        [
            _chunk("c1", 0, "heading", "退费 流程", "退费 流程"),
            _chunk("c2", 1, "normal", "查询 系统", "查询 系统"),
        ]
    )
    res = await pipe.write_es_index(plan, db=_FakeDB())
    assert res.indexed_items == 1
    assert res.failed_item_ids == ["c2"]
    assert set(repo.success) == {"c1"}
    assert any("c2" in ids for ids, _ in repo.failed)
    # 两条都确实发起过写入尝试（upsert_chunks 收到了完整批次）。
    assert {p.chunk_id for p in store.upserted} == {"c1", "c2"}


async def test_empty_plan_is_noop() -> None:
    pipe, store, _ = _pipeline()
    res = await pipe.write_es_index(_plan([]), db=_FakeDB())
    assert res.total_items == 0
    assert res.indexed_items == 0
    assert store.upserted == [] and store.ensured == []


async def test_delete_delegates_to_store_with_user_id_guard() -> None:
    pipe, store, _ = _pipeline()
    n = await pipe.delete_document_index(user_id=3, dataset_id=4, doc_id=9)
    assert n == 3  # 原样透传 store 的真实删除行数，不能被 pipeline 层拍平成 0
    assert store.deleted == [(3, 4, 9)]


async def test_delete_by_dataset_delegates_to_store_drop_table() -> None:
    pipe, store, _ = _pipeline()
    await pipe.delete_by_dataset(user_id=3, dataset_id=7)
    assert store.dropped == [(3, 7)]


async def test_fine_tokens_are_not_required_by_coarse_only_baseline() -> None:
    pipe, store, repo = _pipeline()
    res = await pipe.write_es_index(
        _plan([_chunk("c1", 0, "normal", "退费 流程", "")]), db=_FakeDB()
    )

    assert res.is_success
    assert [point.chunk_id for point in store.upserted] == ["c1"]


async def test_oversized_coarse_tokens_are_rejected_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module.settings, "MANTICORE_MAX_DOCUMENT_BYTES", 8)
    pipe, store, repo = _pipeline()

    res = await pipe.write_es_index(
        _plan([_chunk("too-large", 0, "normal", "中文中文中文", "")]), db=_FakeDB()
    )

    assert res.indexed_items == 0
    assert res.failed_item_ids == ["too-large"]
    assert store.upserted == []
    assert "MANTICORE_MAX_DOCUMENT_BYTES" in repo.failed[0][1]
