"""注册事务与购物素材集成；存储/签发使用 fake，SQL 在独立 SQLite 中执行。"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.management_auth import AccessClaims
from src.api.management_http import BusinessError
from src.application import datasets, demo_dataset, document_files, identity_users
from src.application.identity_session import AccessTokenIssuer
from src.config import settings


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.removed = []
        self.fail_upload = None

    def upload_bytes(self, bucket, key, content, content_type):
        assert content_type == "text/markdown"
        assert content.decode("utf-8").startswith("# 好邻生活商店")
        self.objects[(bucket, key)] = content
        self.uploads.append(key)
        # 模拟服务端已写入，但调用方没收到确认。
        if self.fail_upload == len(self.uploads):
            raise OSError("private-storage-secret")

    def remove_object(self, bucket, key):
        self.removed.append(key)
        self.objects.pop((bucket, key), None)


class SqliteSession:
    """只翻译 outbox 的 MySQL 时间/幂等插入语法，仍执行真实事务与唯一约束。"""

    def __init__(self, session):
        self.session = session

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "INSERT INTO management_mq_outbox" in sql:
            sql = sql.replace("NOW()", "CURRENT_TIMESTAMP").replace(
                "ON DUPLICATE KEY UPDATE event_key=event_key",
                "ON CONFLICT(event_key) DO NOTHING",
            )
        return await self.session.execute(text(sql), params or {})


@pytest.fixture
async def environment(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    schema = [
        "CREATE TABLE sys_user (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, nickname TEXT, email TEXT UNIQUE, phone TEXT, avatar_url TEXT, role TEXT, status INTEGER, bio TEXT, team TEXT, last_login_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, app_code TEXT DEFAULT 'tolink')",
        "CREATE TABLE user_login_event (id INTEGER PRIMARY KEY, user_id INTEGER, login_source TEXT, created_at DATETIME, ip TEXT, user_agent TEXT)",
        "CREATE TABLE llm_model_config (id INTEGER PRIMARY KEY, scope TEXT, owner_user_id INTEGER, capability TEXT, is_active INTEGER)",
        "CREATE TABLE llm_capability_default (scope TEXT, owner_user_id INTEGER, capability TEXT, config_id INTEGER, UNIQUE(scope,owner_user_id,capability))",
        "CREATE TABLE dataset (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, description TEXT, status TEXT, is_deleted INTEGER, deleted_seq INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,name,deleted_seq))",
        "CREATE TABLE dataset_parse_config (user_id INTEGER, dataset_id INTEGER, chunking_config TEXT, enhancement_config TEXT, pdf_config TEXT, recall_config TEXT, sparse_embedding_config_id INTEGER, dense_embedding_config_id INTEGER, is_active INTEGER, UNIQUE(user_id,dataset_id))",
        "CREATE TABLE document_original_file (id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id INTEGER, user_id INTEGER, original_filename TEXT, file_suffix TEXT, file_size INTEGER, content_type TEXT, bucket_name TEXT, object_key TEXT, file_url TEXT, upload_status TEXT, is_upload_success INTEGER, is_deleted INTEGER, deleted_seq INTEGER, UNIQUE(user_id,dataset_id,original_filename,deleted_seq))",
        "CREATE TABLE document_parse_file (id INTEGER PRIMARY KEY AUTOINCREMENT, document_original_file_id INTEGER UNIQUE, dataset_id INTEGER, user_id INTEGER, original_filename TEXT, parse_count INTEGER, latest_parse_task_id TEXT)",
        "CREATE TABLE management_mq_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE, topic TEXT, message_body TEXT, message_key TEXT, status TEXT, attempt_count INTEGER, next_attempt_at DATETIME)",
    ]
    async with engine.begin() as conn:
        for statement in schema:
            await conn.execute(text(statement))
        for config_id, capability in enumerate(("EMBEDDING", "SPARSE_EMBEDDING", "CHAT"), 101):
            await conn.execute(
                text("INSERT INTO llm_model_config VALUES(:id,'SYSTEM',0,:cap,1)"),
                {"id": config_id, "cap": capability},
            )

    @asynccontextmanager
    async def read_context():
        async with factory() as session:
            yield SqliteSession(session)

    @asynccontextmanager
    async def write_context():
        async with factory() as session:
            async with session.begin():
                yield SqliteSession(session)

    monkeypatch.setattr(demo_dataset, "get_db_context", read_context)
    monkeypatch.setattr(identity_users, "get_db_context", read_context)
    monkeypatch.setattr(identity_users, "write_transaction", write_context)
    for key in ("DEMO_DATASET_ENABLED", "B4_DATASET_WRITES_ENABLED", "B5_FILE_WRITES_ENABLED"):
        monkeypatch.setattr(settings, key, True)
    for key in demo_dataset._CONFIG_FIELDS.values():
        monkeypatch.setattr(settings, key, None)
    monkeypatch.setattr(settings, "B5_INTERNAL_FILE_BASE_URL", "http://python.internal")
    monkeypatch.setattr(settings, "B5_INTERNAL_FILE_SERVICE_TOKEN", "test-only-service-token")
    storage = FakeStorage()
    monkeypatch.setattr(demo_dataset.StorageFactory, "get_storage", lambda **_: storage)
    monkeypatch.setattr(identity_users, "audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(demo_dataset, "audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(AccessTokenIssuer, "from_settings", classmethod(lambda cls: object()))
    revoked = []

    class Sessions:
        async def revoke(self, token, claims):
            revoked.append(claims.user_id)

    users = identity_users.IdentityUsers(Sessions())

    async def issue(user_id, role):
        expiry = int(datetime.now(timezone.utc).timestamp()) + 600
        return {"userId": user_id, "accessToken": f"test-{user_id}"}, AccessClaims(
            user_id, "test-jti", expiry
        )

    monkeypatch.setattr(users, "_issue", issue)
    yield SimpleNamespace(
        factory=factory,
        read=read_context,
        write=write_context,
        users=users,
        storage=storage,
        revoked=revoked,
        issue=issue,
    )
    await engine.dispose()


async def rows(env, table):
    async with env.factory() as session:
        return (await session.execute(text(f"SELECT * FROM {table}"))).mappings().all()


@pytest.mark.asyncio
async def test_registration_creates_private_files_defaults_and_durable_parse_tasks(environment):
    env = environment
    result = await env.users.register("shopper-one", "password", "one@example.test")
    user_id = result["userId"]
    dataset = (await rows(env, "dataset"))[0]
    assert dataset["user_id"] == user_id and dataset["name"] == "购物演示数据集"
    configs = (await rows(env, "dataset_parse_config"))[0]
    assert configs["dense_embedding_config_id"] == 101
    assert configs["sparse_embedding_config_id"] == 102
    assert not any(json.loads(configs["enhancement_config"]).values())
    assert json.loads(configs["recall_config"])["recall_enabled_sources"] == [
        "bm25",
        "sparse",
        "dense",
    ]
    defaults = await rows(env, "llm_capability_default")
    assert {(r["capability"], r["config_id"]) for r in defaults} == {
        ("EMBEDDING", 101),
        ("SPARSE_EMBEDDING", 102),
        ("CHAT", 103),
    }
    assert all(r["scope"] == "USER" and r["owner_user_id"] == user_id for r in defaults)
    original_files = await rows(env, "document_original_file")
    assert {f["original_filename"] for f in original_files} == set(demo_dataset.DOCUMENT_NAMES)
    assert len(env.storage.objects) == len(original_files) == 3
    parse_files = {
        r["document_original_file_id"]: r for r in await rows(env, "document_parse_file")
    }
    events = await rows(env, "management_mq_outbox")
    assert len(events) == 3 and len({e["event_key"] for e in events}) == 3
    for event in events:
        payload = json.loads(event["message_body"])
        original = next(f for f in original_files if f["id"] == payload["original_file_id"])
        parse_file = parse_files[original["id"]]
        assert payload["document_parse_file_id"] == parse_file["id"]
        assert payload["task_id"] == parse_file["latest_parse_task_id"]
        assert event["event_key"] == f"parse:{payload['task_id']}"
        assert (
            event["status"] == "PENDING" and event["topic"] == demo_dataset.ParseTaskMessage.MQ_NAME
        )
        assert event["message_key"] == payload["file_type"] == "md"
        assert payload["trigger_mode"] == "upload_auto" and not payload["is_retry"]
        assert payload["user_id"] == original["user_id"] == user_id
        assert payload["dataset_id"] == original["dataset_id"] == dataset["id"]
        assert payload["source_object_key"] == original["object_key"]
        content = env.storage.objects[(original["bucket_name"], original["object_key"])]
        assert len(content) == original["file_size"]
        assert (
            original["file_url"]
            == f"http://python.internal/api/v1/internal/files/{original['id']}/content"
        )
        assert original["upload_status"] == "success" and original["is_upload_success"] == 1
        assert payload["md_object_key"].startswith(
            f"parsed/user-{user_id}/dataset-{dataset['id']}/"
        )


@pytest.mark.asyncio
async def test_two_users_cannot_access_or_delete_each_others_copy(environment):
    env = environment
    first = await env.users.register("first-user", "password", "first@example.test")
    second = await env.users.register("second-user", "password", "second@example.test")
    original_files = await rows(env, "document_original_file")
    assert len(original_files) == len(env.storage.objects) == 6
    assert len({f["object_key"] for f in original_files}) == 6
    assert len({f["dataset_id"] for f in original_files}) == 2
    first_file = next(f for f in original_files if f["user_id"] == first["userId"])
    async with env.read() as db:
        assert (await datasets.owned_dataset(db, first["userId"], first_file["dataset_id"]))[
            "id"
        ] == first_file["dataset_id"]
        with pytest.raises(BusinessError) as forbidden_dataset:
            await datasets.owned_dataset(db, second["userId"], first_file["dataset_id"])
        assert forbidden_dataset.value.http_status == 404
        with pytest.raises(BusinessError) as forbidden_file:
            await document_files.owned_file(db, second["userId"], first_file["id"])
        assert forbidden_file.value.http_status == 404
    # 普通归属字段决定可修改/删除范围，没有引入只读或共享例外。
    async with env.write() as db:
        result = await db.execute(
            text("UPDATE dataset SET is_deleted=1 WHERE id=:id AND user_id=:uid"),
            {"id": first_file["dataset_id"], "uid": second["userId"]},
        )
        assert result.rowcount == 0
        await db.execute(
            text("UPDATE dataset SET name='我的资料' WHERE id=:id AND user_id=:uid"),
            {"id": first_file["dataset_id"], "uid": first["userId"]},
        )
    assert (await rows(env, "dataset"))[0]["name"] == "我的资料"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["session", "bind", "cancel"])
async def test_failed_registration_rolls_back_all_rows_and_removes_objects(
    environment, monkeypatch, failure
):
    env = environment
    if failure == "bind":

        async def broken_bind(db, user_id):
            raise RuntimeError("db failure")

        monkeypatch.setattr(
            demo_dataset.DemoDatasetSeed, "bind", lambda self, db, uid: broken_bind(db, uid)
        )
    else:

        async def broken_issue(user_id, role):
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise ConnectionError("session failure")

        monkeypatch.setattr(env.users, "_issue", broken_issue)
    expected = asyncio.CancelledError if failure == "cancel" else Exception
    with pytest.raises(expected):
        await env.users.register("failed-user", "password", "failed@example.test")
    for table in (
        "sys_user",
        "dataset",
        "document_original_file",
        "document_parse_file",
        "dataset_parse_config",
        "llm_capability_default",
        "management_mq_outbox",
    ):
        assert not await rows(env, table)
    assert not env.storage.objects and len(env.storage.removed) == 3


@pytest.mark.asyncio
async def test_post_issue_failure_revokes_registered_session(environment, monkeypatch):
    env = environment

    @asynccontextmanager
    async def failed_commit():
        async with env.factory() as session:
            async with session.begin():
                yield SqliteSession(session)
                raise RuntimeError("commit failed")

    monkeypatch.setattr(identity_users, "write_transaction", failed_commit)
    with pytest.raises(RuntimeError):
        await env.users.register("failed-user", "password", "failed@example.test")
    assert len(env.revoked) == 1 and not await rows(env, "sys_user")
    assert not env.storage.objects and not await rows(env, "management_mq_outbox")


@pytest.mark.asyncio
async def test_partial_storage_write_is_cleaned_without_leaking_error(environment):
    env = environment
    env.storage.fail_upload = 2
    with pytest.raises(BusinessError) as failed:
        await env.users.register("failed-user", "password", "failed@example.test")
    assert failed.value.http_status == 503 and "private-storage-secret" not in failed.value.message
    assert len(env.storage.removed) == 2 and not env.storage.objects
    assert not await rows(env, "sys_user")


@pytest.mark.asyncio
async def test_cancellation_waits_for_storage_thread_before_cleanup(environment):
    env = environment
    started, release = threading.Event(), threading.Event()
    original = env.storage.upload_bytes

    def slow_upload(*args):
        started.set()
        assert release.wait(timeout=5)
        original(*args)

    env.storage.upload_bytes = slow_upload
    task = asyncio.create_task(demo_dataset.DemoDatasetSeed.prepare())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not env.storage.removed
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(env.storage.removed) == 1 and not env.storage.objects


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["missing", "multiple", "inactive", "user-owned", "wrong-capability", "wrong-system-owner"],
)
async def test_invalid_platform_models_reject_registration_before_storage(
    environment, monkeypatch, case
):
    env = environment
    async with env.factory.begin() as db:
        if case == "missing":
            await db.execute(text("DELETE FROM llm_model_config WHERE id=101"))
        elif case == "multiple":
            await db.execute(
                text("INSERT INTO llm_model_config VALUES(104,'SYSTEM',0,'EMBEDDING',1)")
            )
        else:
            changes = {
                "inactive": "is_active=0",
                "user-owned": "scope='USER',owner_user_id=9",
                "wrong-capability": "capability='CHAT'",
                "wrong-system-owner": "owner_user_id=9",
            }
            await db.execute(text(f"UPDATE llm_model_config SET {changes[case]} WHERE id=101"))
            monkeypatch.setattr(settings, "DEMO_DATASET_DENSE_CONFIG_ID", 101)
    with pytest.raises(BusinessError) as failed:
        await env.users.register("failed-user", "password", "failed@example.test")
    assert failed.value.http_status == 503
    assert not env.storage.uploads and not await rows(env, "sys_user")


@pytest.mark.asyncio
async def test_explicit_model_selection_resolves_multiple_platform_models(environment, monkeypatch):
    env = environment
    async with env.factory.begin() as db:
        await db.execute(text("INSERT INTO llm_model_config VALUES(104,'SYSTEM',0,'EMBEDDING',1)"))
    monkeypatch.setattr(settings, "DEMO_DATASET_DENSE_CONFIG_ID", 104)
    await env.users.register("shopper-user", "password", "shopper@example.test")
    assert (await rows(env, "dataset_parse_config"))[0]["dense_embedding_config_id"] == 104


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "disabled", ["DEMO_DATASET_ENABLED", "B4_DATASET_WRITES_ENABLED", "B5_FILE_WRITES_ENABLED"]
)
async def test_disabled_gate_preserves_registration_without_demo(
    environment, monkeypatch, disabled
):
    env = environment
    monkeypatch.setattr(settings, disabled, False)
    await env.users.register("plain-user", "password", "plain@example.test")
    assert len(await rows(env, "sys_user")) == 1
    assert not await rows(env, "dataset") and not env.storage.uploads


@pytest.mark.asyncio
async def test_duplicate_registration_does_not_damage_existing_demo(environment):
    env = environment
    await env.users.register("shopper-user", "password", "shopper@example.test")
    existing_objects = dict(env.storage.objects)
    with pytest.raises(BusinessError) as failed:
        await env.users.register("shopper-user", "password", "another@example.test")
    assert failed.value.code == 20006
    assert len(await rows(env, "sys_user")) == len(await rows(env, "dataset")) == 1
    assert len(await rows(env, "management_mq_outbox")) == 3
    assert env.storage.objects == existing_objects


@pytest.mark.asyncio
async def test_login_does_not_recreate_deleted_demo(environment, monkeypatch):
    env = environment
    result = await env.users.register("shopper-user", "password", "shopper@example.test")
    async with env.factory.begin() as db:
        await db.execute(
            text("UPDATE dataset SET is_deleted=1 WHERE user_id=:uid"), {"uid": result["userId"]}
        )

    async def must_not_prepare():
        raise AssertionError("login must not seed demo")

    monkeypatch.setattr(demo_dataset.DemoDatasetSeed, "prepare", must_not_prepare)
    assert (await env.users.login("shopper-user", "password"))["userId"] == result["userId"]
    assert (await rows(env, "dataset"))[0]["is_deleted"] == 1
    assert len(env.storage.objects) == 3


@pytest.mark.asyncio
async def test_demo_sql_error_is_not_misreported_as_duplicate_email(environment, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    env = environment
    original_bind = demo_dataset.DemoDatasetSeed._bind

    async def broken_bind(self, db, user_id):
        await original_bind(self, db, user_id)
        raise IntegrityError("demo constraint", {}, RuntimeError("demo failure"))

    monkeypatch.setattr(demo_dataset.DemoDatasetSeed, "_bind", broken_bind)
    with pytest.raises(BusinessError) as failed:
        await env.users.register("failed-user", "password", "failed@example.test")
    assert failed.value.code == failed.value.http_status == 503
    assert not await rows(env, "sys_user") and not await rows(env, "management_mq_outbox")
    assert not env.storage.objects
