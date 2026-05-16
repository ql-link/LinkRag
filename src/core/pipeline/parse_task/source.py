"""解析任务的对象存储 I/O。"""

from __future__ import annotations

from loguru import logger

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.services.storage.base import BaseObjectStorage


class ParseSourceIO:
    """封装对象存储侧的源文件下载与 Markdown 上传。"""

    def __init__(self, storage: BaseObjectStorage) -> None:
        self._storage = storage

    @property
    def storage(self) -> BaseObjectStorage:
        """对外暴露底层 storage，供需要拼接 URL/直接复用的场景使用。"""
        return self._storage

    def download(self, payload: ParseTaskPayload) -> bytes:
        """从对象存储下载待解析原文件。

        Raises:
            Exception: 对象存储下载失败时由底层实现抛出。
        """
        logger.info(
            f"[ParseSourceIO] download file: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}"
        )
        return self._storage.download_bytes(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

    def upload_markdown(self, payload: ParseTaskPayload, markdown: str) -> None:
        """将解析后的 Markdown 写入对象存储。

        Raises:
            Exception: 对象存储上传失败时由底层实现抛出。
        """
        self._storage.upload_bytes(
            bucket=payload.md_bucket,
            object_key=payload.md_object_key,
            content=markdown.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

    def build_source_file_url(self, payload: ParseTaskPayload) -> str:
        """供 MinerU 等需要远端 URL 拉取的解析后端拼接源文件 URL。"""
        return self._storage.build_object_url(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

    @staticmethod
    def should_skip_source_download(payload: ParseTaskPayload) -> bool:
        """MinerU 精准解析使用远端 URL 拉取文件，无需先把 PDF 下载到本服务。"""
        return (
            payload.file_type.lower() == "pdf"
            and (payload.pdf_parser_backend or "mineru").lower() == "mineru"
        )
