"""Exercise B1 authenticated cross-language flows with isolated Dev users.

Only users with the generated ``b1e2e_`` prefix are mutated and removed. Java
issues the tokens; Python verifies them and checks the Java session bridge.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

from scripts.acceptance.b1_live_smoke import _curl
from src.config import settings
from src.database import close_database, get_db_context, write_transaction


@dataclass
class Fixture:
    username: str
    email: str
    token: str | None = None
    user_id: int | None = None


async def _promote_admin(fixture: Fixture) -> None:
    async with write_transaction() as session:
        result = await session.execute(
            text(
                "UPDATE sys_user SET role='ADMIN' "
                "WHERE id=:uid AND username=:username AND email=:email AND role='USER'"
            ),
            {
                "uid": fixture.user_id,
                "username": fixture.username,
                "email": fixture.email,
            },
        )
        if result.rowcount != 1:
            raise RuntimeError("admin fixture promotion guard failed")


async def _cleanup(fixture: Fixture) -> tuple[int, int]:
    async with get_db_context() as session:
        row = (
            await session.execute(
                text("SELECT id,email FROM sys_user WHERE username=:username"),
                {"username": fixture.username},
            )
        ).one_or_none()
    if row is None:
        return 0, 0
    uid, email = row
    if not fixture.username.startswith("b1e2e_") or email != fixture.email:
        raise RuntimeError("fixture cleanup identity guard failed")
    async with write_transaction() as session:
        events = await session.execute(
            text("DELETE FROM user_login_event WHERE user_id=:uid"), {"uid": uid}
        )
        users = await session.execute(
            text("DELETE FROM sys_user WHERE id=:uid AND username=:username AND email=:email"),
            {"uid": uid, "username": fixture.username, "email": fixture.email},
        )
    return int(users.rowcount), int(events.rowcount)


def _register(java_url: str, fixture: Fixture) -> bool:
    password = secrets.token_urlsafe(24)
    status, payload = _curl(
        java_url,
        "POST",
        "/api/v1/auth/register",
        body={"username": fixture.username, "email": fixture.email, "password": password},
    )
    if status != 200 or payload.get("code") != 200:
        print(f"register: FAIL status={status} code={payload.get('code')}")
        return False
    fixture.token = payload["data"]["accessToken"]
    fixture.user_id = int(payload["data"]["userId"])
    return True


def _pair_profile(java_url: str, python_url: str, token: str) -> tuple[bool, dict[str, Any] | None]:
    java_status, java = _curl(java_url, "GET", "/api/v1/user/profile", token=token)
    python_status, python = _curl(python_url, "GET", "/api/v1/user/profile", token=token)
    matched = (
        java_status == python_status == 200
        and java.get("code") == python.get("code") == 200
        and java.get("data") == python.get("data")
    )
    print(
        f"profile_pair: {'PASS' if matched else 'DIFF'} java={java_status}/{java.get('code')} python={python_status}/{python.get('code')}"
    )
    return matched, java.get("data") if matched else None


def _check(label: str, status: int, payload: dict[str, Any], expected_status: int = 200) -> bool:
    okay = status == expected_status and payload.get("code") == expected_status
    print(f"{label}: {'PASS' if okay else 'FAIL'} status={status} code={payload.get('code')}")
    return okay


async def run(java_url: str, python_url: str) -> int:
    db_url = make_url(settings.DATABASE_URL or "")
    if (
        settings.APP_ENV != "development"
        or db_url.database != "tolink_rag_dev"
        or db_url.host != "100.86.10.52"
    ):
        raise RuntimeError("authenticated probe accepts only Dev MySQL")
    preflight_status, preflight = _curl(
        python_url, "GET", "/api/v1/user/profile", token="invalid-b1-preflight"
    )
    if preflight_status != 401 or preflight.get("code") != 401:
        print("auth_preflight=BLOCKED")
        return 2
    suffix = secrets.token_hex(5)
    admin = Fixture(f"b1e2e_admin_{suffix}", f"b1e2e_admin_{suffix}@example.invalid")
    user = Fixture(f"b1e2e_user_{suffix}", f"b1e2e_user_{suffix}@example.invalid")
    fixtures = [admin, user]
    failures = 0
    try:
        for fixture in fixtures:
            if not _register(java_url, fixture):
                return 1
        await _promote_admin(admin)
        matched, _ = _pair_profile(java_url, python_url, user.token)
        failures += not matched

        status, payload = _curl(
            java_url,
            "PATCH",
            "/api/v1/user/profile",
            token=user.token,
            body={"nickname": "B1-Java-probe"},
        )
        failures += not _check("java_profile_patch", status, payload)
        matched, data = _pair_profile(java_url, python_url, user.token)
        failures += not matched or data is None or data.get("nickname") != "B1-Java-probe"

        status, payload = _curl(
            python_url,
            "PATCH",
            "/api/v1/user/profile",
            token=user.token,
            body={"phone": "13800000000"},
        )
        failures += not _check("python_profile_patch", status, payload)
        matched, data = _pair_profile(java_url, python_url, user.token)
        failures += not matched or data is None or data.get("phone") != "13800000000"

        path = "/api/v1/admin/users?page=1&size=10"
        java_status, java_list = _curl(java_url, "GET", path, token=admin.token)
        python_status, python_list = _curl(python_url, "GET", path, token=admin.token)
        lists_match = java_status == python_status == 200 and java_list.get(
            "data"
        ) == python_list.get("data")
        print(
            f"admin_list: {'PASS' if lists_match else 'DIFF'} java={java_status} python={python_status}"
        )
        if not lists_match:
            java_data = java_list.get("data") or {}
            python_data = python_list.get("data") or {}
            for label, data in (("java", java_data), ("python", python_data)):
                print(
                    f"{label}_list_shape: keys={sorted(data)} "
                    f"total={data.get('total')} page={data.get('page')} "
                    f"pageSize={data.get('pageSize')} totalPages={data.get('totalPages')} "
                    f"ids={[item.get('id') for item in data.get('items', [])]}"
                )
            java_by_id = {item.get("id"): item for item in java_data.get("items", [])}
            python_by_id = {item.get("id"): item for item in python_data.get("items", [])}
            for uid in java_by_id.keys() & python_by_id.keys():
                differing = sorted(
                    key
                    for key in java_by_id[uid].keys() | python_by_id[uid].keys()
                    if java_by_id[uid].get(key) != python_by_id[uid].get(key)
                )
                if differing:
                    print(f"list_item_diff: id={uid} fields={differing}")
        failures += not lists_match
        page_path = "/api/v1/admin/users?page=2&size=1"
        java_page_status, java_page = _curl(java_url, "GET", page_path, token=admin.token)
        python_page_status, python_page = _curl(python_url, "GET", page_path, token=admin.token)
        page_match = java_page_status == python_page_status == 200 and java_page.get(
            "data"
        ) == python_page.get("data")
        print(
            f"admin_page_2_size_1: {'PASS' if page_match else 'DIFF'} "
            f"java_items={len((java_page.get('data') or {}).get('items', []))} "
            f"python_items={len((python_page.get('data') or {}).get('items', []))}"
        )
        failures += not page_match

        role_path = f"/api/v1/admin/users/{user.user_id}/role"
        status, payload = _curl(
            java_url,
            "PATCH",
            role_path,
            token=admin.token,
            body={"role": "ADMIN"},
        )
        failures += not _check("java_role_patch", status, payload)
        matched, data = _pair_profile(java_url, python_url, user.token)
        failures += not matched or data is None or data.get("role") != "ADMIN"

        status, payload = _curl(
            python_url,
            "PATCH",
            role_path,
            token=admin.token,
            body={"role": "USER"},
        )
        failures += not _check("python_role_patch", status, payload)
        matched, data = _pair_profile(java_url, python_url, user.token)
        failures += not matched or data is None or data.get("role") != "USER"

        status_path = f"/api/v1/admin/users/{user.user_id}/status"
        status, payload = _curl(
            java_url,
            "PATCH",
            status_path,
            token=admin.token,
            body={"status": 0},
        )
        failures += not _check("java_disable_fixture", status, payload)
        java_disabled_status, java_disabled = _curl(
            java_url, "GET", "/api/v1/user/profile", token=user.token
        )
        python_disabled_status, python_disabled = _curl(
            python_url, "GET", "/api/v1/user/profile", token=user.token
        )
        disabled_match = java_disabled_status == python_disabled_status and java_disabled.get(
            "code"
        ) == python_disabled.get("code")
        print(
            f"disabled_session: {'PASS' if disabled_match else 'DIFF'} "
            f"java={java_disabled_status}/{java_disabled.get('code')} "
            f"python={python_disabled_status}/{python_disabled.get('code')}"
        )
        failures += not disabled_match
        status, payload = _curl(
            java_url,
            "PATCH",
            status_path,
            token=admin.token,
            body={"status": 1},
        )
        failures += not _check("java_reenable_fixture", status, payload)
        matched, _ = _pair_profile(java_url, python_url, user.token)
        failures += not matched

        status, payload = _curl(python_url, "POST", "/api/v1/auth/logout", token=user.token)
        failures += not _check("python_logout_java_token", status, payload)
        for label, base in (("java", java_url), ("python", python_url)):
            result_status, result = _curl(base, "GET", "/api/v1/user/profile", token=user.token)
            failures += not _check(f"{label}_after_logout", result_status, result, 401)
        return 0 if failures == 0 else 1
    finally:
        cleanup_failed = False
        try:
            for fixture in fixtures:
                if fixture.token:
                    try:
                        _curl(java_url, "POST", "/api/v1/auth/logout", token=fixture.token)
                    except Exception:
                        print("cleanup_logout=ERROR")
                        cleanup_failed = True
                try:
                    users, events = await _cleanup(fixture)
                    print(f"cleanup: users={users} login_events={events}")
                except Exception:
                    print("cleanup_database=ERROR")
                    cleanup_failed = True
            if cleanup_failed:
                raise RuntimeError("one or more isolated fixtures could not be cleaned")
        finally:
            await close_database()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-url", required=True)
    parser.add_argument("--python-url", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.java_url, args.python_url))


if __name__ == "__main__":
    raise SystemExit(main())
