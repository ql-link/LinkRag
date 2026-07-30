"""Manticore BM25 存储：按 dataset_id 物理建表，coarse-only 原生 BM25。

与 Qdrant BM25 后端（``qdrant_bm25/store.py``）的关键差异：

- **不需要客户端补算 TF/长度归一**：coarse 预分词字段由 Manticore 原生
  ``bm25a(k1, b)`` 计分，TF、长度归一、IDF 全部由对应 dataset 表的语料动态统计。
- **avgdl 用 Manticore 动态计算**，不传常量覆盖：每张表天然只含一个 dataset 的文档，
  动态平均值本来就是"按 dataset 计算"，不存在跨租户漂移的问题（这是 Qdrant/ES 单一
  全局 collection/index 才会有的问题）。
- **表按 dataset_id 精确路由**（``TableRouter``），不是按 user 哈希分桶——不需要额外
  的 tenant filter 把 BM25 统计口径圈起来；查询/删除仍保留 user_id 硬过滤，写入也校验
  表内 owner，作为消息错配或越权调用的第二道防线。
- **类型加权在候选池召回后于应用层做**：Manticore 的 ``bm25a()`` 是黑盒函数，不支持
  像 Qdrant Formula Query 那样在打分公式里插入按 payload 匹配的条件项；改为先取
  ``prefetch_limit`` 条候选，按 chunk_type 在 Python 侧乘一次权重再重新排序截断，
  语义上与 Qdrant 的「先召回、后按类型乘数重排」一致，只是实现层挪到了应用层。

安全边界：不做任何 SQL 字符串拼接接收用户输入——表名只来自 ``TableRouter``（内部
生成，dataset_id 是整数），MATCH()/WHERE 的值全部走参数化查询。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import ssl
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
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
    IDF_FLAGS,
    TABLE_DDL_OPTIONS,
)
from .table_router import TableRouter

_BM25_K1_DEFAULT = 1.2
_BM25_B_DEFAULT = 0.75
_VERIFY_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class Bm25Point:
    """一个待写入 Manticore 的 chunk：coarse 预分词文本 + 属性。"""

    chunk_id: str
    doc_id: int
    user_id: int
    dataset_id: int
    chunk_type: str
    coarse_tokens: str


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
        timeout: float | None = None,
        connect_timeout: float | None = None,
        acquire_timeout: float | None = None,
        table_prefix: str | None = None,
        table_router: TableRouter | None = None,
        k1: float | None = None,
        b: float | None = None,
        pool_minsize: int | None = None,
        pool_maxsize: int | None = None,
        pool_recycle: int | None = None,
        write_batch_size: int | None = None,
        write_batch_bytes: int | None = None,
        user: str | None = None,
        password: str | None = None,
        ssl_enabled: bool | None = None,
        ssl_ca: str | None = None,
        ssl_cert: str | None = None,
        ssl_key: str | None = None,
        ssl_check_hostname: bool | None = None,
    ) -> None:
        self._conn = conn
        self._owns_conn = conn is None
        self._pool: Any | None = None
        self.host = host or settings.MANTICORE_HOST
        self.port = port or settings.MANTICORE_PORT
        self.timeout = float(
            timeout if timeout is not None else getattr(settings, "MANTICORE_TIMEOUT_SECONDS", 10)
        )
        self.connect_timeout = float(
            connect_timeout
            if connect_timeout is not None
            else (
                timeout
                if timeout is not None
                else getattr(settings, "MANTICORE_CONNECT_TIMEOUT_SECONDS", 5)
            )
        )
        self.acquire_timeout = float(
            acquire_timeout
            if acquire_timeout is not None
            else getattr(settings, "MANTICORE_POOL_ACQUIRE_TIMEOUT_SECONDS", 5)
        )
        self.pool_minsize = int(
            pool_minsize
            if pool_minsize is not None
            else getattr(settings, "MANTICORE_POOL_MINSIZE", 1)
        )
        self.pool_maxsize = int(
            pool_maxsize
            if pool_maxsize is not None
            else getattr(settings, "MANTICORE_POOL_MAXSIZE", 10)
        )
        self.pool_recycle = int(
            pool_recycle
            if pool_recycle is not None
            else getattr(settings, "MANTICORE_POOL_RECYCLE_SECONDS", 300)
        )
        self.write_batch_size = int(
            write_batch_size
            if write_batch_size is not None
            else getattr(settings, "MANTICORE_WRITE_BATCH_SIZE", 500)
        )
        self.write_batch_bytes = int(
            write_batch_bytes
            if write_batch_bytes is not None
            else getattr(settings, "MANTICORE_WRITE_BATCH_BYTES", 5 * 1024 * 1024)
        )
        self.user = user if user is not None else getattr(settings, "MANTICORE_USER", "")
        self.password = (
            password if password is not None else getattr(settings, "MANTICORE_PASSWORD", "")
        )
        self.ssl_enabled = (
            ssl_enabled
            if ssl_enabled is not None
            else bool(getattr(settings, "MANTICORE_SSL_ENABLED", False))
        )
        self.ssl_ca = ssl_ca if ssl_ca is not None else getattr(settings, "MANTICORE_SSL_CA", None)
        self.ssl_cert = (
            ssl_cert if ssl_cert is not None else getattr(settings, "MANTICORE_SSL_CERT", None)
        )
        self.ssl_key = (
            ssl_key if ssl_key is not None else getattr(settings, "MANTICORE_SSL_KEY", None)
        )
        self.ssl_check_hostname = (
            ssl_check_hostname
            if ssl_check_hostname is not None
            else bool(getattr(settings, "MANTICORE_SSL_CHECK_HOSTNAME", True))
        )
        self.table_router = table_router or TableRouter(
            prefix=table_prefix or settings.MANTICORE_BM25_TABLE_PREFIX
        )
        self.k1 = k1 if k1 is not None else getattr(settings, "BM25_K1", _BM25_K1_DEFAULT)
        self.b = b if b is not None else getattr(settings, "BM25_B", _BM25_B_DEFAULT)
        self._ready_tables: set[str] = set()
        self._pool_lock = asyncio.Lock()
        self._table_lock = asyncio.Lock()

    # ---------------- 表生命周期 ----------------
    async def ensure_table(self, dataset_id: int, *, force: bool = False) -> str:
        """确保表存在且结构属于当前索引代际，错误结构不允许静默复用。"""

        table = self.table_router.table_name(dataset_id)
        async with self._table_lock:
            if not force and table in self._ready_tables:
                return table
            async with self._connection() as conn:
                cur = await conn.cursor()
                try:
                    await self._ensure_table_on_connection(conn, cur, table)
                except Exception as exc:
                    raise ManticoreStoreError(f"Failed to ensure table {table}: {exc}") from exc
            self._ready_tables.add(table)
        return table

    @staticmethod
    def _table_ddl(table: str) -> str:
        return (
            f"CREATE TABLE IF NOT EXISTS {table}("
            f"{ATTR_CHUNK_ID} string, {ATTR_DOC_ID} bigint, {ATTR_USER_ID} bigint, "
            f"{ATTR_CHUNK_TYPE} string, {FIELD_COARSE} text indexed"
            f") {TABLE_DDL_OPTIONS}"
        )

    async def _ensure_table_on_connection(self, conn: Any, cur: Any, table: str) -> None:
        await self._execute(conn, cur, self._table_ddl(table))
        await self._validate_table_schema(conn, cur, table)

    async def _validate_table_schema(self, conn: Any, cur: Any, table: str) -> None:
        """校验已存在的同名表，避免 ``IF NOT EXISTS`` 把结构漂移掩盖掉。"""

        await self._execute(conn, cur, f"DESC {table}")
        rows = await cur.fetchall()
        actual = {str(row[0]): (str(row[1]).lower(), str(row[2]).lower()) for row in rows}
        required = {
            "id": ("bigint", ""),
            ATTR_CHUNK_ID: ("string", ""),
            ATTR_DOC_ID: ("bigint", ""),
            ATTR_USER_ID: ("bigint", ""),
            ATTR_CHUNK_TYPE: ("string", ""),
            FIELD_COARSE: ("text", "indexed"),
        }
        mismatches = {
            field: {"expected": expected, "actual": actual.get(field)}
            for field, expected in required.items()
            if actual.get(field) != expected
        }
        unexpected_text_fields = sorted(
            field
            for field, (field_type, _properties) in actual.items()
            if field_type == "text" and field != FIELD_COARSE
        )
        if mismatches or unexpected_text_fields:
            raise ManticoreStoreError(
                f"Incompatible schema for {table}: mismatches={mismatches}, "
                f"unexpected_text_fields={unexpected_text_fields}"
            )

        await self._execute(conn, cur, f"SHOW CREATE TABLE {table}")
        create_rows = await cur.fetchall()
        create_sql = str(create_rows[0][1]).lower() if create_rows else ""
        required_options = (
            "index_field_lengths='1'",
            "charset_table='non_cjk, chinese'",
            "morphology='none'",
        )
        missing_options = [option for option in required_options if option not in create_sql]
        if missing_options:
            raise ManticoreStoreError(
                f"Incompatible table options for {table}: missing={missing_options}"
            )

    async def drop_table(self, dataset_id: int, *, user_id: int) -> None:
        """整表物理删除（dataset 被整体删除时用，而非 ``delete_by_document`` 的文档级删除）。

        与 ES/Qdrant 不同：Manticore 每个 dataset 一张物理表，dataset 删除必须显式
        ``DROP TABLE`` 才能真正回收——只删行不删表会让空表在 dataset 之间只增不减，
        对应的内存/句柄也不会释放（见 POC 里"删表后内存不随 DROP 立即回落"的现象）。
        """

        table = self.table_router.table_name(dataset_id)
        async with self._table_lock:
            if not await self._table_exists(table):
                self._ready_tables.discard(table)
                return
            async with self._connection() as conn:
                cur = await conn.cursor()
                try:
                    # user_id 是删除消息的归属兜底。整表 DROP 前用表内实际数据
                    # 再验一次，防止「dataset_id 正确、user_id 错配」的消息误删。
                    await self._execute(
                        conn,
                        cur,
                        f"SELECT {ATTR_USER_ID} FROM {table} GROUP BY {ATTR_USER_ID} LIMIT 2",
                    )
                    owners = {int(row[0]) for row in await cur.fetchall()}
                    if owners and owners != {int(user_id)}:
                        raise ManticoreStoreError(
                            f"Refusing to drop {table}: expected user_id={user_id}, "
                            f"actual={sorted(owners)}"
                        )
                    await self._execute(conn, cur, f"DROP TABLE IF EXISTS {table}")
                except Exception as exc:
                    if isinstance(exc, ManticoreStoreError):
                        raise
                    raise ManticoreStoreError(f"Failed to drop table {table}: {exc}") from exc
            self._ready_tables.discard(table)

    async def _table_exists(self, table: str) -> bool:
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(conn, cur, "SHOW TABLES LIKE %s", (table,))
                rows = await cur.fetchall()
                # LIKE 会把表名中的 '_' 解释为单字符通配符，必须精确比较。
                return any(str(row[0]) == table for row in rows)
            except Exception as exc:
                raise ManticoreStoreError(
                    f"Failed to check table existence {table}: {exc}"
                ) from exc

    # ---------------- 写入 ----------------
    async def upsert_chunks(self, points: Sequence[Bm25Point]) -> list[str]:
        """按 chunk_id 幂等写入（``REPLACE INTO``），返回回读校验后确认已落地的 chunk_id。

        多行 ``REPLACE INTO`` 同时按条数和估算 UTF-8 字节拆批。任一批失败即向文档级
        编排抛出，由上层统一标记失败并安全重试；批次写完后仍按 chunk_id 批量回读，
        只有真正查得到的行才计入返回值。
        """

        if not points:
            return []
        by_dataset: dict[int, list[Bm25Point]] = {}
        for p in points:
            by_dataset.setdefault(p.dataset_id, []).append(p)

        verified: list[str] = []
        for dataset_id, group in by_dataset.items():
            user_ids = {int(point.user_id) for point in group}
            if len(user_ids) != 1:
                raise ManticoreStoreError(
                    f"Refusing mixed-owner write for dataset_id={dataset_id}: "
                    f"user_ids={sorted(user_ids)}"
                )
            expected_user_id = next(iter(user_ids))
            table = await self.ensure_table(dataset_id)
            attempted: list[str] = []
            async with self._connection() as conn:
                cur = await conn.cursor()
                await self._assert_table_owner(conn, cur, table, expected_user_id)
                for batch in self._write_batches(group):
                    placeholders = ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(batch))
                    params: list[Any] = []
                    for point in batch:
                        params.extend(
                            (
                                _chunk_id_to_row_id(point.chunk_id),
                                point.chunk_id,
                                point.doc_id,
                                point.user_id,
                                point.chunk_type,
                                point.coarse_tokens,
                            )
                        )
                    sql = (
                        f"REPLACE INTO {table} "
                        f"(id, {ATTR_CHUNK_ID}, {ATTR_DOC_ID}, {ATTR_USER_ID}, "
                        f"{ATTR_CHUNK_TYPE}, {FIELD_COARSE}) VALUES {placeholders}"
                    )
                    try:
                        await self._execute(conn, cur, sql, tuple(params))
                    except Exception as exc:
                        # 其他 worker DROP 表后，本进程的 ready cache 可能短暂过期。
                        # 只对明确的缺表错误强制重建并幂等重试一次。
                        if self._is_missing_table_error(exc):
                            self._ready_tables.discard(table)
                            async with self._table_lock:
                                await self._ensure_table_on_connection(conn, cur, table)
                                self._ready_tables.add(table)
                            await self._execute(conn, cur, sql, tuple(params))
                        else:
                            raise ManticoreStoreError(
                                f"Failed to batch upsert {len(batch)} chunks into {table}: {exc}"
                            ) from exc
                    attempted.extend(point.chunk_id for point in batch)
            if attempted:
                verified.extend(await self._verify_written(table, attempted))
        return verified

    async def _assert_table_owner(
        self,
        conn: Any,
        cur: Any,
        table: str,
        expected_user_id: int,
    ) -> None:
        await self._execute(
            conn,
            cur,
            f"SELECT {ATTR_USER_ID} FROM {table} LIMIT 1",
        )
        owners = {int(row[0]) for row in await cur.fetchall()}
        if owners and owners != {expected_user_id}:
            raise ManticoreStoreError(
                f"Refusing write to {table}: expected user_id={expected_user_id}, "
                f"actual={sorted(owners)}"
            )

    def _write_batches(self, points: Sequence[Bm25Point]) -> list[list[Bm25Point]]:
        """按条数和估算字节双限制拆分多行 REPLACE 批次。"""

        batches: list[list[Bm25Point]] = []
        current: list[Bm25Point] = []
        current_bytes = 0
        for point in points:
            point_bytes = (
                len(point.chunk_id.encode("utf-8"))
                + len(point.chunk_type.encode("utf-8"))
                + len(point.coarse_tokens.encode("utf-8"))
                + 64
            )
            if current and (
                len(current) >= self.write_batch_size
                or current_bytes + point_bytes > self.write_batch_bytes
            ):
                batches.append(current)
                current = []
                current_bytes = 0
            current.append(point)
            current_bytes += point_bytes
        if current:
            batches.append(current)
        return batches

    async def _verify_written(self, table: str, chunk_ids: Sequence[str]) -> list[str]:
        """按 chunk_id 批量回读，返回真正查得到的子集——唯一可信的"写入成功"判据。

        与单纯"execute 没抛异常就算成功"不同：这一步能捕捉网络层已确认、但因值
        截断/类型静默转换等原因未真正落地的行。回读本身失败（连接不可用等）视为
        无法判断，直接抛出，交给调用方按整批失败处理。
        """

        if not chunk_ids:
            return []
        verified: list[str] = []
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                for start in range(0, len(chunk_ids), _VERIFY_BATCH_SIZE):
                    batch = chunk_ids[start : start + _VERIFY_BATCH_SIZE]
                    placeholders = ",".join(["%s"] * len(batch))
                    # Manticore SELECT 默认 LIMIT 20；不显式给 LIMIT 会把第 21 条起
                    # 已成功写入的 chunk 误判为失败。同时分批限制 SQL/params 大小。
                    await self._execute(
                        conn,
                        cur,
                        f"SELECT {ATTR_CHUNK_ID} FROM {table} "
                        f"WHERE {ATTR_CHUNK_ID} IN ({placeholders}) LIMIT {len(batch)}",
                        tuple(batch),
                    )
                    verified.extend(str(row[0]) for row in await cur.fetchall())
            except Exception as exc:
                raise ManticoreStoreError(
                    f"Failed to verify written BM25 chunks in {table}: {exc}"
                ) from exc
        return verified

    # ---------------- 查询（coarse BM25 召回 + 应用层类型乘数重排）----------------
    async def query(
        self,
        *,
        query_terms: Sequence[str],
        user_id: int,
        dataset_id: int,
        doc_id: int | None,
        type_mult: Mapping[str, float],
        limit: int,
    ) -> list[Bm25ScoredPoint]:
        """按 dataset_id 路由到对应表做 coarse BM25 召回并重排。

        表不存在时返回空（等价于"无数据"，与写入侧解耦的合法中间态，对齐 Qdrant/ES
        collection/index 不存在时的行为）。
        """

        terms = [t.strip() for t in query_terms if t and t.strip()]
        if not terms:
            return []

        table = self.table_router.table_name(dataset_id)

        match_expr = self._build_match_expr(terms)
        where_doc = f" AND {ATTR_DOC_ID}=%s" if doc_id is not None else ""
        params: tuple[Any, ...] = (
            (match_expr, int(user_id), int(doc_id))
            if doc_id is not None
            else (match_expr, int(user_id))
        )
        fetch_limit = max(limit, settings.BM25_PREFETCH_LIMIT) if type_mult else limit
        ranker = f"1000*bm25a({self.k1},{self.b})"

        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(
                    conn,
                    cur,
                    f"SELECT {ATTR_CHUNK_ID}, {ATTR_DOC_ID}, {ATTR_CHUNK_TYPE}, WEIGHT() as w "
                    f"FROM {table} WHERE MATCH(%s) AND {ATTR_USER_ID}=%s{where_doc} "
                    f"ORDER BY w DESC, id ASC LIMIT {int(fetch_limit)} "
                    f"OPTION ranker=expr('{ranker}'), idf='{IDF_FLAGS}'",
                    params,
                )
                rows = await cur.fetchall()
            except Exception as exc:
                if self._is_missing_table_error(exc):
                    self._ready_tables.discard(table)
                    logger.warning(
                        "[ManticoreBm25Store.query] table not found; empty hits: {}", table
                    )
                    return []
                raise ManticoreStoreError(f"Failed to query BM25 table {table}: {exc}") from exc

        hits = [
            Bm25ScoredPoint(
                chunk_id=str(chunk_id),
                doc_id=int(doc_id_val),
                score=float(w) * type_mult.get(chunk_type, 1.0),
            )
            for chunk_id, doc_id_val, chunk_type, w in rows
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    @staticmethod
    def _build_match_expr(terms: Sequence[str]) -> str:
        """将 term 安全编码成 Manticore extended-query OR 表达式。

        SQL 参数化不会转义 MATCH 内部的 ``|``/``_``/``@`` 等查询语法。
        逐词双引号包裹并转义反斜杠/双引号，可使 ``foo_bar`` 分出的
        ``_`` 安全退化为无命中词，而不是解析错误。
        """

        unique_terms = dict.fromkeys(t for term in terms if (t := str(term).strip()))
        quoted: list[str] = []
        for term in unique_terms:
            escaped = term.replace("\\", "\\\\").replace('"', '\\"')
            quoted.append(f'"{escaped}"')
        return " | ".join(quoted)

    # ---------------- 删除（文档级全量重建的删除半步）----------------
    async def delete_by_document(self, *, user_id: int, dataset_id: int, doc_id: int) -> int:
        """删除某文档在对应 dataset 表里的全部 chunk，返回实际删除的行数。

        表不存在时视为无操作，返回 0；与 ES 的 ``delete_by_query`` 返回 ``deleted``
        字段语义对齐（调用方按返回值判断"是否真的删到东西"，日志/幂等观测都靠它）。
        """

        table = self.table_router.table_name(dataset_id)
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(
                    conn,
                    cur,
                    f"DELETE FROM {table} WHERE {ATTR_USER_ID}=%s AND {ATTR_DOC_ID}=%s",
                    (user_id, doc_id),
                )
            except Exception as exc:
                if self._is_missing_table_error(exc):
                    self._ready_tables.discard(table)
                    return 0
                raise ManticoreStoreError(
                    f"Failed to delete BM25 document from {table}: {exc}"
                ) from exc
            return cur.rowcount or 0

    async def count_chunks(self, *, user_id: int, dataset_id: int) -> int:
        """返回一个租户数据集的行数，供迁移对账与运维检查。"""

        table = self.table_router.table_name(dataset_id)
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(
                    conn,
                    cur,
                    f"SELECT COUNT(*) FROM {table} WHERE {ATTR_USER_ID}=%s",
                    (user_id,),
                )
                rows = await cur.fetchall()
            except Exception as exc:
                if self._is_missing_table_error(exc):
                    self._ready_tables.discard(table)
                    return 0
                raise ManticoreStoreError(f"Failed to count chunks in {table}: {exc}") from exc
        return int(rows[0][0]) if rows else 0

    async def list_chunk_ids_after(
        self,
        *,
        user_id: int,
        dataset_id: int,
        after_row_id: int = 0,
        limit: int = 1000,
    ) -> list[tuple[int, str]]:
        """按内部整数 id 做 keyset 分页，避免大 OFFSET 对账扫描退化。"""

        if limit <= 0:
            raise ValueError("limit must be positive")
        table = self.table_router.table_name(dataset_id)
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(
                    conn,
                    cur,
                    f"SELECT id, {ATTR_CHUNK_ID} FROM {table} "
                    f"WHERE {ATTR_USER_ID}=%s AND id>%s ORDER BY id ASC LIMIT {int(limit)}",
                    (user_id, after_row_id),
                )
                rows = await cur.fetchall()
            except Exception as exc:
                if self._is_missing_table_error(exc):
                    self._ready_tables.discard(table)
                    return []
                raise ManticoreStoreError(f"Failed to list chunk ids from {table}: {exc}") from exc
        return [(int(row_id), str(chunk_id)) for row_id, chunk_id in rows]

    async def delete_chunk_ids(
        self,
        *,
        user_id: int,
        dataset_id: int,
        chunk_ids: Sequence[str],
    ) -> int:
        """按租户保护批量删除指定 chunk，供迁移对账修复孤儿行。"""

        if not chunk_ids:
            return 0
        table = self.table_router.table_name(dataset_id)
        deleted = 0
        for start in range(0, len(chunk_ids), _VERIFY_BATCH_SIZE):
            batch = chunk_ids[start : start + _VERIFY_BATCH_SIZE]
            row_ids = tuple(_chunk_id_to_row_id(chunk_id) for chunk_id in batch)
            placeholders = ",".join(["%s"] * len(row_ids))
            async with self._connection() as conn:
                cur = await conn.cursor()
                try:
                    await self._execute(
                        conn,
                        cur,
                        f"DELETE FROM {table} WHERE {ATTR_USER_ID}=%s "
                        f"AND id IN ({placeholders})",
                        (user_id, *row_ids),
                    )
                except Exception as exc:
                    if self._is_missing_table_error(exc):
                        self._ready_tables.discard(table)
                        return deleted
                    raise ManticoreStoreError(
                        f"Failed to delete reconciled chunks from {table}: {exc}"
                    ) from exc
                deleted += int(cur.rowcount or 0)
        return deleted

    async def list_dataset_ids(self) -> list[int]:
        """列出当前 prefix 下的 dataset 表；对 SHOW LIKE 的通配结果再次严格解析。"""

        prefix = self.table_router.prefix
        pattern = re.compile(rf"^{re.escape(prefix)}_([1-9][0-9]*)$")
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(conn, cur, "SHOW TABLES LIKE %s", (f"{prefix}_%",))
                rows = await cur.fetchall()
            except Exception as exc:
                raise ManticoreStoreError(
                    f"Failed to list Manticore dataset tables: {exc}"
                ) from exc
        return sorted(
            int(match.group(1))
            for row in rows
            if (match := pattern.fullmatch(str(row[0]))) is not None
        )

    async def dataset_owner_ids(self, dataset_id: int) -> set[int]:
        """读取表内最多两个 owner，用于识别非法混租或清理 DB 已不存在的孤儿表。"""

        table = self.table_router.table_name(dataset_id)
        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(
                    conn,
                    cur,
                    f"SELECT {ATTR_USER_ID} FROM {table} GROUP BY {ATTR_USER_ID} LIMIT 2",
                )
                rows = await cur.fetchall()
            except Exception as exc:
                if self._is_missing_table_error(exc):
                    return set()
                raise ManticoreStoreError(f"Failed to inspect owners in {table}: {exc}") from exc
        return {int(row[0]) for row in rows}

    async def ping(self) -> None:
        """执行一次轻量 SQL，用于 readiness；失败和超时均向调用方传播。"""

        async with self._connection() as conn:
            cur = await conn.cursor()
            try:
                await self._execute(conn, cur, "SELECT 1")
                rows = await cur.fetchall()
            except Exception as exc:
                raise ManticoreStoreError(f"Manticore readiness check failed: {exc}") from exc
        if rows != ((1,),) and rows != [(1,)]:
            raise ManticoreStoreError(f"Manticore readiness check returned unexpected rows: {rows}")

    async def close(self) -> None:
        """关闭本 store 自建的连接/连接池（不关闭外部注入的连接，那由调用方管理）。"""

        if not self._owns_conn:
            return
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        async with self._pool_lock:
            pool = self._pool
            self._pool = None
        if pool is not None:
            pool.close()
            await pool.wait_closed()

    async def _execute(
        self,
        conn: Any,
        cur: Any,
        sql: str,
        params: tuple[Any, ...] | None = None,
    ) -> None:
        """在单条 SQL 截止时间内执行；超时后废弃当前协议连接。"""

        try:
            await asyncio.wait_for(cur.execute(sql, params), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            # 取消发生时 MySQL wire 响应可能仍在途中，该连接不应回池复用。
            conn.close()
            raise ManticoreStoreError(f"Manticore SQL timed out after {self.timeout}s") from exc

    @staticmethod
    def _is_missing_table_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return "unknown local table" in message or "unknown table" in message

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
        acquire_ctx = pool.acquire()
        try:
            conn = await asyncio.wait_for(acquire_ctx.__aenter__(), timeout=self.acquire_timeout)
        except TimeoutError as exc:
            raise ManticoreStoreError(
                f"Timed out acquiring Manticore connection after {self.acquire_timeout}s"
            ) from exc
        try:
            yield conn
        finally:
            await acquire_ctx.__aexit__(None, None, None)

    async def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is not None:
                return self._pool
            aiomysql = self._aiomysql()
            pool_options: dict[str, Any] = dict(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                autocommit=True,
                connect_timeout=self.connect_timeout,
                minsize=self.pool_minsize,
                maxsize=self.pool_maxsize,
                pool_recycle=self.pool_recycle,
            )
            if self.ssl_enabled:
                pool_options["ssl"] = self._ssl_context()
            self._pool = await aiomysql.create_pool(**pool_options)
        return self._pool

    def _ssl_context(self) -> ssl.SSLContext:
        try:
            context = ssl.create_default_context(cafile=self.ssl_ca or None)
            context.check_hostname = self.ssl_check_hostname
            if self.ssl_cert and self.ssl_key:
                context.load_cert_chain(certfile=self.ssl_cert, keyfile=self.ssl_key)
            return context
        except (OSError, ssl.SSLError) as exc:
            raise ManticoreConfigurationError(f"Failed to configure Manticore TLS: {exc}") from exc

    @staticmethod
    def _aiomysql() -> Any:
        try:
            import aiomysql  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ManticoreConfigurationError(
                "aiomysql is required to use ManticoreBm25Store."
            ) from exc
        return aiomysql


@lru_cache(maxsize=1)
def get_manticore_bm25_store() -> ManticoreBm25Store:
    """返回进程级共享 store/连接池，避免每条 MQ 消息新建一个池。"""

    return ManticoreBm25Store()


async def close_manticore_bm25_store() -> None:
    """关闭进程共享 Manticore 连接池（应用 lifespan shutdown 调用）。"""

    if get_manticore_bm25_store.cache_info().currsize == 0:
        return
    store = get_manticore_bm25_store()
    get_manticore_bm25_store.cache_clear()
    await store.close()
