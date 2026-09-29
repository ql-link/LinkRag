"""Curl B4 create/update/config against Dev using one disposable dataset and user.

Only B4 writes may be enabled. The probe does not delete via B5 because the
shared Dev database has not received the 0041 outbox migration. Cleanup uses
guarded SQL on the uniquely prefixed fixture and reports its row counts.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets

from sqlalchemy import text
from sqlalchemy.engine import make_url

from scripts.acceptance.b1_authenticated_probe import Fixture, _cleanup, _register
from scripts.acceptance.b1_live_smoke import _curl
from src.cache.dataset_parse_config_cache import DatasetParseConfigCache
from src.cache.redis_client import redis_client
from src.config import settings
from src.database import close_database, get_db_context, write_transaction


async def _models() -> tuple[int, int]:
    async with get_db_context() as db:
        rows = (await db.execute(text("""
            SELECT id,capability FROM llm_model_config
            WHERE scope='SYSTEM' AND owner_user_id=0 AND is_active=1
              AND capability IN ('EMBEDDING','SPARSE_EMBEDDING')
            ORDER BY id
        """))).mappings().all()
    ids = {row["capability"]: int(row["id"]) for row in rows}
    return ids["EMBEDDING"], ids["SPARSE_EMBEDDING"]


async def _cleanup_dataset(user_id: int, dataset_id: int, name_prefix: str) -> tuple[int, int]:
    async with write_transaction() as db:
        row = (
            await db.execute(
                text("SELECT name FROM dataset WHERE id=:did AND user_id=:uid FOR UPDATE"),
                {"did": dataset_id, "uid": user_id},
            )
        ).scalar_one_or_none()
        if row is None:
            return 0, 0
        if not row.startswith(name_prefix):
            raise RuntimeError("fixture dataset name guard failed")
        files = (
            await db.execute(
                text("SELECT COUNT(*) FROM document_original_file WHERE dataset_id=:did"),
                {"did": dataset_id},
            )
        ).scalar_one()
        chats = (
            await db.execute(
                text("SELECT COUNT(*) FROM chat_conversation WHERE dataset_id=:did"),
                {"did": dataset_id},
            )
        ).scalar_one()
        if files or chats:
            raise RuntimeError("fixture dataset unexpectedly has files or chats")
        configs = await db.execute(
            text("DELETE FROM dataset_parse_config WHERE dataset_id=:did AND user_id=:uid"),
            {"did": dataset_id, "uid": user_id},
        )
        datasets = await db.execute(
            text("DELETE FROM dataset WHERE id=:did AND user_id=:uid"),
            {"did": dataset_id, "uid": user_id},
        )
    await DatasetParseConfigCache().invalidate(dataset_id)
    return int(configs.rowcount), int(datasets.rowcount)


async def run(java_url: str, python_url: str) -> int:
    url = make_url(settings.DATABASE_URL or "")
    if (
        settings.APP_ENV != "development"
        or url.database != "tolink_rag_dev"
        or url.host != "100.86.10.52"
    ):
        raise RuntimeError("probe accepts only the named Dev database")
    if (
        not settings.B4_DATASET_WRITES_ENABLED
        or settings.B2_GENERIC_UPLOAD_ENABLED
        or settings.B3_CONTROL_WRITES_ENABLED
        or settings.B5_FILE_WRITES_ENABLED
        or settings.B5_DELETE_WRITES_ENABLED
    ):
        raise RuntimeError("only B4 writes may be enabled")
    dense, sparse = await _models()
    await redis_client.initialize()
    suffix = secrets.token_hex(5)
    fixture = Fixture(f"b1e2e_b4_{suffix}", f"b1e2e_b4_{suffix}@example.invalid")
    name_prefix = f"b4e2e_{suffix}"
    dataset_id = 0
    failures = 0

    def check(
        name: str, status: int, payload: dict, expected: int, code: int | None = None
    ) -> None:
        nonlocal failures
        okay = status == expected and payload.get("code") == (code or expected)
        failures += not okay
        print(f"{name}: {'PASS' if okay else 'FAIL'} http={status} code={payload.get('code')}")

    try:
        if not _register(java_url, fixture):
            raise RuntimeError("fixture registration failed")
        path = "/api/v1/datasets"
        body = {
            "name": f"  {name_prefix}  ",
            "description": "isolated test",
            "dense_embedding_config_id": dense,
            "sparse_embedding_config_id": sparse,
        }
        status, payload = _curl(python_url, "POST", path, token=fixture.token, body=body)
        check("create", status, payload, 200)
        if status != 200:
            return 1
        dataset_id = int(payload["data"]["id"])
        if payload["data"]["name"] != name_prefix:
            failures += 1
            print("create_trim: FAIL")
        else:
            print("create_trim: PASS")
        status, payload = _curl(python_url, "POST", path, token=fixture.token, body=body)
        check("duplicate_name", status, payload, 400)
        status, payload = _curl(python_url, "GET", f"{path}/{dataset_id}", token=fixture.token)
        check("detail", status, payload, 200)
        status, payload = _curl(
            python_url, "GET", f"{path}/{dataset_id}/parse-config", token=fixture.token
        )
        check("default_parse_config", status, payload, 200)
        if status == 200 and (
            payload["data"].get("dense_embedding_config_id"),
            payload["data"].get("sparse_embedding_config_id"),
        ) != (dense, sparse):
            failures += 1
            print("default_bindings: FAIL")
        else:
            print("default_bindings: PASS")
        status, payload = _curl(
            python_url,
            "PATCH",
            f"{path}/{dataset_id}",
            token=fixture.token,
            body={"name": f" {name_prefix}_renamed ", "description": " updated "},
        )
        check("update", status, payload, 200)
        if status == 200 and payload["data"]["name"] != f"{name_prefix}_renamed":
            failures += 1
            print("update_trim: FAIL")
        else:
            print("update_trim: PASS")
        config = {
            "dense_embedding_config_id": dense,
            "sparse_embedding_config_id": sparse,
            "chunking": {"stage_two_algorithm": "NOOP"},
            "recall": {
                "recall_enabled_sources": ["DENSE", "dense", None, " sparse "],
                "rerank_top_n": 7,
            },
        }
        status, payload = _curl(
            python_url, "PUT", f"{path}/{dataset_id}/parse-config", token=fixture.token, body=config
        )
        check("replace_parse_config", status, payload, 200)
        if status == 200 and payload["data"]["recall"].get("recall_enabled_sources") != [
            "dense",
            "sparse",
        ]:
            failures += 1
            print("recall_sources_normalized: FAIL")
        else:
            print("recall_sources_normalized: PASS")
        status, payload = _curl(
            python_url,
            "PUT",
            f"{path}/{dataset_id}/parse-config",
            token=fixture.token,
            body={**config, "recall": {"dense_score_threshold": -0.1}},
        )
        check("negative_threshold", status, payload, 400)
        status, payload = _curl(
            python_url,
            "PUT",
            f"{path}/{dataset_id}/parse-config",
            token=fixture.token,
            body={**config, "dense_embedding_config_id": 99999999},
        )
        check("immutable_dense_binding", status, payload, 400, 10028)
        if (
            status == 400
            and (payload.get("data") or {}).get("field") != "dense_embedding_config_id"
        ):
            failures += 1
            print("immutable_field_detail: FAIL")
        else:
            print("immutable_field_detail: PASS")
        status, payload = _curl(
            python_url, "GET", f"{path}/{dataset_id}/parse-config", token=fixture.token
        )
        check("config_unchanged_after_reject", status, payload, 200)
        if status == 200 and payload["data"]["recall"].get("rerank_top_n") != 7:
            failures += 1
            print("rejected_write_rolled_back: FAIL")
        else:
            print("rejected_write_rolled_back: PASS")
        print(f"result failed={failures}")
        return 0 if failures == 0 else 1
    finally:
        try:
            try:
                if dataset_id and fixture.user_id:
                    configs, datasets = await _cleanup_dataset(
                        int(fixture.user_id), dataset_id, name_prefix
                    )
                    print(f"cleanup_dataset: config_rows={configs} dataset_rows={datasets}")
            finally:
                if fixture.token:
                    try:
                        _curl(java_url, "POST", "/api/v1/auth/logout", token=fixture.token)
                    except Exception:
                        print("cleanup_logout: ERROR")
                users, events = await _cleanup(fixture)
                print(f"cleanup_user: users={users} login_events={events}")
        finally:
            await redis_client.close()
            await close_database()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-url", required=True)
    parser.add_argument("--python-url", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.java_url, args.python_url))


if __name__ == "__main__":
    raise SystemExit(main())
