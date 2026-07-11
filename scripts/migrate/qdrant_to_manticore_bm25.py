#!/usr/bin/env python3
"""Qdrant/ES → Manticore BM25 在线迁移：回填、精确对账与可选修复。

安全顺序：先启用 ``BM25_WRITE_BACKENDS=qdrant,manticore``，再 backfill；反复执行
``reconcile --repair`` 直到零差异，之后才开启影子读与主读切换。所有写入均为幂等
REPLACE，脚本可以从 ``--after-id`` 续跑。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings  # noqa: E402
from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer  # noqa: E402
from src.core.storage.chunks.constants import CHUNK_LIFECYCLE_ACTIVE  # noqa: E402
from src.core.storage.manticore_bm25.store import (  # noqa: E402
    Bm25Point,
    ManticoreBm25Store,
    _chunk_id_to_row_id,
)
from src.database import close_database, get_db_context, init_database  # noqa: E402
from src.models.chunk_record import ChunkRecordDB  # noqa: E402


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    dataset_id: int
    user_id: int
    expected: int
    actual: int
    missing: tuple[str, ...]
    orphan: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.missing and not self.orphan and self.expected == self.actual


def _base_chunk_filter(*, dataset_id: int | None, user_id: int | None):
    predicates = [ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE]
    if dataset_id is not None:
        predicates.append(ChunkRecordDB.set_id == dataset_id)
    if user_id is not None:
        predicates.append(ChunkRecordDB.user_id == user_id)
    return predicates


def _to_points(records: Sequence[ChunkRecordDB], tokenizer: RagFlowTokenizer) -> list[Bm25Point]:
    points: list[Bm25Point] = []
    for record in records:
        coarse = tokenizer.tokenize(record.content).coarse_tokens.strip()
        if not coarse:
            raise RuntimeError(f"chunk {record.chunk_id} produced empty coarse tokens")
        size = len(coarse.encode("utf-8"))
        if size > settings.MANTICORE_MAX_DOCUMENT_BYTES:
            raise RuntimeError(
                f"chunk {record.chunk_id} coarse tokens exceed limit: "
                f"{size}>{settings.MANTICORE_MAX_DOCUMENT_BYTES}"
            )
        points.append(
            Bm25Point(
                chunk_id=record.chunk_id,
                doc_id=int(record.doc_id),
                user_id=int(record.user_id),
                dataset_id=int(record.set_id),
                chunk_type=record.chunk_type,
                coarse_tokens=coarse,
            )
        )
    return points


async def _write_records(
    records: Sequence[ChunkRecordDB],
    *,
    store: ManticoreBm25Store,
    tokenizer: RagFlowTokenizer,
) -> int:
    points = _to_points(records, tokenizer)
    verified = await store.upsert_chunks(points)
    expected_ids = {point.chunk_id for point in points}
    if set(verified) != expected_ids:
        missing = sorted(expected_ids - set(verified))
        raise RuntimeError(f"Manticore read-back verification failed: missing={missing[:20]}")
    return len(verified)


async def backfill(args: argparse.Namespace, store: ManticoreBm25Store) -> int:
    tokenizer = RagFlowTokenizer()
    after_id = args.after_id
    total = 0
    pages = 0
    while True:
        async with get_db_context() as db:
            stmt = (
                select(ChunkRecordDB)
                .where(
                    *_base_chunk_filter(
                        dataset_id=args.dataset_id,
                        user_id=args.user_id,
                    ),
                    ChunkRecordDB.id > after_id,
                )
                .order_by(ChunkRecordDB.id.asc())
                .limit(args.page_size)
            )
            records = list((await db.execute(stmt)).scalars().all())
        if not records:
            break
        written = await _write_records(records, store=store, tokenizer=tokenizer)
        after_id = int(records[-1].id)
        total += written
        pages += 1
        print(f"backfill page={pages} after_id={after_id} written={written} total={total}")
        if args.max_pages and pages >= args.max_pages:
            break
    print(f"backfill complete pages={pages} written={total} checkpoint_after_id={after_id}")
    return 0


async def _dataset_owners(args: argparse.Namespace) -> dict[int, set[int]]:
    async with get_db_context() as db:
        stmt = (
            select(
                ChunkRecordDB.set_id,
                ChunkRecordDB.user_id,
                func.count(ChunkRecordDB.id),
            )
            .where(
                *_base_chunk_filter(
                    dataset_id=args.dataset_id,
                    user_id=args.user_id,
                )
            )
            .group_by(ChunkRecordDB.set_id, ChunkRecordDB.user_id)
        )
        rows = (await db.execute(stmt)).all()
    owners: dict[int, set[int]] = defaultdict(set)
    for dataset_id, user_id, _count in rows:
        owners[int(dataset_id)].add(int(user_id))
    return owners


async def _expected_ids(dataset_id: int, user_id: int) -> dict[int, str]:
    async with get_db_context() as db:
        stmt = select(ChunkRecordDB.chunk_id).where(
            ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
            ChunkRecordDB.set_id == dataset_id,
            ChunkRecordDB.user_id == user_id,
        )
        chunk_ids = [str(value) for value in (await db.execute(stmt)).scalars().all()]
    expected = {_chunk_id_to_row_id(chunk_id): chunk_id for chunk_id in chunk_ids}
    if len(expected) != len(chunk_ids):
        raise RuntimeError(
            f"detected 63-bit row-id collision in dataset_id={dataset_id}; aborting migration"
        )
    return expected


async def _actual_ids(
    store: ManticoreBm25Store,
    *,
    dataset_id: int,
    user_id: int,
    page_size: int,
) -> dict[int, str]:
    actual: dict[int, str] = {}
    after_row_id = 0
    while True:
        page = await store.list_chunk_ids_after(
            user_id=user_id,
            dataset_id=dataset_id,
            after_row_id=after_row_id,
            limit=page_size,
        )
        if not page:
            break
        actual.update(page)
        after_row_id = page[-1][0]
    return actual


async def _load_records(chunk_ids: Sequence[str]) -> list[ChunkRecordDB]:
    records: list[ChunkRecordDB] = []
    for start in range(0, len(chunk_ids), 500):
        batch = chunk_ids[start : start + 500]
        async with get_db_context() as db:
            stmt = select(ChunkRecordDB).where(
                ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
                ChunkRecordDB.chunk_id.in_(batch),
            )
            records.extend((await db.execute(stmt)).scalars().all())
    return records


async def _reconcile_dataset(
    *,
    store: ManticoreBm25Store,
    tokenizer: RagFlowTokenizer,
    dataset_id: int,
    user_id: int,
    page_size: int,
    repair: bool,
) -> ReconcileResult:
    expected = await _expected_ids(dataset_id, user_id)
    actual = await _actual_ids(
        store,
        dataset_id=dataset_id,
        user_id=user_id,
        page_size=page_size,
    )
    missing_row_ids = expected.keys() - actual.keys()
    orphan_row_ids = actual.keys() - expected.keys()
    missing = tuple(expected[row_id] for row_id in sorted(missing_row_ids))
    orphan = tuple(actual[row_id] for row_id in sorted(orphan_row_ids))
    result = ReconcileResult(
        dataset_id=dataset_id,
        user_id=user_id,
        expected=len(expected),
        actual=len(actual),
        missing=missing,
        orphan=orphan,
    )
    if repair and not result.clean:
        if missing:
            records = await _load_records(missing)
            if len(records) != len(missing):
                raise RuntimeError(
                    f"DB changed during repair for dataset_id={dataset_id}; rerun reconciliation"
                )
            await _write_records(records, store=store, tokenizer=tokenizer)
        if orphan:
            await store.delete_chunk_ids(
                user_id=user_id,
                dataset_id=dataset_id,
                chunk_ids=orphan,
            )
        return await _reconcile_dataset(
            store=store,
            tokenizer=tokenizer,
            dataset_id=dataset_id,
            user_id=user_id,
            page_size=page_size,
            repair=False,
        )
    return result


async def reconcile(args: argparse.Namespace, store: ManticoreBm25Store) -> int:
    tokenizer = RagFlowTokenizer()
    owners = await _dataset_owners(args)
    table_dataset_ids = set(await store.list_dataset_ids())
    selected_db_ids = set(owners)
    if args.dataset_id is not None:
        table_dataset_ids &= {args.dataset_id}
    elif args.user_id is not None:
        # 表名不带 user_id；限定用户运行时不能把其他用户的数据集误判为孤儿表。
        table_dataset_ids &= selected_db_ids
    all_dataset_ids = sorted(selected_db_ids | table_dataset_ids)
    failures = 0
    for dataset_id in all_dataset_ids:
        db_owners = owners.get(dataset_id, set())
        if len(db_owners) > 1:
            print(f"ERROR dataset_id={dataset_id} has multiple DB owners={sorted(db_owners)}")
            failures += 1
            continue
        if not db_owners:
            table_owners = await store.dataset_owner_ids(dataset_id)
            print(
                f"ORPHAN_TABLE dataset_id={dataset_id} owners={sorted(table_owners)} "
                f"repair={args.repair}"
            )
            if args.repair and len(table_owners) <= 1:
                owner_id = next(iter(table_owners), 1)
                await store.drop_table(dataset_id, user_id=owner_id)
            else:
                failures += 1
            continue

        user_id = next(iter(db_owners))
        result = await _reconcile_dataset(
            store=store,
            tokenizer=tokenizer,
            dataset_id=dataset_id,
            user_id=user_id,
            page_size=args.page_size,
            repair=args.repair,
        )
        print(
            f"reconcile dataset_id={dataset_id} user_id={user_id} "
            f"expected={result.expected} actual={result.actual} "
            f"missing={len(result.missing)} orphan={len(result.orphan)}"
        )
        if not result.clean:
            print(f"  missing_sample={list(result.missing[:10])}")
            print(f"  orphan_sample={list(result.orphan[:10])}")
            failures += 1
    print(f"reconcile complete datasets={len(all_dataset_ids)} failures={failures}")
    return 0 if failures == 0 else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manticore BM25 online migration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--dataset-id", type=int)
        subparser.add_argument("--user-id", type=int)
        subparser.add_argument("--page-size", type=int, default=500)
        subparser.add_argument("--manticore-host", default=settings.MANTICORE_HOST)
        subparser.add_argument("--manticore-port", type=int, default=settings.MANTICORE_PORT)
        subparser.add_argument("--table-prefix", default=settings.MANTICORE_BM25_TABLE_PREFIX)

    backfill_parser = subparsers.add_parser("backfill")
    add_common(backfill_parser)
    backfill_parser.add_argument("--after-id", type=int, default=0)
    backfill_parser.add_argument("--max-pages", type=int, default=0)
    backfill_parser.add_argument(
        "--allow-unsafe-single-write",
        action="store_true",
        help="仅离线维护窗口使用；在线迁移必须先启用包含 Manticore 的双写",
    )

    reconcile_parser = subparsers.add_parser("reconcile")
    add_common(reconcile_parser)
    reconcile_parser.add_argument(
        "--repair",
        action="store_true",
        help="补写 missing、删除 orphan，并清理 DB 已不存在且 owner 唯一的孤儿表",
    )
    args = parser.parse_args()
    if args.page_size <= 0:
        parser.error("--page-size must be positive")
    if args.dataset_id is not None and args.dataset_id <= 0:
        parser.error("--dataset-id must be positive")
    if args.user_id is not None and args.user_id <= 0:
        parser.error("--user-id must be positive")
    return args


async def _main(args: argparse.Namespace) -> int:
    write_backends = {
        backend.strip()
        for backend in (settings.BM25_WRITE_BACKENDS or settings.BM25_BACKEND).split(",")
        if backend.strip()
    }
    if (
        args.command == "backfill"
        and not args.allow_unsafe_single_write
        and ("manticore" not in write_backends or len(write_backends) < 2)
    ):
        raise RuntimeError(
            "online backfill requires BM25_WRITE_BACKENDS to contain Manticore and the current "
            "primary backend; use --allow-unsafe-single-write only in a write-frozen window"
        )

    store = ManticoreBm25Store(
        host=args.manticore_host,
        port=args.manticore_port,
        table_prefix=args.table_prefix,
    )
    await init_database()
    try:
        await store.ping()
        print(
            f"preflight command={args.command} read={settings.BM25_BACKEND} "
            f"writes={sorted(write_backends)} prefix={args.table_prefix}"
        )
        if args.command == "backfill":
            return await backfill(args, store)
        return await reconcile(args, store)
    finally:
        await store.close()
        await close_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
