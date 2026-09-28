"""Use curl to compare safe, non-mutating Java/Python B1 HTTP contract probes.

This script never registers users or writes test data. Full authenticated acceptance
is recorded separately in .specs/b1-api-parity/manual_acceptance.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Case:
    name: str
    method: str
    path: str
    body: dict[str, Any] | None = None
    headers: tuple[str, ...] = ()


CASES = (
    Case("profile_anonymous", "GET", "/api/v1/user/profile"),
    Case("admin_anonymous", "GET", "/api/v1/admin/users"),
    Case("profile_invalid_token", "GET", "/api/v1/user/profile", headers=("satoken: invalid-b1-probe",)),
    Case("profile_bearer_only", "GET", "/api/v1/user/profile", headers=("Authorization: Bearer invalid-b1-probe",)),
    Case("profile_update_anonymous", "PATCH", "/api/v1/user/profile", {"nickname": "probe"}),
    Case("avatar_anonymous", "POST", "/api/v1/user/avatar"),
    Case("admin_role_anonymous", "PATCH", "/api/v1/admin/users/1/role", {"role": "ADMIN"}),
    Case("admin_status_anonymous", "PATCH", "/api/v1/admin/users/1/status", {"status": 0}),
    Case("login_missing_account", "POST", "/api/v1/auth/login", {"password": "x"}),
    Case("login_missing_password", "POST", "/api/v1/auth/login", {"account": "probe"}),
    Case("login_blank_account", "POST", "/api/v1/auth/login", {"account": "   ", "password": "x"}),
    Case("login_null_account", "POST", "/api/v1/auth/login", {"account": None, "password": "x"}),
    Case("login_numeric_account", "POST", "/api/v1/auth/login", {"account": 123, "password": "x"}),
    Case("register_missing_email", "POST", "/api/v1/auth/register", {"username": "probe", "password": "123456"}),
    Case("register_blank_username", "POST", "/api/v1/auth/register", {"username": "   ", "password": "123456", "email": "probe@example.invalid"}),
    Case("register_short_username", "POST", "/api/v1/auth/register", {"username": "ab", "password": "123456", "email": "probe@example.invalid"}),
    Case("register_blank_password", "POST", "/api/v1/auth/register", {"username": "probe", "password": "      ", "email": "probe@example.invalid"}),
    Case("register_short_password", "POST", "/api/v1/auth/register", {"username": "probe", "password": "abc", "email": "probe@example.invalid"}),
    Case("register_bad_email", "POST", "/api/v1/auth/register", {"username": "probe", "password": "123456", "email": "invalid"}),
    Case("register_trimmed_short_username_bad_email", "POST", "/api/v1/auth/register", {"username": " ab ", "password": "123456", "email": "invalid"}),
    Case("register_null_email", "POST", "/api/v1/auth/register", {"username": "probe", "password": "123456", "email": None}),
    Case("register_long_username", "POST", "/api/v1/auth/register", {"username": "x" * 65, "password": "123456", "email": "probe@example.invalid"}),
    Case("register_long_password", "POST", "/api/v1/auth/register", {"username": "probe", "password": "x" * 129, "email": "probe@example.invalid"}),
    Case("logout_anonymous", "POST", "/api/v1/auth/logout"),
    Case("logout_invalid_token", "POST", "/api/v1/auth/logout", headers=("satoken: invalid-b1-probe",)),
)


def request(base_url: str, case: Case) -> tuple[int, int, str, Any]:
    command = [
        "curl", "--noproxy", "*", "--silent", "--show-error", "--max-time", "8",
        "--request", case.method, "--write-out", "\n%{http_code}",
    ]
    if case.body is not None:
        command.extend(["--header", "Content-Type: application/json", "--data-binary", "@-"])
    for header in case.headers:
        command.extend(["--header", header])
    command.append(f"{base_url.rstrip('/')}{case.path}")
    completed = subprocess.run(
        command,
        input=json.dumps(case.body, ensure_ascii=False) if case.body is not None else None,
        text=True,
        capture_output=True,
        check=True,
    )
    payload, status = completed.stdout.rsplit("\n", 1)
    response = json.loads(payload)
    return int(status), response["code"], response["message"], response.get("data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-url", required=True)
    parser.add_argument("--python-url", required=True)
    args = parser.parse_args()
    failures = 0
    for case in CASES:
        try:
            java = request(args.java_url, case)
            python = request(args.python_url, case)
        except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
            failures += 1
            print(f"{case.name}: ERROR {type(exc).__name__}")
            continue
        matched = java == python
        failures += not matched
        print(f"{case.name}: {'PASS' if matched else 'DIFF'} java={java} python={python}")
    print(f"matched={len(CASES) - failures}/{len(CASES)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
