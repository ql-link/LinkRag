"""Shared fixtures + step 注册入口 for the OOM-governance acceptance suite.

pytest-bdd 8.x 的 step 定义需要在被 pytest 加载到的模块（conftest.py / test 文件）里
可见才会被匹配。这里通过 ``from tests.acceptance.steps.* import *`` 把所有 step 函数
带进当前 conftest，让 pytest-bdd 在收集 acceptance/test_*.py 时能找到对应 step。

把 ``acceptance.feature`` 的运行环境集中到这里：

- ``settings.PARSE_TEMP_DIR`` 隔离到 pytest 的 ``tmp_path``，避免污染主机 /tmp。
- ``fake_storage`` 提供 ``download_to_path``（实际写本地 bytes）+ ``download_bytes``
  spy（用于断言"调用次数 == 0"，验证 OOM 治理生效）。
- ``payload_factory`` 按 file_type / pdf_backend / size_mb 构造 ``ParseTaskPayload``。
- ``pipeline_factory`` 装配带桩依赖的 ``ParseTaskPipeline`` 供主流程/异常路径 step 复用。
"""

from __future__ import annotations

# 通过 star-import 注册所有 step 装饰器到 conftest 命名空间。
# noqa 注释避免 lint 告警；不在意名字冲突，因为 step 函数都用下划线前缀。
from tests.acceptance.steps.background_steps import *  # noqa: F401,F403,E402
from tests.acceptance.steps.storage_steps import *  # noqa: F401,F403,E402
from tests.acceptance.steps.pipeline_steps import *  # noqa: F401,F403,E402
from tests.acceptance.steps.parser_steps import *  # noqa: F401,F403,E402
from tests.acceptance.steps.temp_workspace_steps import *  # noqa: F401,F403,E402
from tests.acceptance.steps.logging_steps import *  # noqa: F401,F403,E402

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from src.config import settings
from src.core.mq.messages.parse_task import ParseTaskPayload


@dataclass
class _ScenarioState:
    """Scenario 间共享的可变上下文。

    pytest-bdd 的 step 之间通过 fixture 传值；某些跨 step 的"中间产物"用普通参数无法
    传递（如 Given 创建的 payload 在后续 When/Then 引用），统一收纳到本对象的属性里。
    """

    payload: ParseTaskPayload | None = None
    object_store: dict[tuple[str, str], bytes] = field(default_factory=dict)
    download_should_raise: BaseException | None = None
    parse_should_raise: BaseException | None = None
    upload_should_raise: BaseException | None = None
    pipeline_result: object | None = None
    pipeline_error: BaseException | None = None
    last_temp_path: Path | None = None
    captured_logs: list[dict] = field(default_factory=list)
    log_sink_id: int | None = None


@pytest.fixture
def state(tmp_path, monkeypatch) -> _ScenarioState:
    # 每个 Scenario 一份独立状态，避免参数化 Outline 之间相互污染。
    monkeypatch.setattr(settings, "PARSE_TEMP_DIR", str(tmp_path / "parse-tmp"))
    s = _ScenarioState()

    def sink(message):
        rec = message.record
        s.captured_logs.append(
            {
                "message": rec["message"],
                "extra": dict(rec["extra"]),
                # loguru 把 logger.info("a={}", b) 的位置参数放在 message 中，
                # 这里同时存原始 message 字符串与已经渲染好的最终文本，断言时按需选取。
                "rendered": message,
            }
        )

    s.log_sink_id = logger.add(sink, level="INFO")
    try:
        yield s
    finally:
        logger.remove(s.log_sink_id)


