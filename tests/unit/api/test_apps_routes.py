"""``/api/v1/apps/*`` 路由：鉴权边界、默认资料库、上传、召回范围与跨用户隔离。

应用身份解析与 application 层函数以替身注入，断言路由只以影子 ``user_id`` 调用下游，
且写入开关 / 文件归属 / 召回范围按方案 BR4–BR8 生效。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.api import app_auth
from src.api.java_access_auth import AuthContext, verify_user_token
from src.api.management_http import BusinessError
from src.api.routes import apps
from src.application.app_identity import AppClient, AppIdentityError, ShadowUser
from src.config import settings
from src.database import get_db

TOKEN = "app_cid.secret"
APP = AppClient(1, "linkresume", "app_cid", 101, 102)


@dataclass
class FakeIdentity:
    """外部用户 → 影子用户：A=5001、B=5002；默认资料库按用户记录。"""

    users: dict[str, int] = field(default_factory=lambda: {"A": 5001, "B": 5002})
    defaults: dict[int, int | None] = field(default_factory=dict)

    async def verify(self, token: str) -> AppClient:
        if token != TOKEN:
            raise AppIdentityError(
                401, "APP_CREDENTIAL_INVALID", "invalid app credential"
            )
        return APP

    async def resolve(self, app: AppClient, external: str | None) -> ShadowUser:
        if external not in self.users:
            raise AppIdentityError(400, "APP_USER_ID_INVALID", "invalid X-App-User-Id")
        uid = self.users[external]
        return ShadowUser(uid, self.defaults.get(uid))

    async def set_default(self, app_code: str, user_id: int, dataset_id: int) -> None:
        self.defaults[user_id] = dataset_id


@pytest.fixture
def identity(monkeypatch):
    fake = FakeIdentity()
    monkeypatch.setattr(settings, "APPS_API_ENABLED", True)
    monkeypatch.setattr(settings, "B4_DATASET_WRITES_ENABLED", True)
    monkeypatch.setattr(settings, "B5_FILE_WRITES_ENABLED", True)
    monkeypatch.setattr(settings, "B5_DELETE_WRITES_ENABLED", True)
    monkeypatch.setattr(app_auth, "verify_app_credential", fake.verify)
    monkeypatch.setattr(app_auth, "resolve_shadow_user", fake.resolve)
    monkeypatch.setattr(apps, "set_default_dataset", fake.set_default)
    return fake


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(apps.router)
    app.state.document_upload_executor = object()
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return app


def _client(app: FastAPI | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app or _app()), base_url="http://test"
    )


def _headers(user: str = "A", token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-App-User-Id": user}


# ---------------------------------------------------------------- 鉴权边界 R1 / BR4


@pytest.mark.asyncio
async def test_switch_off_hides_routes(identity, monkeypatch):
    monkeypatch.setattr(settings, "APPS_API_ENABLED", False)
    async with _client() as client:
        response = await client.get("/api/v1/apps/files/1", headers=_headers())
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "status", "reason"),
    [
        ({}, 401, "APP_CREDENTIAL_INVALID"),
        (
            {"Authorization": "Bearer wrong.secret", "X-App-User-Id": "A"},
            401,
            "APP_CREDENTIAL_INVALID",
        ),
        ({"Authorization": f"Bearer {TOKEN}"}, 400, "APP_USER_ID_INVALID"),
        (
            {"Authorization": f"Bearer {TOKEN}", "X-App-User-Id": "nobody"},
            400,
            "APP_USER_ID_INVALID",
        ),
    ],
)
async def test_credential_and_user_header_required(identity, headers, status, reason):
    async with _client() as client:
        response = await client.get("/api/v1/apps/files/1", headers=headers)
    assert response.status_code == status
    assert response.json()["data"] == {"reason": reason}


@pytest.mark.asyncio
async def test_web_access_token_is_not_accepted(identity):
    """toLink 用户的 Web token 不能访问 /apps/*（即便 Web 鉴权依赖被放行）。"""

    app = _app()
    app.dependency_overrides[verify_user_token] = lambda: AuthContext(1, "r")
    async with _client(app) as client:
        response = await client.get(
            "/api/v1/apps/files/1",
            headers={"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.x.y"},
        )
    assert response.status_code == 401


# ---------------------------------------------------------------- 默认资料库 R4 / BR5


@pytest.mark.asyncio
async def test_default_dataset_created_once_with_app_embedding(identity, monkeypatch):
    created: list[tuple] = []
    existing: set[tuple[int, int]] = set()

    async def create_dataset(user_id, name, description, dense, sparse):
        created.append((user_id, name, dense, sparse))
        existing.add((user_id, 900 + len(created)))
        return {"id": 900 + len(created)}

    async def detail(user_id, dataset_id):
        if (user_id, dataset_id) not in existing:
            raise BusinessError(404, "数据集不存在或无权访问", 404)
        return {"id": dataset_id}

    monkeypatch.setattr(apps.dataset_service, "create_dataset", create_dataset)
    monkeypatch.setattr(apps.dataset_service, "detail", detail)
    async with _client() as client:
        first = await client.put("/api/v1/apps/datasets/default", headers=_headers())
        again = await client.put("/api/v1/apps/datasets/default", headers=_headers())
        other = await client.put("/api/v1/apps/datasets/default", headers=_headers("B"))
    assert first.json()["data"] == again.json()["data"] == {"id": 901}
    assert other.json()["data"] == {"id": 902}
    assert created == [(5001, "资料库", 101, 102), (5002, "资料库", 101, 102)]


@pytest.mark.asyncio
async def test_default_dataset_recreated_after_deletion(identity, monkeypatch):
    identity.defaults[5001] = 777
    calls = []

    async def detail(user_id, dataset_id):
        if dataset_id == 777:
            raise BusinessError(404, "数据集不存在或无权访问", 404)
        return {"id": dataset_id}

    async def create_dataset(*args):
        calls.append(args)
        return {"id": 778}

    monkeypatch.setattr(apps.dataset_service, "detail", detail)
    monkeypatch.setattr(apps.dataset_service, "create_dataset", create_dataset)
    async with _client() as client:
        response = await client.put("/api/v1/apps/datasets/default", headers=_headers())
    assert response.json()["data"] == {"id": 778}
    assert identity.defaults[5001] == 778 and len(calls) == 1


@pytest.mark.asyncio
async def test_default_dataset_requires_app_embedding_config(identity, monkeypatch):
    monkeypatch.setattr(
        app_auth,
        "verify_app_credential",
        AsyncMock(return_value=AppClient(1, "x", "c", None, None)),
    )
    async with _client() as client:
        response = await client.put("/api/v1/apps/datasets/default", headers=_headers())
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_write_switches_apply(identity, monkeypatch):
    monkeypatch.setattr(settings, "B4_DATASET_WRITES_ENABLED", False)
    monkeypatch.setattr(settings, "B5_FILE_WRITES_ENABLED", False)
    monkeypatch.setattr(settings, "B5_DELETE_WRITES_ENABLED", False)
    async with _client() as client:
        ds = await client.put("/api/v1/apps/datasets/default", headers=_headers())
        up = await client.post(
            "/api/v1/apps/files", headers=_headers(), files={"file": ("a.md", b"x")}
        )
        rm = await client.delete("/api/v1/apps/files/1", headers=_headers())
        rp = await client.post("/api/v1/apps/files/1/parse", headers=_headers())
    assert [r.status_code for r in (ds, up, rm, rp)] == [503, 503, 503, 503]


# ---------------------------------------------------------------- 文件 R4


@pytest.mark.asyncio
async def test_upload_uses_shadow_user_and_auto_parse(identity, monkeypatch):
    identity.defaults[5001] = 901
    captured = {}

    async def upload(user_id, dataset_id, file, *, parse_immediately, executor):
        captured.update(user_id=user_id, dataset_id=dataset_id, parse=parse_immediately)
        return {"id": 3001, "datasetId": dataset_id, "uploadStatus": "UPLOADING"}

    monkeypatch.setattr(apps, "upload", upload)
    monkeypatch.setattr(
        apps.dataset_service, "detail", AsyncMock(return_value={"id": 901})
    )
    async with _client() as client:
        response = await client.post(
            "/api/v1/apps/files",
            headers=_headers(),
            files={"file": ("resume.pdf", b"%PDF", "application/pdf")},
            data={"externalRef": "mat-9"},
        )
    assert response.status_code == 200
    assert response.json()["data"]["externalRef"] == "mat-9"
    assert captured == {"user_id": 5001, "dataset_id": 901, "parse": True}


@pytest.mark.asyncio
async def test_file_routes_pass_only_shadow_user_id(identity, monkeypatch):
    seen = []

    async def detail(user_id, file_id):
        seen.append(("detail", user_id, file_id))
        return {"id": file_id, "datasetId": 901, "uploadStatus": "UPLOAD_SUCCESS"}

    async def parse_results(user_id, dataset_id, file_ids):
        seen.append(("parse_results", user_id, dataset_id))
        return [
            {
                "parseStatus": "success",
                "frontendStatus": "parse_success",
                "failureReason": None,
            }
        ]

    async def delete_file(user_id, file_id):
        seen.append(("delete", user_id, file_id))

    async def submit_parse(user_id, file_id):
        seen.append(("parse", user_id, file_id))
        return {"taskId": "t"}

    monkeypatch.setattr(apps.document_files, "detail", detail)
    monkeypatch.setattr(apps.document_files, "parse_results", parse_results)
    monkeypatch.setattr(apps, "delete_file", delete_file)
    monkeypatch.setattr(apps, "submit_parse", submit_parse)
    async with _client() as client:
        status = await client.get("/api/v1/apps/files/11", headers=_headers("B"))
        await client.post("/api/v1/apps/files/11/parse", headers=_headers("B"))
        await client.delete("/api/v1/apps/files/11", headers=_headers("B"))
    assert status.json()["data"]["parseStatus"] == "success"
    assert seen == [
        ("detail", 5002, 11),
        ("parse_results", 5002, 901),
        ("parse", 5002, 11),
        ("delete", 5002, 11),
    ]


@pytest.mark.asyncio
async def test_foreign_file_is_not_found(identity, monkeypatch):
    async def detail(user_id, file_id):
        raise BusinessError(404, "文件不存在或无权访问", 404)

    monkeypatch.setattr(apps.document_files, "detail", detail)
    async with _client() as client:
        response = await client.get("/api/v1/apps/files/11", headers=_headers())
    assert response.status_code == 404


# ---------------------------------------------------------------- 召回 R5 / R6 / BR8


class _Rows:
    def __init__(self, ids):
        self._ids = ids

    def __iter__(self):
        return iter([(i,) for i in self._ids])


@pytest.fixture
def recall_env(identity, monkeypatch):
    """用户 A 拥有数据集 901 与文件 11、12；用户 B 拥有数据集 902 与文件 21。"""

    owned_datasets = {5001: [901], 5002: [902]}
    owned_files = {5001: {11, 12}, 5002: {21}}
    captured: dict = {}

    async def scope(db, *, user_id, requested_dataset_ids):
        owned = owned_datasets[user_id]
        if requested_dataset_ids and not set(requested_dataset_ids) <= set(owned):
            from src.application.recall_errors import RecallApiError

            raise RecallApiError(
                403, "RECALL_SCOPE_FORBIDDEN", "dataset scope is not authorized"
            )
        return list(requested_dataset_ids or owned)

    async def execution(user_id, dataset_ids):
        from src.core.dataset_config.models import RecallConfig

        return RecallConfig(), {}

    def build(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    async def run(pipeline, req, request_id):
        return {
            "hits": [
                {
                    "chunk_id": "c1",
                    "doc_id": 11,
                    "dataset_id": 901,
                    "fused_score": 0.9,
                    "scores": {},
                },
                {
                    "chunk_id": "gone",
                    "doc_id": 12,
                    "dataset_id": 901,
                    "fused_score": 0.5,
                    "scores": {},
                },
            ],
            "failed_sources": [],
        }

    async def details(db, user_id, chunk_ids):
        captured["detail_user"] = user_id
        return [
            {
                "chunkId": "c1",
                "documentId": 11,
                "fileName": "resume.pdf",
                "content": "正文",
            }
        ]

    class DB:
        async def execute(self, statement, params):
            return _Rows(sorted(set(params["fids"]) & owned_files[params["uid"]]))

    app = _app()
    app.dependency_overrides[get_db] = lambda: DB()
    app.dependency_overrides[apps.get_recall_pipeline] = lambda: object()
    monkeypatch.setattr(apps, "resolve_user_dataset_scope", scope)
    monkeypatch.setattr(apps, "aresolve_recall_execution", execution)
    monkeypatch.setattr(apps, "build_recall_request_from_config", build)
    monkeypatch.setattr(apps, "run_recall_json", run)
    monkeypatch.setattr(apps, "load_owned_chunk_details", details)
    return app, captured


@pytest.mark.asyncio
async def test_recall_scopes_to_user_and_returns_content(recall_env):
    app, captured = recall_env
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/apps/recall",
            headers=_headers(),
            json={"query": "项目经历", "fileIds": [11, 11, 12], "topK": 5},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    # 正文不可见的命中（已删除 / 非本人）被丢弃，不回传空内容。
    assert data["hits"] == [
        {
            "chunkId": "c1",
            "fileId": 11,
            "datasetId": 901,
            "score": 0.9,
            "fileName": "resume.pdf",
            "content": "正文",
        }
    ]
    assert captured["user_id"] == 5001 and captured["detail_user"] == 5001
    assert captured["dataset_ids"] == [901]
    assert captured["doc_ids"] == [11, 12]
    assert captured["recall_cfg"].recall_result_limit == 5


@pytest.mark.asyncio
async def test_recall_rejects_other_users_file(recall_env):
    app, _ = recall_env
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/apps/recall",
            headers=_headers(),
            json={"query": "q", "fileIds": [11, 21]},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_recall_rejects_other_users_dataset(recall_env):
    app, _ = recall_env
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/apps/recall",
            headers=_headers(),
            json={"query": "q", "datasetIds": [902]},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "q", "topK": 0},
        {"query": "q", "topK": 51},
        {"query": "q", "userId": 1},
        {"query": "q", "fileIds": list(range(101))},
    ],
)
async def test_recall_validates_body(recall_env, body):
    app, _ = recall_env
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/apps/recall", headers=_headers(), json=body
        )
    assert response.status_code == 400
