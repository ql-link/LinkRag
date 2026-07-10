from __future__ import annotations

import os
from contextlib import suppress
from uuid import uuid4

import pytest

from src.config import settings
from src.core.storage.manticore_bm25 import Bm25Point, ManticoreBm25Store
from src.core.storage.manticore_bm25.exceptions import ManticoreStoreError


def _enabled_real_manticore_tests() -> bool:
    return os.getenv("TOLINK_RUN_REAL_MANTICORE_TESTS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_manticore_tests(),
        reason="Set TOLINK_RUN_REAL_MANTICORE_TESTS=1 to run real Manticore tests.",
    ),
]


@pytest.mark.asyncio
async def test_real_manticore_coarse_bm25_tenant_guard_and_extended_query_escape() -> None:
    pytest.importorskip("aiomysql", reason="aiomysql is required for real Manticore test")

    prefix = f"test_manticore_v2_{uuid4().hex[:12]}"
    store = ManticoreBm25Store(
        host=settings.MANTICORE_HOST,
        port=settings.MANTICORE_PORT,
        timeout=settings.MANTICORE_TIMEOUT_SECONDS,
        table_prefix=prefix,
    )
    dataset_id = 990001
    user_id = 990002
    table = f"{prefix}_{dataset_id}"

    try:
        await store.ensure_table(dataset_id)
        verified = await store.upsert_chunks(
            [
                Bm25Point(
                    chunk_id="real-manticore-code",
                    doc_id=990003,
                    user_id=user_id,
                    dataset_id=dataset_id,
                    chunk_type="code_block",
                    coarse_tokens="foo bar 配置 中心",
                ),
                Bm25Point(
                    chunk_id="real-manticore-text",
                    doc_id=990004,
                    user_id=user_id,
                    dataset_id=dataset_id,
                    chunk_type="mixed",
                    coarse_tokens="公积金 提取 流程",
                ),
            ]
        )
        assert set(verified) == {"real-manticore-code", "real-manticore-text"}
        assert await store.count_chunks(user_id=user_id, dataset_id=dataset_id) == 2
        first_page = await store.list_chunk_ids_after(
            user_id=user_id, dataset_id=dataset_id, limit=1
        )
        assert len(first_page) == 1
        second_page = await store.list_chunk_ids_after(
            user_id=user_id,
            dataset_id=dataset_id,
            after_row_id=first_page[-1][0],
            limit=10,
        )
        assert {chunk_id for _, chunk_id in first_page + second_page} == {
            "real-manticore-code",
            "real-manticore-text",
        }
        assert dataset_id in await store.list_dataset_ids()

        # infinity tokenizer 会把 foo_bar 拆出 foo/_/bar；'_' 不应再触发 P08。
        hits = await store.query(
            query_terms=["foo", "_", "bar"],
            user_id=user_id,
            dataset_id=dataset_id,
            doc_id=None,
            type_mult={},
            limit=10,
        )
        assert [hit.chunk_id for hit in hits] == ["real-manticore-code"]

        # 即使 dataset 表路由正确，错误 user_id 也不能看到或删除数据。
        assert (
            await store.query(
                query_terms=["foo"],
                user_id=user_id + 1,
                dataset_id=dataset_id,
                doc_id=None,
                type_mult={},
                limit=10,
            )
            == []
        )
        assert (
            await store.delete_by_document(
                user_id=user_id + 1, dataset_id=dataset_id, doc_id=990003
            )
            == 0
        )
        with pytest.raises(ManticoreStoreError, match="Refusing to drop"):
            await store.drop_table(dataset_id, user_id=user_id + 1)
        with pytest.raises(ManticoreStoreError, match="Refusing write"):
            await store.upsert_chunks(
                [
                    Bm25Point(
                        chunk_id="wrong-owner",
                        doc_id=990005,
                        user_id=user_id + 1,
                        dataset_id=dataset_id,
                        chunk_type="mixed",
                        coarse_tokens="不应 写入",
                    )
                ]
            )

        # 全文字段只建索引，不额外 stored 一份预分词正文。
        async with store._connection() as conn:
            cur = await conn.cursor()
            await cur.execute(f"DESC {table}")
            fields = {str(row[0]): (str(row[1]), str(row[2])) for row in await cur.fetchall()}
        assert fields["coarse"] == ("text", "indexed")
        assert "fine" not in fields
    finally:
        with suppress(Exception):
            await store.drop_table(dataset_id, user_id=user_id)
        with suppress(Exception):
            await store.close()
