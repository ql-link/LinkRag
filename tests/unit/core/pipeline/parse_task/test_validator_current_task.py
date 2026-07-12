"""ParseTaskGuard 使用 latest_parse_task_id 拒绝 stale task。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import mysql

from src.core.pipeline.parse_task.log_repository import ParseLogRepository
from src.core.pipeline.parse_task.validator import (
    ParseTaskGuard,
    RetryValidationError,
)


def _payload(*, task_id: str = "task-current"):
    return SimpleNamespace(
        task_id=task_id,
        original_file_id=100,
        dataset_id=10,
        user_id=7,
        document_parse_task_id=501,
        previous_task_id="task-previous",
        md_bucket="parsed",
        md_object_key="task.md",
    )


def _parse_task(*, latest_parse_task_id: str | None = "task-current"):
    return SimpleNamespace(
        document_original_file_id=100,
        dataset_id=10,
        user_id=7,
        latest_parse_task_id=latest_parse_task_id,
    )


def test_current_task_passes_validation():
    assert ParseTaskGuard.validate(_payload(), _parse_task()) is None


def test_previous_task_is_rejected_as_stale():
    reason = ParseTaskGuard.validate(
        _payload(task_id="task-old"),
        _parse_task(latest_parse_task_id="task-new"),
    )

    assert reason is not None
    assert reason.startswith("INVALID_TASK_CONTEXT:")
    assert "stale_task" in reason


def test_missing_current_pointer_is_fail_closed():
    reason = ParseTaskGuard.validate(
        _payload(),
        _parse_task(latest_parse_task_id=None),
    )

    assert reason is not None
    assert "stale_task" in reason


def test_existing_context_mismatch_keeps_more_specific_reason():
    parse_task = _parse_task(latest_parse_task_id="task-new")
    parse_task.dataset_id = 999

    reason = ParseTaskGuard.validate(_payload(task_id="task-old"), parse_task)

    assert reason is not None
    assert "数据集ID与文件解析记录不一致" in reason
    assert "stale_task" not in reason


@pytest.mark.asyncio
async def test_retry_rejects_stale_current_pointer_before_supersede_lookup():
    log_repository = SimpleNamespace(
        get_parse_task=AsyncMock(return_value=_parse_task(latest_parse_task_id="task-new")),
        get_by_task_id=AsyncMock(),
    )
    guard = ParseTaskGuard(log_repository, AsyncMock())

    with pytest.raises(RetryValidationError, match="stale_task"):
        await guard.validate_retry_context(
            _payload(task_id="task-old"),
            AsyncMock(),
        )

    log_repository.get_parse_task.assert_awaited_once()
    assert log_repository.get_parse_task.await_args.kwargs["for_share"] is True
    log_repository.get_by_task_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_parse_task_lookup_uses_mysql_shared_row_lock():
    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return None

    class _Db:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return _Result()

    db = _Db()

    await ParseLogRepository.get_parse_task(
        501,
        db,  # type: ignore[arg-type]
        for_share=True,
    )

    sql = str(db.statement.compile(dialect=mysql.dialect()))
    assert "LOCK IN SHARE MODE" in sql
