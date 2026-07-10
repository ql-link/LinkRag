"""ManticoreBm25Store 单元测试：建表 DDL、写入分组、查询过滤/重排（fake 连接，不连真实 Manticore）。"""

from __future__ import annotations

import asyncio

import pytest

from src.core.storage.manticore_bm25.exceptions import ManticoreStoreError
from src.core.storage.manticore_bm25.store import Bm25Point, ManticoreBm25Store, _chunk_id_to_row_id


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self.rowcount = 0
        self._last_sql = ""

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        self._last_sql = sql
        # 模拟某条 REPLACE INTO 在协议层就失败（比如值截断/连接抖动）——按 chunk_id
        # （params[1]）匹配，命中即抛异常且不记入 executed，其余语句正常执行。
        if sql.startswith("REPLACE INTO") and params:
            failed = set(params[1::6]) & self._conn.fail_chunk_ids
            if failed:
                raise RuntimeError(f"simulated REPLACE INTO failure for {sorted(failed)}")
        self._conn.executed.append((sql, params))
        # 只有 DELETE 语句才消费 rowcount_queue——SHOW TABLES LIKE 等探测性查询
        # 走的是另一条 fetchall_queue，不该抢占 DELETE 的模拟返回行数。
        if sql.startswith("DELETE"):
            self.rowcount = self._conn.rowcount_queue.pop(0) if self._conn.rowcount_queue else 0

    async def fetchall(self):
        if self._last_sql.startswith("DESC "):
            return self._conn.desc_rows
        if self._last_sql.startswith("SHOW CREATE TABLE"):
            return self._conn.show_create_rows
        if self._last_sql.startswith("SELECT user_id FROM"):
            return self._conn.owner_rows
        return self._conn.fetchall_queue.pop(0) if self._conn.fetchall_queue else []


class _FakeConn:
    def __init__(
        self,
        fetchall_queue: list | None = None,
        rowcount_queue: list | None = None,
        fail_chunk_ids: set | None = None,
        desc_rows: list | None = None,
        show_create_rows: list | None = None,
        owner_rows: list | None = None,
    ) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.fetchall_queue: list = list(fetchall_queue or [])
        self.rowcount_queue: list = list(rowcount_queue or [])
        self.fail_chunk_ids: set = set(fail_chunk_ids or set())
        self.desc_rows = desc_rows or [
            ("id", "bigint", ""),
            ("coarse", "text", "indexed"),
            ("chunk_id", "string", ""),
            ("doc_id", "bigint", ""),
            ("user_id", "bigint", ""),
            ("chunk_type", "string", ""),
            ("coarse_len", "tokencount", ""),
        ]
        self.show_create_rows = show_create_rows or [
            (
                "bm25_ds_1",
                "CREATE TABLE bm25_ds_1 (...) index_field_lengths='1' "
                "charset_table='non_cjk, chinese' morphology='none'",
            )
        ]
        self.owner_rows = list(owner_rows or [])
        self.closed = False

    async def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class _FakePoolAcquireCtx:
    def __init__(self, pool: "_FakePool") -> None:
        self._pool = pool

    async def __aenter__(self):
        self._pool.acquired += 1
        return self._pool.conn

    async def __aexit__(self, *exc) -> bool:
        self._pool.released += 1
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn
        self.acquired = 0
        self.released = 0
        self.closed = False
        self.wait_closed_called = False

    def acquire(self) -> _FakePoolAcquireCtx:
        return _FakePoolAcquireCtx(self)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_called = True


class _FakeAiomysqlModule:
    """替身 aiomysql 模块：只记录 ``create_pool`` 收到的参数，不真连网络。"""

    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool
        self.create_pool_calls: list[dict] = []

    async def create_pool(self, **kwargs):
        self.create_pool_calls.append(kwargs)
        return self._pool


