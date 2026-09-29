"""Compare avatar validation without creating MinIO objects.

The file cases are missing, empty, unsupported suffix, and above 5 MiB; no
valid avatar is uploaded. A generated Java user is deleted after probing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

from scripts.acceptance.b1_authenticated_probe import Fixture, _cleanup, _register
from scripts.acceptance.b1_live_smoke import _curl
from src.config import settings
from src.database import close_database


def _avatar_request(base: str, token: str, file: Path | None, filename: str = ""):
    command = [
        "curl",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--max-time",
        "30",
        "--request",
        "POST",
        "--header",
        f"satoken: {token}",
        "--write-out",
        "\n%{http_code}",
    ]
    if file is not None:
        command.extend(["--form", f"file=@{file};filename={filename}"])
    else:
        command.extend(["--form", "probe=1"])
    command.append(f"{base.rstrip('/')}/api/v1/user/avatar")
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("avatar curl transport failed")
    payload, status = result.stdout.rsplit("\n", 1)
    body = json.loads(payload)
    return int(status), body.get("code"), body.get("message"), body.get("data")


async def run(java_url: str, python_url: str, include_oversized: bool = False) -> int:
    db_url = make_url(settings.DATABASE_URL or "")
    if (
        settings.APP_ENV != "development"
        or db_url.database != "tolink_rag_dev"
        or db_url.host != "100.86.10.52"
    ):
        raise RuntimeError("avatar probe accepts only Dev MySQL")
    status, payload = _curl(python_url, "GET", "/api/v1/user/profile", token="invalid-b1-preflight")
    if status != 401 or payload.get("code") != 401:
        print("auth_preflight=BLOCKED")
        return 2
    suffix = secrets.token_hex(5)
    fixture = Fixture(f"b1e2e_avatar_{suffix}", f"b1e2e_avatar_{suffix}@example.invalid")
    failures = 0
    try:
        if not _register(java_url, fixture):
            return 1
        with tempfile.TemporaryDirectory(prefix="b1-avatar-") as directory:
            root = Path(directory)
            empty = root / "empty.png"
            empty.write_bytes(b"")
            unsupported = root / "unsupported.txt"
            unsupported.write_bytes(b"not-an-image")
            oversized = root / "oversized.png"
            with oversized.open("wb") as target:
                target.seek(5 * 1024 * 1024)
                target.write(b"x")
            cases = [
                ("missing", None, ""),
                ("empty", empty, "empty.png"),
                ("unsupported", unsupported, "unsupported.txt"),
            ]
            if include_oversized:
                cases.append(("oversized", oversized, "oversized.png"))
            for name, file, filename in cases:
                java = _avatar_request(java_url, fixture.token, file, filename)
                python = _avatar_request(python_url, fixture.token, file, filename)
                matched = java == python
                failures += not matched
                print(
                    f"{name}: {'PASS' if matched else 'DIFF'} java={java[:3]} python={python[:3]}"
                )
        return 0 if failures == 0 else 1
    finally:
        try:
            if fixture.token:
                try:
                    _curl(java_url, "POST", "/api/v1/auth/logout", token=fixture.token)
                except Exception:
                    print("cleanup_logout=ERROR")
            users, events = await _cleanup(fixture)
            print(f"cleanup: users={users} login_events={events}")
        finally:
            await close_database()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-url", required=True)
    parser.add_argument("--python-url", required=True)
    parser.add_argument("--include-oversized", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.java_url, args.python_url, args.include_oversized))


if __name__ == "__main__":
    raise SystemExit(main())
