"""B5 bounded background upload using existing storage, DB and parse controls."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from src.api.management_http import BusinessError
from src.application.datasets import owned_dataset
from src.application.document_files import _dto
from src.application.document_runtime_config import current_limits
from src.application.markdown_asset_bundle import AssetFile, BundleUpload, materialize, preflight
from src.application.parse_task_control import submit_parse
from src.config import settings
from src.core.pipeline.parse_task.temp_workspace import create_temp_file, safe_unlink
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event
from src.services.storage.factory import StorageFactory


@dataclass(frozen=True)
class UploadJob:
    file_id: int
    user_id: int
    dataset_id: int
    filename: str
    content_type: str
    path: Path
    object_key: str
    parse_immediately: bool
    bundle_uploads: tuple[BundleUpload, ...] = ()
    temp_paths: tuple[Path, ...] = ()


class DocumentUploadExecutor:
    """Per-process bounded queue; DB CAS and stale scan provide restart recovery."""

    def __init__(self, *, workers: int = 4, capacity: int = 32) -> None:
        self._queue: asyncio.Queue[UploadJob] = asyncio.Queue(maxsize=capacity)
        self._tasks: list[asyncio.Task] = []
        self._workers = workers
        self._closing = False

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._worker()) for _ in range(self._workers)]

    async def close(self) -> None:
        self._closing = True
        # Let accepted uploads finish before stopping workers. Cancelling an
        # asyncio.to_thread upload leaves the underlying storage write running.
        await self._queue.join()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def submit(self, job: UploadJob) -> None:
        if self._closing or not self._tasks:
            raise RuntimeError("upload executor is not accepting jobs")
        self._queue.put_nowait(job)

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await _process(job)
            except asyncio.CancelledError:
                try:
                    await _mark_failed(job.file_id, "文件上传失败，请稍后重试")
                except Exception:
                    audit_event("DOCUMENT_UPLOAD_STATUS_REPAIR", "failed", target_id=job.file_id)
                raise
            except Exception:
                audit_event("DOCUMENT_UPLOAD", "failed", target_id=job.file_id)
                try:
                    await _mark_failed(job.file_id, "文件上传失败，请稍后重试")
                except Exception:
                    audit_event("DOCUMENT_UPLOAD_STATUS_REPAIR", "failed", target_id=job.file_id)
            finally:
                safe_unlink(job.path)
                for path in job.temp_paths:
                    safe_unlink(path)
                self._queue.task_done()


async def _mark_failed(file_id: int, reason: str) -> None:
    async with write_transaction() as db:
        await db.execute(
            text(
                "UPDATE document_original_file SET upload_status='failed', "
                "is_upload_success=0,failure_reason=:reason "
                "WHERE id=:fid AND upload_status='uploading'"
            ),
            {"fid": file_id, "reason": reason},
        )


async def _process(job: UploadJob) -> None:
    storage = StorageFactory.get_storage()
    uploads = job.bundle_uploads or (BundleUpload(job.path, job.object_key, job.content_type),)
    uploaded: list[str] = []
    try:
        for item in uploads:
            # A storage timeout may happen after the object was written.
            uploaded.append(item.object_key)
            await asyncio.to_thread(
                storage.upload_path,
                settings.MINIO_RAW_BUCKET,
                item.object_key,
                item.path,
                item.content_type,
            )
        async with write_transaction() as db:
            base_url = settings.B5_INTERNAL_FILE_BASE_URL
            if not base_url:
                raise RuntimeError("B5 internal file URL is not configured")
            file_url = base_url.rstrip("/")
            file_url += f"/api/v1/internal/files/{job.file_id}/content"
            update = await db.execute(
                text("""
                UPDATE document_original_file
                SET object_key=:key,file_url=:url,upload_status='success',
                    is_upload_success=1,failure_reason=NULL
                WHERE id=:fid AND upload_status='uploading' AND is_deleted=0
            """),
                {"key": job.object_key, "url": file_url, "fid": job.file_id},
            )
            if cast(CursorResult[Any], update).rowcount:
                await db.execute(
                    text("""
                    INSERT INTO document_parse_file
                      (document_original_file_id,dataset_id,user_id,original_filename,parse_count)
                    VALUES(:fid,:did,:uid,:name,0)
                    ON DUPLICATE KEY UPDATE id=id
                """),
                    {
                        "fid": job.file_id,
                        "did": job.dataset_id,
                        "uid": job.user_id,
                        "name": job.filename,
                    },
                )
        if not cast(CursorResult[Any], update).rowcount:
            for key in reversed(uploaded):
                await asyncio.to_thread(storage.remove_object, settings.MINIO_RAW_BUCKET, key)
            audit_event("DOCUMENT_UPLOAD_ORPHAN_CLEANUP", "success", target_id=job.file_id)
            return
    except Exception:
        for key in reversed(uploaded):
            try:
                await asyncio.to_thread(storage.remove_object, settings.MINIO_RAW_BUCKET, key)
            except Exception:
                audit_event("DOCUMENT_UPLOAD_ORPHAN_CLEANUP", "failed", target_id=job.file_id)
        raise
    if job.parse_immediately:
        try:
            await submit_parse(job.user_id, job.file_id, trigger_mode="upload_auto")
        except Exception:
            audit_event("DOCUMENT_AUTO_PARSE", "failed", target_id=job.file_id)


def _filename(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        raise BusinessError(400, "请选择要上传的文件", 400)
    if len(name) > 255:
        raise BusinessError(400, "文件名长度不能超过255个字符", 400)
    if name in {".", ".."} or any(ord(char) < 32 for char in name):
        raise BusinessError(400, "文件名包含非法字符", 400)
    return name


def _validate_plain_markdown(path: Path, suffix: str) -> None:
    if suffix not in {"md", "markdown"}:
        return
    try:
        markdown = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BusinessError(400, "Markdown 文件编码不合法", 400) from exc
    excluded = _excluded_markdown_positions(markdown)

    # The Java scanner ignores remote/data URLs but requires an asset context
    # for local targets. Keep Obsidian targets closed until package scanning is
    # migrated, while undefined reference labels follow Java's ignored behavior.
    def local(target: str) -> bool:
        parts = target.strip().strip("<>").split(maxsplit=1)
        value = parts[0].lower() if parts else ""
        return bool(value) and not value.startswith(("http:", "https:", "data:", "//", "#"))

    inline = re.finditer(r"!\[(?:\\.|[^\]])*\]\(((?:\\.|[^)])*)\)", markdown)
    if any(not excluded[match.start()] and local(match.group(1)) for match in inline):
        raise BusinessError(30010, "Markdown 包含本地图片，请选择图片文件夹或确认缺图上传", 400)
    definitions = {
        match.group(1).strip().lower(): match.group(2).strip()
        for match in re.finditer(r"(?m)^ {0,3}\[([^\]]+)\]:\s*(.+)$", markdown)
        if not excluded[match.start()]
    }
    references = re.finditer(r"!\[([^\]]*)\]\[([^\]]*)\]", markdown)
    if any(
        not excluded[match.start()]
        and local(definitions.get((match.group(2) or match.group(1)).strip().lower(), ""))
        for match in references
    ):
        raise BusinessError(30010, "Markdown 包含本地图片，请选择图片文件夹或确认缺图上传", 400)
    tags = re.finditer(r"<img\b[^>]*>", markdown, re.IGNORECASE | re.DOTALL)
    if any(
        local(source.group(1) or source.group(2) or source.group(3))
        for tag in tags
        if not excluded[tag.start()]
        if (
            source := re.search(
                r"\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag.group(), re.IGNORECASE
            )
        )
    ):
        raise BusinessError(30010, "Markdown 包含本地图片，请选择图片文件夹或确认缺图上传", 400)
    if any(not excluded[match.start()] for match in re.finditer(r"!\[\[[^\]]+\]\]", markdown)):
        raise BusinessError(30010, "Markdown 包含本地图片，请选择图片文件夹或确认缺图上传", 400)


def _excluded_markdown_positions(markdown: str) -> bytearray:
    """Skip fenced and inline code where Java's image scanner finds no references."""
    excluded = bytearray(len(markdown))
    fence_char = ""
    fence_length = 0
    offset = 0
    for line in markdown.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence_char:
            excluded[offset : offset + len(line)] = b"\x01" * len(line)
            if (
                marker
                and marker.group(1)[0] == fence_char
                and len(marker.group(1)) >= fence_length
                and not marker.group(2).strip()
            ):
                fence_char = ""
        elif marker:
            fence_char = marker.group(1)[0]
            fence_length = len(marker.group(1))
            excluded[offset : offset + len(line)] = b"\x01" * len(line)
        offset += len(line)
    index = 0
    while index < len(markdown):
        if markdown[index] != "`" or excluded[index]:
            index += 1
            continue
        end = index
        while end < len(markdown) and markdown[end] == "`":
            end += 1
        run = end - index
        close = end
        while close < len(markdown):
            close = markdown.find("`", close)
            if close < 0:
                break
            closing_end = close
            while closing_end < len(markdown) and markdown[closing_end] == "`":
                closing_end += 1
            if not excluded[close] and closing_end - close == run:
                excluded[index:closing_end] = b"\x01" * (closing_end - index)
                index = closing_end
                break
            close = closing_end
        else:
            index = end
            continue
        if close < 0:
            index = end
    return excluded


