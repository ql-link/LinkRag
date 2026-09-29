"""B5 parse submission reusing the existing MQ producer and Python consumer."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from src.api.management_http import BusinessError
from src.application.document_files import _asset_summary, owned_file
from src.application.management_outbox import enqueue, publish_one
from src.config import settings
from src.core.mq.messages.parse_task import ParseTaskMessage
from src.database import write_transaction
from src.observability.audit import audit_event
from src.services.mq_service import MQService


def _md_key(row: dict, task_id: str) -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    filename = row["original_filename"].rsplit(".", 1)[0] + ".md"
    return (
        f"parsed/user-{row['user_id']}/dataset-{row['dataset_id']}/"
        f"{now:%Y/%m/%d}/{task_id}/{filename}"
    )


async def submit_parse(
    user_id: int,
    file_id: int,
    *,
    ignore_missing_assets: bool = False,
    trigger_mode: str = "manual_retry",
    mq: MQService | None = None,
) -> dict:
    previous_pointer: str | None = None
    payload: dict | None = None
    event_key: str | None = None
    async with write_transaction() as db:
        file = await owned_file(db, user_id, file_id)
        if file["upload_status"] != "success" or not file["is_upload_success"]:
            raise BusinessError(400, "原文件尚未上传成功，不能解析", 400)
        if file["file_suffix"] not in {"md", "markdown", "pdf", "docx", "html", "htm"}:
            raise BusinessError(400, "当前文件格式暂不支持解析", 400)
        parse_file = (
            (
                await db.execute(
                    text(
                        "SELECT id,latest_parse_task_id FROM document_parse_file "
                        "WHERE document_original_file_id=:fid FOR UPDATE"
                    ),
                    {"fid": file_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if parse_file is None:
            raise BusinessError(400, "解析文件记录不存在", 400)
        previous_pointer = parse_file["latest_parse_task_id"]
        retry = None
        if previous_pointer:
            latest = (
                (
                    await db.execute(
                        text(
                            "SELECT parsed_bucket_name,parsed_object_key "
                            "FROM document_parsed_log WHERE task_id=:tid"
                        ),
                        {"tid": previous_pointer},
                    )
                )
                .mappings()
                .one_or_none()
            )
            pipeline = (
                (
                    await db.execute(
                        text(
                            "SELECT pipeline_status FROM document_parse_pipeline "
                            "WHERE task_id=:tid"
                        ),
                        {"tid": previous_pointer},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                latest is None
                or pipeline is None
                or pipeline["pipeline_status"] not in {"SUCCESS", "FAILED"}
            ):
                return {
                    "fileId": file_id,
                    "originalFilename": file["original_filename"],
                    "frontendStatus": "parsing",
                    "taskId": previous_pointer,
                    "alreadyRunning": True,
                    "assetSummary": await _asset_summary(file, required=False),
                }
            if pipeline["pipeline_status"] == "SUCCESS":
                raise BusinessError(409, "文件已解析成功，无需重复解析", 409)
            if latest["parsed_object_key"]:
                retry = latest
        summary = await _asset_summary(file, required=True)
        if (
            summary
            and (
                summary.get("blockingIssues")
                or summary.get("missingCount", 0) > 0
                or summary.get("ambiguousCount", 0) > 0
                or summary.get("unsupportedCount", 0) > 0
            )
            and not ignore_missing_assets
        ):
            raise BusinessError(
                30020,
                "文档存在未解决的本地图片",
                409,
                data={"errorKind": "ASSET_MISSING", "assetSummary": summary},
            )
        task_id = str(uuid4())
        await db.execute(
            text("UPDATE document_parse_file SET latest_parse_task_id=:tid " "WHERE id=:id"),
            {"tid": task_id, "id": parse_file["id"]},
        )
        pdf_backend = None
        if file["file_suffix"] == "pdf":
            value = (
                await db.execute(
                    text(
                        "SELECT pdf_config FROM dataset_parse_config "
                        "WHERE user_id=:uid AND dataset_id=:did"
                    ),
                    {"uid": user_id, "did": file["dataset_id"]},
                )
            ).scalar_one_or_none()
            if value:
                pdf = json.loads(value) if isinstance(value, str) else value
                candidate = pdf.get("pdf_parser_backend")
                if candidate in {"auto", "mineru", "opendataloader", "naive"}:
                    pdf_backend = candidate
        message = ParseTaskMessage.build(
            task_id=task_id,
            original_file_id=file_id,
            document_parse_task_id=int(parse_file["id"]),
            user_id=user_id,
            dataset_id=int(file["dataset_id"]),
            file_type=file["file_suffix"],
            source_bucket=file["bucket_name"],
            source_object_key=file["object_key"],
            source_filename=file["original_filename"],
            md_bucket=retry["parsed_bucket_name"] if retry else settings.MINIO_PRIVATE_BUCKET,
            md_object_key=retry["parsed_object_key"] if retry else _md_key(file, task_id),
            trigger_mode=trigger_mode,
            pdf_parser_backend=pdf_backend,
            is_retry=retry is not None,
            previous_task_id=previous_pointer if retry else None,
        )
        payload = message.get_payload().model_dump(by_alias=True, exclude_none=True)
        payload.pop("message_id", None)
        payload.pop("timestamp", None)
        event_key = await enqueue(
            db,
            topic=ParseTaskMessage.MQ_NAME,
            payload=payload,
            key=file["file_suffix"],
            event_key=f"parse:{task_id}",
        )
    # The pointer and exact retry payload are committed together. A lost broker
    # acknowledgement can be retried with the same task ID by the outbox worker.
    if not await publish_one(event_key, mq=mq):
        audit_event("PARSE_TASK_PUBLISH", "failed", actor_id=user_id, target_id=file_id)
        raise BusinessError(500, "解析提交失败，请稍后重试", 500)
    audit_event("PARSE_TASK_PUBLISH", "success", actor_id=user_id, target_id=file_id)
    return {
        "fileId": file_id,
        "originalFilename": file["original_filename"],
        "frontendStatus": "parsing",
        "taskId": task_id,
        "alreadyRunning": False,
        "assetSummary": summary,
    }
