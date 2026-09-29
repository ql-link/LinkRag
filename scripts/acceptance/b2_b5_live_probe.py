"""Curl B2-B5 Dev APIs with isolated Java-issued identities and safe write gates.

This probe intentionally leaves B2-B5 write switches off. It checks real
authentication, read queries, validation, and fail-closed gates without
modifying shared model/dataset/file data or consuming Dev MQ jobs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import subprocess
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

from scripts.acceptance.b1_authenticated_probe import Fixture, _cleanup, _promote_admin, _register
from scripts.acceptance.b1_live_smoke import _curl
from src.config import settings
from src.database import close_database, get_db_context


@dataclass(frozen=True)
class Case:
    name: str
    method: str
    path: str
    actor: str
    expected: int | None
    body: dict[str, Any] | None = None
    expected_code: int | None = None


def cases(other_dataset_id: int, other_file_id: int) -> list[Case]:
    result = [
        Case("b2_missing_file_validation", "POST", "/api/v1/oss-files/avatar", "none", 400),
        Case("b3_catalog", "GET", "/api/v1/llm/providers", "user", 200),
        Case("b3_catalog_filter", "GET", "/api/v1/llm/providers?capability=CHAT", "user", 200),
        Case(
            "b3_catalog_bad_capability",
            "GET",
            "/api/v1/llm/providers?capability=INVALID",
            "user",
            400,
            expected_code=10011,
        ),
        Case("b3_configs_existing_key", "GET", "/api/v1/llm/configs", "user", 200),
        Case("b3_defaults", "GET", "/api/v1/llm/defaults", "user", 200),
        Case("b3_default", "GET", "/api/v1/llm/defaults/CHAT", "user", 200),
        Case(
            "b3_default_bad_capability",
            "GET",
            "/api/v1/llm/defaults/INVALID",
            "user",
            400,
            expected_code=10011,
        ),
        Case(
            "b3_setup_gate",
            "POST",
            "/api/v1/llm/configs/setup-provider",
            "user",
            503,
            {"providerType": "openai", "apiKey": "probe-only"},
        ),
        Case(
            "b3_active_gate",
            "PATCH",
            "/api/v1/llm/configs/99999999/active",
            "user",
            503,
            {"isActive": False},
        ),
        Case(
            "b3_emergency_gate",
            "POST",
            "/api/v1/llm/configs/99999999/emergency-disable",
            "user",
            503,
            {"confirmed": True},
        ),
        Case("b3_delete_gate", "DELETE", "/api/v1/llm/configs/99999999", "user", 503),
        Case(
            "b3_default_write_gate",
            "PUT",
            "/api/v1/llm/defaults/CHAT",
            "user",
            503,
            {"configId": 99999999},
        ),
        Case("b3_default_clear_gate", "DELETE", "/api/v1/llm/defaults/CHAT", "user", 503),
        Case("b3_admin_providers", "GET", "/api/v1/admin/providers?page=1&size=2", "admin", 200),
        Case("b3_admin_models", "GET", "/api/v1/admin/provider-models?page=1&size=2", "admin", 200),
        Case("b3_admin_configs_existing_key", "GET", "/api/v1/admin/llm/configs", "admin", 200),
        Case("b3_admin_sync_jobs_unmigrated", "GET", "/api/v1/admin/model-sync-jobs", "admin", 503),
        Case(
            "b3_admin_sync_candidates_unmigrated",
            "GET",
            "/api/v1/admin/model-sync-candidates",
            "admin",
            503,
        ),
        Case(
            "b3_admin_create_gate",
            "POST",
            "/api/v1/admin/providers",
            "admin",
            503,
            {
                "providerType": "probe",
                "providerName": "Probe",
                "apiBaseUrl": "https://example.invalid",
                "defaultProtocol": "openai",
                "isActive": False,
                "priority": 0,
            },
        ),
        Case(
            "b3_admin_sync_gate",
            "POST",
            "/api/v1/admin/providers/99999999/model-sync",
            "admin",
            503,
            {},
        ),
        Case("b3_admin_config_gate", "POST", "/api/v1/admin/llm/configs", "admin", 503, {}),
        Case(
            "b3_admin_update_gate",
            "PATCH",
            "/api/v1/admin/provider-models/99999999",
            "admin",
            503,
            {"displayName": "Probe"},
        ),
        Case(
            "b3_admin_review_gate",
            "PATCH",
            "/api/v1/admin/model-sync-candidates/99999999/review",
            "admin",
            503,
            {"reviewStatus": "REJECTED"},
        ),
        Case(
            "b3_admin_publish_gate",
            "POST",
            "/api/v1/admin/model-sync-candidates/99999999/publish",
            "admin",
            503,
            {},
        ),
        Case("b4_list_empty", "GET", "/api/v1/datasets?page=1&pageSize=2", "user", 200),
        Case("b4_bad_page", "GET", "/api/v1/datasets?page=0", "user", 400),
        Case("b4_missing", "GET", "/api/v1/datasets/99999999", "user", 404),
        Case(
            "b4_parse_config_missing", "GET", "/api/v1/datasets/99999999/parse-config", "user", 404
        ),
        Case(
            "b4_create_gate",
            "POST",
            "/api/v1/datasets",
            "user",
            503,
            {"name": "probe", "dense_embedding_config_id": 1, "sparse_embedding_config_id": 2},
        ),
        Case(
            "b4_update_gate", "PATCH", "/api/v1/datasets/99999999", "user", 503, {"name": "probe"}
        ),
        Case(
            "b4_config_write_gate",
            "PUT",
            "/api/v1/datasets/99999999/parse-config",
            "user",
            503,
            {"dense_embedding_config_id": 1, "sparse_embedding_config_id": 2},
        ),
        Case("b4_delete_gate", "DELETE", "/api/v1/datasets/99999999", "user", 503),
        Case("b5_capabilities", "GET", "/api/v1/document-file-capabilities", "user", 200),
        Case("b5_recent_empty", "GET", "/api/v1/files/recent", "user", 200),
        Case("b5_file_missing", "GET", "/api/v1/files/99999999", "user", 404),
        Case("b5_list_missing_dataset", "GET", "/api/v1/datasets/99999999/files", "user", 404),
        Case(
            "b5_parse_results_empty",
            "GET",
            "/api/v1/datasets/99999999/files/parse-results?fileIds=",
            "user",
            400,
        ),
        Case(
            "b5_parse_results_bad_id",
            "GET",
            "/api/v1/datasets/99999999/files/parse-results?fileIds=x",
            "user",
            400,
        ),
        Case("b5_parse_gate", "POST", "/api/v1/files/99999999/parse", "user", 503),
        Case("b5_delete_gate", "DELETE", "/api/v1/files/99999999", "user", 503),
        Case(
            "b5_internal_anonymous", "GET", "/api/v1/internal/files/99999999/content", "none", 401
        ),
        Case(
            "b5_internal_user_jwt_not_service",
            "GET",
            "/api/v1/internal/files/99999999/content",
            "user",
            401,
        ),
    ]
    if other_dataset_id:
        result.append(
            Case(
                "b4_other_user_dataset", "GET", f"/api/v1/datasets/{other_dataset_id}", "user", 404
            )
        )
        result.append(
            Case(
                "b5_other_user_files",
                "GET",
                f"/api/v1/datasets/{other_dataset_id}/files",
                "user",
                404,
            )
        )
    if other_file_id:
        result.append(
            Case("b5_other_user_file", "GET", f"/api/v1/files/{other_file_id}", "user", 404)
        )
    for prefix, path in (
        ("b3", "/api/v1/llm/providers"),
        ("b4", "/api/v1/datasets"),
        ("b5", "/api/v1/document-file-capabilities"),
    ):
        result.append(Case(f"{prefix}_anonymous", "GET", path, "none", 401))
        result.append(Case(f"{prefix}_invalid_token", "GET", path, "invalid", 401))
    for name, path in (
        ("providers", "/api/v1/admin/providers"),
        ("models", "/api/v1/admin/provider-models"),
        ("configs", "/api/v1/admin/llm/configs"),
        ("sync_jobs", "/api/v1/admin/model-sync-jobs"),
        ("sync_candidates", "/api/v1/admin/model-sync-candidates"),
    ):
        result.append(Case(f"b3_user_cannot_admin_{name}", "GET", path, "user", 403))
    return result


async def _other_ids(user_id: int) -> tuple[int, int]:
    async with get_db_context() as db:
        dataset = (
            await db.execute(
                text("SELECT id FROM dataset WHERE user_id<>:uid AND is_deleted=0 LIMIT 1"),
                {"uid": user_id},
            )
        ).scalar_one_or_none()
        file = (
            await db.execute(
                text(
                    "SELECT id FROM document_original_file WHERE user_id<>:uid "
                    "AND is_deleted=0 LIMIT 1"
                ),
                {"uid": user_id},
            )
        ).scalar_one_or_none()
    return int(dataset or 0), int(file or 0)


def _curl_file(
    base_url: str, path: str, *, token: str | None = None, bundle: bool = False
) -> tuple[int, int]:
    command = [
        "curl",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--max-time",
        "10",
        "--request",
        "POST",
        "--write-out",
        "\n%{http_code}",
    ]
    if token:
        command.extend(["--header", f"satoken: {token}"])
    command.extend(["--form", "file=@/dev/null;filename=probe.md"])
    if bundle:
        command.extend(["--form", "matchMode=SHALLOW_BASENAME"])
    command.append(f"{base_url.rstrip('/')}{path}")
    process = subprocess.run(command, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError("multipart curl transport failed")
    body, status = process.stdout.rsplit("\n", 1)
    return int(status), int(json.loads(body)["code"])


async def run(java_url: str, python_url: str) -> int:
    db_url = make_url(settings.DATABASE_URL or "")
    if (
        settings.APP_ENV != "development"
        or db_url.database != "tolink_rag_dev"
        or db_url.host != "100.86.10.52"
    ):
        raise RuntimeError("probe accepts only the named Dev database")
    if any(
        (
            settings.B2_GENERIC_UPLOAD_ENABLED,
            settings.B3_CONTROL_WRITES_ENABLED,
            settings.B4_DATASET_WRITES_ENABLED,
            settings.B5_FILE_WRITES_ENABLED,
            settings.B5_DELETE_WRITES_ENABLED,
        )
    ):
        raise RuntimeError("write switches must remain off for shared Dev probe")
    status, payload = _curl(python_url, "GET", "/api/v1/llm/providers", token="invalid-preflight")
    if status != 401 or payload.get("code") != 401:
        raise RuntimeError("Python authentication preflight failed")
    suffix = secrets.token_hex(5)
    fixtures = [
        Fixture(f"b1e2e_b2b5_admin_{suffix}", f"b1e2e_b2b5_admin_{suffix}@example.invalid"),
        Fixture(f"b1e2e_b2b5_user_{suffix}", f"b1e2e_b2b5_user_{suffix}@example.invalid"),
    ]
    passed = failed = blocked = 0
    try:
        for fixture in fixtures:
            if not _register(java_url, fixture):
                raise RuntimeError("isolated Dev fixture registration failed")
        await _promote_admin(fixtures[0])
        other_dataset_id, other_file_id = await _other_ids(int(fixtures[1].user_id))
        tokens = {
            "admin": fixtures[0].token,
            "user": fixtures[1].token,
            "none": None,
            "invalid": "invalid-b2b5-probe",
        }
        for case in cases(other_dataset_id, other_file_id):
            try:
                status, payload = _curl(
                    python_url, case.method, case.path, token=tokens[case.actor], body=case.body
                )
            except Exception:
                failed += 1
                print(f"{case.name}: FAIL transport")
                continue
            code = payload.get("code")
            if (
                case.name in {"b3_configs_existing_key", "b3_admin_configs_existing_key"}
                and status == 200
            ):
                records = payload.get("data")
                if (
                    not isinstance(records, list)
                    or not records
                    or any(
                        not isinstance(row, dict) or "apiKeyMasked" not in row or "apiKey" in row
                        for row in records
                    )
                ):
                    failed += 1
                    print(f"{case.name}: FAIL masked_config_contract")
                    continue
            if case.expected is None:
                blocked += 1
                print(f"{case.name}: OBSERVED http={status} code={code}")
            elif status == case.expected and code == (case.expected_code or case.expected):
                passed += 1
                print(f"{case.name}: PASS http={status} code={code}")
            else:
                failed += 1
                print(
                    f"{case.name}: FAIL http={status} code={code} "
                    f"expected={case.expected}/{case.expected_code or case.expected}"
                )
        for name, path, token, bundle in (
            ("b2_generic_gate", "/api/v1/oss-files/avatar", None, False),
            ("b2_unknown_type_gate", "/api/v1/oss-files/unknown", None, False),
            ("b5_upload_gate", "/api/v1/datasets/99999999/files", fixtures[1].token, False),
            ("b5_bundle_gate", "/api/v1/datasets/99999999/files", fixtures[1].token, True),
        ):
            try:
                status, code = _curl_file(python_url, path, token=token, bundle=bundle)
                okay = status == code == 503
            except Exception:
                status = code = None
                okay = False
            passed += okay
            failed += not okay
            print(f"{name}: {'PASS' if okay else 'FAIL'} http={status} code={code}")
        print(f"result passed={passed} failed={failed} observed_unverified={blocked}")
        return 0 if failed == 0 else 1
    finally:
        try:
            for fixture in fixtures:
                if fixture.token:
                    try:
                        _curl(java_url, "POST", "/api/v1/auth/logout", token=fixture.token)
                    except Exception:
                        print("cleanup_logout: ERROR")
                users, events = await _cleanup(fixture)
                print(f"cleanup: users={users} login_events={events}")
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