@pytest.fixture
def fake_storage(state):
    """对象存储桩。

    - ``download_to_path`` 按 (bucket, object_key) 在 ``state.object_store`` 里查内容，
      流式写入 ``dst``；命中 ``state.download_should_raise`` 时抛出对应异常。
    - ``download_bytes`` 保留为 MagicMock 仅供断言 ``assert_not_called`` —— 协议层已经
      删除该方法，存在仅为了让"非旁路路径不再调用全量 bytes 下载接口"这条 Scenario
      可以直接 spy。
    """
    storage = MagicMock()
    storage.download_bytes = MagicMock(side_effect=AssertionError("download_bytes 不应被调用"))

    def _download_to_path(bucket, object_key, dst):
        if state.download_should_raise is not None:
            raise state.download_should_raise
        content = state.object_store.get((bucket, object_key))
        if content is None:
            raise FileNotFoundError(f"object not found: {bucket}/{object_key}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
        state.last_temp_path = dst

    storage.download_to_path = MagicMock(side_effect=_download_to_path)

    def _upload_bytes(**kwargs):
        if state.upload_should_raise is not None:
            raise state.upload_should_raise
        state.object_store[(kwargs["bucket"], kwargs["object_key"])] = kwargs["content"]

    storage.upload_bytes = MagicMock(side_effect=_upload_bytes)
    storage.build_object_url = MagicMock(
        side_effect=lambda bucket, object_key: f"oss://{bucket}/{object_key}"
    )
    return storage


@pytest.fixture
def payload_factory():
    """构造 ParseTaskPayload 的工厂。"""

    def _build(
        file_type: str = "docx",
        pdf_backend: str | None = "mineru",
        task_id: str = "t-acc-001",
        source_bucket: str = "src-bucket",
        source_object_key: str | None = None,
    ) -> ParseTaskPayload:
        # MQ 消息构造器走 ParseTaskMessage.build → get_payload，与生产链路一致。
        from src.core.mq.messages import ParseTaskMessage

        return ParseTaskMessage.build(
            task_id=task_id,
            original_file_id=1,
            document_parse_task_id=10,
            user_id=20,
            dataset_id=30,
            file_type=file_type,
            source_bucket=source_bucket,
            source_object_key=source_object_key or f"uploads/{task_id}.{file_type}",
            source_filename=f"{task_id}.{file_type}",
            md_bucket="md-bucket",
            md_object_key=f"parsed/{task_id}.md",
            pdf_parser_backend=pdf_backend,
        ).get_payload()

    return _build


@pytest.fixture
def parse_service_stub(state, monkeypatch):
    """把 ``ParseTaskService.aprocess`` 替换为受控桩。

    桩内：
    - 命中 ``state.parse_should_raise`` 时抛对应异常（PARSE_ENGINE_FAILED 用例）
    - 否则返回一个固定 markdown 结果；同时记录被 parser 收到的 source_path 到状态对象，
      供 step 断言"_parse_file 入参 source_path 为 None / 为 Path"。
    """
    received: dict = {}

    async def _aprocess(source_path, file_type, source_file=None, **parser_kwargs):
        received["source_path"] = source_path
        received["file_type"] = file_type
        received["parser_kwargs"] = parser_kwargs
        # 注入最小 sleep 让外层 pipeline 的 parse_ms 计数大于 0；零耗时会让"parse_ms > 0"
        # 这条 observability 契约判错。
        import asyncio as _asyncio

        await _asyncio.sleep(0.002)
        if state.parse_should_raise is not None:
            raise state.parse_should_raise
        return {
            "markdown": "# parsed\n\nhello world",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 1},
            "time_cost_ms": 5,
        }

    monkeypatch.setattr(
        "src.core.pipeline.parse_task.pipeline.ParseTaskService.aprocess",
        _aprocess,
    )
    monkeypatch.setattr(
        "src.core.pipeline.parse_task.pipeline.ParseTaskPipeline._chunk_markdown",
        staticmethod(lambda *a, **kw: [MagicMock()]),
    )
    return received


@pytest.fixture
def post_process_repository_stub():
    """post-process repository 桩：所有 mark_* 接口都是 no-op，避免触发真实 DB。"""
    repo = MagicMock()
    pipeline_row = SimpleNamespace(
        id=1,
        pipeline_status="PENDING",
        chunking_status="PENDING",
        vectorizing_status="PENDING",
        es_indexing_status="PENDING",
        pretokenize_status="PENDING",
        started_at=None,
    )
    repo.get_by_log_id = AsyncMock(return_value=pipeline_row)
    repo.mark_processing = AsyncMock()
    repo.mark_chunking_success = AsyncMock()
    repo.mark_chunking_failed = AsyncMock()
    repo.mark_vectorizing_success = AsyncMock()
    repo.mark_vectorizing_failed = AsyncMock()
    repo.mark_pretokenize_success = AsyncMock()
    repo.mark_pretokenize_failed = AsyncMock()
    repo.mark_es_success = AsyncMock()
    repo.mark_es_failed = AsyncMock()
    return repo


