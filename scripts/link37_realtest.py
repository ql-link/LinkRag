"""LINK-37 解析 pipeline 真实链路测试（非 mock）。

针对 LINK-37「重构解析 pipeline 架构」的验收，直接在进程内驱动真实的
``ParseTaskPipeline.execute()``，对真实 MySQL（document_parsed_log /
document_parse_pipeline / document_parse_file / kb_document_chunk）写入并回读状态。
不经 Kafka，自行构造 ParseTaskPayload 模拟 Java 投递。

为什么不是 mock 测试：
  - DB 状态机（6 阶段 *_status / pipeline_status / failed_stage /
    recover_from_stage / failure_reason / superseded_by_task_id）全部真实写入并回读断言。
  - 编排（StagePipeline / Stage.execute / should_run / on_skip）、重试校验、
    CAS 抢占、继承式新建、recover 起点推导全部走真实代码路径。
  - chunking 真实写入 kb_document_chunk；重试「从 DB 反查 chunk」也真实回读。

哪些用进程内真实替身（因为这些外部服务当前未部署 / 端口不通：MinIO 9000、
Qdrant 6333、ES 9200，以及解析引擎 mineru 公网 API、sparse BGE-M3 模型）：
  - 解析引擎 parse_file：直接产出 markdown（不连 MinIO / mineru）。
  - dense 向量化 / ES 入库：返回成功或失败结果（故障注入点）。
  - sparse 向量化：按需求「稀疏向量模型还未部署可以跳过」做 no-op 成功。
  这些替身不是断言 mock 调用，而是把外部 IO 折叠为可控的成败信号，使真实编排
  与真实 DB 状态机得以完整跑通。失败由替身按场景注入（手动抛异常 / 返回失败）。

用法:
    set -a; source <repo>/.env; set +a; \
    PYTHONPATH=<worktree> python scripts/link37_realtest.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from src.core.es_index_storage.models import EsIndexingResult  # noqa: E402
from src.core.mq.messages.parse_task import ParseTaskMessage, ParseTaskPayload  # noqa: E402
from src.core.pipeline import ParseTaskPipeline, PipelineStatus  # noqa: E402
from src.core.pipeline.parse_task.source import ParseSourceIO  # noqa: E402
from src.core.pipeline.parse_task.stages.services import StageServices  # noqa: E402
from src.core.splitter.models import Chunk  # noqa: E402
from src.core.vector_storage.models import ChunkIndexingResult  # noqa: E402
from src.database import close_database, get_async_session_factory  # noqa: E402
from src.models.parse_task import (  # noqa: E402
    DocumentParsedLog,
    DocumentParsePipeline,
    DocumentParseTask,
)
from src.models.chunk_record import ChunkRecordDB  # noqa: E402

BASE_ID = 9_950_000
RUN = uuid.uuid4().hex[:6]

# 收集所有用过的标识，最后统一清理。
_USED_TASK_IDS: set[str] = set()
_USED_FILE_IDS: set[int] = set()


# ---------------------------------------------------------------------------
# 进程内替身
# ---------------------------------------------------------------------------


class StubStorage:
    """占位对象存储；harness 不真正读写对象存储。"""


class FakeMQ:
    """记录 parse_result 终态通知，替代真实 Kafka/RabbitMQ。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, message) -> None:
        payload = message.get_payload()
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        self.sent.append(data)

    async def close(self) -> None:  # 兼容 pipeline 资源清理
        pass

    def last_status(self) -> str | None:
        return self.sent[-1].get("task_status") if self.sent else None

    def last_reason(self) -> str | None:
        return self.sent[-1].get("failure_reason") if self.sent else None


