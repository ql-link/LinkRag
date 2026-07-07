"""ManticoreBm25Store 单元测试：建表 DDL、写入分组、查询过滤/重排（fake 连接，不连真实 Manticore）。"""

from __future__ import annotations

from src.core.storage.manticore_bm25.store import Bm25Point, ManticoreBm25Store, _chunk_id_to_row_id


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self.rowcount = 0

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        # 模拟某条 REPLACE INTO 在协议层就失败（比如值截断/连接抖动）——按 chunk_id
        # （params[1]）匹配，命中即抛异常且不记入 executed，其余语句正常执行。
        if sql.startswith("REPLACE INTO") and params and params[1] in self._conn.fail_chunk_ids:
            raise RuntimeError(f"simulated REPLACE INTO failure for {params[1]}")
        self._conn.executed.append((sql, params))
        # 只有 DELETE 语句才消费 rowcount_queue——SHOW TABLES LIKE 等探测性查询
        # 走的是另一条 fetchall_queue，不该抢占 DELETE 的模拟返回行数。
        if sql.startswith("DELETE"):
            self.rowcount = self._conn.rowcount_queue.pop(0) if self._conn.rowcount_queue else 0

    async def fetchall(self):
        return self._conn.fetchall_queue.pop(0) if self._conn.fetchall_queue else []


class _FakeConn:
    def __init__(
        self,
        fetchall_queue: list | None = None,
        rowcount_queue: list | None = None,
        fail_chunk_ids: set | None = None,
    ) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.fetchall_queue: list = list(fetchall_queue or [])
        self.rowcount_queue: list = list(rowcount_queue or [])
        self.fail_chunk_ids: set = set(fail_chunk_ids or set())
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


async def test_upsert_chunks_returns_readback_verified_ids() -> None:
    # verify 阶段的 SELECT 回读命中两条 chunk_id，upsert_chunks 应把它们原样返回。
    conn = _FakeConn(fetchall_queue=[[("c1",), ("c2",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    verified = await store.upsert_chunks([_point(cid="c1", dataset_id=1), _point(cid="c2", dataset_id=1)])

    assert set(verified) == {"c1", "c2"}
    select_calls = [(s, p) for s, p in conn.executed if s.startswith("SELECT")]
    assert len(select_calls) == 1
    assert "WHERE chunk_id IN (%s,%s)" in select_calls[0][0]
    assert select_calls[0][1] == ("c1", "c2")


async def test_upsert_chunks_excludes_ids_not_confirmed_by_readback() -> None:
    # REPLACE INTO 两条都没抛异常，但回读只查到 c1——c2 视为未落地，不计入返回值。
    conn = _FakeConn(fetchall_queue=[[("c1",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    verified = await store.upsert_chunks([_point(cid="c1", dataset_id=1), _point(cid="c2", dataset_id=1)])

    assert verified == ["c1"]


async def test_upsert_chunks_skips_failed_item_but_verifies_the_rest() -> None:
    # c2 的 REPLACE INTO 直接抛异常（模拟单条写坏），c1/c3 应继续写入且被回读确认，
    # 不能因为 c2 失败就让整批都判定失败。
    conn = _FakeConn(fail_chunk_ids={"c2"}, fetchall_queue=[[("c1",), ("c3",)]])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    verified = await store.upsert_chunks(
        [_point(cid="c1", dataset_id=1), _point(cid="c2", dataset_id=1), _point(cid="c3", dataset_id=1)]
    )

    assert set(verified) == {"c1", "c3"}
    attempted_chunk_ids = {p[1] for s, p in conn.executed if s.startswith("REPLACE INTO")}
    assert attempted_chunk_ids == {"c1", "c3"}  # c2 从未真正落到 executed 日志里


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
    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]], rowcount_queue=[3])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    n = await store.delete_by_document(dataset_id=1, doc_id=9)

    delete_calls = [(s, p) for s, p in conn.executed if s.startswith("DELETE")]
    assert len(delete_calls) == 1
    assert "bm25_ds_1" in delete_calls[0][0]
    assert delete_calls[0][1] == (9,)
    # 返回值必须是真实删除行数（对齐 ES delete_by_query 的 "deleted" 字段语义），
    # 不能像之前那样恒定返回 0——调用方靠这个数判断是否真的删到了东西。
    assert n == 3


async def test_delete_by_document_returns_zero_when_no_rows_matched() -> None:
    # 表存在但没有命中该 doc_id 的行：rowcount=0，属于合法的幂等空删。
    conn = _FakeConn(fetchall_queue=[[("bm25_ds_1",)]], rowcount_queue=[0])
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    n = await store.delete_by_document(dataset_id=1, doc_id=9)

    assert n == 0


async def test_drop_table_issues_drop_statement_and_evicts_cache() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")
    await store.ensure_table(1)  # 预热进程内 _ready_tables 缓存

    await store.drop_table(1)

    drop_calls = [s for s, _ in conn.executed if s.startswith("DROP TABLE")]
    assert len(drop_calls) == 1
    assert "IF EXISTS bm25_ds_1" in drop_calls[0]
    assert "bm25_ds_1" not in store._ready_tables


async def test_drop_table_is_idempotent_when_table_missing() -> None:
    conn = _FakeConn()
    store = ManticoreBm25Store(conn=conn, table_prefix="bm25_ds")

    await store.drop_table(999)  # 从未 ensure 过，DROP TABLE IF EXISTS 应仍然安全

    drop_calls = [s for s, _ in conn.executed if s.startswith("DROP TABLE")]
    assert len(drop_calls) == 1


# --------------------------------------------------------------------------- #
# 连接池：未注入 conn 时应走进程内连接池，而不是每次新建/复用单条常驻连接
# --------------------------------------------------------------------------- #
async def test_uses_pool_and_acquires_connection_when_no_conn_injected() -> None:
    from src.core.storage.manticore_bm25 import store as store_module

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
    assert kwargs["minsize"] == store_module._POOL_MINSIZE
    assert kwargs["maxsize"] == store_module._POOL_MAXSIZE
    assert fake_pool.acquired == 1
    assert fake_pool.released == 1


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
