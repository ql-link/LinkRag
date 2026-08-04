"""QdrantIndexStore 写入路径瞬时故障重试回归。

锁定 named-dense 解耦后并行写入对共享 Qdrant 网关 5xx 的容错：
  1. 瞬时 502 → 退避后重试，最终成功（写操作幂等，重试安全）。
  2. 非瞬时错误（如 4xx 校验失败）→ 不重试，立即透传。
  3. 持续瞬时故障 → 耗尽重试次数后抛 QdrantStoreError。
"""

import pytest

from src.core.storage.qdrant import QdrantIndexStore
from src.core.storage.qdrant.exceptions import QdrantStoreError
from src.core.storage.qdrant.models import IndexedPoint


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    # 退避睡眠归零：重试逻辑照常计数，但测试不空等。
    async def _instant(_delay):
        return None

    monkeypatch.setattr("src.core.storage.qdrant.qdrant_store.asyncio.sleep", _instant)


class _FlakyClient:
    """retrieve 永远空（点不存在），upsert 前 N 次抛瞬时 502、之后成功。"""

    def __init__(self, *, fail_times: int, error: Exception) -> None:
        self._remaining = fail_times
        self._error = error
        self.upsert_attempts = 0

    async def retrieve(self, **_kwargs):
        return []

    async def upsert(self, **_kwargs):
        self.upsert_attempts += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error
        return None


def _point() -> IndexedPoint:
    return IndexedPoint(
        chunk_id="11111111-1111-1111-1111-111111111111",
        vector=[],
        payload={"doc_id": 1, "set_id": 1, "user_id": 1},
    )


async def test_transient_502_is_retried_then_succeeds():
    client = _FlakyClient(fail_times=1, error=RuntimeError("Unexpected Response: 502 Bad Gateway"))
    store = QdrantIndexStore(client=client)

    await store.ensure_points(points=[_point()])

    # 第 1 次 502、第 2 次成功 → 共 2 次 upsert 调用。
    assert client.upsert_attempts == 2


async def test_non_transient_error_is_not_retried():
    client = _FlakyClient(fail_times=1, error=ValueError("400 Bad Request: invalid payload"))
    store = QdrantIndexStore(client=client)

    with pytest.raises(QdrantStoreError):
        await store.ensure_points(points=[_point()])

    # 非瞬时错误立即透传，只调用 1 次，不浪费退避。
    assert client.upsert_attempts == 1


async def test_persistent_transient_failure_exhausts_retries():
    client = _FlakyClient(fail_times=99, error=RuntimeError("503 Service Unavailable"))
    store = QdrantIndexStore(client=client)

    with pytest.raises(QdrantStoreError):
        await store.ensure_points(points=[_point()])

    # 默认 max_attempts=3 → 共尝试 3 次后放弃。
    assert client.upsert_attempts == 3