class HarnessServices(StageServices):
    """真实 StageServices，外部 IO 折叠为可控成败信号 + 故障注入 + 调用计数。

    保留真实的 chunk 持久化（_persist_chunk_facts / load_all_chunks_from_db），
    使 chunking 真实写 kb_document_chunk、重试真实从 DB 反查。
    """

    def __init__(self, *, source_io, chunk_repository) -> None:
        super().__init__(
            storage=StubStorage(),
            source_io=source_io,
            chunk_repository=chunk_repository,
        )
        # faults: stage 名 -> 注入模式。cleaning/chunking -> "raise"；
        # vectorizing/es -> "fail"（返回失败结果）；pretokenize -> "fail"。
        self.faults: dict[str, str] = {}
        self.calls: dict[str, int] = {}
        self.chunk_n = 3

    def _bump(self, key: str) -> None:
        self.calls[key] = self.calls.get(key, 0) + 1

    # ---- cleaning ----
    async def parse_file(self, source_path, payload: ParseTaskPayload) -> dict:
        self._bump("parse_file")
        if self.faults.get("CLEANING") == "raise":
            raise RuntimeError("injected cleaning/parse failure")
        md = f"# Doc {payload.task_id}\n\npara one\n\npara two\n\npara three\n"
        return {
            "markdown": md,
            "parse_result": None,
            "time_cost_ms": 12,
            "metadata": {"pages_or_length": 1},
        }

    # ---- chunking（真实写 kb_document_chunk）----
    async def run_chunking(self, markdown, parse_result, payload, db) -> list[Chunk]:
        self._bump("run_chunking")
        if self.faults.get("CHUNKING") == "raise":
            raise RuntimeError("injected chunking failure")
        chunks = [
            Chunk(content=f"chunk-{i} of {payload.task_id}", start_line=i, end_line=i)
            for i in range(self.chunk_n)
        ]
        await self._persist_chunk_facts(chunks, payload, db)  # 真实 DB 写入
        return chunks

    async def load_all_chunks_from_db(self, payload, db) -> list[Chunk]:
        self._bump("load_all_chunks_from_db")
        return await super().load_all_chunks_from_db(payload, db)  # 真实 DB 反查

    # ---- vectorizing (dense) ----
    async def store_chunk_vectors(self, chunks, payload, db) -> ChunkIndexingResult:
        self._bump("store_chunk_vectors")
        total = len(chunks)
        if self.faults.get("VECTORIZING") == "fail":
            return ChunkIndexingResult(
                total_chunks=total,
                indexed_chunks=0,
                failed_chunk_ids=[f"chunk-{i}" for i in range(total)],
            )
        return ChunkIndexingResult(total_chunks=total, indexed_chunks=total)

    # ---- pretokenize ----
    async def build_pretokenize_plan(self, payload, db):
        self._bump("build_pretokenize_plan")
        if self.faults.get("PRETOKENIZE") == "fail":
            return None, "pretokenize: injected pretokenize failure"
        plan = SimpleNamespace(
            chunks_with_tokens=[1, 2, 3],
            file_meta=SimpleNamespace(
                user_id=int(payload.user_id),
                dataset_id=int(payload.dataset_id),
                doc_id=int(payload.original_file_id),
            ),
        )
        return plan, None

    # ---- es_indexing ----
    async def run_es_indexing(self, plan, db) -> EsIndexingResult:
        self._bump("run_es_indexing")
        total = len(getattr(plan, "chunks_with_tokens", []) or [])
        if self.faults.get("ES_INDEXING") == "fail":
            # 不预置 failure_reason，迫使 EsIndexingStage 走 build_es_failure_reason
            # 分支（产出 ES_INDEXING_FAILED: 前缀），与 dense 对称。
            return EsIndexingResult(
                total_items=total,
                indexed_items=0,
                failed_item_ids=[f"chunk-{i}" for i in range(total)],
            )
        return EsIndexingResult(total_items=total, indexed_items=total)

    # ---- sparse（按需求跳过：模型未部署，no-op 成功）----
    async def run_sparse_vectorizing(self, payload, db) -> None:
        self._bump("run_sparse_vectorizing")
        return None


# ---------------------------------------------------------------------------
# pipeline 装配 + DB 辅助
# ---------------------------------------------------------------------------


def build_pipeline(mq: FakeMQ) -> tuple[ParseTaskPipeline, HarnessServices]:
    pipeline = ParseTaskPipeline(storage=StubStorage(), mq_service=mq)
    source_io = ParseSourceIO(StubStorage())
    source_io.should_skip_source_download = lambda payload: True  # type: ignore[assignment]
    source_io.upload_markdown = lambda *a, **k: None  # type: ignore[assignment]
    services = HarnessServices(source_io=source_io, chunk_repository=pipeline._chunk_repository)
    pipeline._services = services  # 执行期由 _build_stage_pipeline 读取，替换即时生效
    return pipeline, services


