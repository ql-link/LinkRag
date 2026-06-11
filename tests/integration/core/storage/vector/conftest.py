from __future__ import annotations

import pytest


class StubTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StubSession:
    def begin(self) -> StubTransaction:
        return StubTransaction()

    async def close(self) -> None:
        return None


class StubSessionFactory:
    def __init__(self, session: StubSession) -> None:
        self._session = session

    def __call__(self) -> "StubSessionFactory":
        return self

    async def __aenter__(self) -> StubSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture
def mock_session() -> StubSession:
    return StubSession()


@pytest.fixture
def mock_session_factory(mock_session: StubSession) -> StubSessionFactory:
    return StubSessionFactory(mock_session)
