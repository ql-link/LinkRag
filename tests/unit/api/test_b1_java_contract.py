"""Java Dev B1 error responses observed with curl on 2026-09-28."""

import httpx
import pytest
from fastapi import FastAPI

from src.api.routes import identity_users


def test_java_string_field_coercion() -> None:
    assert identity_users.LoginRequest(account=123, password=True).model_dump() == {
        "account": "123",
        "password": "true",
    }
    assert identity_users.RegisterRequest(
        username=123, password=123456, email="probe@example.invalid"
    ).model_dump() == {
        "username": "123",
        "password": "123456",
        "email": "probe@example.invalid",
    }
    # Java 先按原始长度执行 @Size，再在服务层 trim。
    assert (
        identity_users.RegisterRequest(
            username=" ab ", password="123456", email="probe@example.invalid"
        ).username
        == "ab"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body,status,code,message",
    [
        ("GET", "/api/v1/user/profile", None, 401, 401, "未登录或登录已过期"),
        ("GET", "/api/v1/admin/users", None, 401, 401, "未登录或登录已过期"),
        ("POST", "/api/v1/auth/login", {"password": "x"}, 400, 400, "account: 账号不能为空"),
        ("POST", "/api/v1/auth/login", {"account": "probe"}, 400, 400, "password: 密码不能为空"),
        (
            "POST",
            "/api/v1/auth/login",
            {"account": "   ", "password": "x"},
            400,
            400,
            "account: 账号不能为空",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": "probe", "password": "123456"},
            400,
            400,
            "email: 邮箱不能为空",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": "   ", "password": "123456", "email": "probe@example.invalid"},
            400,
            400,
            "username: 用户名不能为空",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": "ab", "password": "123456", "email": "probe@example.invalid"},
            400,
            400,
            "username: 用户名长度必须在3-64之间",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": "probe", "password": "      ", "email": "probe@example.invalid"},
            400,
            400,
            "password: 密码不能为空",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": "probe", "password": "abc", "email": "probe@example.invalid"},
            400,
            400,
            "password: 密码长度必须在6-128之间",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": "probe", "password": "123456", "email": "invalid"},
            400,
            400,
            "email: 邮箱格式不正确",
        ),
        (
            "POST",
            "/api/v1/auth/register",
            {"username": " ab ", "password": "123456", "email": "invalid"},
            400,
            400,
            "email: 邮箱格式不正确",
        ),
        ("POST", "/api/v1/auth/logout", None, 200, 200, "success"),
    ],
)
async def test_java_observed_anonymous_contract(method, path, body, status, code, message):
    app = FastAPI()
    app.include_router(identity_users.auth_router)
    app.include_router(identity_users.user_router)
    app.include_router(identity_users.admin_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=body)
    assert response.status_code == status
    assert response.json() == {"code": code, "message": message, "data": None}
