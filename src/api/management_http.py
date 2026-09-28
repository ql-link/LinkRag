"""Java 业务路由专用的响应和异常适配，不改变现有 RAG 接口。"""

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from src.observability.logging import logger

T = TypeVar("T")


class ApiResult(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T | None = None


class BusinessError(Exception):
    def __init__(self, code: int, message: str, http_status: int,
                 data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data


def success(data: T | None = None) -> ApiResult[T]:
    return ApiResult(data=data)


def _validation_message(request: Request, exc: RequestValidationError) -> str:
    """兼容 Java B1 DTO 的字段级校验消息，其他管理路由保留通用响应。"""
    if not exc.errors():
        return "请求参数不合法"
    error = exc.errors()[0]
    loc = error.get("loc", ())
    field = loc[-1] if loc else None
    value = error.get("input")
    missing = error.get("type") == "missing"
    path = request.url.path
    if path == "/api/v1/auth/login" and field in {"account", "password"}:
        label = "账号" if field == "account" else "密码"
        return f"{field}: {label}不能为空"
    if path == "/api/v1/auth/register":
        if field == "username":
            reason = (
                "用户名不能为空"
                if missing or value is None or isinstance(value, str) and not value.strip()
                else "用户名长度必须在3-64之间"
            )
            return f"username: {reason}"
        if field == "password":
            reason = (
                "密码不能为空"
                if missing or value is None or isinstance(value, str) and not value.strip()
                else "密码长度必须在6-128之间"
            )
            return f"password: {reason}"
        if field == "email":
            reason = (
                "邮箱不能为空"
                if missing or value is None or isinstance(value, str) and not value.strip()
                else "邮箱格式不正确"
            )
            return f"email: {reason}"
    if path == "/api/v1/user/avatar" and field == "file":
        return "缺少必填参数: file"
    return "请求参数不合法"


class ManagementRoute(APIRoute):
    """只处理经本路由类注册的管理端接口异常。"""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Any:
            try:
                return await handler(request)
            except BusinessError as exc:
                return JSONResponse(
                    status_code=exc.http_status,
                    content=ApiResult(code=exc.code, message=exc.message,
                                      data=exc.data).model_dump(),
                )
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=400,
                    content=ApiResult(
                        code=400, message=_validation_message(request, exc)
                    ).model_dump(),
                )
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content=ApiResult(
                        code=exc.status_code, message=str(exc.detail)
                    ).model_dump(),
                    headers=exc.headers,
                )
            except Exception as exc:
                logger.bind(
                    event="management_http_error",
                    method=request.method,
                    path=request.url.path,
                    error_type=type(exc).__name__,
                ).error("管理端请求处理失败")
                return JSONResponse(
                    status_code=500,
                    content=ApiResult(code=50001, message="系统内部错误").model_dump(),
                )

        return wrapped


class ManagementRouter(APIRouter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(route_class=ManagementRoute, **kwargs)
