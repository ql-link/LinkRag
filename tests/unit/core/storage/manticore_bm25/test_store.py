"""ManticoreBm25Store 单元测试：建表 DDL、写入分组、查询过滤/重排（fake 连接，不连真实 Manticore）。"""

from __future__ import annotations

from src.core.storage.manticore_bm25.store import Bm25Point, ManticoreBm25Store, _chunk_id_to_row_id


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        self._conn.executed.append((sql, params))

    async def fetchall(self):
        return self._conn.fetchall_queue.pop(0) if self._conn.fetchall_queue else []


class _FakeConn:
    def __init__(self, fetchall_queue: list | None = None) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.fetchall_queue: list = list(fetchall_queue or [])
        self.closed = False

    async def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _point(cid="c1", doc_id=1, user_id=1, dataset_id=2, chunk_type="normal", coarse="退费 流程", fine="退费 流程"):
    return Bm25Point(
        chunk_id=cid, doc_id=doc_id, user_id=user_id, dataset_id=dataset_id,
        chunk_type=chunk_type, coarse_tokens=coarse, fine_tokens=fine,
    )


async def test_ensure_table_creates_with_expected_ddl_options() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    table = await store.ensure_table(42)

    assert table == "bm25_ds_42"
    sql, _ = conn.executed[0]
    assert "CREATE TABLE IF NOT EXISTS bm25_ds_42" in sql
    assert "charset_table='non_cjk, chinese'" in sql
    assert "index_field_lengths='1'" in sql
    assert "morphology='none'" in sql


async def test_ensure_table_only_creates_once_per_dataset() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.ensure_table(1)
    await store.ensure_table(1)

    create_calls = [s for s, _ in conn.executed if "CREATE TABLE" in s]
    assert len(create_calls) == 1


async def test_upsert_chunks_groups_by_dataset_and_replaces_idempotently() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.upsert_chunks([_point(cid="c1", dataset_id=1), _point(cid="c2", dataset_id=2)])

    replace_calls = [(s, p) for s, p in conn.executed if s.startswith("REPLACE INTO")]
    assert len(replace_calls) == 2
    assert "bm25_ds_1" in replace_calls[0][0]
    assert "bm25_ds_2" in replace_calls[1][0]
    # chunk_id → row id 是确定性映射，同一个 chunk_id 永远算出同一个 id（幂等 REPLACE 的前提）。
    assert replace_calls[0][1][0] == _chunk_id_to_row_id("c1")


async def test_upsert_empty_points_is_noop() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.upsert_chunks([])

    assert conn.executed == []


async def test_query_returns_empty_when_table_missing() -> None:
    conn = _FakeConn(fetchall_queue=[[]])  # SHOW TABLES LIKE 无结果
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    hits = await store.query(query_terms=["退费"], dataset_id=1, doc_id=None, type_mult={}, limit=10)

    assert hits == []


async def test_query_applies_type_mult_and_resorts() -> None:
    conn = _FakeConn(
        fetchall_queue=[
            [("bm25_ds_1",)],  # SHOW TABLES LIKE 命中
            [  # SELECT ... 原始候选（按 WEIGHT 降序，未考虑 type_mult 前）
                ("c1", 10, "normal", 100.0),
                ("c2", 11, "table", 90.0),
            ],
        ]
    )
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    hits = await store.query(
        query_terms=["退费"], dataset_id=1, doc_id=None,
        type_mult={"table": 1.5}, limit=10,
    )

    # c2 原始分 90 × 1.5 = 135，超过 c1 的 100，重排后应排到第一。
    assert [h.chunk_id for h in hits] == ["c2", "c1"]
    assert hits[0].score == 135.0


async def test_query_empty_terms_short_circuits() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    hits = await store.query(query_terms=["", "  "], dataset_id=1, doc_id=None, type_mult={}, limit=10)

    assert hits == []
    assert conn.executed == []


async def test_delete_by_document_noop_when_table_missing() -> None:
    conn = _FakeConn(fetchall_queue=[[]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    n = await store.delete_by_document(dataset_id=1, doc_id=9)

    assert n == 0
    assert not any(s.startswith("DELETE") for s, _ in conn.executed)


async def test_delete_by_document_issues_delete_statement() -> None:
    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.delete_by_document(dataset_id=1, doc_id=9)

    delete_calls = [(s, p) for s, p in conn.executed if s.startswith("DELETE")]
    assert len(delete_calls) == 1
    assert "bm25_ds_1" in delete_calls[0][0]
    assert delete_calls[0][1] == (9,)