_RENAME_ATTEMPTS = 5
_RENAME_MAX_INDEX = 1000


def _renamed(filename: str, index: int) -> str:
    """``简历.pdf`` → ``简历 (2).pdf``；保持后缀，整体不超过 255 字符。"""

    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    tail = f" ({index})" + (f".{ext}" if dot else "")
    return stem[: 255 - len(tail)] + tail


async def _next_free_name(db: Any, user_id: int, dataset_id: int, filename: str, suffix: str) -> str:
    rows = await db.execute(
        text("""
            SELECT original_filename FROM document_original_file
            WHERE dataset_id=:did AND user_id=:uid AND file_suffix=:suffix AND is_deleted=0
        """),
        {"did": dataset_id, "uid": user_id, "suffix": suffix},
    )
    taken = {str(row[0]) for row in rows}
    for index in range(2, _RENAME_MAX_INDEX):
        candidate = _renamed(filename, index)
        if candidate not in taken:
            return candidate
    raise BusinessError(400, "当前数据集下同名原文件过多，请先重命名后再上传", 400)


async def _claim_file_record(
    user_id: int,
    dataset_id: int,
    record_filename: str,
    suffix: str,
    size: int,
    content_type: str | None,
    *,
    rename: bool,
) -> tuple[int, Any, str]:
    """占用（或复用失败记录的）原文件行，返回 ``(file_id, row, 最终文件名)``。"""

    async with write_transaction() as db:
        await owned_dataset(db, user_id, dataset_id)
        existing = (
            (
                await db.execute(
                    text("""
            SELECT id,upload_status FROM document_original_file
            WHERE dataset_id=:did AND user_id=:uid AND original_filename=:name
              AND file_suffix=:suffix AND is_deleted=0 FOR UPDATE
        """),
                    {
                        "did": dataset_id,
                        "uid": user_id,
                        "name": record_filename,
                        "suffix": suffix,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing and existing["upload_status"] != "failed":
            if not rename:
                raise BusinessError(400, "当前数据集下已存在同名原文件，请先重命名后再上传", 400)
            record_filename = await _next_free_name(
                db, user_id, dataset_id, record_filename, suffix
            )
            existing = None
        if existing:
            file_id = int(existing["id"])
            await db.execute(
                text("""
                UPDATE document_original_file
                SET upload_status='uploading',is_upload_success=0,failure_reason=NULL,
                    object_key=NULL,file_url=NULL,file_size=:size,content_type=:mime,
                    bucket_name=:bucket
                WHERE id=:fid AND upload_status='failed'
            """),
                {
                    "size": size,
                    "mime": content_type,
                    "bucket": settings.MINIO_RAW_BUCKET,
                    "fid": file_id,
                },
            )
        else:
            result = await db.execute(
                text("""
                INSERT INTO document_original_file
                  (dataset_id,user_id,original_filename,file_suffix,file_size,content_type,
                   bucket_name,upload_status,is_upload_success,is_deleted,deleted_seq)
                VALUES(:did,:uid,:name,:suffix,:size,:mime,:bucket,'uploading',0,0,0)
            """),
                {
                    "did": dataset_id,
                    "uid": user_id,
                    "name": record_filename,
                    "suffix": suffix,
                    "size": size,
                    "mime": content_type,
                    "bucket": settings.MINIO_RAW_BUCKET,
                },
            )
            file_id = int(cast(CursorResult[Any], result).lastrowid)
        created_row = (
            (
                await db.execute(
                    text("SELECT * FROM document_original_file WHERE id=:fid"),
                    {"fid": file_id},
                )
            )
            .mappings()
            .one()
        )
    return file_id, created_row, record_filename


async def upload(
    user_id: int,
    dataset_id: int,
    file: UploadFile,
    *,
    parse_immediately: bool,
    executor: DocumentUploadExecutor,
    match_mode: str | None = None,
    document_path: str | None = None,
    assets: list[UploadFile] | None = None,
    asset_relative_paths: list[str] | None = None,
    asset_inventory_paths: list[str] | None = None,
    rename_on_conflict: bool = False,
) -> dict:
    """``rename_on_conflict``：同名且未失败的原文件已存在时自动改名为 ``name (n).ext``，
    而不是返回 400。仅接入应用 API 开启（其用户无法感知资料库内已有文件名）；
    Web 端保持拒绝重名，Markdown 资源包不改名（路径与图片引用绑定）。
    """
    # Reject an unrelated dataset before accepting and spooling multipart data.
    # Recheck ownership under the write transaction below to cover deletion races.
    async with get_db_context() as db:
        await owned_dataset(db, user_id, dataset_id)
    filename = _filename(file.filename)
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    assets = assets or []
    asset_relative_paths = asset_relative_paths or []
    asset_inventory_paths = asset_inventory_paths or []
    match_mode = (match_mode or "").strip().upper() or None
    if match_mode and match_mode not in {"FULL_PATH", "SHALLOW_BASENAME"}:
        raise BusinessError(400, "不支持的 Markdown 图片匹配模式", 400)
    has_context = bool(
        match_mode or document_path or assets or asset_relative_paths or asset_inventory_paths
    )
    if has_context and suffix not in {"md", "markdown"}:
        raise BusinessError(400, "仅 Markdown 文件支持配套图片", 400)
    if not match_mode and (assets or asset_relative_paths):
        raise BusinessError(30010, "Markdown 包含本地图片，请选择图片文件夹或确认缺图上传", 400)
    if len(assets) != len(asset_relative_paths):
        raise BusinessError(400, "配套图片和路径数量不一致", 400)
    limits = await current_limits()
    if suffix not in limits.allowed_suffixes:
        raise BusinessError(400, "当前文件格式暂不支持", 400)
    # Parse workers clean only top-level files at startup. Keep accepted upload
    # spools in a child directory so another worker's startup cannot remove one.
    temp_dir = Path(settings.PARSE_TEMP_DIR) / "management_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = create_temp_file(str(user_id), temp_dir, suffix="." + suffix)
    asset_temp_paths: list[Path] = []
    materialized_paths: tuple[Path, ...] = ()
    size = 0
    try:
        with path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limits.max_size_bytes:
                    raise BusinessError(400, "文件大小超过限制", 400)
                output.write(chunk)
        if size == 0:
            raise BusinessError(400, "请选择要上传的文件", 400)
        plan = None
        if match_mode:
            if len(assets) > 200 or len(asset_inventory_paths) > 5000:
                raise BusinessError(30017, "图片数量超过限制", 400)
            source_assets: list[AssetFile] = []
            bundle_size = size
            for index, asset in enumerate(assets):
                asset_path = create_temp_file(str(user_id), temp_dir, suffix=".asset")
                asset_temp_paths.append(asset_path)
                asset_size = 0
                with asset_path.open("wb") as output:
                    while chunk := await asset.read(1024 * 1024):
                        asset_size += len(chunk)
                        if asset_size > 20 * 1024 * 1024:
                            raise BusinessError(30016, "单张图片大小超过限制", 400)
                        bundle_size += len(chunk)
                        if bundle_size > 80 * 1024 * 1024:
                            raise BusinessError(30018, "Markdown 资源包总大小超过限制", 400)
                        output.write(chunk)
                source_assets.append(
                    AssetFile(
                        asset_relative_paths[index],
                        asset.filename or "",
                        asset_path,
                        asset.content_type,
                        asset_size,
                    )
                )
            plan = preflight(
                path, filename, match_mode, document_path, source_assets, asset_inventory_paths
            )
        else:
            _validate_plain_markdown(path, suffix)
        record_filename = plan.document_path if plan else filename
        rename = rename_on_conflict and plan is None
        attempts = _RENAME_ATTEMPTS if rename else 1
        for attempt in range(attempts):
            try:
                file_id, created_row, record_filename = await _claim_file_record(
                    user_id,
                    dataset_id,
                    record_filename,
                    suffix,
                    size,
                    file.content_type,
                    rename=rename,
                )
                break
            except IntegrityError:
                # 并发改名撞上同一候选名：唯一键兜底，下一轮会看到对方已占用的名字。
                if attempt + 1 >= attempts:
                    raise
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        # The file ID keeps a same-name reupload from overwriting a soft-
        # deleted RAW original from the same day.
        object_key = f"{user_id}/{dataset_id}/{now:%Y/%m/%d}/{file_id}/{record_filename}"
        bundle_uploads: tuple[BundleUpload, ...] = ()
        if plan:
            try:
                object_key, bundle_uploads, materialized_paths = materialize(
                    plan,
                    path,
                    user_id=user_id,
                    dataset_id=dataset_id,
                    file_id=file_id,
                    directory=temp_dir,
                )
            except Exception:
                await _mark_failed(file_id, "文件上传失败，请稍后重试")
                raise
        job = UploadJob(
            file_id,
            user_id,
            dataset_id,
            record_filename,
            file.content_type or "application/octet-stream",
            path,
            object_key,
            parse_immediately,
            bundle_uploads,
            tuple(asset_temp_paths) + materialized_paths,
        )
        try:
            executor.submit(job)
        except (asyncio.QueueFull, RuntimeError):
            await _mark_failed(file_id, "文件上传失败，请稍后重试")
            raise BusinessError(500, "文件上传失败，请稍后重试", 500) from None
        return _dto(dict(created_row), plan.summary if plan else None)
    except IntegrityError as exc:
        safe_unlink(path)
        for extra in (*asset_temp_paths, *materialized_paths):
            safe_unlink(extra)
        raise BusinessError(400, "当前数据集下已存在同名原文件，请先重命名后再上传", 400) from exc
    except Exception:
        safe_unlink(path)
        for extra in (*asset_temp_paths, *materialized_paths):
            safe_unlink(extra)
        raise


async def fail_stuck_uploads(minutes: int = 10) -> int:
    async with write_transaction() as db:
        result = await db.execute(
            text("""
            UPDATE document_original_file SET upload_status='failed',is_upload_success=0,
                failure_reason='文件上传失败，请稍后重试'
            WHERE upload_status='uploading'
              AND (CASE WHEN :boundary IS NOT NULL AND updated_at < :boundary
                        THEN DATE_ADD(updated_at, INTERVAL 8 HOUR)
                        ELSE updated_at END) < DATE_SUB(NOW(), INTERVAL :minutes MINUTE)
        """),
            {"minutes": minutes, "boundary": settings.FILE_DB_BEIJING_SINCE},
        )
        count = int(cast(CursorResult[Any], result).rowcount or 0)
    # Crash leftovers are not in the in-process queue. Give other workers a
    # wide lease before deleting only our dedicated spool files.
    temp_dir = Path(settings.PARSE_TEMP_DIR) / "management_uploads"
    if temp_dir.is_dir():
        threshold = time.time() - 60 * 60
        for path in temp_dir.iterdir():
            try:
                if (
                    path.is_file()
                    and path.name.startswith("parse-")
                    and path.stat().st_mtime < threshold
                ):
                    safe_unlink(path)
            except OSError:
                continue
    return count
