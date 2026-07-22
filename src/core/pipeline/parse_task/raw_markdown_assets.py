"""安全读取 Java 规范化 Markdown 中的 RAW 图片资源。"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote_to_bytes, urlsplit

from loguru import logger

from src.config import settings
from src.observability.logging import safe_exception_stack, truncate_log_value
from src.services.storage.base import BaseObjectStorage

from . import temp_workspace
from ._utils import task_log_context

_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_IMAGE_NAME = re.compile(r"image-[0-9a-f]{64}\.(jpg|png|gif|webp|bmp|tiff)")
_DIRECT_MIME = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


class AssetScopeViolation(ValueError):
    """逻辑 URI 不属于当前解析任务。"""


class AssetReadFailed(RuntimeError):
    """RAW 对象下载或大小校验失败。"""


class ImageDecodeFailed(RuntimeError):
    """BMP/TIFF 无法安全转换为 Vision 支持的 PNG。"""


class RawMarkdownAssetLoader:
    """把当前 fileId 的 ``tolink-raw://`` 图片按批加载为 Vision 字节。"""

    def __init__(
        self,
        storage: BaseObjectStorage,
        *,
        max_bytes: int | None = None,
        download_concurrency: int | None = None,
        temp_dir: Path | None = None,
    ) -> None:
        self._storage = storage
        self._max_bytes = max_bytes or settings.RAW_MARKDOWN_IMAGE_MAX_BYTES
        self._semaphore = asyncio.Semaphore(
            download_concurrency or settings.RAW_MARKDOWN_IMAGE_DOWNLOAD_CONCURRENCY
        )
        self._temp_dir = temp_dir or Path(settings.PARSE_TEMP_DIR)

    @staticmethod
    def expected_base_prefix(payload) -> str:
        return (
            "markdown-assets/v1/"
            f"user-{int(payload.user_id)}/dataset-{int(payload.dataset_id)}/"
            f"file-{int(payload.original_file_id)}/"
        )

    @classmethod
    def is_v1_source(cls, payload) -> bool:
        try:
            expected = cls.expected_base_prefix(payload) + "source/normalized.md"
        except (TypeError, ValueError, AttributeError):
            return False
        return (
            payload.source_bucket == settings.MINIO_RAW_BUCKET
            and payload.source_object_key == expected
        )

    def resolve_object_key(self, uri: str, payload) -> str:
        try:
            parsed = urlsplit(uri)
            # Accessing port also rejects malformed authorities such as ``raw:abc``.
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise AssetScopeViolation("invalid logical URI") from exc
        if (
            parsed.scheme != "tolink-raw"
            or parsed.netloc != "raw"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AssetScopeViolation("invalid logical URI authority")

        segments = parsed.path.split("/")
        if not segments or segments[0] != "" or any(not segment for segment in segments[1:]):
            raise AssetScopeViolation("invalid logical URI path")
        decoded_segments = [self._decode_segment(segment) for segment in segments[1:]]
        object_key = "/".join(decoded_segments)

        try:
            expected_prefix = self.expected_base_prefix(payload)
        except (TypeError, ValueError, AttributeError) as exc:
            raise AssetScopeViolation("invalid task scope") from exc
        if payload.source_bucket != settings.MINIO_RAW_BUCKET:
            raise AssetScopeViolation("unexpected source bucket")
        if payload.source_object_key != expected_prefix + "source/normalized.md":
            raise AssetScopeViolation("unexpected source object")
        image_prefix = expected_prefix + "images/"
        filename = object_key[len(image_prefix) :] if object_key.startswith(image_prefix) else ""
        if not filename or "/" in filename or not _IMAGE_NAME.fullmatch(filename):
            raise AssetScopeViolation("image is outside current file scope")
        return object_key

    async def load_batch(
        self, uris: Iterable[str], payload
    ) -> dict[str, tuple[bytes, str]]:
        unique = list(dict.fromkeys(uris))
        results = await asyncio.gather(*(self.load_one(uri, payload) for uri in unique))
        return {
            uri: loaded
            for uri, loaded in zip(unique, results, strict=True)
            if loaded is not None
        }

    async def load_one(self, uri: str, payload) -> tuple[bytes, str] | None:
        try:
            object_key = self.resolve_object_key(uri, payload)
        except AssetScopeViolation as exc:
            self._log_failure(payload, "image_scope", "ASSET_SCOPE_VIOLATION", exc)
            return None

        extension = object_key.rsplit(".", 1)[-1]
        temp_path = temp_workspace.create_temp_file(
            str(payload.task_id), self._temp_dir, suffix=extension
        )
        try:
            async with self._semaphore:
                await asyncio.to_thread(
                    self._storage.download_to_path,
                    payload.source_bucket,
                    object_key,
                    temp_path,
                )
            size = await asyncio.to_thread(temp_path.stat)
            if size.st_size > self._max_bytes:
                raise AssetReadFailed("RAW image exceeds configured byte limit")
            content = await asyncio.to_thread(temp_path.read_bytes)
            if extension in _DIRECT_MIME:
                return content, _DIRECT_MIME[extension]
            return await asyncio.to_thread(self._convert_to_png, content)
        except ImageDecodeFailed as exc:
            self._log_failure(payload, "image_decode", "IMAGE_DECODE_FAILED", exc)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._log_failure(payload, "image_load", "ASSET_READ_FAILED", exc)
            return None
        finally:
            temp_workspace.safe_unlink(temp_path)

    @staticmethod
    def _decode_segment(segment: str) -> str:
        percent_count = segment.count("%")
        if percent_count and len(_PERCENT_ESCAPE.findall(segment)) != percent_count:
            raise AssetScopeViolation("invalid percent escape")
        try:
            decoded = unquote_to_bytes(segment).decode("utf-8", "strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise AssetScopeViolation("invalid UTF-8 path segment") from exc
        if (
            not decoded
            or decoded in {".", ".."}
            or "/" in decoded
            or "\\" in decoded
            or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
        ):
            raise AssetScopeViolation("unsafe decoded path segment")
        return decoded

    @staticmethod
    def _convert_to_png(content: bytes) -> tuple[bytes, str]:
        try:
            import cv2
            import numpy as np

            image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ImageDecodeFailed("image decode returned empty result")
            encoded, png = cv2.imencode(".png", image)
            if not encoded:
                raise ImageDecodeFailed("PNG encoding failed")
            return png.tobytes(), "image/png"
        except ImageDecodeFailed:
            raise
        except Exception as exc:
            raise ImageDecodeFailed("image conversion failed") from exc

    @staticmethod
    def _log_failure(payload, stage: str, error_kind: str, exc: Exception) -> None:
        logger.bind(
            event="image_enhancement_failed",
            outcome="skipped",
            stage=stage,
            error_kind=error_kind,
            task_id=getattr(payload, "task_id", ""),
            original_file_id=getattr(payload, "original_file_id", None),
            user_id=getattr(payload, "user_id", None),
            dataset_id=getattr(payload, "dataset_id", None),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning(
            "RAW Markdown 图片增强已跳过: {} stage={} error_kind={}",
            task_log_context(payload),
            stage,
            error_kind,
        )


def raw_image_urls(markdown: str) -> list[str]:
    """快速筛出规范化 Markdown 图片目标；Java 已统一为标准 Markdown 节点。"""

    return list(
        dict.fromkeys(
            match.group(1)
            for match in re.finditer(r"!\[[^\]]*]\((tolink-raw://[^)\s]+)\)", markdown)
        )
    )
