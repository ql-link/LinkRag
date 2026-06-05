"""MinerUBackend 轮询退避用例（LINK-28）。

聚焦回归点：轮询返回 code != 0 的警告分支必须经过退避，不能退化为 busy-loop，
并在连续失败达到阈值时熔断，而非硬等满 _timeout。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.parser.pdf.backends import mineru_backend as mineru_mod
from src.core.parser.pdf.backends.mineru_backend import (
    _MAX_CONSECUTIVE_POLL_ERRORS,
    MinerUBackend,
)


def _resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def _make_client(create_payload: dict, poll_responses: list[MagicMock]) -> MagicMock:
    """构造一个上下文管理器风格的 fake httpx.Client。"""
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = _resp(create_payload)
    client.get.side_effect = poll_responses
    return client


_CREATE_OK = {"code": 0, "data": {"task_id": "t-123"}}


@pytest.fixture
def backend() -> MinerUBackend:
    return MinerUBackend(api_url="https://mineru.example.com", api_key="k", timeout=300)


def test_warning_branch_applies_backoff_not_busy_loop(backend, monkeypatch):
    """连续 code != 0 时每轮都应 sleep 退避，而不是全速空转。"""
    sleep_calls: list[float] = []
    monkeypatch.setattr(mineru_mod.time, "sleep", lambda s: sleep_calls.append(s))

    # 阈值前一次成功结束，确保只统计警告分支的退避次数
    error_resps = [_resp({"code": -1, "msg": "rate limited"}) for _ in range(3)]
    done_resp = _resp({"code": 0, "data": {"state": "done", "full_md_url": "http://md"}})
    client = _make_client(_CREATE_OK, error_resps + [done_resp])

    with patch.object(mineru_mod.httpx, "Client", return_value=client):
        with patch.object(backend, "_download_markdown", return_value="# ok"):
            markdown, assets = backend._call_cloud_api("http://file", "vlm")

    assert markdown == "# ok"
    # 3 次警告分支各退避一次（done 分支不退避）
    assert len(sleep_calls) == 3
    # busy-loop 会产生远超轮询次数的 get；这里 get 次数应与响应数一致
    assert client.get.call_count == 4


def test_consecutive_errors_trigger_circuit_breaker(backend, monkeypatch):
    """连续失败达到阈值即抛异常，不等满 timeout。"""
    monkeypatch.setattr(mineru_mod.time, "sleep", lambda s: None)

    error_resps = [
        _resp({"code": -1, "msg": "5xx"}) for _ in range(_MAX_CONSECUTIVE_POLL_ERRORS + 2)
    ]
    client = _make_client(_CREATE_OK, error_resps)

    with patch.object(mineru_mod.httpx, "Client", return_value=client):
        with pytest.raises(Exception, match="连续"):
            backend._call_cloud_api("http://file", "vlm")

    # 命中阈值即停，不会把所有错误响应耗尽
    assert client.get.call_count == _MAX_CONSECUTIVE_POLL_ERRORS


def test_success_resets_error_counter(backend, monkeypatch):
    """中途成功一次应重置计数，避免间歇性抖动被误判为连续失败。"""
    monkeypatch.setattr(mineru_mod.time, "sleep", lambda s: None)

    # 交替失败/进行中，累计失败次数从未连续达到阈值
    poll = []
    for _ in range(_MAX_CONSECUTIVE_POLL_ERRORS + 3):
        poll.append(_resp({"code": -1, "msg": "blip"}))
        poll.append(_resp({"code": 0, "data": {"state": "running", "extract_progress": {}}}))
    poll.append(_resp({"code": 0, "data": {"state": "done", "full_md_url": "http://md"}}))
    client = _make_client(_CREATE_OK, poll)

    with patch.object(mineru_mod.httpx, "Client", return_value=client):
        with patch.object(backend, "_download_markdown", return_value="# ok"):
            markdown, _ = backend._call_cloud_api("http://file", "vlm")

    assert markdown == "# ok"
