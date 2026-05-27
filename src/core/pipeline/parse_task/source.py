"""解析任务的对象存储 I/O。"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.services.storage.base import BaseObjectStorage


class ParseSourceIO:
    """封装对象存储侧的源文件下载与 Markdown 上传。

    下载侧仅暴露流式 ``download_to_path``：调用方负责生成本地目标路径并在结束后清理，
    本类不持有临时文件所有权——这样 pipeline 层 try/finally 边界更清晰。
    """

    def __init__(self, storage: BaseObjectStorage) -> None:
        self._storage = storage

    @property
    def storage(self) -> BaseObjectStorage:
        """对外暴露底层 storage，供需要拼接 URL/直接复用的场景使用。"""
        return self._storage

    def download_to_path(self, payload: ParseTaskPayload, dst: Path) -> None:
        """从对象存储流式下载源文件到本地路径。

        Raises:
            OSError: 磁盘满（errno=ENOSPC）等本机 IO 异常，由 pipeline 分类为
                ``TEMP_DISK_FULL``。
            Exception: 对象存储侧 404 / 网络异常，由 pipeline 分类为
                ``SOURCE_FILE_NOT_FOUND``。
        """
        logger.info(
            f"[ParseSourceIO] download file: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}, dst={dst}"
        )
        self._storage.download_to_path(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
            dst=dst,
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