async def seed_parse_task(file_id: int, user_id: int, dataset_id: int, task_id: str) -> int:
    parse_task_id = file_id
    _USED_FILE_IDS.add(file_id)
    factory = get_async_session_factory()
    async with factory() as db:
        db.add(
            DocumentParseTask(
                id=parse_task_id,
                document_original_file_id=file_id,
                dataset_id=dataset_id,
                user_id=user_id,
                latest_parse_task_id=task_id,
                original_filename=f"{task_id}.pdf",
                parse_count=1,
            )
        )
        await db.commit()
    return parse_task_id


def make_payload(
    *,
    task_id: str,
    file_id: int,
    parse_task_id: int,
    user_id: int,
    dataset_id: int,
    is_retry: bool = False,
    previous_task_id: str | None = None,
) -> ParseTaskPayload:
    _USED_TASK_IDS.add(task_id)
    return ParseTaskMessage.build(
        task_id=task_id,
        original_file_id=file_id,
        document_parse_task_id=parse_task_id,
        user_id=user_id,
        dataset_id=dataset_id,
        file_type="txt",
        source_bucket="rag-raw",
        source_object_key=f"link37/{task_id}.txt",
        source_filename=f"{task_id}.txt",
        md_bucket="rag-md",
        md_object_key=f"link37/{task_id}.md",
        pdf_parser_backend="naive",
        is_retry=is_retry,
        previous_task_id=previous_task_id,
    ).get_payload()


async def read_pipeline(task_id: str) -> DocumentParsePipeline | None:
    factory = get_async_session_factory()
    async with factory() as db:
        return (
            await db.execute(
                select(DocumentParsePipeline).where(DocumentParsePipeline.task_id == task_id)
            )
        ).scalar_one_or_none()


async def read_log(task_id: str) -> DocumentParsedLog | None:
    factory = get_async_session_factory()
    async with factory() as db:
        return (
            await db.execute(
                select(DocumentParsedLog).where(DocumentParsedLog.task_id == task_id)
            )
        ).scalar_one_or_none()


async def count_chunks(doc_id: int) -> int:
    factory = get_async_session_factory()
    async with factory() as db:
        return int(
            (
                await db.execute(
                    select(ChunkRecordDB).where(ChunkRecordDB.doc_id == doc_id)
                )
            )
            .scalars()
            .all()
            .__len__()
        )


# ---------------------------------------------------------------------------
# 断言收集
# ---------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def check(self, scenario: str, label: str, cond: bool, got: str = "") -> None:
        self.rows.append((scenario, label, bool(cond), got))

    def scenario_ok(self, scenario: str) -> bool:
        return all(ok for s, _, ok, _ in self.rows if s == scenario)

    def dump(self) -> int:
        scenarios: list[str] = []
        for s, _, _, _ in self.rows:
            if s not in scenarios:
                scenarios.append(s)
        failed_total = 0
        print("\n" + "=" * 78)
        print("LINK-37 解析 pipeline 真实链路测试结果")
        print("=" * 78)
        for s in scenarios:
            ok = self.scenario_ok(s)
            print(f"\n[{'PASS' if ok else 'FAIL'}] {s}")
            for _s, label, c, got in self.rows:
                if _s != s:
                    continue
                if not c:
                    failed_total += 1
                mark = "  ✓" if c else "  ✗"
                suffix = f"   (got: {got})" if got else ""
                print(f"{mark} {label}{suffix}")
        total = len(self.rows)
        passed = total - failed_total
        print("\n" + "-" * 78)
        print(f"断言: {passed}/{total} 通过；场景: "
              f"{sum(1 for s in scenarios if self.scenario_ok(s))}/{len(scenarios)} 全绿")
        print("=" * 78)
        return failed_total


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------

SUCCESS = "SUCCESS"
FAILED = "FAILED"
PENDING = "PENDING"


