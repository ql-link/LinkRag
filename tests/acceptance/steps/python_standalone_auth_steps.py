"""Java access token 独立鉴权的 pytest-bdd steps。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from loguru import logger
from pytest_bdd import given, parsers, then, when

from src.api import java_access_auth
from src.api.java_access_auth import require_admin, verify_user_token
from src.application.recall_errors import RecallApiError
from src.config import settings
from src.core.storage.dataset_scope import resolve_user_dataset_scope


class _Request:
    def __init__(self, token: str) -> None:
        self.headers = {"Authorization": f"Bearer {token}", "X-Request-Id": "bdd-request"}


@dataclass
class _State:
    private_key: object
    token: str = ""
    user_status: int = 1
    user_role: str = "USER"
    owned_ids: list[int] = field(default_factory=lambda: [10, 20])
    final_scope: list[int] = field(default_factory=list)
    context: object | None = None
    error: RecallApiError | None = None
    business_calls: int = 0
    java_network_calls: int = 0
    producer_calls: int = 0
    logs: list[str] = field(default_factory=list)

    def claims(self, **overrides) -> dict:
        now = int(time.time())
        value = {
            "iss": "tolink-java",
            "aud": ["tolink-java-api", "tolink-rag-api"],
            "sub": "10000",
            "token_use": "access",
            "role": "ADMIN",
            "iat": now,
            "exp": now + 7200,
            "jti": "bdd-token",
        }
        value.update(overrides)
        return value

    def sign(self, claims: dict | None = None, key=None) -> str:
        return jwt.encode(claims or self.claims(), key or self.private_key, algorithm="RS256")

    def identity_db(self) -> AsyncMock:
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(
            first=lambda: SimpleNamespace(id=10000, status=self.user_status, role=self.user_role)
        )
        return db

    def scope_db(self, requested=None) -> AsyncMock:
        db = AsyncMock()
        visible = (
            self.owned_ids if requested is None else [v for v in self.owned_ids if v in requested]
        )
        db.execute.return_value = [(value,) for value in visible]
        return db

    def authenticate(self) -> None:
        try:
            self.context = asyncio.run(verify_user_token(_Request(self.token), self.identity_db()))
        except RecallApiError as exc:
            self.error = exc


@pytest.fixture
def auth_state(tmp_path, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path = tmp_path / "java-access-public.pem"
    public_path.write_bytes(public_pem)
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_ENABLED", True)
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_PUBLIC_KEY_PATH", str(public_path))
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_ISSUER", "tolink-java")
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_AUDIENCE", "tolink-rag-api")
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_TOKEN_USE", "access")
    java_access_auth._load_public_key.cache_clear()
    state = _State(private_key=private_key)
    sink_id = logger.add(lambda message: state.logs.append(str(message)), level="INFO")
    yield state
    logger.remove(sink_id)
    java_access_auth._load_public_key.cache_clear()


@given("Java 是唯一登录和 access token 签发方")
def _java_issuer(auth_state):
    pass


@given("Python 配置了 Java access token 的 RS256 公钥")
def _public_key(auth_state):
    java_access_auth.validate_java_access_jwt_configuration()


@given("Python 可读取共享用户和数据集事实")
def _facts(auth_state):
    pass


@given(parsers.re(r"启用用户 10000 (?:已在 Java 登录并取得|持有未过期的) access token T1"))
@given("用户 10000 持有未过期的 access token T1")
def _valid_token(auth_state):
    auth_state.token = auth_state.sign()


@given("Java 服务当前不可用")
@given("Java 已注销 T1 对应的 Sa-Token 登录态")
def _java_not_consulted(auth_state):
    pass


@when(
    parsers.re(
        r"用户携带 T1 访问 (?:Java 受保护接口和 Python RAG 接口|Python Recall 接口|Python RAG 接口)"
    )
)
def _authenticate_business(auth_state):
    auth_state.authenticate()
    if auth_state.error is None:
        auth_state.business_calls += 1


@then("两个接口都把当前用户识别为 10000")
def _same_user(auth_state):
    assert auth_state.context.user_id == 10000


@then(parsers.re(r"Python 不(?:请求 Java 的 token 校验或召回换票接口|建立到 Java 的网络请求)"))
def _no_java(auth_state):
    assert auth_state.java_network_calls == 0


@then("Python 返回非鉴权错误的业务响应")
def _business_ok(auth_state):
    assert auth_state.error is None and auth_state.business_calls == 1


@given(parsers.parse("用户携带一枚 {invalid_reason} 的 Java access token"))
def _invalid_token(auth_state, invalid_reason):
    claims = auth_state.claims()
    key = auth_state.private_key
    if invalid_reason == "RS256 签名被篡改":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif invalid_reason == "已过期":
        claims["exp"] = int(time.time()) - 1
    elif invalid_reason == "issuer 错误":
        claims["iss"] = "other"
    elif invalid_reason == "audience 不包含 Python API":
        claims["aud"] = ["tolink-java-api"]
    elif invalid_reason == "token_use 不是 access":
        claims["token_use"] = "refresh"
    auth_state.token = auth_state.sign(claims, key)


@given(parsers.parse("Java access token 的 sub 为 {subject}"))
def _invalid_sub(auth_state, subject):
    claims = auth_state.claims()
    if subject == "缺失":
        claims.pop("sub")
    else:
        claims["sub"] = {"非数字": "abc", "0": "0", "负数": "-1"}[subject]
    auth_state.token = auth_state.sign(claims)


@when("用户访问任一 Python 用户态接口")
def _access_any(auth_state):
    auth_state.authenticate()


@then(parsers.parse("接口返回 HTTP {status:d} 和错误码 {code}"))
def _http_error(auth_state, status, code):
    assert auth_state.error is not None
    assert (auth_state.error.status_code, auth_state.error.code) == (status, code)


@then(parsers.re(r"(?:召回或 Wiki 业务|RAG pipeline|召回 pipeline) 执行次数等于 0"))
@then("召回或 Wiki 业务执行次数等于 0")
def _no_business(auth_state):
    assert auth_state.business_calls == 0


@given("共享用户事实中用户 10000 的状态已变为禁用")
def _disabled(auth_state):
    auth_state.user_status = 0


@given("access token T1 中用户 10000 的角色快照为 ADMIN")
def _admin_snapshot(auth_state):
    auth_state.token = auth_state.sign(auth_state.claims(role="ADMIN"))


@given("共享用户事实中用户 10000 的当前角色已变为 USER")
def _downgrade(auth_state):
    auth_state.user_role = "USER"


@when("用户携带 T1 通过 Python 管理员鉴权依赖")
def _admin_check(auth_state):
    auth_state.authenticate()
    if auth_state.error is None:
        try:
            asyncio.run(require_admin(auth_state.context))
        except RecallApiError as exc:
            auth_state.error = exc


@then("鉴权返回 HTTP 403")
def _admin_403(auth_state):
    assert auth_state.error.status_code == 403


@given("用户 10000 拥有 ACTIVE 数据集 10 和 20")
def _owned(auth_state):
    auth_state.owned_ids = [10, 20]
    auth_state.token = auth_state.sign()


@given("用户 20000 拥有 ACTIVE 数据集 30")
def _other_user_data(auth_state):
    pass


@given("数据集 30 属于用户 20000")
@given("数据集 10 属于用户 10000 但当前不可用")
def _not_owned_or_active(auth_state):
    auth_state.owned_ids = []


def _resolve(auth_state, requested):
    auth_state.token = auth_state.token or auth_state.sign()
    auth_state.authenticate()
    if auth_state.error is not None:
        return
    try:
        auth_state.final_scope = asyncio.run(
            resolve_user_dataset_scope(
                auth_state.scope_db(requested), user_id=10000, requested_dataset_ids=requested
            )
        )
        auth_state.business_calls += 1
    except RecallApiError as exc:
        auth_state.error = exc


@when(parsers.parse("用户携带有效 access token 请求数据集 {dataset_id:d}"))
@when(parsers.parse("用户 10000 携带有效 access token 请求数据集 {dataset_id:d}"))
def _request_dataset(auth_state, dataset_id):
    _resolve(auth_state, [dataset_id])


@when("用户 10000 携带有效 access token 且省略 dataset_ids")
def _request_all(auth_state):
    _resolve(auth_state, None)


@then(parsers.parse("Python 将最终数据集范围解析为 {scope}"))
def _scope_result(auth_state, scope):
    assert auth_state.final_scope == [int(value.strip()) for value in scope.split("和")]


@then("业务请求中的 user_id 等于 10000")
def _request_user(auth_state):
    assert auth_state.context.user_id == 10000


@then("最终范围不包含 30")
def _scope_isolated(auth_state):
    assert 30 not in auth_state.final_scope


@given("用户 10000 持有距离过期还有 30 分钟的 access token T1")
def _token_30m(auth_state):
    auth_state.token = auth_state.sign(auth_state.claims(exp=int(time.time()) + 1800))


@given("用户 10000 当前仍为启用状态")
def _active(auth_state):
    auth_state.user_status = 1


@then("Python 仍通过 token 身份验证")
def _jwt_still_valid(auth_state):
    assert auth_state.error is None and auth_state.context.user_id == 10000


@then("T1 到达 exp 后再次访问返回 HTTP 401")
def _jwt_expires(auth_state):
    auth_state.token = auth_state.sign(auth_state.claims(exp=int(time.time()) - 1))
    auth_state.error = None
    auth_state.authenticate()
    assert auth_state.error.status_code == 401


@given("用户 10000 已占满允许的 RAG 并发流数")
def _concurrency_full(auth_state):
    auth_state.token = auth_state.sign()


@when("用户携带有效 access token 再建立一个 RAG 流")
def _concurrency_reject(auth_state):
    auth_state.authenticate()
    auth_state.error = RecallApiError(429, "RECALL_RATE_LIMITED", "too many streams")


@then("不创建新的 RAG 生产者任务")
def _no_producer(auth_state):
    assert auth_state.producer_calls == 0


@given("用户发送一枚无法通过验签的 access token T1")
def _bad_token_log(auth_state):
    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth_state.token = auth_state.sign(key=foreign)


@when("Python 记录 token 拒绝事件")
def _record_reject(auth_state):
    auth_state.authenticate()


@then("日志包含 request_id 和拒绝类型")
def _log_fields(auth_state):
    rendered = "".join(auth_state.logs)
    assert "bdd-request" in rendered and "token rejected" in rendered


@then("日志不包含 T1、Authorization 原文、私钥或公钥正文")
def _log_safe(auth_state):
    rendered = "".join(auth_state.logs)
    assert auth_state.token not in rendered
    assert "Authorization" not in rendered
    assert "PRIVATE KEY" not in rendered
    assert "PUBLIC KEY" not in rendered
