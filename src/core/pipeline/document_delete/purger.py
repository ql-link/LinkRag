"""删除链路编排（LINK-55）。

核心铁律：**先删外部存储（Qdrant / ES / OSS），最后删 DB 行**。DB 行（chunk 真值 +
解析三表）是定位外部产物的账本——chunk_id 定位 Qdrant 点、parsed_object_key 定位 OSS
产物。若先删账本，崩溃重试时就再也找不到外部产物，导致永久泄漏。把账本留到最后删，
任何一步失败/重复消费都能从 DB 重读重做，整条链幂等且崩溃安全。

不触碰原文件：``document_original_file`` 行由 Java 软删保留、OSS 原文件对象由 Java 保留；
透传 md（``file_type∈{md,markdown}``）的 ``parsed_object_key`` 指向原文件对象，由
``_PARSED_PRODUCT_PREFIX`` 护栏排除，绝不删原文件。
"""

from __future__ import annotations

import asyncio
import posixpath
from collections import defaultdict

from src.config import settings
from src.core.mq.messages.document_delete import (
    DELETE_TYPE_FILE,
    DocumentDeletePayload,
)
from src.core.pipeline.document_delete.repository import ParseDeleteRepository
from src.core.storage.bm25_backend import build_indexing_pipeline
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.es.pipeline import EsIndexingPipeline
from src.core.storage.qdrant.qdrant_store import QdrantIndexStore
from src.database import get_db_context
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory
from src.utils.logger import logger

# 解析产物对象键根前缀（Java buildMdObjectKey 固定以此开头）。只有落在此根下的
# parsed_object_key 才执行 OSS 前缀删除；透传 md 指向原文件区，前缀不匹配即跳过。
_PARSED_PRODUCT_PREFIX = "parsed/"
# 解析任务目录前缀的最小段数安全阀。Java buildMdObjectKey 规范键的父目录为
# parsed/user-{uid}/dataset-{did}/{Y}/{M}/{D}/{taskId} 共 7 段。设下限拦掉异常浅前缀
# （如 parsed/ 根、parsed/user-*、parsed/user/dataset），防止 remove_prefix 误删整片产物区。
_MIN_TASK_DIR_SEGMENTS = 5


