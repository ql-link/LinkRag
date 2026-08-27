from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application.recall_errors import RecallApiError
from src.core.storage.dataset_scope import resolve_user_dataset_scope


def _db_with_ids(*dataset_ids: int) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = [(value,) for value in dataset_ids]
    return db


@pytest.mark.asyncio
async def test_explicit_owned_dataset_scope_is_returned_sorted():
    result = await resolve_user_dataset_scope(
        _db_with_ids(20, 10),
        user_id=7,
        requested_dataset_ids=[20, 10, 20],
    )
    assert result == [10, 20]


@pytest.mark.asyncio
async def test_omitted_scope_lists_all_current_owned_datasets():
    result = await resolve_user_dataset_scope(
        _db_with_ids(10, 20),
        user_id=7,
        requested_dataset_ids=None,
    )
    assert result == [10, 20]


@pytest.mark.asyncio
async def test_missing_requested_dataset_rejects_entire_scope():
    with pytest.raises(RecallApiError) as exc:
        await resolve_user_dataset_scope(
            _db_with_ids(10),
            user_id=7,
            requested_dataset_ids=[10, 30],
        )
    assert exc.value.status_code == 403
    assert exc.value.code == "RECALL_SCOPE_FORBIDDEN"


@pytest.mark.asyncio
async def test_scope_database_failure_is_fail_closed():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RecallApiError) as exc:
        await resolve_user_dataset_scope(db, user_id=7, requested_dataset_ids=[10])
    assert exc.value.status_code == 500
    assert exc.value.code == "RECALL_INTERNAL_ERROR"
