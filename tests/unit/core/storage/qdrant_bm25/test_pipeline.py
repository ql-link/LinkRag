"""QdrantBm25IndexingPipeline 单元测试：写入/删除逻辑（fake store/repo/db，不连 Qdrant/DB）。

plan/chunk/meta 用 SimpleNamespace 鸭子构造——pipeline 只读属性、不强制真实类型。
"""

from __future__ import annotations

from types import SimpleNamespace

from src.core.storage.qdrant_bm25 import Bm25SparseEncoder, QdrantBm25IndexingPipeline


class _FakeStore:
    def __init__(self) -> None:
        self.ensured = False
        self.upserted: list = []
        self.deleted: list = []

    async def ensure_collection(self) -> None:
        self.ensured = True

    async def upsert_chunks(self, points) -> None:
        self.upserted.extend(points)

    async def delete_by_document(self, *, user_id, dataset_id, doc_id) -> int:
        self.deleted.append((user_id, dataset_id, doc_id))
        return 0


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


def _pipeline():
    store = _FakeStore()
    repo = _FakeRepo()
    pipe = QdrantBm25IndexingPipeline(
        store=store, chunk_repository=repo, encoder=Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=5.0)
    )
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
    assert store.ensured is True
    assert {p.chunk_id for p in store.upserted} == {"c1", "c2"}
    # 多租户 / 类型 payload 透传。
    p = store.upserted[0]
    assert (p.doc_id, p.user_id, p.dataset_id) == (1, 1, 2)
    assert p.sparse_vector.indices  # 非空 BM25 向量
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


async def test_empty_plan_is_noop() -> None:
    pipe, store, _ = _pipeline()
    res = await pipe.write_es_index(_plan([]), db=_FakeDB())
    assert res.total_items == 0
    assert res.indexed_items == 0
    assert store.upserted == [] and store.ensured is False


async def test_delete_delegates_to_store() -> None:
    pipe, store, _ = _pipeline()
    n = await pipe.delete_document_index(user_id=3, dataset_id=4, doc_id=9)
    assert n == 0
    assert store.deleted == [(3, 4, 9)]