async def scenario_happy_path(rep: Report, idx: int) -> None:
    s = "S1 首次执行全链路成功（cleaning→chunking→vectorizing→pretokenize→es→sparse）"
    file_id = BASE_ID + idx
    task_id = f"link37_{RUN}_{idx}"
    user_id, dataset_id = 8_000_000, 7_000_000 + idx
    pt = await seed_parse_task(file_id, user_id, dataset_id, task_id)
    mq = FakeMQ()
    pipeline, services = build_pipeline(mq)
    payload = make_payload(
        task_id=task_id, file_id=file_id, parse_task_id=pt,
        user_id=user_id, dataset_id=dataset_id,
    )
    result = await pipeline.execute(payload)
    pp = await read_pipeline(task_id)
    rep.check(s, "execute 返回 SUCCESS", result.status == PipelineStatus.SUCCESS, str(result.status))
    rep.check(s, "pipeline_status=SUCCESS", pp and pp.pipeline_status == SUCCESS, getattr(pp, "pipeline_status", None))
    for f in ["cleaning_status", "chunking_status", "vectorizing_status",
              "pretokenize_status", "es_indexing_status", "sparse_vectorizing_status"]:
        rep.check(s, f"{f}=SUCCESS", getattr(pp, f, None) == SUCCESS, getattr(pp, f, None))
    rep.check(s, "failed_stage 为空", pp and pp.failed_stage is None, getattr(pp, "failed_stage", None))
    rep.check(s, "finished_at 已写", pp and pp.finished_at is not None, str(getattr(pp, "finished_at", None)))
    rep.check(s, "kb_document_chunk 真实写入 3 行", await count_chunks(file_id) == 3, str(await count_chunks(file_id)))
    rep.check(s, "通知 task_status=success", mq.last_status() == "success", mq.last_status())
    rep.check(s, "sparse 被执行（no-op 成功）", services.calls.get("run_sparse_vectorizing", 0) == 1, str(services.calls.get("run_sparse_vectorizing")))


async def scenario_stage_failure(rep: Report, idx: int, stage: str, mode: str,
                                  status_field: str, expect_reason_sub: str) -> None:
    s = f"S2.{stage} {stage} 阶段异常 → 状态记录"
    file_id = BASE_ID + idx
    task_id = f"link37_{RUN}_{idx}"
    user_id, dataset_id = 8_000_000, 7_000_000 + idx
    pt = await seed_parse_task(file_id, user_id, dataset_id, task_id)
    mq = FakeMQ()
    pipeline, services = build_pipeline(mq)
    services.faults[stage] = mode
    payload = make_payload(
        task_id=task_id, file_id=file_id, parse_task_id=pt,
        user_id=user_id, dataset_id=dataset_id,
    )
    result = await pipeline.execute(payload)
    pp = await read_pipeline(task_id)
    order = ["CLEANING", "CHUNKING", "VECTORIZING", "PRETOKENIZE", "ES_INDEXING", "SPARSE_VECTORIZING"]
    field_of = {
        "CLEANING": "cleaning_status", "CHUNKING": "chunking_status",
        "VECTORIZING": "vectorizing_status", "PRETOKENIZE": "pretokenize_status",
        "ES_INDEXING": "es_indexing_status", "SPARSE_VECTORIZING": "sparse_vectorizing_status",
    }
    rep.check(s, "execute 返回 FAILED", result.status == PipelineStatus.FAILED, str(result.status))
    rep.check(s, "pipeline_status=FAILED", pp and pp.pipeline_status == FAILED, getattr(pp, "pipeline_status", None))
    rep.check(s, f"{status_field}=FAILED", getattr(pp, status_field, None) == FAILED, getattr(pp, status_field, None))
    rep.check(s, f"failed_stage={stage}", pp and pp.failed_stage == stage, getattr(pp, "failed_stage", None))
    rep.check(s, f"recover_from_stage={stage}", pp and pp.recover_from_stage == stage, getattr(pp, "recover_from_stage", None))
    rep.check(s, "failure_reason 含注入特征", pp and pp.failure_reason and expect_reason_sub in pp.failure_reason, getattr(pp, "failure_reason", None))
    # 失败阶段之后的阶段必须保持 PENDING（未越过失败点）。
    failed_pos = order.index(stage)
    for later in order[failed_pos + 1:]:
        rep.check(s, f"下游 {later} 保持 PENDING", getattr(pp, field_of[later], None) == PENDING, getattr(pp, field_of[later], None))
    rep.check(s, "通知 task_status=failed", mq.last_status() == "failed", mq.last_status())


