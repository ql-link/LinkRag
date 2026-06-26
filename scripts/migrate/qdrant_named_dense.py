"""把旧 Qdrant collection（匿名默认 dense + named sparse）迁移到 named-dense schema。

背景：named-dense 解耦（见 docs/internals/parse_task_pipeline.md）把 dense 从 Qdrant
**匿名默认向量**改为**命名向量 `dense`**。新代码只认 named schema——旧 collection 在
迁移前，dense 写入（`update_vectors({dense: ...})`）与 dense 召回（`using="dense"`）都会
失败。本脚本做**向量保真、免重 embedding** 的就地迁移：

    snapshot（可恢复）→ scroll 读旧点（dense 在空串 key ""、sparse 在 "sparse_text"）
    → 建 named schema 新表 → 重灌（"" 重命名为 "dense"，sparse 原样）→ 校验计数 → 落定

读出形态（已实测）：collection 为「匿名 dense + named sparse」时，
``point.vector`` 是 dict：``{"": [..1024..], "sparse_text": SparseVector(...)}``。
迁移即把空串 key 改名为配置的 dense 向量名，其余原样保留。

安全设计：
- **dry-run 默认**：不加 ``--apply`` 只打印计划，绝不改动任何 collection。
- **先快照**：非空 collection 迁移前 ``create_snapshot``，失败可恢复。
- **计数校验**：每步比对 source/dest 点数，不一致即中止并保留快照 + 临时表。
- **幂等**：已是 named-dense 的 collection 自动跳过；可重复运行。
- **评测库默认排除**：``eval_kb_bucket_9`` 影响评测基线，需 ``--include-eval`` 显式纳入。
- **空表默认跳过**：空 collection 无数据但仍是旧 schema（首次写入会失败），用
  ``--include-empty`` 重建为 named schema（删后重建，无数据风险）。

用法：
    # 只看计划（默认 dry-run，全部 kb_bucket_*，排除 eval 与空表）
    python scripts/migrate/qdrant_named_dense.py

    # 真正执行（仅非空 kb_bucket_*）
    python scripts/migrate/qdrant_named_dense.py --apply

    # 指定 collection
    python scripts/migrate/qdrant_named_dense.py --apply --collections kb_bucket_74,kb_bucket_92

    # 纳入评测库（谨慎）/ 纳入空表
    python scripts/migrate/qdrant_named_dense.py --apply --include-eval --include-empty

    # 仅校验现状（不迁移）
    python scripts/migrate/qdrant_named_dense.py --verify-only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

# 允许以 `python scripts/migrate/qdrant_named_dense.py` 直接运行（补 sys.path 到仓库根）。
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.config import settings  # noqa: E402
from src.core.storage.qdrant.constants import (  # noqa: E402
    DEFAULT_COLLECTION_PREFIX,
    QDRANT_PAYLOAD_INDEX_FIELDS,
)

DENSE_NAME = getattr(settings, "DENSE_VECTOR_QDRANT_VECTOR_NAME", "dense")
SPARSE_NAME = getattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", "sparse_text")
DEFAULT_PREFIX = getattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX)
EVAL_COLLECTION = "eval_kb_bucket_9"
TMP_SUFFIX = "__named_tmp"
SCROLL_BATCH = 256
UPSERT_BATCH = 256
RETRY_ATTEMPTS = 6
RETRY_BACKOFF = 0.5

# 迁移前点 vector dict 里 dense 所在的 key：匿名默认 dense 读出为空串 key。
_LEGACY_DENSE_KEY = ""


@dataclass
class CollPlan:
    name: str
    points: int
    dense_kind: str  # "unnamed" | "named:<names>" | "unknown"
    action: str = "pending"  # skip-already-named | skip-empty | recreate-empty | migrate | skip-eval
    note: str = ""


@dataclass
class MigrationReport:
    plans: list[CollPlan] = field(default_factory=list)
    migrated: list[str] = field(default_factory=list)
    recreated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _client(timeout: int = 60):
    from qdrant_client import AsyncQdrantClient

    return AsyncQdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=getattr(settings, "QDRANT_API_KEY", None) or None,
        timeout=timeout,
    )


_TRANSIENT_MARKERS = ("502", "503", "504", "bad gateway", "timeout", "timed out", "unavailable")
# 传输层异常往往 str(exc) 为空，只能靠类名兜底（与 qdrant_store._is_transient_error 对齐）。
_TRANSIENT_TYPES = (
    "timeout", "connecterror", "connecttimeout", "readtimeout", "writetimeout",
    "remoteprotocolerror", "responsehandlingexception", "readerror", "writeerror",
    "remotedisconnected", "pooltimeout", "networkerror", "protocolerror",
)


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(m in msg for m in _TRANSIENT_MARKERS):
        return True
    type_name = type(exc).__name__.lower()
    if any(t in type_name for t in _TRANSIENT_TYPES):
        return True
    # 空消息的裸传输错误：幂等写 + 末尾计数校验下，宽松重试是安全的。
    return msg.strip() == ""


async def _with_retry(op_name: str, thunk):
    """对幂等 Qdrant 操作做瞬时故障（502/503/504/超时/裸传输错误）重试。"""
    attempt = 0
    while True:
        try:
            return await thunk()
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if attempt >= RETRY_ATTEMPTS or not _is_transient(exc):
                raise
            delay = RETRY_BACKOFF * (2 ** (attempt - 1))
            print(f"    · transient failure on {op_name} ({type(exc).__name__}); "
                  f"retry {attempt}/{RETRY_ATTEMPTS - 1} after {delay:.1f}s: {exc!r}")
            await asyncio.sleep(delay)


def _dense_kind(collection_info: Any) -> tuple[str, int | None]:
    """返回 (dense 描述, dense 维度)。区分匿名 / named / 已迁移。"""
    vectors = collection_info.config.params.vectors
    if hasattr(vectors, "size"):  # 匿名默认 VectorParams
        return "unnamed", int(vectors.size)
    if isinstance(vectors, dict):
        names = sorted(vectors.keys())
        size = None
        if DENSE_NAME in vectors:
            size = int(vectors[DENSE_NAME].size)
        return f"named:{names}", size
    return "unknown", None


def _models():
    from qdrant_client import models

    return models


async def _create_named_collection(client, name: str, dense_size: int) -> None:
    """按 named-dense schema 建表 + 重建 payload 索引（与 app ensure_collection 对齐）。"""
    models = _models()
    await _with_retry(
        f"create_collection({name})",
        lambda: client.create_collection(
            collection_name=name,
            vectors_config={
                DENSE_NAME: models.VectorParams(size=dense_size, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams()},
        ),
    )
    for field_name in QDRANT_PAYLOAD_INDEX_FIELDS:
        await _with_retry(
            f"create_payload_index({name}.{field_name})",
            lambda field_name=field_name: client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.INTEGER,
                wait=True,
            ),
        )


async def _scroll_all(client, name: str) -> list[Any]:
    """全量 scroll 旧点，返回重命名后的 PointStruct 列表（dense ""→DENSE_NAME）。"""
    models = _models()
    out: list[Any] = []
    offset = None
    while True:
        points, offset = await _with_retry(
            f"scroll({name})",
            lambda offset=offset: client.scroll(
                collection_name=name,
                limit=SCROLL_BATCH,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            ),
        )
        for p in points:
            vec = p.vector or {}
            new_vec: dict[str, Any] = {}
            if isinstance(vec, dict):
                if _LEGACY_DENSE_KEY in vec and vec[_LEGACY_DENSE_KEY] is not None:
                    new_vec[DENSE_NAME] = vec[_LEGACY_DENSE_KEY]
                if SPARSE_NAME in vec and vec[SPARSE_NAME] is not None:
                    new_vec[SPARSE_NAME] = vec[SPARSE_NAME]
            elif isinstance(vec, list):  # 理论上不该出现（无 sparse 的纯匿名 dense）
                new_vec[DENSE_NAME] = vec
            out.append(models.PointStruct(id=p.id, vector=new_vec, payload=p.payload or {}))
        if offset is None:
            break
    return out


async def _upsert_all(client, name: str, points: list[Any]) -> None:
    for i in range(0, len(points), UPSERT_BATCH):
        batch = points[i : i + UPSERT_BATCH]
        await _with_retry(
            f"upsert({name})",
            lambda batch=batch: client.upsert(collection_name=name, points=batch, wait=True),
        )


async def _count(client, name: str) -> int:
    res = await _with_retry(f"count({name})", lambda: client.count(collection_name=name))
    return int(res.count)


async def _migrate_one(client, plan: CollPlan, report: MigrationReport) -> None:
    """非空 collection 的向量保真就地迁移。"""
    name = plan.name
    tmp = f"{name}{TMP_SUFFIX}"
    print(f"  → migrating {name} ({plan.points} pts)")

    # 0. 临时表残留检查（上次中断）。
    if await _exists(client, tmp):
        raise RuntimeError(f"temp collection {tmp} already exists (前次迁移未清理？先手动处理)")

    # 1. 快照（可恢复）。
    snap = await _with_retry(f"snapshot({name})", lambda: client.create_snapshot(collection_name=name))
    snap_name = getattr(snap, "name", snap)
    print(f"    · snapshot: {snap_name}")

    # 2. 读出全部点（重命名后）。
    info = await _get_collection(client, name)
    _, dense_size = _dense_kind(info)
    dense_size = dense_size or settings.DENSE_VECTOR_DIMENSION
    points = await _scroll_all(client, name)
    if len(points) != plan.points:
        raise RuntimeError(f"scroll count {len(points)} != reported {plan.points}")

    # 3. 灌入临时 named 表并校验。
    await _create_named_collection(client, tmp, dense_size)
    await _upsert_all(client, tmp, points)
    tmp_cnt = await _count(client, tmp)
    if tmp_cnt != len(points):
        raise RuntimeError(f"tmp count {tmp_cnt} != source {len(points)}（已保留快照与临时表）")

    # 4. 删原表 → 以 named schema 重建 → 回灌 → 校验。
    await _with_retry(f"delete({name})", lambda: client.delete_collection(collection_name=name))
    await _create_named_collection(client, name, dense_size)
    await _upsert_all(client, name, points)
    final_cnt = await _count(client, name)
    if final_cnt != len(points):
        raise RuntimeError(
            f"final count {final_cnt} != source {len(points)}（快照 {snap_name} 可恢复，临时表 {tmp} 保留）"
        )

    # 5. 清理临时表（快照保留，由运维确认后手动删）。
    await _with_retry(f"delete({tmp})", lambda: client.delete_collection(collection_name=tmp))
    print(f"    ✓ {name} migrated: {final_cnt} pts, named dense + sparse_text; snapshot kept: {snap_name}")
    report.migrated.append(name)


async def _recreate_empty(client, plan: CollPlan, report: MigrationReport) -> None:
    name = plan.name
    print(f"  → recreating empty {name}")
    await _with_retry(f"delete({name})", lambda: client.delete_collection(collection_name=name))
    await _create_named_collection(client, name, settings.DENSE_VECTOR_DIMENSION)
    report.recreated.append(name)
    print(f"    ✓ {name} recreated with named schema")


async def _exists(client, name: str) -> bool:
    return await _with_retry(
        f"collection_exists({name})", lambda: client.collection_exists(collection_name=name)
    )


async def _get_collection(client, name: str):
    return await _with_retry(
        f"get_collection({name})", lambda: client.get_collection(collection_name=name)
    )


async def _resolve_targets(client, args) -> list[str]:
    if args.collections:
        return [c.strip() for c in args.collections.split(",") if c.strip()]
    cols = (await _with_retry("get_collections", lambda: client.get_collections())).collections
    names = [c.name for c in cols if c.name.startswith(DEFAULT_PREFIX)]
    if args.include_eval or EVAL_COLLECTION in (args.collections or ""):
        if EVAL_COLLECTION not in names:
            names.append(EVAL_COLLECTION)
    return sorted(names)


async def build_plan(client, args) -> list[CollPlan]:
    plans: list[CollPlan] = []
    for name in await _resolve_targets(client, args):
        if not await _exists(client, name):
            plans.append(CollPlan(name=name, points=0, dense_kind="missing", action="skip-missing"))
            continue
        info = await _get_collection(client, name)
        kind, _ = _dense_kind(info)
        pts = await _count(client, name)
        plan = CollPlan(name=name, points=pts, dense_kind=kind)
        if name == EVAL_COLLECTION and not args.include_eval:
            plan.action, plan.note = "skip-eval", "评测库，需 --include-eval"
        elif kind.startswith("named") and DENSE_NAME in kind:
            plan.action, plan.note = "skip-already-named", "已是 named-dense"
        elif pts == 0:
            if args.include_empty:
                plan.action = "recreate-empty"
            else:
                plan.action, plan.note = "skip-empty", "空表，旧 schema（首次写入会失败），--include-empty 重建"
        else:
            plan.action = "migrate"
        plans.append(plan)
    return plans


def _print_plan(plans: list[CollPlan]) -> None:
    print("\n=== 迁移计划 ===")
    print(f"{'collection':32s} {'pts':>7}  {'action':20s} dense_kind / note")
    for p in plans:
        print(f"{p.name:32s} {p.points:>7}  {p.action:20s} {p.dense_kind} {('| ' + p.note) if p.note else ''}")
    todo = [p for p in plans if p.action in ("migrate", "recreate-empty")]
    print(f"\n待执行: {len(todo)}（migrate={sum(1 for p in todo if p.action=='migrate')}, "
          f"recreate-empty={sum(1 for p in todo if p.action=='recreate-empty')}）；"
          f"总点数={sum(p.points for p in todo if p.action=='migrate')}")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate Qdrant collections to named-dense schema.")
    ap.add_argument("--apply", action="store_true", help="真正执行（默认 dry-run 只打印计划）")
    ap.add_argument("--verify-only", action="store_true", help="只打印现状/计划，不迁移")
    ap.add_argument("--collections", default="", help="逗号分隔的指定 collection（覆盖默认枚举）")
    ap.add_argument("--include-eval", action="store_true", help="纳入 eval_kb_bucket_9（评测库，谨慎）")
    ap.add_argument("--include-empty", action="store_true", help="重建空的旧 schema collection")
    args = ap.parse_args()

    client = _client()
    report = MigrationReport()
    try:
        plans = await build_plan(client, args)
        report.plans = plans
        _print_plan(plans)

        if args.verify_only or not args.apply:
            print("\n[dry-run] 未改动任何 collection。加 --apply 执行。")
            return 0

        print("\n=== 开始执行（--apply）===")
        for p in plans:
            try:
                if p.action == "migrate":
                    await _migrate_one(client, p, report)
                elif p.action == "recreate-empty":
                    await _recreate_empty(client, p, report)
                else:
                    report.skipped.append(p.name)
            except Exception as exc:  # noqa: BLE001
                print(f"    ✗ {p.name} FAILED: {exc}")
                report.failed.append((p.name, str(exc)))

        print("\n=== 迁移结果 ===")
        print(f"migrated={len(report.migrated)} {report.migrated}")
        print(f"recreated={len(report.recreated)} {report.recreated}")
        print(f"skipped={len(report.skipped)}")
        if report.failed:
            print(f"FAILED={len(report.failed)}:")
            for name, err in report.failed:
                print(f"  {name}: {err}")
            return 1
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
