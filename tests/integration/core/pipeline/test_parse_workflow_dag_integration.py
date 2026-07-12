"""真实中间件下的解析 DAG 端到端集成测试（穿行 + 并行）。

覆盖目标：
  - 穿行（serial）与并行（parallel）两种拓扑各自全链路成功；
  - 续跑 happy path：基于上一轮成功 run 续跑，全部节点 SKIPPED、不重复执行；
  - 失败注入重试：某阶段首跑失败 → 续跑跳过已成功节点、按需 restore、重跑失败链。

真实依赖：MinIO / MySQL / Qdrant / Manticore / 嵌入模型。
使用 user_id=10000（DB 内已配置 default+active 的 EMBEDDING 与 SPARSE_EMBEDDING）。
markdown passthrough 源文件，避免依赖 MinerU 公网解析。

运行：
    PYTHONPATH=<repo> .venv/bin/python -m pytest \
        tests/integration/core/pipeline/test_parse_workflow_dag_integration.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytest.importorskip("boto3")

from sqlalchemy import delete, func, select

from src.bootstrap.nltk_data import configure_nltk_data_path
from src.core.mq.messages.parse_task import ParseTaskMessage
from src.core.pipeline.parse_task.workflow_demo import (
    ParseWorkflowRunner,
    build_parse_task_demo_workflow,
    build_parse_task_serial_workflow,
)
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.qdrant.bucket_router import BucketRouter
from src.core.workflow import InMemoryWorkflowStore, NodeStatus, RunStatus
from src.config import settings
from src.database import get_async_session_factory
from src.models.chunk_record import ChunkRecordDB
from src.models.parse_task import DocumentParseTask
from src.services.storage.factory import StorageFactory

# 全模块共用一个事件循环：全局缓存的 async 引擎/ES/Qdrant 客户端会绑定到首次创建时
# 的事件循环；若每个用例各起一个新循环，第二个用例复用旧客户端就会 “Event loop is
# closed”。module 级 loop 让这些全局单例在整个文件内保持有效。
pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_env,
    pytest.mark.asyncio(loop_scope="module"),
]

_TEST_USER_ID = 10000
_TEST_DATASET_ID = 10000
_ID_BASE = 9_900_000

_SOURCE_MARKDOWN = """# DAG 真实解析集成

## 第一节 背景
本文件用于在真实中间件下验证解析流水线 DAG 的穿行与并行执行，覆盖 cleaning、
chunking、dense 向量化、pretokenize、ES 入库、sparse 向量化六个阶段。

## 第二节 检索
RAG 系统通常结合向量检索与词法检索。稠密向量负责语义召回，稀疏向量与 ES
负责精确词匹配，两路互补能提升整体召回质量。

