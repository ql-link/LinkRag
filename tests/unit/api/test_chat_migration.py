"""B6 cutover and replay behavior without external database or MQ."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from src.api.management_auth import require_login
from src.api.routes import chat
from src.api.routes.chat import BatchChunkDetailRequest, CreateConversationRequest
from src.application.chat_service import (
    _page,
    create_conversation,
    delete_conversation,
    list_conversations,
    list_messages,
    persist_chat_turn,
    update_conversation,
)
from src.core.mq.messages.chat_turn import ChatTurnMessage
from src.database import get_db
from src.models.db_models import ChatConversationDB, ChatMessageDB


@compiles(BigInteger, "sqlite")
def _sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(MEDIUMTEXT, "sqlite")
def _sqlite_mediumtext(_type, _compiler, **_kwargs):
    return "TEXT"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self):
        self.conversation = SimpleNamespace(
            id=9,
            user_id=3,
            title="新对话",
            last_config_id=None,
            last_model_name=None,
            updated_at=datetime.now(),
        )
        self.message = None
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        if self.calls % 2:
            return _Result(
                self.conversation if self.conversation.user_id == 3 else None
            )
        return _Result(self.message)

    def add(self, message):
        self.message = message

    async def flush(self):
        return None


def _payload(status="GENERATING", title=None, answer=""):
    return ChatTurnMessage.build(
        conversation_id=9,
        request_id="request-1",
        turn_id="turn-1",
        user_id=3,
        query="问题",
        answer=answer,
        config_id=7,
        status=status,
        title=title,
    ).get_payload()


@pytest.mark.asyncio
async def test_chat_turn_replay_and_terminal_state():
    db = _Session()
    assert await persist_chat_turn(db, _payload())
    assert db.message.status == "GENERATING"
    assert await persist_chat_turn(db, _payload("COMPLETED", "生成标题", "答案"))
    assert db.message.status == "COMPLETED"
    assert db.message.answer == "答案"
    assert db.conversation.title == "生成标题"
    assert await persist_chat_turn(db, _payload("GENERATING"))
    assert db.message.status == "COMPLETED"
    assert db.message.answer == "答案"


@pytest.mark.asyncio
async def test_chat_turn_owner_and_manual_title_are_preserved():
    db = _Session()
    db.conversation.user_id = 4
    assert not await persist_chat_turn(db, _payload("COMPLETED", "标题"))
    assert db.message is None
    db.conversation.user_id = 3
    db.calls = 0
    db.conversation.title = "用户标题"
    assert await persist_chat_turn(db, _payload("COMPLETED", "模型标题"))
    assert db.conversation.title == "用户标题"


def test_java_response_page_shape_and_request_aliases():
    assert _page([], 21, 2, 20) == {
        "items": [],
        "total": 21,
        "page": 2,
        "pageSize": 20,
        "totalPages": 2,
    }
    assert CreateConversationRequest.model_validate({"datasetId": 1}).datasetId == 1
    assert BatchChunkDetailRequest.model_validate({"chunkIds": ["a"]}).chunkIds == ["a"]


@pytest.mark.asyncio
async def test_conversation_route_keeps_java_response_shape(monkeypatch):
    app = FastAPI()
    app.include_router(chat.router)
    db = SimpleNamespace()

    async def fake_db():
        yield db

    app.dependency_overrides[require_login] = lambda: SimpleNamespace(user_id=3)
    app.dependency_overrides[get_db] = fake_db

    async def fake_list(_db, user_id, page, page_size):
        assert (_db, user_id, page, page_size) == (db, 3, 2, 20)
        return _page([], 21, page, page_size)

    monkeypatch.setattr(chat.chat_service, "list_conversations", fake_list)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/chat/conversations?page=2")
    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "success",
        "data": {"items": [], "total": 21, "page": 2, "pageSize": 20, "totalPages": 2},
    }


@pytest.mark.asyncio
async def test_chat_lifecycle_against_sql_tables():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                ChatConversationDB.metadata.create_all,
                tables=[ChatConversationDB.__table__, ChatMessageDB.__table__],
            )
            await conn.execute(
                text("CREATE TABLE dataset (id INTEGER PRIMARY KEY, user_id INTEGER)")
            )
            await conn.execute(text("INSERT INTO dataset (id, user_id) VALUES (5, 3)"))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            row = await create_conversation(db, 3, 5, None, None)
            assert row["title"] == "新对话"
            assert (await list_conversations(db, 3, 1, 20))["total"] == 1
            payload = ChatTurnMessage.build(
                conversation_id=row["id"],
                request_id="request-1",
                turn_id="turn-1",
                user_id=3,
                query="问题",
                answer="答案",
                config_id=7,
                status="COMPLETED",
                title="自动标题",
            ).get_payload()
            assert await persist_chat_turn(db, payload)
            assert await persist_chat_turn(db, payload)
            messages = await list_messages(db, 3, row["id"], 1, 50)
            assert messages["total"] == 1
            assert messages["items"][0]["answer"] == "答案"
            updated = await update_conversation(db, 3, row["id"], "用户标题", True)
            assert updated["isPinned"] and updated["title"] == "用户标题"
            await delete_conversation(db, 3, row["id"])
            assert (await list_conversations(db, 3, 1, 20))["total"] == 0
            await db.commit()
    finally:
        await engine.dispose()
