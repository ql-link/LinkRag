from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.api.management_auth import CurrentUser
from src.api.management_http import BusinessError
from src.api.routes import recall
from src.application.recall_errors import RecallApiError
from src.config import settings


@pytest.mark.asyncio
async def test_session_handshake_reuses_active_python_token_and_checks_scope(monkeypatch):
    monkeypatch.setattr(settings, "B1_PYTHON_ISSUER_ENABLED", True)
    checked = []

    async def resolve(_db, *, user_id, requested_dataset_ids):
        checked.append((user_id, requested_dataset_ids))
        return [7]

    monkeypatch.setattr(recall, "resolve_user_dataset_scope", resolve)
    verifier = SimpleNamespace(
        verify=lambda token: SimpleNamespace(expires_at=int(time.time()) + 60)
    )
    request = SimpleNamespace(
        headers={"satoken": "python-access-token"},
        app=SimpleNamespace(
            state=SimpleNamespace(management_authenticator=SimpleNamespace(_verifier=verifier))
        ),
    )
    result = await recall.create_recall_session(
        request,
        recall.RecallSessionRequest(datasetIds=[7]),
        CurrentUser(11, "USER"),
        object(),
    )
    assert checked == [(11, [7])]
    assert result.data["token"] == "python-access-token"
    assert result.data["streamUrl"] == "/api/v1/rag/stream"
    assert result.data["datasetIds"] == [7]
    assert 0 < result.data["expiresIn"] <= 60


@pytest.mark.asyncio
async def test_session_handshake_rejects_foreign_dataset(monkeypatch):
    monkeypatch.setattr(settings, "B1_PYTHON_ISSUER_ENABLED", True)

    async def reject(*args, **kwargs):
        raise RecallApiError(403, "RECALL_SCOPE_FORBIDDEN", "dataset scope is not authorized")

    monkeypatch.setattr(recall, "resolve_user_dataset_scope", reject)
    with pytest.raises(BusinessError) as exc:
        await recall.create_recall_session(
            SimpleNamespace(),
            recall.RecallSessionRequest(datasetIds=[8]),
            CurrentUser(11, "USER"),
            object(),
        )
    assert exc.value.http_status == 403
