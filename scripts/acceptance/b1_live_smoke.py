"""Create one isolated Java B1 user, probe both APIs, and remove only that user.

Run only against the named Dev database. Tokens and generated credentials remain
in process memory; output contains response status/code and field names only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import subprocess
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.config import settings
from src.database import close_database, get_db_context, write_transaction


def _curl(
    base_url: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    command = [
        "curl", "--noproxy", "*", "--silent", "--show-error", "--max-time", "10",
        "--request", method, "--write-out", "\n%{http_code}",
    ]
    if token:
        command.extend(["--header", f"satoken: {token}"])
    if body is not None:
        command.extend(["--header", "Content-Type: application/json", "--data-binary", "@-"])
    command.append(f"{base_url.rstrip('/')}{path}")
    result = subprocess.run(
        command,
        input=json.dumps(body) if body is not None else None,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        # CalledProcessError 会把含 satoken 的命令参数写入异常字符串。
        raise RuntimeError(f"curl transport failed for {method} {path}")
    payload, status = result.stdout.rsplit("\n", 1)
    return int(status), json.loads(payload)


async def _cleanup(username: str, email: str) -> tuple[int, int]:
    async with get_db_context() as session:
        row = (
            await session.execute(
                text("SELECT id,email FROM sys_user WHERE username=:username"),
                {"username": username},
            )
        ).one_or_none()
    if row is None:
        return 0, 0
    user_id, stored_email = row
    if stored_email != email or not username.startswith("b1e2e_"):
        raise RuntimeError("cleanup guard rejected user identity")
    async with write_transaction() as session:
        events = await session.execute(
            text("DELETE FROM user_login_event WHERE user_id=:uid"), {"uid": user_id}
        )
        users = await session.execute(
            text("DELETE FROM sys_user WHERE id=:uid AND username=:username AND email=:email"),
            {"uid": user_id, "username": username, "email": email},
        )
    return int(users.rowcount), int(events.rowcount)


async def _cleanup_and_close(username: str, email: str) -> tuple[int, int]:
    try:
        return await _cleanup(username, email)
    finally:
        await close_database()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-url", required=True)
    parser.add_argument("--python-url", required=True)
    args = parser.parse_args()
    db_url = make_url(settings.DATABASE_URL or "")
    if (
        settings.APP_ENV != "development"
        or db_url.database != "tolink_rag_dev"
        or db_url.host != "100.86.10.52"
    ):
        raise RuntimeError("live smoke accepts only the configured Dev MySQL")
    preflight_status, preflight = _curl(
        args.python_url,
        "GET",
        "/api/v1/user/profile",
        token="invalid-b1-preflight",
    )
    if preflight_status == 503:
        print("auth_preflight=BLOCKED: local Python verifier is not configured")
        return 2
    if preflight_status != 401 or preflight.get("code") != 401:
        raise RuntimeError("local Python auth preflight returned an unexpected response")
    suffix = secrets.token_hex(5)
    username = f"b1e2e_{suffix}"
    email = f"{username}@example.invalid"
    password = secrets.token_urlsafe(24)
    token: str | None = None
    parity_status = "FAIL"
    java_profile_data: dict[str, Any] | None = None
    try:
        status, response = _curl(
            args.java_url, "POST", "/api/v1/auth/register",
            body={"username": username, "email": email, "password": password},
        )
        print(f"java_register: status={status} code={response.get('code')}")
        if status != 200 or response.get("code") != 200:
            return 1
        token = response["data"]["accessToken"]
        user_id = response["data"]["userId"]
        print(f"fixture_user_id={user_id}")
        for label, base in (("java", args.java_url), ("python", args.python_url)):
            profile_status, profile = _curl(
                base, "GET", "/api/v1/user/profile", token=token
            )
            data = profile.get("data")
            fields = sorted(data) if isinstance(data, dict) else []
            print(
                f"{label}_profile: status={profile_status} "
                f"code={profile.get('code')} fields={fields}"
            )
            if label == "java" and (
                profile_status != 200 or data.get("id") != user_id
            ):
                raise RuntimeError("Java registered user profile differs from register")
            if label == "java":
                java_profile_data = data
            elif profile_status == 503 and profile.get("code") == 503:
                parity_status = "BLOCKED"
            elif profile_status == 200 and data == java_profile_data:
                parity_status = "PASS"
        print(f"authenticated_profile_parity={parity_status}")
        return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[parity_status]
    finally:
        if token:
            try:
                status, response = _curl(
                    args.java_url, "POST", "/api/v1/auth/logout", token=token
                )
                print(f"java_logout: status={status} code={response.get('code')}")
            except Exception as exc:
                print(f"java_logout: ERROR {type(exc).__name__}")
        users, events = asyncio.run(_cleanup_and_close(username, email))
        print(f"cleanup: users={users} login_events={events}")


if __name__ == "__main__":
    raise SystemExit(main())
