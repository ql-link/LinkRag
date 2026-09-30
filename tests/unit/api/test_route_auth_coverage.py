"""全量路由鉴权覆盖门禁。

每条注册到 ``src.main.app`` 的路由必须挂载一种已知鉴权依赖，或显式列入匿名白名单。
新增路由忘记鉴权时本测试失败；确需匿名的路由要在 ``ANONYMOUS_ROUTES`` 中登记并说明原因。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.routing import APIRoute

from src.api import java_access_auth, management_auth, route_guards

# 路由自身在处理函数内完成凭证校验（非 Depends），在此登记以免误报。
_INLINE_AUTH_ROUTES = {
    ("GET", "/api/v1/internal/files/{file_id}/content"),  # B5 服务令牌，compare_digest
}

ANONYMOUS_ROUTES = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/logout"),  # 无效 / 缺失 token 幂等成功
    ("POST", "/api/v1/feedback"),  # 公开反馈提交，受 B10 写入开关控制
    ("GET", "/api/v1/blog/posts"),
    ("GET", "/api/v1/blog/posts/{slug}"),
    ("GET", "/api/v1/oss-files/public/{object_key:path}"),  # 仅 PUBLIC 桶
}

_AUTH_DEPENDENCIES: set[Callable] = {
    java_access_auth.verify_user_token,
    java_access_auth.require_admin,
    management_auth.require_login,
    route_guards.require_internal_service_token,
}


def _iter_routes(routes) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _iter_routes(route.original_router.routes)


def _dependency_calls(dependant) -> Iterator[Callable]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dependency_calls(sub)


def _is_authenticated(route: APIRoute) -> bool:
    # require_role(...) 返回闭包，其内部依赖 require_login，递归遍历即可命中。
    return any(
        call in _AUTH_DEPENDENCIES for call in _dependency_calls(route.dependant)
    )


def _registered_routes() -> list[tuple[str, str, APIRoute]]:
    from src.main import app

    return [
        (method, route.path, route)
        for route in _iter_routes(app.routes)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"})
    ]


def test_every_route_is_authenticated_or_explicitly_anonymous():
    unguarded = [
        f"{method} {path}"
        for method, path, route in _registered_routes()
        if (method, path) not in ANONYMOUS_ROUTES
        and (method, path) not in _INLINE_AUTH_ROUTES
        and not _is_authenticated(route)
    ]
    assert unguarded == [], (
        f"以下路由缺少鉴权依赖，请补鉴权或登记匿名白名单: {unguarded}"
    )


def test_allowlists_do_not_contain_stale_entries():
    registered = {(method, path) for method, path, _ in _registered_routes()}
    stale = (ANONYMOUS_ROUTES | _INLINE_AUTH_ROUTES) - registered
    assert stale == set(), f"白名单中存在已不存在的路由: {stale}"


@pytest.mark.parametrize(
    "prefix",
    ["/api/v1/mq/", "/api/v1/parser/"],
)
def test_debug_routes_require_switch_and_admin(prefix):
    for _method, path, route in _registered_routes():
        if not path.startswith(prefix):
            continue
        calls = set(_dependency_calls(route.dependant))
        assert route_guards.require_debug_endpoints_enabled in calls, path
        assert java_access_auth.require_admin in calls, path