class DocumentDeletePurger:
    """按删除通知清理解析域全部衍生产物。"""

    def __init__(
        self,
        *,
        chunk_repository: ChunkRepository | None = None,
        parse_repository: ParseDeleteRepository | None = None,
        qdrant_store: QdrantIndexStore | None = None,
        es_pipeline: EsIndexingPipeline | None = None,
        storage: BaseObjectStorage | None = None,
        page_size: int | None = None,
    ) -> None:
        self._chunk_repo = chunk_repository or ChunkRepository()
        self._parse_repo = parse_repository or ParseDeleteRepository()
        self._qdrant_store = qdrant_store or QdrantIndexStore()
        self._es_pipeline = es_pipeline or build_indexing_pipeline()
        self._storage = storage or StorageFactory.get_storage()
        self._page_size = page_size or settings.DOCUMENT_DELETE_PAGE_SIZE

    async def purge(self, payload: DocumentDeletePayload) -> None:
        """删除入口：按范围分流。失败向上抛，由消费者归类为暂时性失败重试。"""
        if payload.delete_type == DELETE_TYPE_FILE:
            assert payload.original_file_id is not None  # 反序列化已校验
            await self._purge_file(
                user_id=payload.user_id,
                dataset_id=payload.dataset_id,
                doc_id=payload.original_file_id,
            )
        else:
            await self._purge_dataset(
                user_id=payload.user_id,
                dataset_id=payload.dataset_id,
            )

    async def _purge_dataset(self, *, user_id: int, dataset_id: int) -> None:
        """按数据集枚举名下文件逐个清理（分页：每删完一页恒取表头，取空即止）。"""
        total = 0
        while True:
            async with get_db_context() as db:
                doc_ids = await self._parse_repo.list_doc_ids_by_dataset(
                    db, dataset_id, user_id, limit=self._page_size
                )
            if not doc_ids:
                break
            for doc_id in doc_ids:
                await self._purge_file(user_id=user_id, dataset_id=dataset_id, doc_id=doc_id)
            total += len(doc_ids)
        logger.info(
            f"[DocumentDeletePurger] dataset 清理完成: dataset_id={dataset_id}, "
            f"user_id={user_id}, files={total}"
        )

    async def _purge_file(self, *, user_id: int, dataset_id: int, doc_id: int) -> None:
        """单文件清理：先读路由 → 删 Qdrant → 删 ES → 删 OSS → 最后删 DB 行。"""
        # STEP 1 读路由（只读，不删）：拿到 chunk_id/bucket_id 与 OSS 产物前缀
        async with get_db_context() as db:
            routing = await self._chunk_repo.list_routing_by_doc_id(db, doc_id, user_id)
            parsed_keys = await self._parse_repo.list_parsed_oss_keys_by_doc_id(db, doc_id)

        # STEP 2 删 Qdrant 点：按 bucket_id 分组（一个 user 通常一个 bucket，仍防御性分组）
        grouped: dict[int, list[str]] = defaultdict(list)
        for chunk_id, bucket_id in routing:
            if bucket_id is None:
                continue
            grouped[bucket_id].append(chunk_id)
        for bucket_id, chunk_ids in grouped.items():
            await self._qdrant_store.delete_points(bucket_id=bucket_id, chunk_ids=chunk_ids)

        # STEP 3 删 ES：按 user+dataset+doc 三维 filter（无匹配返 0，幂等）
        await self._es_pipeline.delete_document_index(
            user_id=user_id, dataset_id=dataset_id, doc_id=doc_id
        )

        # STEP 4 删 OSS：对每个解析任务目录前缀整删（md + 图片同目录）；护栏排除原文件
        for prefix, bucket in self._task_dir_prefixes(parsed_keys):
            # 存储 SDK 为同步实现，放线程池避免阻塞事件循环
            await asyncio.to_thread(self._storage.remove_prefix, bucket, prefix)

        # STEP 5 最后删 DB 行（单事务）：chunk 真值 + 解析三表，外部产物确认清掉后才销账
        async with get_db_context() as db:
            await self._chunk_repo.delete_by_doc_id(db, doc_id)
            await self._parse_repo.delete_parse_rows_by_doc_id(db, doc_id)
            await db.commit()

        logger.info(
            f"[DocumentDeletePurger] file 清理完成: doc_id={doc_id}, dataset_id={dataset_id}, "
            f"user_id={user_id}, qdrant_chunks={sum(len(v) for v in grouped.values())}"
        )

    @staticmethod
    def _task_dir_prefixes(
        parsed_keys: list[tuple[str | None, str | None]],
    ) -> list[tuple[str, str]]:
        """从 parsed_log 行算出去重后的 ``(prefix, bucket)`` 删除目标。

        仅保留 ``parsed_object_key`` 落在 ``parsed/`` 根下的行（解析产物），透传 md 指向
        原文件对象的行被排除（护栏）。前缀取 ``parsed_object_key`` 的父目录（= 解析任务
        目录 ``parsed/.../{taskId}/``），整删即清掉 Markdown + 全部图片。
        """
        seen: set[tuple[str, str]] = set()
        targets: list[tuple[str, str]] = []
        for bucket, object_key in parsed_keys:
            if not bucket or not object_key:
                continue
            if not object_key.startswith(_PARSED_PRODUCT_PREFIX):
                continue  # 护栏：非解析产物区（含透传 md 原文件）一律跳过
            parent = posixpath.dirname(object_key)
            if not parent:
                continue
            # 深度安全阀：规范 key 父目录为 parsed/user-*/dataset-*/Y/M/D/taskId（7 段）。
            # 异常浅 key（如 parsed/x.md → parent="parsed"）会得到 "parsed/" 这类宽前缀，
            # remove_prefix 会误删整片产物区——拦掉并告警，绝不下发宽前缀删除。
            segment_count = len([seg for seg in parent.split("/") if seg])
            if segment_count < _MIN_TASK_DIR_SEGMENTS:
                logger.warning(
                    "[DocumentDeletePurger] 跳过异常浅的解析产物前缀，疑似脏数据: "
                    f"bucket={bucket}, object_key={object_key}, parent_segments={segment_count}"
                )
                continue
            prefix = parent + "/"
            key = (prefix, bucket)
            if key in seen:
                continue
            seen.add(key)
            targets.append((prefix, bucket))
        return targets
