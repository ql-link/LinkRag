from __future__ import annotations

import pytest

from src.core.vector_storage.stores.repository import ChunkRepository


class StubExecuteResult:
    rowcount = 0


class CapturingSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return StubExecuteResult()


def _where_criteria_count(session: CapturingSession) -> int:
    return len(session.statement._where_criteria)


@pytest.mark.asyncio
async def test_should_protect_delete_states_when_mark_indexed_has_no_expected_status():
    # Arrange: 准备数据
    repository = ChunkRepository()
    session = CapturingSession()

    # Act: 执行动作
    await repository.mark_indexed(session, ["chunk-1"])

    # Assert: 断言结果
    assert _where_criteria_count(session) == 2


@pytest.mark.asyncio
async def test_should_protect_delete_states_when_mark_failed_has_no_expected_status():
    # Arrange: 准备数据
    repository = ChunkRepository()
    session = CapturingSession()

    # Act: 执行动作
    await repository.mark_failed(session, ["chunk-1"], error_msg="boom")

    # Assert: 断言结果
    assert _where_criteria_count(session) == 2


@pytest.mark.asyncio
async def test_should_protect_delete_states_when_mark_indexing_has_no_expected_status():
    # Arrange: 准备数据
    repository = ChunkRepository()
    session = CapturingSession()

    # Act: 执行动作
    await repository.mark_indexing(session, ["chunk-1"])

    # Assert: 断言结果
    assert _where_criteria_count(session) == 2