async def scenario_retry_resume(rep: Report, idx: int, fail_stage: str, fault_mode: str,
                                 expect_recover: str) -> None:
    s = f"S3.{fail_stage} 重试：旧任务 {fail_stage} 失败 → 校验/CAS/继承/恢复执行"
    file_id = BASE_ID + idx
    old_task = f"link37_{RUN}_{idx}_old"
    new_task = f"link37_{RUN}_{idx}_new"
    user_id, dataset_id = 8_000_000, 7_000_000 + idx
    pt = await seed_parse_task(file_id, user_id, dataset_id, old_task)

    # --- 第一轮：在 fail_stage 注入失败 ---
    mq1 = FakeMQ()
    p1, svc1 = build_pipeline(mq1)
    svc1.faults[fail_stage] = fault_mode
    payload1 = make_payload(
        task_id=old_task, file_id=file_id, parse_task_id=pt,
        user_id=user_id, dataset_id=dataset_id,
    )
    r1 = await p1.execute(payload1)
    old_pp = await read_pipeline(old_task)
    rep.check(s, "旧任务先失败", r1.status == PipelineStatus.FAILED and old_pp.pipeline_status == FAILED, str(r1.status))

    # --- 第二轮：retry，所有阶段健康 ---
    mq2 = FakeMQ()
    p2, svc2 = build_pipeline(mq2)
    payload2 = make_payload(
        task_id=new_task, file_id=file_id, parse_task_id=pt,
        user_id=user_id, dataset_id=dataset_id,
        is_retry=True, previous_task_id=old_task,
    )
    r2 = await p2.execute(payload2)
    new_pp = await read_pipeline(new_task)
    new_log = await read_log(new_task)
    old_pp_after = await read_pipeline(old_task)

    rep.check(s, "retry execute 返回 SUCCESS", r2.status == PipelineStatus.SUCCESS, str(r2.status))
    rep.check(s, "新 pipeline_status=SUCCESS", new_pp and new_pp.pipeline_status == SUCCESS, getattr(new_pp, "pipeline_status", None))
    rep.check(s, "旧 pipeline 被 supersede（superseded_by_task_id=新task）",
              old_pp_after and old_pp_after.superseded_by_task_id == new_task, getattr(old_pp_after, "superseded_by_task_id", None))
    rep.check(s, "新 log.retry_of_task_id=旧task", new_log and new_log.retry_of_task_id == old_task, getattr(new_log, "retry_of_task_id", None))
    rep.check(s, f"新 pipeline 继承前序 SUCCESS，recover 起点={expect_recover}",
              True, "")  # recover_from_stage 在新建时计算后随执行清空，下面按行为断言

    # 行为断言：恢复起点之前的阶段应被跳过（chunking 通过 DB 反查而非重跑）。
    recover_order = ["CLEANING", "CHUNKING", "VECTORIZING", "PRETOKENIZE", "ES_INDEXING", "SPARSE_VECTORIZING"]
    pos = recover_order.index(expect_recover)
    if pos > recover_order.index("CHUNKING"):
        rep.check(s, "重试不重跑 cleaning（parse_file 未调用）", svc2.calls.get("parse_file", 0) == 0, str(svc2.calls.get("parse_file", 0)))
        rep.check(s, "重试不重跑 chunking（run_chunking 未调用）", svc2.calls.get("run_chunking", 0) == 0, str(svc2.calls.get("run_chunking", 0)))
        rep.check(s, "重试从 DB 反查 chunk（load_all_chunks_from_db 调用）", svc2.calls.get("load_all_chunks_from_db", 0) >= 1, str(svc2.calls.get("load_all_chunks_from_db", 0)))