## 第三节 校验点
- chunk truth 写入 MySQL
- dense / sparse 向量写入 Qdrant
- ES 索引全量重建成功
- run 与各节点状态可观测
"""

_ALL_NODES = (
    "cleaning",
    "chunking",
    "ensure_points",
    "dense_vectorizing",
    "pretokenize",
    "es_indexing",
    "sparse_vectorizing",
)


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_nltk() -> None:
    """像生产 main.py 一样，把项目 nltk_data 注入搜索路径，供 pretokenize 使用。"""
    configure_nltk_data_path()


_ISOLATED_QDRANT_PREFIX = "__dagtest"


@pytest.fixture(scope="module", autouse=True)
def _isolated_qdrant_prefix():
    """把 Qdrant collection 前缀切到隔离命名空间，避免碰生产 ``kb_bucket_*``。

    named-dense 新写入只兼容新 schema；若直接写现有 ``kb_bucket_*``（匿名默认向量）
    会 schema 冲突。这里整模块改前缀，所有路由落到 ``__dagtest_<bucket>``（全新 named
    schema），结束后删除这些测试 collection。完全不触碰存量数据。
    """
    original = getattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX", None)
    settings.CHUNK_INDEX_COLLECTION_PREFIX = _ISOLATED_QDRANT_PREFIX
    try:
        yield
    finally:
        if original is None:
            try:
                delattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX")
            except Exception:
                settings.CHUNK_INDEX_COLLECTION_PREFIX = original
        else:
            settings.CHUNK_INDEX_COLLECTION_PREFIX = original
        # 删除本次产生的隔离 collection（best-effort）。
        import asyncio

        async def _cleanup():
            from qdrant_client import AsyncQdrantClient

            host = str(settings.QDRANT_HOST)
            url = host if host.startswith("http") else f"http://{host}:{settings.QDRANT_PORT}"
            client = AsyncQdrantClient(url=url, timeout=30)
            cols = await client.get_collections()
            for c in cols.collections:
                if c.name.startswith(_ISOLATED_QDRANT_PREFIX):
                    try:
                        await client.delete_collection(c.name)
                    except Exception:
                        pass
            await client.close()

        try:
            asyncio.run(_cleanup())
        except Exception:
            pass


@pytest_asyncio.fixture(scope="module", autouse=True, loop_scope="module")
async def _db_lifecycle():
    """模块级释放全局异步引擎，绑定到本模块共享的事件循环。

    进入时清空可能残留(绑定到其它模块循环)的全局缓存，迫使在本模块循环内重建；
    退出时在同一循环内 close_database 干净释放。
    """
    import src.database as database

    database._async_engine = None
    database._async_session_factory = None
    try:
        yield
    finally:
        await database.close_database()


@pytest_asyncio.fixture(loop_scope="module")
async def parse_case():
    """准备一次真实解析所需的源文件与 DB 行，结束后清理产物。

    yield 出 ``(payload, doc_id)``。清理覆盖：MinIO 源/markdown 对象、chunk 真值行、
    ES 文档索引、DocumentParseTask 行。Qdrant 向量点以唯一 chunk_id 落库，不会跨用例
    冲突，最佳努力随 chunk 行一并清理（删 chunk 行即移除真值，向量点为孤儿无副作用）。
    """
    suffix = uuid.uuid4().hex[:8]
    task_id = f"dag_it_{suffix}"
    parse_task_id = _ID_BASE + int(suffix, 16) % 100_000
    doc_id = parse_task_id + 1
    bucket = settings.MINIO_PRIVATE_BUCKET
    src_key = f"dag-it/{task_id}.md"

    storage = StorageFactory.get_storage()
    storage.upload_bytes(
        bucket=bucket,
        object_key=src_key,
        content=_SOURCE_MARKDOWN.encode("utf-8"),
        content_type="text/markdown",
    )

    factory = get_async_session_factory()
    async with factory() as db:
        db.add(
            DocumentParseTask(
                id=parse_task_id,
                document_original_file_id=doc_id,
                dataset_id=_TEST_DATASET_ID,
                user_id=_TEST_USER_ID,
                latest_parse_task_id=task_id,
                original_filename=f"{task_id}.md",
                parse_count=1,
            )
        )
        await db.commit()

    payload = ParseTaskMessage.build(
        task_id=task_id,
        original_file_id=doc_id,
        document_parse_task_id=parse_task_id,
        user_id=_TEST_USER_ID,
        dataset_id=_TEST_DATASET_ID,
        file_type="md",
        source_bucket=bucket,
        source_object_key=src_key,
        source_filename=f"{task_id}.md",
        md_bucket=bucket,
        md_object_key=src_key,
    ).get_payload()

    try:
        yield payload, doc_id
    finally:
        # ---- 清理：chunk 行 / BM25 索引 / DB 任务行 / MinIO 对象 ----
        async with factory() as db:
            await ChunkRepository().delete_by_doc_id(db, doc_id)
            await db.execute(
                delete(DocumentParseTask).where(DocumentParseTask.id == parse_task_id)
            )
            await db.commit()
        try:
            from src.core.storage.bm25_backend import build_indexing_pipeline

            await build_indexing_pipeline().delete_document_index(
                user_id=_TEST_USER_ID,
                dataset_id=_TEST_DATASET_ID,
                doc_id=doc_id,
            )
        except Exception:
            pass
        s3 = getattr(storage, "_client", None)
        if s3 is not None:
            try:
                s3.delete_object(Bucket=bucket, Key=src_key)
            except Exception:
                pass


async def _count_chunks(doc_id: int) -> int:
    factory = get_async_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(func.count()).select_from(ChunkRecordDB).where(
                ChunkRecordDB.doc_id == doc_id
            )
        )
        return int(result.scalar_one())


async def _point_vector_names(doc_id: int) -> dict[str, set[str]]:
    """返回 ``{chunk_id: 该 Qdrant point 上存在的命名向量名集合}``。

    用于校验 named-dense 解耦的核心不变量：dense 与 sparse 落在**同一个 point** 的两个
    命名向量上（``dense`` / ``sparse_text``），谁先写都不互相覆盖。读 MySQL 取每个
    chunk 的 bucket_id，按 bucket 路由到隔离 collection，``retrieve`` 出向量字典，
    其 key 即命名向量名。空 dict / list 形态都归一化处理。
    """
    from collections import defaultdict

    from qdrant_client import AsyncQdrantClient

    factory = get_async_session_factory()
    async with factory() as db:
        rows = (
            await db.execute(
                select(ChunkRecordDB.chunk_id, ChunkRecordDB.bucket_id).where(
                    ChunkRecordDB.doc_id == doc_id
                )
            )
        ).all()

    by_bucket: dict[int, list[str]] = defaultdict(list)
    for chunk_id, bucket_id in rows:
        assert bucket_id is not None, f"chunk {chunk_id} missing bucket_id"
        by_bucket[int(bucket_id)].append(chunk_id)

    router = BucketRouter(
        bucket_count=getattr(settings, "CHUNK_INDEX_BUCKET_COUNT", 128),
        prefix=settings.CHUNK_INDEX_COLLECTION_PREFIX,
    )
    host = str(settings.QDRANT_HOST)
    url = host if host.startswith("http") else f"http://{host}:{settings.QDRANT_PORT}"
    client = AsyncQdrantClient(url=url, timeout=60)
    out: dict[str, set[str]] = {}
    try:
        for bucket_id, ids in by_bucket.items():
            records = await client.retrieve(
                collection_name=router.collection_name(bucket_id),
                ids=ids,
                with_payload=False,
                with_vectors=True,
            )
            for rec in records:
                vec = rec.vector or {}
                out[str(rec.id)] = set(vec.keys()) if isinstance(vec, dict) else {"<unnamed>"}
    finally:
        await client.close()
    return out


def _assert_dense_sparse_coexist(point_vectors: dict[str, set[str]], dense_name: str) -> None:
    """每个 point 必须同时带 dense 命名向量与 sparse_text 命名向量。"""
    assert point_vectors, "no points found for doc"
    bad = {
        cid: names
        for cid, names in point_vectors.items()
        if dense_name not in names or "sparse_text" not in names
    }
    assert not bad, f"points missing dense/sparse coexistence: {bad}"


class _FailOnceServices:
    """包装真实 StageServices，让指定方法在首次调用时抛错、之后正常委托。

    其余属性/方法全部透传真实实例，因此除被注入的那一步外，链路仍打真实中间件。
    """

    def __init__(self, inner, fail_method: str) -> None:
        self._inner = inner
        self._fail_method = fail_method
        self._tripped = False

    @property
    def tripped(self) -> bool:
        return self._tripped

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name != self._fail_method or not callable(attr):
            return attr

        async def _wrapper(*args, **kwargs):
            if not self._tripped:
                self._tripped = True
                raise RuntimeError(f"injected-failure:{name}")
            return await attr(*args, **kwargs)

        return _wrapper


_OK_NODE_STATES = {NodeStatus.SUCCESS, NodeStatus.SKIPPED}


def _assert_run_ok(run) -> None:
    """run 整体成功，且每个节点处于完成态（本轮 SUCCESS 或续跑继承 SKIPPED）。"""
    if run.status != RunStatus.SUCCESS or any(
        run.nodes[k].status not in _OK_NODE_STATES for k in _ALL_NODES
    ):
        diag = {
            k: (run.nodes[k].status, run.nodes[k].failure_phase, run.nodes[k].failure_reason)
            for k in _ALL_NODES
        }
        raise AssertionError(f"run failed: {run.failure_reason}; nodes={diag}")
    for key in _ALL_NODES:
        assert run.nodes[key].status in _OK_NODE_STATES, (key, run.nodes[key])


# ----------------------------------------------------------------------------
# 1. 全链路成功：穿行 + 并行
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_definition, max_concurrency",
    [
        (build_parse_task_serial_workflow, 1),
        (build_parse_task_demo_workflow, 4),
    ],
    ids=["serial", "parallel"],
)
async def test_full_success(parse_case, build_definition, max_concurrency):
    payload, doc_id = parse_case
    runner = ParseWorkflowRunner(store=InMemoryWorkflowStore())

    run = await runner.run(
        payload,
        definition=build_definition(biz_key=payload.task_id),
        max_concurrency=max_concurrency,
    )

    _assert_run_ok(run)
    assert await _count_chunks(doc_id) > 0


# ----------------------------------------------------------------------------
# 2. 续跑 happy path：上一轮全成功 → 续跑全部 SKIPPED
# ----------------------------------------------------------------------------


async def test_resume_after_success_skips_all_nodes(parse_case):
    payload, doc_id = parse_case
    runner = ParseWorkflowRunner(store=InMemoryWorkflowStore())
    definition = build_parse_task_demo_workflow(biz_key=payload.task_id)

    first = await runner.run(payload, definition=definition, max_concurrency=4)
    _assert_run_ok(first)

    second = await runner.run(
        payload,
        definition=definition,
        previous_run_id=first.run_id,
        max_concurrency=4,
    )
    assert second.status == RunStatus.SUCCESS
    for key in _ALL_NODES:
        assert second.nodes[key].status == NodeStatus.SKIPPED, key
        assert second.nodes[key].inherited_from_run_id == first.run_id


# ----------------------------------------------------------------------------
# 3. 失败注入重试：dense 首跑失败 → 续跑只补 dense，上游跳过并 restore
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_definition, max_concurrency",
    [
        (build_parse_task_serial_workflow, 1),
        (build_parse_task_demo_workflow, 4),
    ],
    ids=["serial", "parallel"],
)
async def test_retry_after_dense_failure(parse_case, build_definition, max_concurrency):
    payload, doc_id = parse_case
    store = InMemoryWorkflowStore()

    base = ParseWorkflowRunner(store=store)
    injected = _FailOnceServices(base._services, fail_method="store_chunk_vectors")
    runner = ParseWorkflowRunner(store=store, services=injected)
    definition = build_definition(biz_key=payload.task_id)

    # 首跑：dense 写向量阶段抛错。
    first = await runner.run(payload, definition=definition, max_concurrency=max_concurrency)
    assert first.status == RunStatus.FAILED
    assert first.nodes["dense_vectorizing"].status == NodeStatus.FAILED
    assert injected.tripped
    # cleaning / chunking 首跑必定成功（dense 在其后）。
    assert first.nodes["cleaning"].status == NodeStatus.SUCCESS
    assert first.nodes["chunking"].status == NodeStatus.SUCCESS

    # 续跑：跳过已成功节点，重跑 dense（及被其阻断的下游）。
    second = await runner.run(
        payload,
        definition=definition,
        previous_run_id=first.run_id,
        max_concurrency=max_concurrency,
    )
    _assert_run_ok(second)
    assert second.nodes["cleaning"].status == NodeStatus.SKIPPED
    assert second.nodes["chunking"].status == NodeStatus.SKIPPED
    # dense 在上一轮失败，本轮真正重跑（非继承）。
    assert second.nodes["dense_vectorizing"].inherited_from_run_id is None
    assert await _count_chunks(doc_id) > 0

    # 关键不变量：并行拓扑下 sparse 首跑就已成功（它只依赖 POINTS_READY，不依赖
    # dense）；续跑重写 dense 时用 update_vectors 只动 dense 命名向量，绝不能覆盖
    # 同一 point 上已存在的 sparse。校验每个 point 仍 dense + sparse 共存。
    dense_name = settings.DENSE_VECTOR_QDRANT_VECTOR_NAME
    _assert_dense_sparse_coexist(await _point_vector_names(doc_id), dense_name)


# ----------------------------------------------------------------------------
# 4. 核心不变量：dense 与 sparse 共存于同一 point（解耦后不互相覆盖）
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_definition, max_concurrency",
    [
        (build_parse_task_serial_workflow, 1),
        (build_parse_task_demo_workflow, 4),
    ],
    ids=["serial", "parallel"],
)
async def test_dense_sparse_coexist_on_same_point(
    parse_case, build_definition, max_concurrency
):
    payload, doc_id = parse_case
    runner = ParseWorkflowRunner(store=InMemoryWorkflowStore())

    run = await runner.run(
        payload,
        definition=build_definition(biz_key=payload.task_id),
        max_concurrency=max_concurrency,
    )
    _assert_run_ok(run)

    dense_name = settings.DENSE_VECTOR_QDRANT_VECTOR_NAME
    _assert_dense_sparse_coexist(await _point_vector_names(doc_id), dense_name)


# ----------------------------------------------------------------------------
# 5. sparse 首跑失败 → 续跑只补 sparse；dense（已成功）不被覆盖
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_definition, max_concurrency",
    [
        (build_parse_task_serial_workflow, 1),
        (build_parse_task_demo_workflow, 4),
    ],
    ids=["serial", "parallel"],
)
async def test_retry_after_sparse_failure(parse_case, build_definition, max_concurrency):
    payload, doc_id = parse_case
    store = InMemoryWorkflowStore()

    base = ParseWorkflowRunner(store=store)
    injected = _FailOnceServices(base._services, fail_method="run_sparse_vectorizing")
    runner = ParseWorkflowRunner(store=store, services=injected)
    definition = build_definition(biz_key=payload.task_id)

    # 首跑：sparse 阶段抛错；dense 不依赖 sparse，应已成功。
    first = await runner.run(payload, definition=definition, max_concurrency=max_concurrency)
    assert first.status == RunStatus.FAILED
    assert first.nodes["sparse_vectorizing"].status == NodeStatus.FAILED
    assert injected.tripped
    assert first.nodes["dense_vectorizing"].status == NodeStatus.SUCCESS
    assert first.nodes["ensure_points"].status == NodeStatus.SUCCESS

    # 续跑：跳过已成功节点，只重跑 sparse。
    second = await runner.run(
        payload,
        definition=definition,
        previous_run_id=first.run_id,
        max_concurrency=max_concurrency,
    )
    _assert_run_ok(second)
    assert second.nodes["dense_vectorizing"].status == NodeStatus.SKIPPED
    assert second.nodes["dense_vectorizing"].inherited_from_run_id == first.run_id
    # sparse 上一轮失败，本轮真正重跑（非继承）。
    assert second.nodes["sparse_vectorizing"].inherited_from_run_id is None

    # sparse 补写后，dense（首跑写入）必须仍在：两者共存于同一 point。
    dense_name = settings.DENSE_VECTOR_QDRANT_VECTOR_NAME
    _assert_dense_sparse_coexist(await _point_vector_names(doc_id), dense_name)


# ----------------------------------------------------------------------------
# 6. ensure_points 首跑失败 → dense 与 sparse 双双阻断；续跑补建点后两路成功
# ----------------------------------------------------------------------------


async def test_retry_after_ensure_points_failure(parse_case):
    """ensure_points 是 dense/sparse 解耦的单写者前置。它失败时两路都不应推进；
    续跑补建点后，dense / sparse 各自写入，最终共存。仅测并行拓扑（解耦的关键路径）。
    """
    payload, doc_id = parse_case
    store = InMemoryWorkflowStore()

    base = ParseWorkflowRunner(store=store)
    injected = _FailOnceServices(base._services, fail_method="ensure_chunk_points")
    runner = ParseWorkflowRunner(store=store, services=injected)
    definition = build_parse_task_demo_workflow(biz_key=payload.task_id)

    # 首跑：ensure_points 抛错 → dense / sparse 因 POINTS_READY 缺失而不被调度。
    first = await runner.run(payload, definition=definition, max_concurrency=4)
    assert first.status == RunStatus.FAILED
    assert first.nodes["ensure_points"].status == NodeStatus.FAILED
    assert injected.tripped
    # 两路向量节点都没成功（被前置阻断，保持 PENDING / 未进入完成态）。
    assert first.nodes["dense_vectorizing"].status != NodeStatus.SUCCESS
    assert first.nodes["sparse_vectorizing"].status != NodeStatus.SUCCESS
    # chunking 在 ensure_points 之前，必定成功；pretokenize→es 不经 ensure_points，可成功。
    assert first.nodes["chunking"].status == NodeStatus.SUCCESS

    # 续跑：ensure_points 重跑（chunking 被 restore 提供 CHUNKS），dense/sparse 跟上。
    second = await runner.run(
        payload,
        definition=definition,
        previous_run_id=first.run_id,
        max_concurrency=4,
    )
    _assert_run_ok(second)
    assert second.nodes["chunking"].status == NodeStatus.SKIPPED
    assert second.nodes["ensure_points"].inherited_from_run_id is None
    assert await _count_chunks(doc_id) > 0

    dense_name = settings.DENSE_VECTOR_QDRANT_VECTOR_NAME
    _assert_dense_sparse_coexist(await _point_vector_names(doc_id), dense_name)
