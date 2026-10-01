"""新用户购物演示库：独立原件、原子注册记录及既有解析 outbox。"""

from __future__ import annotations

import asyncio
from importlib.resources import files
from typing import Any, Callable, cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.application.datasets import create_dataset_records
from src.application.management_outbox import enqueue
from src.application.model_configs import require_executable
from src.application.parse_task_control import _md_key
from src.config import settings
from src.core.mq.messages.parse_task import ParseTaskMessage
from src.database import get_db_context
from src.observability.audit import audit_event
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

DOCUMENT_NAMES = (
    "好邻生活商店商品选购指南.md",
    "好邻生活商店下单与配送说明.md",
    "好邻生活商店退换货与售后说明.md",
)
DATASET_NAME = "购物演示数据集"
_CONFIG_FIELDS = {
    "EMBEDDING": "DEMO_DATASET_DENSE_CONFIG_ID",
    "SPARSE_EMBEDDING": "DEMO_DATASET_SPARSE_CONFIG_ID",
    "CHAT": "DEMO_DATASET_CHAT_CONFIG_ID",
}


async def _storage_call(fn: Callable[..., Any], *args: Any) -> Any:
    """取消协程不会停止存储线程；先等 SDK 的有界请求结束，再交给上层清理。"""
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


async def _platform_config(db: AsyncSession, capability: str, config_id: int | None) -> int:
    if config_id is None:
        candidates = (
            (
                await db.execute(
                    text(
                        "SELECT id FROM llm_model_config "
                        "WHERE scope='SYSTEM' AND owner_user_id=0 AND is_active=1 "
                        "AND capability=:cap ORDER BY id LIMIT 2"
                    ),
                    {"cap": capability},
                )
            )
            .scalars()
            .all()
        )
        if len(candidates) != 1:
            raise BusinessError(503, "演示数据集平台模型尚未配置完成", 503)
        config_id = int(candidates[0])
    try:
        row = await require_executable(db, 0, config_id, capability)
    except BusinessError as exc:
        raise BusinessError(503, "演示数据集平台模型尚未配置完成", 503) from exc
    if row["scope"] != "SYSTEM" or int(row["owner_user_id"]) != 0:
        raise BusinessError(503, "演示数据集平台模型尚未配置完成", 503)
    return config_id


