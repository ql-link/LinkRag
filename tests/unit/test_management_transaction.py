import pytest

from src import database


class FakeSession:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_):
        self.events.append("closed")

    def begin(self):
        session = self

        class Transaction:
            async def __aenter__(self):
                session.events.append("begin")

            async def __aexit__(self, exc_type, *_):
                session.events.append("rollback" if exc_type else "commit")

        return Transaction()


@pytest.mark.asyncio
async def test_write_transaction_commits_before_side_effect(monkeypatch):
    events = []
    monkeypatch.setattr(database, "get_async_session_factory", lambda: lambda: FakeSession(events))
    async with database.write_transaction():
        events.append("db-write")
    events.append("invalidate-cache")
    assert events == ["begin", "db-write", "commit", "closed", "invalidate-cache"]


@pytest.mark.asyncio
async def test_write_transaction_rolls_back_on_business_or_external_failure(
    monkeypatch,
):
    events = []
    monkeypatch.setattr(database, "get_async_session_factory", lambda: lambda: FakeSession(events))
    with pytest.raises(ValueError):
        async with database.write_transaction():
            events.append("db-write")
            raise ValueError("business failure")
    assert events == ["begin", "db-write", "rollback", "closed"]

    events.clear()
    with pytest.raises(OSError):
        async with database.write_transaction():
            raise OSError("external operation failed")
    assert events == ["begin", "rollback", "closed"]
