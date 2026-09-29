"""Focused guards for the B3/B5 control-plane migration."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymysql.err import ProgrammingError
from sqlalchemy.exc import DBAPIError

from src.api.management_http import BusinessError
from src.application import (
    datasets,
    document_files,
    document_runtime_config,
    management_outbox,
    model_configs,
    model_sync,
)
from src.application.document_uploads import (
    DocumentUploadExecutor,
    UploadJob,
    _validate_plain_markdown,
    upload,
)


def test_b3_wrong_decryption_key_fails_closed(monkeypatch):
    row = {
        "id": 19,
        "api_key": "encrypted",
        "scope": "USER",
        "provider_id": 1,
        "provider_type": "demo",
        "provider_name": "Demo",
        "icon_url": None,
        "model_name": "m",
        "display_name": "M",
        "capability": "CHAT",
        "protocol": "openai",
        "api_base_url": "https://example.invalid",
        "is_active": True,
        "owner_user_id": 7,
        "snapshot_version": 1,
        "created_at": None,
        "updated_at": None,
    }
    monkeypatch.setattr(
        model_configs, "decrypt_api_key", lambda _: (_ for _ in ()).throw(ValueError("secret"))
    )
    monkeypatch.setattr(model_configs, "audit_event", lambda *args, **kwargs: None)
    with pytest.raises(BusinessError) as error:
        model_configs._dto(row, 7)
    assert error.value.http_status == 503
    assert "secret" not in error.value.message


def test_models_dev_candidates_are_isolated_until_review():
    catalog = {
        "anthropic": {
            "models": {
                "claude-test": {
                    "id": "claude-test",
                    "name": "Claude Test",
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "limit": {"context": 1000},
                },
            }
        }
    }
    entries = model_sync._models_for_provider(catalog, "claude")
    assert {item["capability"] for item in entries} == {"CHAT", "VISION"}
    assert {item["external_model_id"] for item in entries} == {"claude-test"}
    assert model_sync._facts(
        {"provider_type": "claude", "api_base_url": "https://api.example/v1"}, "CHAT"
    ) == ("anthropic", "https://api.example/v1/messages")
    with pytest.raises(BusinessError):
        model_sync._models_for_provider(catalog, "unknown")


@pytest.mark.asyncio
async def test_b3_sync_read_reports_missing_migration_as_503(monkeypatch):
    class DB:
        async def execute(self, *_args, **_kwargs):
            raise DBAPIError("SELECT", {}, ProgrammingError(1146, "missing table"))

    @asynccontextmanager
    async def context():
        yield DB()

    monkeypatch.setattr(model_sync, "get_db_context", context)
    with pytest.raises(BusinessError) as error:
        await model_sync.list_jobs(1, 10, None, None, None)
    assert error.value.http_status == 503
    assert "missing table" not in error.value.message


@pytest.mark.asyncio
async def test_b5_upload_limits_keep_last_valid_shared_snapshot(monkeypatch):
    document_runtime_config._last_valid = document_runtime_config.DocumentUploadLimits()
    monkeypatch.setattr(
        document_runtime_config.redis_client,
        "get",
        AsyncMock(return_value='{"allowedSuffixes":["pdf"],"maxSizeBytes":1048576}'),
    )
    current = await document_runtime_config.current_limits()
    assert current.allowed_suffixes == {"pdf"}
    monkeypatch.setattr(
        document_runtime_config.redis_client, "get", AsyncMock(side_effect=ConnectionError("redis"))
    )
    monkeypatch.setattr(document_runtime_config, "audit_event", lambda *args, **kwargs: None)
    assert await document_runtime_config.current_limits() == current


def test_plain_markdown_upload_rejects_unresolved_images(tmp_path):
    path = tmp_path / "readme.md"
    path.write_text("# Guide\n\nNo images.\n", encoding="utf-8")
    _validate_plain_markdown(path, "md")
    for source in (
        "![logo](./logo.png)",
        "![logo][ref]\n[ref]: ./logo.png",
        '<img src="logo.png">',
        "![[logo.png]]",
    ):
        path.write_text(source, encoding="utf-8")
        with pytest.raises(BusinessError) as error:
            _validate_plain_markdown(path, "md")
        assert error.value.code == 30010
    for source in (
        "![logo](https://example.invalid/logo.png)",
        "![logo][ref]\n\n[ref]: https://example.invalid/logo.png",
        '<img src="data:image/png;base64,abc">',
        "![logo][undefined]",
        "![empty]()",
    ):
        path.write_text(source, encoding="utf-8")
        _validate_plain_markdown(path, "md")
    path.write_text("```md\n![example](local.png)\n```\n", encoding="utf-8")
    _validate_plain_markdown(path, "md")
    path.write_text("`![example](local.png)`\n", encoding="utf-8")
    _validate_plain_markdown(path, "md")


@pytest.mark.parametrize("field", ["sparse_score_threshold", "dense_score_threshold"])
def test_dataset_recall_rejects_negative_threshold_like_java(field):
    with pytest.raises(BusinessError, match=field):
        datasets._normalized_configs({"recall": {field: -0.01}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (None, 10020),
        ({"scope": "USER", "owner_user_id": 8, "is_active": 0, "capability": "VISION"}, 10021),
        ({"scope": "USER", "owner_user_id": 8, "is_active": 1, "capability": "VISION"}, 10022),
        ({"scope": "USER", "owner_user_id": 7, "is_active": 1, "capability": "VISION"}, 10023),
    ],
)
async def test_b3_execution_binding_preserves_java_error_order(monkeypatch, row, expected):
    monkeypatch.setattr(model_configs, "_config_row", AsyncMock(return_value=row))
    with pytest.raises(BusinessError) as error:
        await model_configs.require_executable(object(), 7, 19, "CHAT")
    assert error.value.code == expected


@pytest.mark.asyncio
async def test_b5_parse_result_uses_pipeline_terminal_status(monkeypatch):
    rows = [
        {
            "id": 1,
            "original_filename": "a.pdf",
            "parsed_filename": "a.md",
            "pipeline_status": "SUCCESS",
            "parse_failure_reason": None,
            "latest_parse_task_id": "task-a",
            "object_key": "raw/a.pdf",
        },
        {
            "id": 2,
            "original_filename": "b.pdf",
            "parsed_filename": None,
            "pipeline_status": "FAILED",
            "parse_failure_reason": "parse failed",
            "latest_parse_task_id": "task-b",
            "object_key": "raw/b.pdf",
        },
        {
            "id": 3,
            "original_filename": "c.pdf",
            "parsed_filename": None,
            "pipeline_status": None,
            "parse_failure_reason": None,
            "latest_parse_task_id": "task-c",
            "object_key": "raw/c.pdf",
        },
    ]

    class Query:
        def mappings(self):
            return self

        def all(self):
            return rows

    class DB:
        async def execute(self, *_args, **_kwargs):
            return Query()

    @asynccontextmanager
    async def context():
        yield DB()

    monkeypatch.setattr(document_files, "get_db_context", context)
    monkeypatch.setattr(document_files, "owned_dataset", AsyncMock(return_value={"id": 5}))
    result = await document_files.parse_results(7, 5, [1, 2, 3])
    assert [(item["frontendStatus"], item["parseStatus"]) for item in result] == [
        ("parse_success", "success"),
        ("parse_failed", "failed"),
        ("parsing", "created"),
    ]
    assert result[1]["failureReason"] == "parse failed"
    assert result[0]["failureReason"] is None


@pytest.mark.asyncio
async def test_b5_asset_manifest_identity_must_match_owned_file(monkeypatch):
    class Storage:
        def download_to_path(self, _bucket, _key, path):
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "fileId": 999,
                        "userId": 7,
                        "datasetId": 5,
                        "source": {
                            "normalizedObjectKey": "markdown-assets/v1/user-7/dataset-5/file-3/source/normalized.md"
                        },
                        "summary": {"matchedCount": 1},
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(document_files.StorageFactory, "get_storage", lambda: Storage())
    row = {
        "id": 3,
        "user_id": 7,
        "dataset_id": 5,
        "object_key": "markdown-assets/v1/user-7/dataset-5/file-3/source/normalized.md",
    }
    with pytest.raises(BusinessError) as error:
        await document_files._asset_summary(row, required=True)
    assert error.value.http_status == 503


@pytest.mark.asyncio
async def test_upload_checks_dataset_ownership_before_reading_body(monkeypatch):
    from src.application import document_uploads

    @asynccontextmanager
    async def db_context():
        yield object()

    async def reject(*_args):
        raise BusinessError(404, "数据集不存在", 404)

    monkeypatch.setattr(document_uploads, "get_db_context", db_context)
    monkeypatch.setattr(document_uploads, "owned_dataset", reject)
    file = SimpleNamespace(filename="large.pdf", read=AsyncMock())
    with pytest.raises(BusinessError) as error:
        await upload(7, 99, file, parse_immediately=False, executor=DocumentUploadExecutor())
    assert error.value.http_status == 404
    file.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_executor_drains_accepted_job_before_shutdown(monkeypatch, tmp_path):
    from src.application import document_uploads

    entered = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def process(_job):
        entered.set()
        await release.wait()
        completed.set()

    monkeypatch.setattr(document_uploads, "_process", process)
    executor = DocumentUploadExecutor(workers=1, capacity=1)
    executor.start()
    path = tmp_path / "upload.pdf"
    path.write_bytes(b"data")
    executor.submit(
        UploadJob(1, 1, 1, "upload.pdf", "application/pdf", path, "1/1/upload.pdf", False)
    )
    await asyncio.wait_for(entered.wait(), 1)
    closing = asyncio.create_task(executor.close())
    await asyncio.sleep(0)
    assert not closing.done()
    assert not completed.is_set()
    release.set()
    await asyncio.wait_for(closing, 1)
    assert completed.is_set()
    assert not path.exists()
    with pytest.raises(RuntimeError):
        executor.submit(UploadJob(2, 1, 1, "x", "application/pdf", Path("x"), "x", False))


@pytest.mark.asyncio
async def test_outbox_retries_the_same_payload_after_broker_failure(monkeypatch):
    state = {"status": "PENDING", "body": '{"task_id":"stable-id"}', "attempts": 0}

    class Result:
        def __init__(self, claimed):
            self.rowcount = claimed

        def mappings(self):
            return self

        def one(self):
            return {
                "topic": "tolink.rag.parse_task",
                "message_body": state["body"],
                "message_key": "pdf",
            }

    class DB:
        async def execute(self, stmt, params):
            sql = str(stmt)
            if "SET status='CLAIMED'" in sql:
                if state["status"] != "PENDING":
                    return Result(0)
                state["status"] = "CLAIMED"
                state["attempts"] += 1
                return Result(1)
            if "SET status='PENDING'" in sql:
                state["status"] = "PENDING"
            if "SET status='SENT'" in sql:
                state["status"] = "SENT"
            return Result(1)

    @asynccontextmanager
    async def transaction():
        yield DB()

    monkeypatch.setattr(management_outbox, "write_transaction", transaction)
    monkeypatch.setattr(management_outbox, "audit_event", lambda *args, **kwargs: None)
    mq = SimpleNamespace(send_raw=AsyncMock(side_effect=RuntimeError("broker down")))
    assert not await management_outbox.publish_one("parse:stable-id", mq=mq)
    assert state["status"] == "PENDING"
    mq.send_raw.side_effect = None
    assert await management_outbox.publish_one("parse:stable-id", mq=mq)
    assert state["status"] == "SENT"
    assert state["attempts"] == 2
    assert mq.send_raw.call_args_list[0].args == mq.send_raw.call_args_list[1].args
