"""Cross-process document and branch mutation guard backed by MySQL GET_LOCK."""

from __future__ import annotations

import hashlib
import time
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import AsyncIterator, Protocol, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from src.config import settings
from src.database import get_async_engine
from src.observability.logging import safe_exception_stack, truncate_log_value
from src.utils.logger import logger

from .index_mutation_models import IndexBranch


class IndexMutationLockTimeout(TimeoutError):
    """The document and branch lock was not acquired within the timeout."""


class IndexMutationLockLost(RuntimeError):
    """The pinned MySQL connection could not confirm advisory-lock release."""


class StaleIndexMutationError(RuntimeError):
    """A writer or repair no longer owns the current parse attempt."""


@dataclass(frozen=True, slots=True)
class CurrentTaskSnapshot:
    """Current pipeline state read while holding a mutation lock."""

    pipeline_id: int
    task_id: str
    pipeline_status: str
    superseded_by_task_id: str | None


class MutationGuardProtocol(Protocol):
    def hold(
        self,
        *,
        doc_id: int,
        branch: IndexBranch,
        timeout_seconds: int | None = None,
    ) -> AbstractAsyncContextManager[AsyncConnection | None]: ...

    async def assert_current_task(
        self,
        connection: AsyncConnection | None,
        *,
        doc_id: int,
        task_id: str,
        allowed_pipeline_statuses: Sequence[str],
        require_unsuperseded: bool = False,
    ) -> CurrentTaskSnapshot | None: ...