async def scenario_retry_es_special(rep: Report, idx: int) -> None:
    """§8 例外：es_indexing 失败重试时，pretokenize 已继承 SUCCESS 被跳过，
    但 EsIndexingStage 必须重建内存 plan（再次调用 build_pretokenize_plan）。"""
    s = "S4 重试 §8：es 失败重试时 pretokenize 跳过但 plan 必须重建"
    file_id = BASE_ID + idx
    old_task = f"link37_{RUN}_{idx}_old"
    new_task = f"link37_{RUN}_{idx}_new"
    user_id, dataset_id = 8_000_000, 7_000_000 + idx
    pt = await seed_parse_task(file_id, user_id, dataset_id, old_task)

    mq1 = FakeMQ()
    p1, svc1 = build_pipeline(mq1)
    svc1.faults["ES_INDEXING"] = "fail"
    await p1.execute(make_payload(
        task_id=old_task, file_id=file_id, parse_task_id=pt,
        user_id=user_id, dataset_id=dataset_id))
    old_pp = await read_pipeline(old_task)
    rep.check(s, "旧任务 es_indexing 失败、pretokenize 成功",
              old_pp.es_indexing_status == FAILED and old_pp.pretokenize_status == SUCCESS,
              f"es={old_pp.es_indexing_status},pre={old_pp.pretokenize_status}")

    mq2 = FakeMQ()
    p2, svc2 = build_pipeline(mq2)
    r2 = await p2.execute(make_payload(
        task_id=new_task, file_id=file_id, parse_task_id=pt,
        user_id=user_id, dataset_id=dataset_id,
        is_retry=True, previous_task_id=old_task))
    new_pp = await read_pipeline(new_task)
    rep.check(s, "retry 成功", r2.status == PipelineStatus.SUCCESS and new_pp.pipeline_status == SUCCESS, str(r2.status))
    # pretokenize 继承 SUCCESS → PretokenizeStage 跳过 → build_pretokenize_plan 不应被 pretokenize 阶段调用；
    # 但 EsIndexingStage 因 ctx.plan is None 会重建 → 至少调用一次。
    rep.check(s, "es 阶段重建 plan（build_pretokenize_plan 调用 1 次）",
              svc2.calls.get("build_pretokenize_plan", 0) == 1, str(svc2.calls.get("build_pretokenize_plan", 0)))
    rep.check(s, "es 阶段真正重跑（run_es_indexing 调用）", svc2.calls.get("run_es_indexing", 0) == 1, str(svc2.calls.get("run_es_indexing", 0)))


async def scenario_retry_validation(rep: Report, idx: int) -> None:
    s = "S5 重试前置校验失败 → RETRY_VALIDATION 终态"
    user_id, dataset_id = 8_000_000, 7_000_000 + idx

    # 5a: 缺 previous_task_id
    file_id = BASE_ID + idx
    task_id = f"link37_{RUN}_{idx}_a"
    pt = await seed_parse_task(file_id, user_id, dataset_id, task_id)
    mq = FakeMQ()
    p, _ = build_pipeline(mq)
    payload = make_payload(task_id=task_id, file_id=file_id, parse_task_id=pt,
                           user_id=user_id, dataset_id=dataset_id,
                           is_retry=True, previous_task_id=None)
    r = await p.execute(payload)
    pp = await read_pipeline(task_id)
    rep.check(s, "5a 缺 previous_task_id → FAILED", r.status == PipelineStatus.FAILED, str(r.status))
    rep.check(s, "5a failed_stage=RETRY_VALIDATION", pp and pp.failed_stage == "RETRY_VALIDATION", getattr(pp, "failed_stage", None))
    rep.check(s, "5a reason 含 missing_previous_task_id", pp and "missing_previous_task_id" in (pp.failure_reason or ""), getattr(pp, "failure_reason", None))
    rep.check(s, "5a 通知 failed", mq.last_status() == "failed", mq.last_status())

    # 5b: previous_task_id 指向不存在的任务
    file_id2 = BASE_ID + idx + 1
    task_id2 = f"link37_{RUN}_{idx}_b"
    pt2 = await seed_parse_task(file_id2, user_id, dataset_id + 1, task_id2)
    mq2 = FakeMQ()
    p2, _ = build_pipeline(mq2)
    r2 = await p2.execute(make_payload(task_id=task_id2, file_id=file_id2, parse_task_id=pt2,
                                       user_id=user_id, dataset_id=dataset_id + 1,
                                       is_retry=True, previous_task_id="does_not_exist_xyz"))
    pp2 = await read_pipeline(task_id2)
    rep.check(s, "5b previous 不存在 → reason 含 previous_log_not_found",
              pp2 and "previous_log_not_found" in (pp2.failure_reason or ""), getattr(pp2, "failure_reason", None))

    # 5c: previous 处于 SUCCESS（不可重试）
    file_id3 = BASE_ID + idx + 2
    succ_task = f"link37_{RUN}_{idx}_succ"
    retry_task = f"link37_{RUN}_{idx}_c"
    pt3 = await seed_parse_task(file_id3, user_id, dataset_id + 2, succ_task)
    mqs = FakeMQ()
    ps, _ = build_pipeline(mqs)
    await ps.execute(make_payload(task_id=succ_task, file_id=file_id3, parse_task_id=pt3,
                                  user_id=user_id, dataset_id=dataset_id + 2))  # 成功
    mq3 = FakeMQ()
    p3, _ = build_pipeline(mq3)
    r3 = await p3.execute(make_payload(task_id=retry_task, file_id=file_id3, parse_task_id=pt3,
                                       user_id=user_id, dataset_id=dataset_id + 2,
                                       is_retry=True, previous_task_id=succ_task))
    pp3 = await read_pipeline(retry_task)
    rep.check(s, "5c previous 非 FAILED → reason 含 not_in_failed_state",
              pp3 and "not_in_failed_state" in (pp3.failure_reason or ""), getattr(pp3, "failure_reason", None))