class _FakeSession:
    """最小可用 AsyncSession 桩，用作 ``ParseTaskPipeline._run`` 的 ``db`` 入参。"""

    def __init__(self):
        self.commit = AsyncMock()
        self.add = MagicMock()
        self.close = AsyncMock()
        self.refresh = AsyncMock()
        self.flush = AsyncMock()


class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.fixture
def pipeline_factory(
    fake_storage,
    parse_service_stub,
    post_process_repository_stub,
    state,
    monkeypatch,
):
    """组合一个可执行的 ParseTaskPipeline。

    刻意避开真实 DB / MQ / 向量库：log_repository / guard / notifier 用桩件直通。
    具体业务 Scenario 通常只关心"是否调了 download_to_path / 是否清理临时文件 / 是否
    设置正确的 failure_reason"，不需要走完整后处理链路；因此把成功路径在 markdown 上传
    完成后立即短路掉。
    """
    from src.core.pipeline import ParseTaskPipeline
    from src.core.pipeline.parse_task.models import ParsePipelineResult, PipelineStatus

    def _factory():
        session = _FakeSession()

        pipeline = ParseTaskPipeline.__new__(ParseTaskPipeline)
        pipeline._storage = fake_storage
        pipeline._session_factory = _FakeSessionFactory(session)
        pipeline._mq_service = MagicMock()
        pipeline._vector_storage = MagicMock()
        pipeline._pipeline_repository = post_process_repository_stub
        pipeline._es_indexing_pipeline = MagicMock()
        pipeline._preprocessor = MagicMock()
        pipeline._chunk_repository = MagicMock()

        from src.core.pipeline.parse_task.source import ParseSourceIO

        pipeline._source_io = ParseSourceIO(fake_storage)

        # log_repository 桩：create 直通返回 DocumentParsedLog；mark_failed/mark_success
        # 仅记录入参便于断言。
        log_row = SimpleNamespace(
            id=1,
            parse_started_at=None,
            parse_finished_at=None,
            task_status="CREATED",
        )
        log_repo = MagicMock()
        log_repo.create = AsyncMock(return_value=log_row)
        log_repo.get_parse_task = AsyncMock(
            return_value=SimpleNamespace(
                task_id="t-acc-001",
                file_type=None,
                source_object_key=None,
                source_bucket=None,
            )
        )

        async def _mark_failed(payload, log_record, reason, db):
            log_record.task_status = "FAILED"
            log_record.failure_reason = reason
            log_record.parse_finished_at = "2026-05-19T00:00:00"

        async def _mark_success(payload, log_record, db):
            log_record.task_status = "SUCCESS"

        log_repo.mark_failed = AsyncMock(side_effect=_mark_failed)
        log_repo.mark_success = AsyncMock(side_effect=_mark_success)
        pipeline._log_repository = log_repo

        # guard 桩：放行所有任务（acceptance 仅治理下载/解析路径，不复审 guard 行为）。
        guard = MagicMock()
        guard.validate = MagicMock(return_value=None)
        guard.handle_duplicate = AsyncMock(return_value=ParsePipelineResult(
            status=PipelineStatus.SKIPPED, task_id="t-acc-001"
        ))
        pipeline._guard = guard

        # notifier 桩：吞掉对外 MQ 通知。
        notifier = MagicMock()
        notifier.send_or_raise = AsyncMock()
        notifier.send = AsyncMock()
        pipeline._notifier = notifier

        # 关停 post-process 与 chunk 后续阶段：成功路径触达 markdown 上传后直接返回。
        # 用一个轻量补丁让 _run 在 mark_success 后早返，避免触达 chunk / 向量 / ES。
        from src.core.pipeline.parse_task import pipeline as pipeline_module

        original_run = pipeline_module.ParseTaskPipeline._run

        async def _run_short_circuit(self, payload, db):
            return await original_run(self, payload, db)

        # 不打补丁——_run 会自然走到 post_process_repository 桩件（已 AsyncMock no-op）
        # 与 notifier 桩件（已 AsyncMock no-op），最后返回 SUCCESS / FAILED。
        return pipeline, session

    return _factory


@pytest.fixture
def feature_path() -> Path:
    """供 step 测试时定位 acceptance.feature 的绝对路径。"""
    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "解析任务OOM风险治理"
        / "acceptance.feature"
    )
