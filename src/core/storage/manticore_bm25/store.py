"""Manticore BM25 存储：按 dataset_id 物理建表，原生 bm25f 双字段真 BM25F。

与 Qdrant BM25 后端（``qdrant_bm25/store.py``）的关键差异：

- **不需要客户端补算 TF/长度归一**：Manticore 原生支持 ``bm25f(k1, b, {field=weight})``，
  coarse/fine 两个字段直接建两个全文字段索引，TF、长度归一、IDF 全部由 Manticore 服务端
  按这张表（=这个 dataset）自己的语料统计算出，不需要 Qdrant 那套 hash 维度隔离编码。
- **avgdl 用 Manticore 动态计算**，不传常量覆盖：每张表天然只含一个 dataset 的文档，
  动态平均值本来就是"按 dataset 计算"，不存在跨租户漂移的问题（这是 Qdrant/ES 单一
  全局 collection/index 才会有的问题）。
- **表按 dataset_id 精确路由**（``TableRouter``），不是按 user 哈希分桶——不需要额外
  的 tenant filter 把统计口径圈起来，WHERE 条件只需要处理 doc_id（同 dataset 内选定
  某一篇文档）。
- **类型加权在候选池召回后于应用层做**：Manticore 的 ``bm25f()`` 是黑盒函数，不支持
  像 Qdrant Formula Query 那样在打分公式里插入按 payload 匹配的条件项；改为先取
  ``prefetch_limit`` 条候选，按 chunk_type 在 Python 侧乘一次权重再重新排序截断，
  语义上与 Qdrant 的「先召回、后按类型乘数重排」一致，只是实现层挪到了应用层。

安全边界：不做任何 SQL 字符串拼接接收用户输入——表名只来自 ``TableRouter``（内部
生成，dataset_id 是整数），MATCH()/WHERE 的值全部走参数化查询。
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.utils.logger import logger

from .exceptions import ManticoreConfigurationError, ManticoreStoreError
from .schema import (
    ATTR_CHUNK_ID,
    ATTR_CHUNK_TYPE,
    ATTR_DOC_ID,
    ATTR_USER_ID,
    FIELD_COARSE,
    FIELD_FINE,
    TABLE_DDL_OPTIONS,
)
from .table_router import TableRouter

_BM25_K1_DEFAULT = 1.2
_BM25_B_DEFAULT = 0.75
# 与 src/database.py 的 SQLAlchemy pool_size=10 对齐：并发请求下多条连接可用，
# 避免单连接排队成为召回/写入路径的瓶颈。
_POOL_MINSIZE = 1
_POOL_MAXSIZE = 10


@dataclass(frozen=True, slots=True)
class Bm25Point:
    """一个待写入 Manticore 的 chunk：预分词文本 + 多租户/类型属性。"""

    chunk_id: str
    doc_id: int
    user_id: int
    dataset_id: int
    chunk_type: str
    coarse_tokens: str
    fine_tokens: str


@dataclass(frozen=True, slots=True)
class Bm25ScoredPoint:
    """一次查询命中的中立结果（不含 Manticore/SQL 相关类型）。"""

    chunk_id: str
    doc_id: int
    score: float


def _chunk_id_to_row_id(chunk_id: str) -> int:
    """chunk_id（字符串）→ Manticore 行 id（正整数 bigint）的确定性映射。

    Manticore RT 表的 id 必须是整数；用 blake2b 取 8 字节保证同一个 chunk_id 永远
    映射到同一行 id，配合 ``REPLACE INTO`` 做到跟 Qdrant upsert 同等的幂等写入。
    掩掉最高位保证落在有符号 bigint 的正数范围内。
    """

    digest = hashlib.blake2b(chunk_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF


class ManticoreBm25Store:
    """按 dataset_id 物理建表的 Manticore BM25 访问封装。"""

    def __init__(
        self,
        *,
        conn: Any | None = None,
        host: str | None = None,
        port: int | None = None,
        timeout: int | None = None,
        table_prefix: str | None = None,
        table_router: TableRouter | None = None,
        k1: float | None = None,
        b: float | None = None,
        coarse_boost: float | None = None,
    ) -> None:
        self._conn = conn
        self._owns_conn = conn is None
        self._pool: Any | None = None
        self.host = host or settings.MANTICORE_HOST
        self.port = port or settings.MANTICORE_PORT
        self.timeout = timeout or getattr(settings, "MANTICORE_TIMEOUT_SECONDS", 10)
        self.table_router = table_router or TableRouter(
            prefix=table_prefix or settings.MANTICORE_BM25_TABLE_PREFIX
        )
        self.k1 = k1 if k1 is not None else getattr(settings, "BM25_K1", _BM25_K1_DEFAULT)
        self.b = b if b is not None else getattr(settings, "BM25_B", _BM25_B_DEFAULT)
        self.coarse_boost = (
            coarse_boost if coarse_boost is not None else getattr(settings, "BM25_COARSE_BOOST", 2.0)
        )
        self._ready_tables: set[str] = set()

    # ---------------- 表生命周期 ----------------
    async def ensure_table(self, dataset_id: int) -> str:
        """确保某 dataset 对应的表存在（幂等，按进程内缓存避免重复建表请求）。"""

        table = self.table_router.table_name(dataset_id)
        if table in self._ready_tables:
            return table
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {table}("
                    f"{ATTR_CHUNK_ID} string, {ATTR_DOC_ID} bigint, {ATTR_USER_ID} bigint, "
                    f"{ATTR_CHUNK_TYPE} string, {FIELD_COARSE} text, {FIELD_FINE} text"
                    f") {TABLE_DDL_OPTIONS}"
                )
            except Exception as exc:
                raise ManticoreStoreError(f"Failed to ensure table {table}: {exc}") from exc
        self._ready_tables.add(table)
        return table

    async def drop_table(self, dataset_id: int) -> None:
        """整表物理删除（dataset 被整体删除时用，而非 ``delete_by_document`` 的文档级删除）。

        与 ES/Qdrant 不同：Manticore 每个 dataset 一张物理表，dataset 删除必须显式
        ``DROP TABLE`` 才能真正回收——只删行不删表会让空表在 dataset 之间只增不减，
        对应的内存/句柄也不会释放（见 POC 里"删表后内存不随 DROP 立即回落"的现象）。
        """

        table = self.table_router.table_name(dataset_id)
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await cur.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception as exc:
                raise ManticoreStoreError(f"Failed to drop table {table}: {exc}") from exc
        self._ready_tables.discard(table)

    async def _table_exists(self, table: str) -> bool:
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await cur.execute("SHOW TABLES LIKE %s", (table,))
                rows = await cur.fetchall()
                return bool(rows)
            except Exception as exc:
                raise ManticoreStoreError(f"Failed to check table existence {table}: {exc}") from exc

    # ---------------- 写入 ----------------
    async def upsert_chunks(self, points: Sequence[Bm25Point]) -> list[str]:
        """按 chunk_id 幂等写入（``REPLACE INTO``），返回回读校验后确认已落地的 chunk_id。

        单条 ``REPLACE INTO`` 出错只记录、跳过，不让同批次其余已经成功的写入被
        牵连判定失败——批次内某个 chunk 写坏（数据本身有问题）不该导致同批其余
        chunk 被误标失败、引发不必要的重试。批次写完后按 chunk_id 做一次批量
        ``SELECT`` 回读，只有真正查得到的行才计入返回值，调用方（pipeline.py）
        据此精确标记每个 chunk 的 ``es_status``，而不是"这批是否抛过异常"这种
        粗粒度判断。
        """

        if not points:
            return []
        by_dataset: dict[int, list[Bm25Point]] = {}
        for p in points:
            by_dataset.setdefault(p.dataset_id, []).append(p)

        verified: list[str] = []
        for dataset_id, group in by_dataset.items():
            table = await self.ensure_table(dataset_id)
            attempted: list[str] = []
            async with self._connection() as conn:
                cur = await conn.cursor()
                for p in group:
                    row_id = _chunk_id_to_row_id(p.chunk_id)
                    try:
                        await cur.execute(
                            f"REPLACE INTO {table} "
                            f"(id, {ATTR_CHUNK_ID}, {ATTR_DOC_ID}, {ATTR_USER_ID}, "
                            f"{ATTR_CHUNK_TYPE}, {FIELD_COARSE}, {FIELD_FINE}) "
                            f"VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (row_id, p.chunk_id, p.doc_id, p.user_id, p.chunk_type, p.coarse_tokens, p.fine_tokens),
                        )
                        attempted.append(p.chunk_id)
                    except Exception as exc:
                        logger.error(
                            "[ManticoreBm25Store.upsert_chunks] REPLACE INTO failed "
                            "table={} chunk_id={} error={}",
                            table,
                            p.chunk_id,
                            exc,
                        )
            if attempted:
                verified.extend(await self._verify_written(table, attempted))
        return verified

    async def _verify_written(self, table: str, chunk_ids: Sequence[str]) -> list[str]:
        """按 chunk_id 批量回读，返回真正查得到的子集——唯一可信的"写入成功"判据。

        与单纯"execute 没抛异常就算成功"不同：这一步能捕捉网络层已确认、但因值
        截断/类型静默转换等原因未真正落地的行。回读本身失败（连接不可用等）视为
        无法判断，直接抛出，交给调用方按整批失败处理。
        """

        if not chunk_ids:
            return []
        async with self._connection() as conn:
            cur = await conn.cursor()
            placeholders = ",".join(["%s"] * len(chunk_ids))
            try:
                await cur.execute(
                    f"SELECT {ATTR_CHUNK_ID} FROM {table} WHERE {ATTR_CHUNK_ID} IN ({placeholders})",
                    tuple(chunk_ids),
                )
                rows = await cur.fetchall()
            except Exception as exc:
                raise ManticoreStoreError(
                    f"Failed to verify written BM25 chunks in {table}: {exc}"
                ) from exc
        return [str(row[0]) for row in rows]

    # ---------------- 查询（BM25F 召回 + 应用层类型乘数重排）----------------
    async def query(
        self,
        *,
        query_terms: Sequence[str],
        dataset_id: int,
        doc_id: int | None,
        type_mult: Mapping[str, float],
        limit: int,
    ) -> list[Bm25ScoredPoint]:
        """按 dataset_id 路由到对应表做 BM25F 召回，非空 ``type_mult`` 时应用层重排。

        表不存在时返回空（等价于"无数据"，与写入侧解耦的合法中间态，对齐 Qdrant/ES
        collection/index 不存在时的行为）。
        """

        terms = [t.strip() for t in query_terms if t and t.strip()]
        if not terms:
            return []

        table = self.table_router.table_name(dataset_id)
        if not await self._table_exists(table):
            logger.warning("[ManticoreBm25Store.query] table not found; empty hits: {}", table)
            return []

        match_expr = " | ".join(t.replace("'", " ") for t in terms)
        where_doc = f" AND {ATTR_DOC_ID}={int(doc_id)}" if doc_id is not None else ""
        fetch_limit = max(limit, settings.BM25_PREFETCH_LIMIT) if type_mult else limit
        ranker = f"1000*bm25f({self.k1},{self.b},{{{FIELD_COARSE}={self.coarse_boost},{FIELD_FINE}=1}})"

        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await cur.execute(
                    f"SELECT {ATTR_CHUNK_ID}, {ATTR_DOC_ID}, {ATTR_CHUNK_TYPE}, WEIGHT() as w "
                    f"FROM {table} WHERE MATCH(%s){where_doc} "
                    f"ORDER BY w DESC LIMIT {int(fetch_limit)} OPTION ranker=expr('{ranker}')",
                    (match_expr,),
                )
                rows = await cur.fetchall()
            except Exception as exc:
                raise ManticoreStoreError(f"Failed to query BM25 table {table}: {exc}") from exc

        hits = [
            Bm25ScoredPoint(chunk_id=str(chunk_id), doc_id=int(doc_id_val), score=float(w) * type_mult.get(chunk_type, 1.0))
            for chunk_id, doc_id_val, chunk_type, w in rows
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    # ---------------- 删除（文档级全量重建的删除半步）----------------
    async def delete_by_document(self, *, dataset_id: int, doc_id: int) -> int:
        """删除某文档在对应 dataset 表里的全部 chunk，返回实际删除的行数。

        表不存在时视为无操作，返回 0；与 ES 的 ``delete_by_query`` 返回 ``deleted``
        字段语义对齐（调用方按返回值判断"是否真的删到东西"，日志/幂等观测都靠它）。
        """

        table = self.table_router.table_name(dataset_id)
        if not await self._table_exists(table):
            return 0
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await cur.execute(f"DELETE FROM {table} WHERE {ATTR_DOC_ID}=%s", (doc_id,))
            except Exception as exc:
                raise ManticoreStoreError(f"Failed to delete BM25 document from {table}: {exc}") from exc
            return cur.rowcount or 0

    async def close(self) -> None:
        """关闭本 store 自建的连接/连接池（不关闭外部注入的连接，那由调用方管理）。"""

        if not self._owns_conn:
            return
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    # ---------------- 内部：连接（外部注入单连接 / 内部自建连接池） ----------------
    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        """产出一条可用连接。

        显式注入 ``conn``（测试、或调用方自行管理连接生命周期）时直接复用，不建池；
        否则从进程内连接池按需借还——单条常驻连接会让并发写入/查询请求排队在同一
        条 MySQL 协议连接上，池化后并发请求可以拿到不同的物理连接并行执行。
        """

        if self._conn is not None:
            yield self._conn
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            yield conn

    async def _get_pool(self) -> Any:
        if self._pool is None:
            aiomysql = self._aiomysql()
            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user="",
                password="",
                autocommit=True,
                connect_timeout=self.timeout,
                minsize=_POOL_MINSIZE,
                maxsize=_POOL_MAXSIZE,
            )
        return self._pool

    @staticmethod
    def _aiomysql() -> Any:
        try:
            import aiomysql
        except ImportError as exc:
            raise ManticoreConfigurationError(
                "aiomysql is required to use ManticoreBm25Store."
            ) from exc
        return aiomysql