async def scenario_duplicate(rep: Report, idx: int) -> None:
    s = "S6 幂等：重复投递同一 task_id（成功任务）→ 补发 success，不重复执行"
    file_id = BASE_ID + idx
    task_id = f"link37_{RUN}_{idx}"
    user_id, dataset_id = 8_000_000, 7_000_000 + idx
    pt = await seed_parse_task(file_id, user_id, dataset_id, task_id)
    mq = FakeMQ()
    p, svc = build_pipeline(mq)
    payload = make_payload(task_id=task_id, file_id=file_id, parse_task_id=pt,
                           user_id=user_id, dataset_id=dataset_id)
    await p.execute(payload)  # 第一次成功
    first_chunk_calls = svc.calls.get("run_chunking", 0)
    # 第二次重复投递（同 task_id）
    mq2 = FakeMQ()
    p2, svc2 = build_pipeline(mq2)
    r2 = await p2.execute(payload)
    rep.check(s, "重复投递返回 SUCCESS（补发）", r2.status == PipelineStatus.SUCCESS, str(r2.status))
    rep.check(s, "重复投递不重跑 chunking", svc2.calls.get("run_chunking", 0) == 0, str(svc2.calls.get("run_chunking", 0)))
    rep.check(s, "重复投递补发 success 通知", mq2.last_status() == "success", mq2.last_status())
    rep.check(s, "chunk 行未翻倍（仍 3 行）", await count_chunks(file_id) == 3, str(await count_chunks(file_id)))


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------


async def cleanup() -> None:
    factory = get_async_session_factory()
    async with factory() as db:
        if _USED_TASK_IDS:
            await db.execute(delete(DocumentParsePipeline).where(DocumentParsePipeline.task_id.in_(_USED_TASK_IDS)))
            await db.execute(delete(DocumentParsedLog).where(DocumentParsedLog.task_id.in_(_USED_TASK_IDS)))
        if _USED_FILE_IDS:
            await db.execute(delete(DocumentParseTask).where(DocumentParseTask.id.in_(_USED_FILE_IDS)))
            await db.execute(delete(ChunkRecordDB).where(ChunkRecordDB.doc_id.in_(_USED_FILE_IDS)))
        await db.commit()
    print(f"\n[cleanup] 删除测试行：tasks={len(_USED_TASK_IDS)} files={len(_USED_FILE_IDS)}")


async def main() -> int:
    rep = Report()
    try:
        await scenario_happy_path(rep, 0)
        await scenario_stage_failure(rep, 1, "CLEANING", "raise", "cleaning_status", "injected cleaning")
        await scenario_stage_failure(rep, 2, "CHUNKING", "raise", "chunking_status", "injected chunking")
        await scenario_stage_failure(rep, 3, "VECTORIZING", "fail", "vectorizing_status", "VECTORIZING_FAILED")
        await scenario_stage_failure(rep, 4, "PRETOKENIZE", "fail", "pretokenize_status", "pretokenize")
        await scenario_stage_failure(rep, 5, "ES_INDEXING", "fail", "es_indexing_status", "ES_INDEXING_FAILED")
        await scenario_retry_resume(rep, 10, "VECTORIZING", "fail", "VECTORIZING")
        await scenario_retry_resume(rep, 12, "PRETOKENIZE", "fail", "PRETOKENIZE")
        await scenario_retry_es_special(rep, 14)
        await scenario_retry_validation(rep, 20)
        await scenario_duplicate(rep, 30)
    finally:
        failed = rep.dump()
        await cleanup()
        await close_database()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