class IndexMutationGuard:
    """Serialize external mutations for the same document and index branch.

    GET_LOCK is connection-scoped.  An AsyncConnection is checked out for the
    complete critical section; transaction commits therefore do not return the
    connection to the pool or release the advisory lock.  ``assert_current_task``
    additionally takes a shared row lock on the current parse-file/pipeline rows;
    callers must leave that transaction open until ``hold`` exits so Java cannot
    switch ``latest_parse_task_id`` halfway through an external mutation.
    """

    def __init__(
        self,
        *,
        engine: AsyncEngine | None = None,
        default_timeout_seconds: int | None = None,
    ) -> None:
        self._engine = engine
        configured = getattr(settings, "INDEX_MUTATION_LOCK_TIMEOUT_SECONDS", 10)
        self._default_timeout_seconds = (
            int(configured) if default_timeout_seconds is None else int(default_timeout_seconds)
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine or get_async_engine()

    @staticmethod
    def lock_name(doc_id: int, branch: IndexBranch) -> str:
        raw = f"{int(doc_id)}:{branch.value}".encode("utf-8")
        return f"tolink:index:{hashlib.sha256(raw).hexdigest()[:40]}"

    @asynccontextmanager
    async def hold(
        self,
        *,
        doc_id: int,
        branch: IndexBranch,
        timeout_seconds: int | None = None,
    ) -> AsyncIterator[AsyncConnection]:
        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else max(0, int(timeout_seconds))
        )
        name = self.lock_name(doc_id, branch)
        async with self.engine.connect() as connection:
            wait_started = time.monotonic()
            try:
                acquired = await connection.scalar(
                    text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
                    {"lock_name": name, "timeout_seconds": timeout},
                )
            except Exception as exc:
                wait_ms = int((time.monotonic() - wait_started) * 1000)
                logger.bind(
                    error_type=type(exc).__name__,
                    error_message=truncate_log_value(exc),
                    stack_trace=safe_exception_stack(exc),
                ).error(
                    "[IndexMutationGuard] event=lock_error doc_id={} branch={} "
                    "wait_ms={} timeout_seconds={} timeout_count=0 error_type={}",
                    doc_id,
                    branch.value,
                    wait_ms,
                    timeout,
                    type(exc).__name__,
                )
                raise
            await connection.commit()
            wait_ms = int((time.monotonic() - wait_started) * 1000)
            if int(acquired or 0) != 1:
                logger.warning(
                    "[IndexMutationGuard] event=lock_timeout doc_id={} branch={} "
                    "wait_ms={} timeout_seconds={} timeout_count=1",
                    doc_id,
                    branch.value,
                    wait_ms,
                    timeout,
                )
                raise IndexMutationLockTimeout(
                    f"timed out acquiring index mutation lock for doc={doc_id} "
                    f"branch={branch.value}"
                )
            logger.info(
                "[IndexMutationGuard] event=lock_acquired doc_id={} branch={} "
                "wait_ms={} timeout_seconds={} timeout_count=0",
                doc_id,
                branch.value,
                wait_ms,
                timeout,
            )
            body_error: BaseException | None = None
            try:
                yield connection
            except BaseException as exc:
                body_error = exc
                raise
            finally:
                try:
                    if connection.in_transaction():
                        await connection.rollback()
                    released = await connection.scalar(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": name},
                    )
                    await connection.commit()
                    if int(released or 0) != 1:
                        raise RuntimeError(
                            f"MySQL did not confirm RELEASE_LOCK for {name}: {released!r}"
                        )
                except Exception as exc:
                    # Returning a DBAPI connection to SQLAlchemy's pool does
                    # not physically close it and therefore does not release a
                    # MySQL connection-scoped lock.  Invalidate it so the pool
                    # must discard the underlying session.
                    await connection.invalidate(exc)
                    if body_error is None:
                        raise IndexMutationLockLost(
                            f"lost index mutation lock for doc={doc_id} branch={branch.value}"
                        ) from exc

    async def assert_current_task(
        self,
        connection: AsyncConnection | None,
        *,
        doc_id: int,
        task_id: str,
        allowed_pipeline_statuses: Sequence[str],
        require_unsuperseded: bool = False,
    ) -> CurrentTaskSnapshot:
        if connection is None:
            raise StaleIndexMutationError("real mutation guard requires a pinned connection")
        statuses = tuple(str(value) for value in allowed_pipeline_statuses)
        if not statuses:
            raise ValueError("allowed_pipeline_statuses must not be empty")

        predicates = " OR ".join(
            f"p.pipeline_status = :status_{index}" for index in range(len(statuses))
        )
        params: dict[str, object] = {"doc_id": int(doc_id), "task_id": task_id}
        params.update({f"status_{index}": value for index, value in enumerate(statuses)})
        unsuperseded = " AND p.superseded_by_task_id IS NULL" if require_unsuperseded else ""
        result = await connection.execute(
            text(
                "SELECT p.id, p.task_id, p.pipeline_status, p.superseded_by_task_id "
                "FROM document_parse_file AS f "
                "JOIN document_parse_pipeline AS p "
                "  ON p.task_id = f.latest_parse_task_id "
                " AND p.document_parse_file_id = f.id "
                " AND p.document_original_file_id = f.document_original_file_id "
                "WHERE f.document_original_file_id = :doc_id "
                "  AND f.latest_parse_task_id = :task_id "
                f"  AND ({predicates})"
                f"{unsuperseded} "
                "LIMIT 1 LOCK IN SHARE MODE"
            ),
            params,
        )
        row = result.first()
        if row is None:
            await self._log_current_task_miss(
                connection,
                doc_id=doc_id,
                task_id=task_id,
                allowed_pipeline_statuses=statuses,
                require_unsuperseded=require_unsuperseded,
            )
            raise StaleIndexMutationError(
                f"task {task_id} is not current or eligible for doc {doc_id}"
            )
        return CurrentTaskSnapshot(
            pipeline_id=int(row[0]),
            task_id=str(row[1]),
            pipeline_status=str(row[2]),
            superseded_by_task_id=row[3],
        )

    @staticmethod
    async def _log_current_task_miss(
        connection: AsyncConnection,
        *,
        doc_id: int,
        task_id: str,
        allowed_pipeline_statuses: Sequence[str],
        require_unsuperseded: bool,
    ) -> None:
        """Classify a failed current-task fence without inventing a missing pointer."""

        result = await connection.execute(
            text(
                "SELECT latest_parse_task_id FROM document_parse_file "
                "WHERE document_original_file_id = :doc_id LIMIT 1"
            ),
            {"doc_id": int(doc_id)},
        )
        row = result.first()
        current_task_id = None if row is None else row[0]
        if current_task_id is None:
            logger.error(
                "[IndexMutationGuard] event=current_task_pointer_missing doc_id={} "
                "expected_task_id={}",
                doc_id,
                task_id,
            )
            return
        logger.warning(
            "[IndexMutationGuard] event=current_task_not_eligible doc_id={} "
            "expected_task_id={} current_task_id={} allowed_pipeline_statuses={} "
            "require_unsuperseded={}",
            doc_id,
            task_id,
            str(current_task_id),
            tuple(allowed_pipeline_statuses),
            require_unsuperseded,
        )


class NoopIndexMutationGuard:
    """Explicit test double; production factories inject the real guard."""

    @asynccontextmanager
    async def hold(
        self,
        *,
        doc_id: int,
        branch: IndexBranch,
        timeout_seconds: int | None = None,
    ) -> AsyncIterator[None]:
        _ = (doc_id, branch, timeout_seconds)
        yield None

    async def assert_current_task(
        self,
        connection: AsyncConnection | None,
        *,
        doc_id: int,
        task_id: str,
        allowed_pipeline_statuses: Sequence[str],
        require_unsuperseded: bool = False,
    ) -> None:
        _ = (
            connection,
            doc_id,
            task_id,
            allowed_pipeline_statuses,
            require_unsuperseded,
        )
        return None


@lru_cache(maxsize=1)
def get_index_mutation_guard() -> IndexMutationGuard:
    """返回进程内共享的 MySQL 索引写入互斥器。"""

    return IndexMutationGuard()
