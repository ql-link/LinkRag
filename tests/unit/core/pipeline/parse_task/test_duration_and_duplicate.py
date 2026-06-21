# -*- coding: utf-8 -*-
"""parse_task 耗时计算与中断任务收敛的时区回归测试。

补齐历史盲区（见 issue #164 / 线上样本 document_parse_file_id=10015）：
``duration_ms`` 与 ``ParseTaskGuard.handle_duplicate`` 此前无直接单测，且 acceptance
将 guard / 耗时字段整体 mock，导致 "DB 读回的 naive datetime 减 now() 的 aware
datetime" 这条真实路径从未在测试下执行，最终在生产以
``TypeError: can't subtract offset-naive and offset-aware datetimes`` 暴露，
使中断任务无法收敛为 FAILED 而进入 DLT。

本文件直接执行真实 ``duration_ms``（**刻意不 mock**），锁定归一化行为。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.core.pipeline.parse_task._utils import duration_ms, now
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_PROCESSING,
    STAGE_STATUS_PENDING,
)
from src.core.pipeline.parse_task.validator import ParseTaskGuard
from src.core.pipeline.parse_task.models import PipelineStatus

# 模拟 MySQL DATETIME 经 SQLAlchemy 读出的 naive 值（语义上为 UTC）
NAIVE_PAST = datetime(2026, 6, 8, 10, 0, 0)
AWARE_PAST = datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc)


# ============ duration_ms 纯函数：naive/aware 全组合 ============


def test_duration_ms_naive_started_aware_finished_no_typeerror():
    """核心回归：naive started_at（DB 读回）减 aware finished_at（now()）不再抛错。"""
    result = duration_ms(NAIVE_PAST, now())
    assert isinstance(result, int)
    assert result > 0


def test_duration_ms_aware_started_naive_finished():
    """反向组合（aware started + naive finished）同样不抛错。"""
    result = duration_ms(AWARE_PAST, datetime(2026, 6, 8, 10, 0, 1))
    assert result == 1000


def test_duration_ms_both_aware():
    start = datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc)
    finish = start + timedelta(seconds=2)
    assert duration_ms(start, finish) == 2000


def test_duration_ms_both_naive():
    assert duration_ms(NAIVE_PAST, NAIVE_PAST + timedelta(milliseconds=500)) == 500


def test_duration_ms_none_started_returns_none():
    assert duration_ms(None, now()) is None


def test_duration_ms_naive_treated_as_utc_not_local():
    """naive 一律按 UTC 解释：与同一时刻的 aware-UTC 相减应为 0，而非 8h 偏移。

    服务器时区为 Shanghai(UTC+8) 时，若误把 naive 当本地时间会得到 ±8h 偏差。
    """
    aware_utc = datetime(2026, 6, 8, 2, 0, 0, tzinfo=timezone.utc)
    naive_same_wall_clock = datetime(2026, 6, 8, 2, 0, 0)
    assert duration_ms(naive_same_wall_clock, aware_utc) == 0


# ============ handle_duplicate：中断任务收敛真实路径（不 mock duration_ms） ============


def _make_guard_with_processing_pipeline(started_at):
    """构造一个 guard：重复 task 命中非终态(PROCESSING)、且 started_at 为给定值。

    仅 mock 仓储边界（DB 访问与 mark_*_failed 落库），**不** mock duration_ms，
    使收敛路径里的真实耗时计算得到执行。
    """
    log_repo = MagicMock()
    log_repo.get_by_task_id = AsyncMock(
        return_value=SimpleNamespace(id=1, parsed_object_key="ds/x.md")
    )

    pipeline_record = SimpleNamespace(
        pipeline_status=PIPELINE_STATUS_PROCESSING,
        cleaning_status=STAGE_STATUS_PENDING,  # 首个非 SUCCESS → recover=CLEANING
        chunking_status=STAGE_STATUS_PENDING,
        vectorizing_status=STAGE_STATUS_PENDING,
        pretokenize_status=STAGE_STATUS_PENDING,
        es_indexing_status=STAGE_STATUS_PENDING,
        started_at=started_at,
    )
    pipeline_repo = MagicMock()
    pipeline_repo.get_by_log_id = AsyncMock(return_value=pipeline_record)
    pipeline_repo.mark_cleaning_failed = AsyncMock()

    guard = ParseTaskGuard(log_repository=log_repo, pipeline_repository=pipeline_repo)
    return guard, pipeline_repo


async def test_handle_duplicate_naive_started_converges_to_failed():
    """naive started_at 的非终态 pipeline 应被收敛为 FAILED，不抛 TypeError、不进 DLT。"""
    guard, pipeline_repo = _make_guard_with_processing_pipeline(NAIVE_PAST)
    payload = SimpleNamespace(task_id="task-naive-1")

    result = await guard.handle_duplicate(payload, db=MagicMock())

    assert result.status == PipelineStatus.FAILED
    assert result.task_id == "task-naive-1"
    # 真实 duration_ms 已在收敛路径执行（未被 mock），naive started_at 未导致异常
    pipeline_repo.mark_cleaning_failed.assert_awaited_once()
    passed_duration = pipeline_repo.mark_cleaning_failed.await_args.kwargs["duration_ms"]
    assert isinstance(passed_duration, int)
    assert passed_duration > 0


async def test_handle_duplicate_aware_started_also_ok():
    """aware started_at 路径同样正常收敛（无回归）。"""
    guard, pipeline_repo = _make_guard_with_processing_pipeline(AWARE_PAST)
    payload = SimpleNamespace(task_id="task-aware-1")

    result = await guard.handle_duplicate(payload, db=MagicMock())

    assert result.status == PipelineStatus.FAILED
    pipeline_repo.mark_cleaning_failed.assert_awaited_once()
    assert isinstance(
        pipeline_repo.mark_cleaning_failed.await_args.kwargs["duration_ms"], int
    )