def _point(cid="c1", doc_id=1, user_id=1, dataset_id=2, chunk_type="normal", coarse="退费 流程"):
    return Bm25Point(
        chunk_id=cid,
        doc_id=doc_id,
        user_id=user_id,
        dataset_id=dataset_id,
        chunk_type=chunk_type,
        coarse_tokens=coarse,
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
    assert "coarse text indexed" in sql
    assert "fine" not in sql


async def test_ensure_table_only_creates_once_per_dataset() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.ensure_table(1)
    await store.ensure_table(1)

    create_calls = [s for s, _ in conn.executed if s.startswith("CREATE TABLE")]
    assert len(create_calls) == 1


async def test_ensure_table_rejects_incompatible_existing_schema() -> None:
    conn = _FakeConn(
        desc_rows=[
            ("id", "bigint", ""),
            ("coarse", "text", "indexed"),
            ("fine", "text", "indexed"),
            ("chunk_id", "string", ""),
            ("doc_id", "bigint", ""),
            ("user_id", "bigint", ""),
            ("chunk_type", "string", ""),
        ]
    )
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    with pytest.raises(ManticoreStoreError, match="Incompatible schema"):
        await store.ensure_table(1)

    assert "bm25_ds_1" not in store._ready_tables


async def test_ensure_table_rejects_incompatible_tokenizer_options() -> None:
    conn = _FakeConn(show_create_rows=[("bm25_ds_1", "CREATE TABLE bm25_ds_1 (...)")])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    with pytest.raises(ManticoreStoreError, match="Incompatible table options"):
        await store.ensure_table(1)


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


async def test_upsert_rejects_mixed_owner_points_for_one_dataset() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    with pytest.raises(ManticoreStoreError, match="mixed-owner write"):
        await store.upsert_chunks(
            [
                _point(cid="c1", dataset_id=1, user_id=7),
                _point(cid="c2", dataset_id=1, user_id=8),
            ]
        )


async def test_upsert_rejects_existing_table_owner_mismatch() -> None:
    conn = _FakeConn(owner_rows=[(99,)])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    with pytest.raises(ManticoreStoreError, match="Refusing write"):
        await store.upsert_chunks([_point(cid="c1", dataset_id=1, user_id=7)])

    assert not any(sql.startswith("REPLACE") for sql, _ in conn.executed)


async def test_upsert_chunks_batches_by_row_count() -> None:
    conn = _FakeConn(fetchall_queue=[[(f"c{i}",) for i in range(5)]])
    store = ManticoreBm25Store(
        conn=conn, table_prefix="bm25_ds", write_batch_size=2, write_batch_bytes=10_000
    )

    verified = await store.upsert_chunks([_point(cid=f"c{i}", dataset_id=1) for i in range(5)])

    replace_calls = [(sql, params) for sql, params in conn.executed if sql.startswith("REPLACE")]
    assert [len(params) // 6 for _, params in replace_calls] == [2, 2, 1]
    assert verified == [f"c{i}" for i in range(5)]


async def test_upsert_chunks_batches_by_estimated_bytes() -> None:
    conn = _FakeConn(fetchall_queue=[[("c1",), ("c2",)]])
    store = ManticoreBm25Store(
        conn=conn, table_prefix="bm25_ds", write_batch_size=100, write_batch_bytes=80
    )

    await store.upsert_chunks(
        [
            _point(cid="c1", dataset_id=1, coarse="x" * 20),
            _point(cid="c2", dataset_id=1, coarse="y" * 20),
        ]
    )

    replace_calls = [(sql, params) for sql, params in conn.executed if sql.startswith("REPLACE")]
    assert [len(params) // 6 for _, params in replace_calls] == [1, 1]


async def test_upsert_chunks_returns_readback_verified_ids() -> None:
    # verify 阶段的 SELECT 回读命中两条 chunk_id，upsert_chunks 应把它们原样返回。
    conn = _FakeConn(fetchall_queue=[[("c1",), ("c2",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    verified = await store.upsert_chunks(
        [_point(cid="c1", dataset_id=1), _point(cid="c2", dataset_id=1)]
    )

    assert set(verified) == {"c1", "c2"}
    select_calls = [(s, p) for s, p in conn.executed if s.startswith("SELECT chunk_id")]
    assert len(select_calls) == 1
    assert "WHERE chunk_id IN (%s,%s)" in select_calls[0][0]
    assert select_calls[0][1] == ("c1", "c2")
    assert select_calls[0][0].endswith("LIMIT 2")


async def test_verify_written_does_not_fall_back_to_manticore_default_limit_20() -> None:
    ids = [f"c{i}" for i in range(25)]
    conn = _FakeConn(fetchall_queue=[[(cid,) for cid in ids]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    verified = await store._verify_written("bm25_ds_1", ids)

    assert verified == ids
    sql, params = conn.executed[0]
    assert sql.endswith("LIMIT 25")
    assert params == tuple(ids)


async def test_upsert_chunks_excludes_ids_not_confirmed_by_readback() -> None:
    # REPLACE INTO 两条都没抛异常，但回读只查到 c1——c2 视为未落地，不计入返回值。
    conn = _FakeConn(fetchall_queue=[[("c1",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    verified = await store.upsert_chunks(
        [_point(cid="c1", dataset_id=1), _point(cid="c2", dataset_id=1)]
    )

    assert verified == ["c1"]


async def test_upsert_batch_failure_is_raised_for_document_level_cleanup() -> None:
    # 多行 REPLACE 一批失败时不猜测部分成功，向上抛出让文档级编排统一清理。
    conn = _FakeConn(fail_chunk_ids={"c2"})
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    with pytest.raises(ManticoreStoreError, match="batch upsert"):
        await store.upsert_chunks(
            [
                _point(cid="c1", dataset_id=1),
                _point(cid="c2", dataset_id=1),
                _point(cid="c3", dataset_id=1),
            ]
        )
    assert not any(s.startswith("REPLACE INTO") for s, _ in conn.executed)


async def test_upsert_empty_points_is_noop() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.upsert_chunks([])

    assert conn.executed == []


async def test_query_returns_empty_when_table_missing() -> None:
    conn = _FakeConn(fetchall_queue=[[]])  # SHOW TABLES LIKE 无结果
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    hits = await store.query(
        query_terms=["退费"], user_id=7, dataset_id=1, doc_id=None, type_mult={}, limit=10
    )

    assert hits == []


async def test_query_applies_type_mult_and_resorts() -> None:
    conn = _FakeConn(
        fetchall_queue=[
            [  # SELECT ... 原始候选（按 WEIGHT 降序，未考虑 type_mult 前）
                ("c1", 10, "normal", 100.0),
                ("c2", 11, "table", 90.0),
            ],
        ]
    )
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    hits = await store.query(
        query_terms=["退费"],
        user_id=7,
        dataset_id=1,
        doc_id=None,
        type_mult={"table": 1.5},
        limit=10,
    )

    # c2 原始分 90 × 1.5 = 135，超过 c1 的 100，重排后应排到第一。
    assert [h.chunk_id for h in hits] == ["c2", "c1"]
    assert hits[0].score == 135.0
    query_sql, query_params = next((s, p) for s, p in conn.executed if "MATCH(%s)" in s)
    assert "user_id=%s" in query_sql
    assert "bm25a(1.2,0.75)" in query_sql
    assert "idf='plain,tfidf_unnormalized'" in query_sql
    assert query_params == ('"退费"', 7)


async def test_query_empty_terms_short_circuits() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    hits = await store.query(
        query_terms=["", "  "], user_id=7, dataset_id=1, doc_id=None, type_mult={}, limit=10
    )

    assert hits == []
    assert conn.executed == []


def test_build_match_expr_quotes_extended_syntax_and_deduplicates() -> None:
    expr = ManticoreBm25Store._build_match_expr(["foo", "_", "bar", "foo", 'a"b', r"c\d"])

    assert expr == '"foo" | "_" | "bar" | "a\\"b" | "c\\\\d"'


async def test_table_exists_rejects_like_wildcard_false_positive() -> None:
    # '_' 在 SHOW TABLES LIKE 中是通配符：即使 Manticore 返回相似名，也不能当成目标表。
    conn = _FakeConn(fetchall_queue=[[("bm25XdsX1",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    assert await store._table_exists("bm25_ds_1") is False


async def test_delete_by_document_returns_zero_when_no_rows_match() -> None:
    conn = _FakeConn(rowcount_queue=[0])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    n = await store.delete_by_document(user_id=7, dataset_id=1, doc_id=9)

    assert n == 0
    assert any(s.startswith("DELETE") for s, _ in conn.executed)


async def test_delete_by_document_issues_delete_statement() -> None:
    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]], rowcount_queue=[3])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    n = await store.delete_by_document(user_id=7, dataset_id=1, doc_id=9)

    delete_calls = [(s, p) for s, p in conn.executed if s.startswith("DELETE")]
    assert len(delete_calls) == 1
    assert "bm25_ds_1" in delete_calls[0][0]
    assert delete_calls[0][1] == (7, 9)
    # 返回值必须是真实删除行数（对齐 ES delete_by_query 的 "deleted" 字段语义），
    # 不能像之前那样恒定返回 0——调用方靠这个数判断是否真的删到了东西。
    assert n == 3


async def test_delete_by_document_returns_zero_when_no_rows_matched() -> None:
    # 表存在但没有命中该 doc_id 的行：rowcount=0，属于合法的幂等空删。
    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]], rowcount_queue=[0])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    n = await store.delete_by_document(user_id=7, dataset_id=1, doc_id=9)

    assert n == 0


async def test_ping_executes_lightweight_readiness_query() -> None:
    conn = _FakeConn(fetchall_queue=[[(1,)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.ping()

    assert ("SELECT 1", None) in conn.executed


async def test_count_and_keyset_listing_keep_user_guard() -> None:
    conn = _FakeConn(fetchall_queue=[[(2,)], [(11, "c1"), (19, "c2")]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    count = await store.count_chunks(user_id=7, dataset_id=1)
    page = await store.list_chunk_ids_after(user_id=7, dataset_id=1, after_row_id=10, limit=2)

    assert count == 2
    assert page == [(11, "c1"), (19, "c2")]
    count_sql, count_params = conn.executed[0]
    page_sql, page_params = conn.executed[1]
    assert "WHERE user_id=%s" in count_sql and count_params == (7,)
    assert "user_id=%s AND id>%s" in page_sql and page_params == (7, 10)


async def test_delete_chunk_ids_uses_hashed_ids_and_user_guard() -> None:
    conn = _FakeConn(rowcount_queue=[2])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    deleted = await store.delete_chunk_ids(user_id=7, dataset_id=1, chunk_ids=["c1", "c2"])

    assert deleted == 2
    sql, params = next((sql, params) for sql, params in conn.executed if sql.startswith("DELETE"))
    assert "user_id=%s AND id IN (%s,%s)" in sql
    assert params == (7, _chunk_id_to_row_id("c1"), _chunk_id_to_row_id("c2"))


async def test_list_dataset_ids_rejects_show_like_false_positives() -> None:
    conn = _FakeConn(
        fetchall_queue=[[("bm25_ds_1",), ("bm25Xds_2",), ("bm25_ds_bad",), ("other_3",)]]
    )
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    assert await store.list_dataset_ids() == [1]


async def test_drop_table_issues_drop_statement_and_evicts_cache() -> None:
    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]], owner_rows=[(7,)])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")
    await store.ensure_table(1)  # 预热进程内 _ready_tables 缓存

    await store.drop_table(1, user_id=7)

    drop_calls = [s for s, _ in conn.executed if s.startswith("DROP TABLE")]
    assert len(drop_calls) == 1
    assert "IF EXISTS bm25_ds_1" in drop_calls[0]
    assert "bm25_ds_1" not in store._ready_tables


async def test_drop_table_is_idempotent_when_table_missing() -> None:
    conn = _FakeConn(fetchall_queue=[[]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.drop_table(999, user_id=7)

    drop_calls = [s for s, _ in conn.executed if s.startswith("DROP TABLE")]
    assert drop_calls == []


async def test_drop_table_refuses_owner_mismatch() -> None:
    import pytest

    from src.core.storage.manticore_bm25.exceptions import ManticoreStoreError

    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]], owner_rows=[(99,)])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    with pytest.raises(ManticoreStoreError, match="Refusing to drop"):
        await store.drop_table(1, user_id=7)
    assert not any(s.startswith("DROP TABLE") for s, _ in conn.executed)


# --------------------------------------------------------------------------- #
# 连接池：未注入 conn 时应走进程内连接池，而不是每次新建/复用单条常驻连接
# --------------------------------------------------------------------------- #
async def test_uses_pool_and_acquires_connection_when_no_conn_injected() -> None:
    fake_conn = _FakeConn()
    fake_pool = _FakePool(fake_conn)
    fake_aiomysql = _FakeAiomysqlModule(fake_pool)
    store = ManticoreBm25Store(table_prefix="bm25_ds", host="mh", port=1234, timeout=5)
    store._aiomysql = lambda: fake_aiomysql  # type: ignore[method-assign]

    table = await store.ensure_table(1)

    assert table == "bm25_ds_1"
    assert len(fake_aiomysql.create_pool_calls) == 1
    kwargs = fake_aiomysql.create_pool_calls[0]
    assert kwargs["host"] == "mh"
    assert kwargs["port"] == 1234
    assert kwargs["minsize"] == store.pool_minsize
    assert kwargs["maxsize"] == store.pool_maxsize
    assert kwargs["pool_recycle"] == store.pool_recycle
    assert kwargs["connect_timeout"] == 5
    assert fake_pool.acquired == 1
    assert fake_pool.released == 1


async def test_pool_passes_tls_context_only_when_enabled() -> None:
    fake_pool = _FakePool(_FakeConn())
    fake_aiomysql = _FakeAiomysqlModule(fake_pool)
    store = ManticoreBm25Store(table_prefix="bm25_ds", ssl_enabled=True)
    sentinel_context = object()
    store._aiomysql = lambda: fake_aiomysql  # type: ignore[method-assign]
    store._ssl_context = lambda: sentinel_context  # type: ignore[method-assign]

    await store._get_pool()

    assert fake_aiomysql.create_pool_calls[0]["ssl"] is sentinel_context


async def test_pool_created_once_and_reused_across_calls() -> None:
    fake_conn = _FakeConn()
    fake_pool = _FakePool(fake_conn)
    fake_aiomysql = _FakeAiomysqlModule(fake_pool)
    store = ManticoreBm25Store(table_prefix="bm25_ds")
    store._aiomysql = lambda: fake_aiomysql  # type: ignore[method-assign]

    await store.ensure_table(1)
    await store.ensure_table(2)

    # 两次不同 dataset 的建表各自借还了一次连接，但连接池本身只建了一次。
    assert len(fake_aiomysql.create_pool_calls) == 1
    assert fake_pool.acquired == 2
    assert fake_pool.released == 2


async def test_pool_created_once_under_concurrent_first_use() -> None:
    class _YieldingFakeAiomysql(_FakeAiomysqlModule):
        async def create_pool(self, **kwargs):
            self.create_pool_calls.append(kwargs)
            await asyncio.sleep(0.01)
            return self._pool

    fake_pool = _FakePool(_FakeConn())
    fake_aiomysql = _YieldingFakeAiomysql(fake_pool)
    store = ManticoreBm25Store(table_prefix="bm25_ds")
    store._aiomysql = lambda: fake_aiomysql  # type: ignore[method-assign]

    pools = await asyncio.gather(*(store._get_pool() for _ in range(20)))

    assert all(pool is fake_pool for pool in pools)
    assert len(fake_aiomysql.create_pool_calls) == 1


async def test_sql_timeout_closes_protocol_connection() -> None:
    class _SlowCursor:
        async def execute(self, sql, params=None):
            await asyncio.sleep(1)

    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds", timeout=0.001)

    with pytest.raises(ManticoreStoreError, match="SQL timed out"):
        await store._execute(conn, _SlowCursor(), "SELECT 1")

    assert conn.closed is True


async def test_close_closes_owned_pool() -> None:
    fake_conn = _FakeConn()
    fake_pool = _FakePool(fake_conn)
    fake_aiomysql = _FakeAiomysqlModule(fake_pool)
    store = ManticoreBm25Store(table_prefix="bm25_ds")
    store._aiomysql = lambda: fake_aiomysql  # type: ignore[method-assign]
    await store.ensure_table(1)  # 触发建池

    await store.close()

    assert fake_pool.closed is True
    assert fake_pool.wait_closed_called is True


async def test_close_does_not_touch_externally_injected_conn() -> None:
    # 显式注入 conn 时，store 不拥有它的生命周期，close() 不应该关闭调用方的连接。
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.close()

    assert conn.closed is False