class DemoDatasetSeed:
    """一次注册尝试持有一份原件；事务提交后将所有权交给普通文件生命周期。"""

    def __init__(self, configs: dict[str, int], storage: BaseObjectStorage) -> None:
        self.configs = configs
        self.storage = storage
        self.bucket = settings.MINIO_RAW_BUCKET
        self.prefix = f"demo/{uuid4().hex}"
        self.documents: list[tuple[str, str, int]] = []
        self._attempted_keys: list[str] = []

    @classmethod
    async def prepare(cls) -> DemoDatasetSeed | None:
        # 旧迁移/只读部署保留原注册行为，不绕过 B4/B5 的唯一写入者门禁。
        if not (
            settings.DEMO_DATASET_ENABLED
            and settings.B4_DATASET_WRITES_ENABLED
            and settings.B5_FILE_WRITES_ENABLED
        ):
            return None
        seed = None
        try:
            if (
                not settings.B5_INTERNAL_FILE_BASE_URL
                or not settings.B5_INTERNAL_FILE_SERVICE_TOKEN
            ):
                raise BusinessError(503, "演示数据集文件服务尚未就绪", 503)
            async with get_db_context() as db:
                configs = {
                    cap: await _platform_config(db, cap, getattr(settings, field))
                    for cap, field in _CONFIG_FIELDS.items()
                }
            # 一次性读齐打包素材，缺文件时不开始写对象。
            root = files("src").joinpath("assets", "demo_dataset")
            documents = [(name, root.joinpath(name).read_bytes()) for name in DOCUMENT_NAMES]
            if any(not content for _, content in documents):
                raise ValueError("empty demo document")
            storage = StorageFactory.get_storage(request_timeout_seconds=5, max_attempts=2)
            seed = cls(configs, storage)
            for name, content in documents:
                key = f"{seed.prefix}/{name}"
                # 超时可能发生在服务端已写入后，失败的当前 key 也要补偿。
                seed._attempted_keys.append(key)
                await _storage_call(
                    storage.upload_bytes, seed.bucket, key, content, "text/markdown"
                )
                seed.documents.append((name, key, len(content)))
            return seed
        except BaseException as exc:
            if seed is not None:
                await seed.discard()
            if isinstance(exc, (asyncio.CancelledError, BusinessError)):
                raise
            if not isinstance(exc, Exception):
                raise
            audit_event("DEMO_DATASET_PREPARE", "failed")
            raise BusinessError(503, "演示数据集暂不可用，请稍后重试", 503) from exc

    async def discard(self) -> None:
        """仅用于提交前失败的尝试，不清理已成功注册的文件。"""
        for key in reversed(self._attempted_keys):
            try:
                await _storage_call(self.storage.remove_object, self.bucket, key)
            except Exception:
                audit_event("DEMO_DATASET_OBJECT_CLEANUP", "failed")

    async def bind(self, db: AsyncSession, user_id: int) -> int:
        """必须与 sys_user 插入在同一事务；不在事务中进行存储或 MQ 请求。"""
        try:
            return await self._bind(db, user_id)
        except BusinessError:
            raise
        except Exception as exc:
            # 演示表写入异常不是用户名/邮箱冲突，不能被 B1 错误转换误报。
            audit_event("DEMO_DATASET_BIND", "failed", actor_id=user_id)
            raise BusinessError(503, "演示数据集暂不可用，请稍后重试", 503) from exc

    async def _bind(self, db: AsyncSession, user_id: int) -> int:
        for cap, config_id in self.configs.items():
            await _platform_config(db, cap, config_id)
        dataset_id = await create_dataset_records(
            db,
            user_id,
            DATASET_NAME,
            "三份虚构商店资料，涵盖商品选购、下单配送和退换货，可直接用于对话体验。",
            self.configs["EMBEDDING"],
            self.configs["SPARSE_EMBEDDING"],
        )
        for cap, config_id in self.configs.items():
            await db.execute(
                text(
                    "INSERT INTO llm_capability_default(scope,owner_user_id,capability,config_id) "
                    "VALUES('USER',:uid,:cap,:cid)"
                ),
                {"uid": user_id, "cap": cap, "cid": config_id},
            )
        for name, key, size in self.documents:
            await self._bind_file(db, user_id, dataset_id, name, key, size)
        return dataset_id

    async def _bind_file(
        self, db: AsyncSession, user_id: int, dataset_id: int, name: str, key: str, size: int
    ) -> None:
        result = await db.execute(
            text(
                "INSERT INTO document_original_file "
                "(dataset_id,user_id,original_filename,file_suffix,file_size,content_type,"
                "bucket_name,object_key,upload_status,is_upload_success,is_deleted,deleted_seq) "
                "VALUES(:did,:uid,:name,'md',:size,'text/markdown',:bucket,:key,'success',1,0,0)"
            ),
            {
                "did": dataset_id,
                "uid": user_id,
                "name": name,
                "size": size,
                "bucket": self.bucket,
                "key": key,
            },
        )
        file_id = int(cast(CursorResult[Any], result).lastrowid)
        base_url = cast(str, settings.B5_INTERNAL_FILE_BASE_URL).rstrip("/")
        await db.execute(
            text("UPDATE document_original_file SET file_url=:url WHERE id=:id"),
            {"id": file_id, "url": f"{base_url}/api/v1/internal/files/{file_id}/content"},
        )
        task_id = str(uuid4())
        result = await db.execute(
            text(
                "INSERT INTO document_parse_file "
                "(document_original_file_id,dataset_id,user_id,original_filename,parse_count,latest_parse_task_id) "
                "VALUES(:fid,:did,:uid,:name,0,:tid)"
            ),
            {"fid": file_id, "did": dataset_id, "uid": user_id, "name": name, "tid": task_id},
        )
        parse_file_id = int(cast(CursorResult[Any], result).lastrowid)
        message = ParseTaskMessage.build(
            task_id=task_id,
            original_file_id=file_id,
            document_parse_task_id=parse_file_id,
            user_id=user_id,
            dataset_id=dataset_id,
            file_type="md",
            source_bucket=self.bucket,
            source_object_key=key,
            source_filename=name,
            md_bucket=settings.MINIO_PRIVATE_BUCKET,
            md_object_key=_md_key(
                {"user_id": user_id, "dataset_id": dataset_id, "original_filename": name}, task_id
            ),
            trigger_mode="upload_auto",
            pdf_parser_backend=None,
            is_retry=False,
        )
        payload = message.get_payload().model_dump(by_alias=True, exclude_none=True)
        payload.pop("message_id", None)
        payload.pop("timestamp", None)
        await enqueue(
            db,
            topic=ParseTaskMessage.MQ_NAME,
            payload=payload,
            key="md",
            event_key=f"parse:{task_id}",
        )
