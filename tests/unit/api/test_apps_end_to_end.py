"""``/api/v1/apps/*`` 端到端：真实凭证 → 影子用户 → 默认资料库 → 召回，全程走真实代码与共享 SQLite。

只替换召回 pipeline（向量 / BM25 外部依赖）、数据集配置缓存失效（Redis）与召回范围解析
（MySQL collation，替身保持同语义）；
身份、数据集、文件归属、正文回读均为生产实现，验证两个外部用户之间、以及与 toLink 用户之间的隔离。
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import src.database as database
from src.api.routes import apps
from src.application import app_identity, datasets
from src.config import settings
from src.models.chunk_record import ChunkRecordDB

_SCHEMA = [
    "CREATE TABLE sys_user (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, "
    "password_hash TEXT NOT NULL, nickname TEXT, email TEXT UNIQUE, role TEXT, status INTEGER, "
    "app_code TEXT NOT NULL DEFAULT 'tolink')",
    "CREATE TABLE app_client (id INTEGER PRIMARY KEY AUTOINCREMENT, app_code TEXT UNIQUE, "
    "client_id TEXT UNIQUE, secret_hash TEXT, status TEXT DEFAULT 'ACTIVE', "
    "default_dense_config_id INTEGER, default_sparse_config_id INTEGER, description TEXT)",
    "CREATE TABLE app_user_binding (id INTEGER PRIMARY KEY AUTOINCREMENT, app_code TEXT, "
    "external_user_id TEXT, user_id INTEGER UNIQUE, default_dataset_id INTEGER, "
    "UNIQUE (app_code, external_user_id))",
    "CREATE TABLE llm_model_config (id INTEGER PRIMARY KEY, scope TEXT, owner_user_id INTEGER, "
    "capability TEXT, is_active INTEGER)",
    "CREATE TABLE dataset (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, "
    "description TEXT, status TEXT, is_deleted INTEGER DEFAULT 0, deleted_seq INTEGER DEFAULT 0, "
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
    "UNIQUE (user_id, name, deleted_seq))",
    "CREATE TABLE dataset_parse_config (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
    "dataset_id INTEGER, chunking_config TEXT, enhancement_config TEXT, pdf_config TEXT, "
    "recall_config TEXT, sparse_embedding_config_id INTEGER, dense_embedding_config_id INTEGER, "
    "is_active INTEGER)",
    "CREATE TABLE document_original_file (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "dataset_id INTEGER, user_id INTEGER, original_filename TEXT, file_suffix TEXT, "
    "file_size INTEGER, content_type TEXT, bucket_name TEXT, object_key TEXT, file_url TEXT, "
    "upload_status TEXT, is_upload_success INTEGER DEFAULT 0, failure_reason TEXT, "
    "is_deleted INTEGER DEFAULT 0, deleted_seq INTEGER DEFAULT 0, "
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
    "UNIQUE (dataset_id, user_id, original_filename, file_suffix, deleted_seq))",
]


@pytest.fixture
async def env(monkeypatch, tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'apps_e2e.db'}", connect_args={"timeout": 5}
    )

    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def _strip_for_update(conn, cursor, statement, parameters, context, executemany):
        # SQLite 不支持行锁子句；并发语义由唯一键兜底，这里只验证业务结果。
        return statement.replace(" FOR UPDATE", ""), parameters

    async with engine.begin() as conn:
        for ddl in _SCHEMA:
            await conn.execute(text(ddl))
        # chunk 表按 ORM 建，保证正文回读查询的列集合与生产一致。
        await conn.run_sync(ChunkRecordDB.__table__.create)
        await conn.execute(
            text(
                "INSERT INTO llm_model_config VALUES (1,'SYSTEM',0,'EMBEDDING',1),"
                "(2,'SYSTEM',0,'SPARSE_EMBEDDING',1)"
            )
        )
        # toLink 存量用户及其数据：任何接入应用调用都不应触达。
        await conn.execute(
            text(
                "INSERT INTO sys_user (id,username,password_hash,role,status) "
                "VALUES (1,'tolink-user','x','USER',1)"
            )
        )
        await conn.execute(
            text("INSERT INTO dataset (id,user_id,name,status) VALUES (500,1,'资料库','ACTIVE')")
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "_async_session_factory", factory)
    for flag in (
        "APPS_API_ENABLED",
        "B4_DATASET_WRITES_ENABLED",
        "B5_FILE_WRITES_ENABLED",
        "B5_DELETE_WRITES_ENABLED",
    ):
        monkeypatch.setattr(settings, flag, True)

    async def no_evict(dataset_id: int) -> None:
        return None

    monkeypatch.setattr(datasets, "_evict", no_evict)
    app_identity.credential_cache.clear()

    client_id, secret = await app_identity.create_app_client(
        "linkresume", dense_config_id=1, sparse_config_id=2
    )
    pipeline = SimpleNamespace(hits=[])

    async def execution(user_id, dataset_ids):
        from src.core.dataset_config.models import RecallConfig

        return RecallConfig(), {}

    async def run(_pipeline, req, request_id):
        pipeline.last_request = req
        # 模拟向量层按 user_id / set_id / doc_id 过滤后的结果。
        return {
            "hits": [
                h
                for h in pipeline.hits
                if h["dataset_id"] in req.dataset_ids
                and (not req.doc_ids or h["doc_id"] in req.doc_ids)
            ],
            "failed_sources": [],
        }

    async def scope(db, *, user_id, requested_dataset_ids):
        # 与 resolve_user_dataset_scope 同语义（其 MySQL collation 在 SQLite 不可用）：
        # 显式范围必须完整命中本人 ACTIVE 未删除数据集，否则 403。
        from src.application.recall_errors import RecallApiError

        owned = sorted(
            int(r[0])
            for r in await db.execute(
                text(
                    "SELECT id FROM dataset WHERE user_id=:uid AND status='ACTIVE' AND is_deleted=0"
                ),
                {"uid": user_id},
            )
        )
        requested = set(requested_dataset_ids or ())
        if requested and not requested <= set(owned):
            raise RecallApiError(403, "RECALL_SCOPE_FORBIDDEN", "forbidden")
        return sorted(requested) if requested else owned

    monkeypatch.setattr(apps, "resolve_user_dataset_scope", scope)
    monkeypatch.setattr(apps, "aresolve_recall_execution", execution)
    monkeypatch.setattr(apps, "run_recall_json", run)

    app = FastAPI()
    app.include_router(apps.router)
    submitted: list = []
    # 只记录上传任务，不真正写 MinIO / 发 MQ。
    app.state.document_upload_executor = SimpleNamespace(submit=submitted.append)
    monkeypatch.setattr(settings, "PARSE_TEMP_DIR", str(tmp_path / "parse"))
    app.dependency_overrides[apps.get_recall_pipeline] = lambda: object()
    app.dependency_overrides[apps.get_db] = _db
    yield SimpleNamespace(
        app=app,
        factory=factory,
        token=f"{client_id}.{secret}",
        pipeline=pipeline,
        submitted=submitted,
    )
    app_identity.credential_cache.clear()
    await engine.dispose()


async def _db():
    async with database.get_db_context() as session:
        yield session


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _headers(env, user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {env.token}", "X-App-User-Id": user}


async def _seed_file(env, file_id: int, dataset_id: int, user_id: int, chunk: str) -> None:
    async with env.factory() as session:
        await session.execute(
            text(
                "INSERT INTO document_original_file (id,dataset_id,user_id,original_filename,"
                "file_suffix,file_size,upload_status) VALUES (:fid,:did,:uid,:name,'pdf',10,'success')"
            ),
            {
                "fid": file_id,
                "did": dataset_id,
                "uid": user_id,
                "name": f"f{file_id}.pdf",
            },
        )
        session.add(
            ChunkRecordDB(
                id=file_id,  # BIGINT 主键在 SQLite 不自增
                chunk_id=chunk,
                doc_id=file_id,
                set_id=dataset_id,
                user_id=user_id,
                content=chunk,
                content_hash=chunk,
                chunk_type="text",
                lifecycle_status="ACTIVE",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_two_external_users_are_isolated_end_to_end(env):
    async with _client(env.app) as client:
        a = await client.put("/api/v1/apps/datasets/default", headers=_headers(env, "1001"))
        b = await client.put("/api/v1/apps/datasets/default", headers=_headers(env, "1002"))
        again = await client.put("/api/v1/apps/datasets/default", headers=_headers(env, "1001"))
        assert a.status_code == b.status_code == again.status_code == 200
        ds_a, ds_b = a.json()["data"]["id"], b.json()["data"]["id"]
        # 幂等；两人各自一个库；都不是 toLink 用户同名库 500。
        assert again.json()["data"]["id"] == ds_a
        assert len({ds_a, ds_b, 500}) == 3

        async with env.factory() as session:
            users = dict(
                (
                    await session.execute(
                        text(
                            "SELECT b.external_user_id,b.user_id FROM app_user_binding b "
                            "ORDER BY b.external_user_id"
                        )
                    )
                ).all()
            )
            owners = dict((await session.execute(text("SELECT id,user_id FROM dataset"))).all())
        uid_a, uid_b = users["1001"], users["1002"]
        assert owners[ds_a] == uid_a and owners[ds_b] == uid_b and 1 not in (uid_a, uid_b)

        await _seed_file(env, 11, ds_a, uid_a, "a-chunk")
        await _seed_file(env, 21, ds_b, uid_b, "b-chunk")
        await _seed_file(env, 31, 500, 1, "tolink-chunk")
        # 召回层即便（错误地）返回了他人的命中，正文回读也按影子用户过滤掉。
        env.pipeline.hits = [
            {
                "chunk_id": c,
                "doc_id": f,
                "dataset_id": d,
                "fused_score": 0.5,
                "scores": {},
            }
            for c, f, d in (
                ("a-chunk", 11, ds_a),
                ("b-chunk", 21, ds_b),
                ("tolink-chunk", 31, 500),
            )
        ]
        env.pipeline.hits.append(
            {
                "chunk_id": "b-chunk",
                "doc_id": 21,
                "dataset_id": ds_a,
                "fused_score": 0.4,
                "scores": {},
            }
        )

        recall_a = await client.post(
            "/api/v1/apps/recall", headers=_headers(env, "1001"), json={"query": "经历"}
        )
        assert recall_a.status_code == 200
        assert [h["content"] for h in recall_a.json()["data"]["hits"]] == ["a-chunk"]
        assert env.pipeline.last_request.user_id == uid_a
        assert env.pipeline.last_request.dataset_ids == [ds_a]

        # 他人文件 / 他人数据集 / toLink 数据集：整体 403。
        for body in (
            {"query": "q", "fileIds": [21]},
            {"query": "q", "fileIds": [31]},
            {"query": "q", "datasetIds": [ds_b]},
            {"query": "q", "datasetIds": [500]},
        ):
            denied = await client.post(
                "/api/v1/apps/recall", headers=_headers(env, "1001"), json=body
            )
            assert denied.status_code == 403, body

        # 文件读取同样按影子用户隔离。
        foreign = await client.get("/api/v1/apps/files/21", headers=_headers(env, "1001"))
        assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_wrong_or_rotated_credential_rejected_end_to_end(env):
    async with _client(env.app) as client:
        bad = await client.put(
            "/api/v1/apps/datasets/default",
            headers={"Authorization": f"Bearer {env.token}x", "X-App-User-Id": "1001"},
        )
        assert bad.status_code == 401
        assert bad.json()["data"]["reason"] == "APP_CREDENTIAL_INVALID"

        await app_identity.set_app_status("linkresume", "DISABLED")
        app_identity.credential_cache.clear()  # 生产上最长 60 秒后生效
        disabled = await client.put("/api/v1/apps/datasets/default", headers=_headers(env, "1001"))
        assert disabled.status_code == 403
        assert disabled.json()["data"]["reason"] == "APP_DISABLED"


@pytest.mark.asyncio
async def test_same_name_upload_is_renamed_and_web_still_rejects(env):
    """接入应用重名上传自动改名为 ``name (n).ext``；同一数据集走 Web 语义仍拒绝重名。"""

    from src.application.document_uploads import upload
    from src.api.management_http import BusinessError
    from starlette.datastructures import UploadFile
    import io

    names = []
    async with _client(env.app) as client:
        for _ in range(3):
            response = await client.post(
                "/api/v1/apps/files",
                headers=_headers(env, "1001"),
                files={"file": ("简历.pdf", b"%PDF-1.4 x", "application/pdf")},
            )
            assert response.status_code == 200, response.text
            names.append(response.json()["data"]["originalFilename"])
        # 另一个外部用户用同名文件不受影响（各自资料库）。
        other = await client.post(
            "/api/v1/apps/files",
            headers=_headers(env, "1002"),
            files={"file": ("简历.pdf", b"%PDF-1.4 y", "application/pdf")},
        )
    assert names == ["简历.pdf", "简历 (2).pdf", "简历 (3).pdf"]
    assert other.json()["data"]["originalFilename"] == "简历.pdf"
    # 上传任务使用改名后的文件名（决定对象存储 key 与解析文件名）。
    assert [job.filename for job in env.submitted[:3]] == names

    dataset_id = other.json()["data"]["datasetId"]
    async with env.factory() as session:
        uid_b = (
            await session.execute(
                text("SELECT user_id FROM app_user_binding WHERE external_user_id='1002'")
            )
        ).scalar_one()
    with pytest.raises(BusinessError) as rejected:
        await upload(
            uid_b,
            dataset_id,
            UploadFile(io.BytesIO(b"%PDF-1.4 z"), filename="简历.pdf"),
            parse_immediately=False,
            executor=env.app.state.document_upload_executor,
        )
    assert rejected.value.code == 400


@pytest.mark.parametrize(
    ("name", "index", "expected"),
    [
        ("简历.pdf", 2, "简历 (2).pdf"),
        ("a.b.docx", 3, "a.b (3).docx"),
        ("README", 2, "README (2)"),
    ],
)
def test_renamed_keeps_suffix(name, index, expected):
    from src.application.document_uploads import _renamed

    assert _renamed(name, index) == expected


def test_renamed_stays_within_column_limit():
    from src.application.document_uploads import _renamed

    renamed = _renamed("x" * 251 + ".pdf", 12)
    assert len(renamed) == 255 and renamed.endswith(" (12).pdf")


@pytest.mark.asyncio
async def test_failed_same_name_upload_is_reused_not_renamed(env):
    """同名记录上次上传失败：复用该记录重传，不产生 ``(2)``。"""

    async with _client(env.app) as client:
        first = await client.post(
            "/api/v1/apps/files",
            headers=_headers(env, "1001"),
            files={"file": ("简历.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        file_id = first.json()["data"]["id"]
        async with env.factory() as session:
            await session.execute(
                text("UPDATE document_original_file SET upload_status='failed' WHERE id=:id"),
                {"id": file_id},
            )
            await session.commit()
        retry = await client.post(
            "/api/v1/apps/files",
            headers=_headers(env, "1001"),
            files={"file": ("简历.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
    assert retry.json()["data"]["id"] == file_id
    assert retry.json()["data"]["originalFilename"] == "简历.pdf"


@pytest.mark.asyncio
async def test_concurrent_same_name_uploads_get_distinct_names(env):
    """并发同名上传：唯一键兜底 + 重试，最终每个文件名各不相同。"""

    import asyncio

    async with _client(env.app) as client:
        await client.put("/api/v1/apps/datasets/default", headers=_headers(env, "1001"))

        async def send():
            return await client.post(
                "/api/v1/apps/files",
                headers=_headers(env, "1001"),
                files={"file": ("简历.pdf", b"%PDF-1.4 x", "application/pdf")},
            )

        responses = await asyncio.gather(*(send() for _ in range(4)))
    assert [r.status_code for r in responses] == [200] * 4
    names = {r.json()["data"]["originalFilename"] for r in responses}
    assert names == {"简历.pdf", "简历 (2).pdf", "简历 (3).pdf", "简历 (4).pdf"}
