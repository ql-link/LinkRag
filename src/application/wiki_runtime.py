"""Wiki 标题搜索、正文展开、反向定位和整树读取的应用编排。"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from src.api.recall_session_auth import SessionAuthContext
from src.application.recall_errors import (
    CODE_ALL_SOURCES_FAILED,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_TIMEOUT,
    RecallApiError,
)
from src.config import settings
from src.core.pipeline.recall.document_readiness import MySqlDocumentReadinessGate
from src.core.pipeline.recall.models import RetrieverHit
from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer
from src.core.storage.bm25_backend import build_bm25_recall_backend
from src.core.storage.bm25_retriever import Bm25Retriever
from src.core.storage.wiki_tree.repository import WikiTreeRepository
from src.core.wiki.exceptions import WikiCursorError
from src.core.wiki.models import (
    EffectiveWikiScope,
    WikiChunkLocationRecord,
    WikiChunkRecord,
    WikiHeadingPreview,
    WikiHeadingRecord,
)
from src.core.wiki.search_service import (
    MAX_SEARCH_POSITIONS_PER_CHUNK,
    Bm25RoundRobin,
    RoundRobinPosition,
    WikiCursorCodec,
    WikiResultMerger,
    make_scope_fingerprint,
    normalize_wiki_query,
)
from src.database import get_db_context
from src.utils.logger import logger

BRANCH_EXACT = "exact"
BRANCH_MIXED = "mixed"
BRANCH_HEADING_CHUNKS = "heading_chunks"
SOURCE_EXACT = "exact_title"
SOURCE_PREFIX = "title_prefix"
SOURCE_BM25 = "bm25"


class WikiRuntime:
    """编排授权 SQL、BM25、分页游标及 Chunk 真值回填。"""

    def __init__(
        self,
        *,
        repository: WikiTreeRepository,
        bm25_retriever: Bm25Retriever,
        readiness_gate: MySqlDocumentReadinessGate,
        cursor_codec: WikiCursorCodec,
        page_size: int,
        bm25_top_k_per_dataset: int,
        strict: bool,
    ) -> None:
        """注入 Wiki 仓储、召回器、可见性门禁和固定搜索策略。"""

        self._repository = repository
        self._bm25 = bm25_retriever
        self._readiness = readiness_gate
        self._cursor = cursor_codec
        self._page_size = page_size
        self._bm25_top_k = bm25_top_k_per_dataset
        self._strict = strict

    async def search(
        self,
        ctx: SessionAuthContext,
        *,
        query: str,
        dataset_ids: Sequence[int] | None,
        doc_ids: Sequence[int] | None,
        cursor: str | None,
    ) -> dict[str, Any]:
        """在全局超时内执行 Wiki 搜索，并记录不含正文的结果指标。"""

        normalized_query = normalize_wiki_query(query)
        if not normalized_query:
            raise RecallApiError(400, CODE_INVALID_REQUEST, "query is empty or blank")
        started_at = time.monotonic()
        try:
            payload = await asyncio.wait_for(
                self._search(
                    ctx,
                    normalized_query=normalized_query,
                    dataset_ids=dataset_ids,
                    doc_ids=doc_ids,
                    cursor=cursor,
                ),
                timeout=settings.RECALL_STREAM_TIMEOUT_MS / 1000,
            )
        except asyncio.TimeoutError as exc:
            raise RecallApiError(504, CODE_TIMEOUT, "Wiki search timeout") from exc
        branch = (
            BRANCH_EXACT
            if payload["results"]
            and all(item.get("source") == SOURCE_EXACT for item in payload["results"])
            else BRANCH_MIXED
        )
        logger.bind(
            event="wiki_search_completed",
            request_id=ctx.request_id,
            user_id=ctx.user_id,
            dataset_count=len(dataset_ids or ctx.dataset_ids or ()),
            doc_count=len(doc_ids or ()),
            branch=branch,
            result_count=len(payload["results"]),
            chunk_count=len(payload["chunks"]),
            failed_sources=payload["failed_sources"],
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
        ).info("Wiki search completed")
        return payload

    async def _search(
        self,
        ctx: SessionAuthContext,
        *,
        normalized_query: str,
        dataset_ids: Sequence[int] | None,
        doc_ids: Sequence[int] | None,
        cursor: str | None,
    ) -> dict[str, Any]:
        """解析授权范围与游标分支，优先精确标题，未命中再进入混合召回。"""

        scope = await self._resolve_scope(ctx, dataset_ids=dataset_ids, doc_ids=doc_ids)
        binding = self._search_binding(normalized_query, scope)
        if cursor is not None:
            branch, state = self._decode_search_cursor(cursor, binding=binding)
            if branch == BRANCH_EXACT:
                return await self._exact_page(normalized_query, scope, binding=binding, state=state)
            return await self._mixed_page(normalized_query, scope, binding=binding, state=state)

        # 首次请求必须先查 exact；一旦命中，本页和该游标链都不会调用 prefix/BM25，
        # 保证“完整标题相等”的结果不被相似正文稀释。
        try:
            async with get_db_context() as db:
                exact, has_more = await self._repository.find_heading_page(
                    db,
                    mode="exact",
                    normalized_title=normalized_query,
                    scope=scope,
                    after=None,
                    limit=self._page_size,
                )
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_ALL_SOURCES_FAILED, "exact title search failed") from exc
        if exact:
            logger.bind(
                event="wiki_search_candidates_collected",
                branch=BRANCH_EXACT,
                exact_candidate_count=len(exact),
                prefix_candidate_count=0,
                bm25_candidate_count=0,
            ).info("Wiki search candidates collected")
            return await self._hydrate_search_page(
                headings=exact,
                bm25_hits=(),
                source=SOURCE_EXACT,
                scope=scope,
                failed_sources=(),
                has_more=has_more,
                next_cursor=self._encode_exact_cursor(binding, exact[-1]) if has_more else None,
            )
        return await self._mixed_page(normalized_query, scope, binding=binding, state={})

    async def _exact_page(
        self,
        normalized_query: str,
        scope: EffectiveWikiScope,
        *,
        binding: dict[str, object],
        state: dict[str, object],
    ) -> dict[str, Any]:
        """按 exact 游标的三元 keyset 继续读取精确标题结果。"""

        after = self._triple_state(state.get("after"), "exact after")
        try:
            async with get_db_context() as db:
                headings, has_more = await self._repository.find_heading_page(
                    db,
                    mode="exact",
                    normalized_title=normalized_query,
                    scope=scope,
                    after=after,
                    limit=self._page_size,
                )
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_ALL_SOURCES_FAILED, "exact title search failed") from exc
        return await self._hydrate_search_page(
            headings=headings,
            bm25_hits=(),
            source=SOURCE_EXACT,
            scope=scope,
            failed_sources=(),
            has_more=has_more,
            next_cursor=(
                self._encode_exact_cursor(binding, headings[-1]) if has_more and headings else None
            ),
        )

    async def _mixed_page(
        self,
        normalized_query: str,
        scope: EffectiveWikiScope,
        *,
        binding: dict[str, object],
        state: dict[str, object],
    ) -> dict[str, Any]:
        """并行读取标题前缀与每库 BM25，并按冻结配额合并一页结果。"""

        prefix_after_raw = state.get("prefix_after")
        prefix_after = (
            self._triple_state(prefix_after_raw, "prefix after")
            if prefix_after_raw is not None
            else None
        )
        bm25_position = RoundRobinPosition(
            rank=self._non_negative_int(state.get("bm25_rank", 0), "bm25 rank"),
            dataset_index=self._non_negative_int(
                state.get("bm25_dataset_index", 0), "bm25 dataset index"
            ),
        )

        async def load_prefix() -> tuple[tuple[WikiHeadingRecord, ...], bool]:
            """使用独立短事务读取一页授权标题前缀候选。"""

            async with get_db_context() as db:
                return await self._repository.find_heading_page(
                    db,
                    mode="prefix",
                    normalized_title=normalized_query,
                    scope=scope,
                    after=prefix_after,
                    limit=self._page_size,
                )

        async def load_bm25() -> dict[int, list[RetrieverHit]]:
            """按有效数据集分别读取固定深度的 BM25 候选。"""

            return await self._bm25.recall_by_dataset(
                normalized_query,
                scope.dataset_ids,
                user_id=scope.user_id,
                top_k=self._bm25_top_k,
                doc_ids_by_dataset=(
                    scope.doc_ids_by_dataset if scope.doc_ids is not None else None
                ),
            )

        # 两路并行读取降低端到端延迟；return_exceptions 让 strict/lenient 策略
        # 在同一处判断是否降级，而不是由任一路异常提前取消另一条有效来源。
        prefix_result, bm25_result = await asyncio.gather(
            load_prefix(), load_bm25(), return_exceptions=True
        )
        failures: list[str] = []
        if isinstance(prefix_result, BaseException):
            failures.append(SOURCE_PREFIX)
            prefix_items: tuple[WikiHeadingRecord, ...] = ()
            prefix_has_more = False
        else:
            prefix_items, prefix_has_more = prefix_result
            prefix_items = tuple({item.id: item for item in prefix_items}.values())
        if isinstance(bm25_result, BaseException):
            failures.append(SOURCE_BM25)
            bm25_by_dataset: dict[int, list[RetrieverHit]] = {}
        else:
            bm25_by_dataset = bm25_result
        if len(failures) == 2 or (failures and self._strict):
            raise RecallApiError(500, CODE_ALL_SOURCES_FAILED, "Wiki search sources failed")

        if SOURCE_BM25 not in failures:
            flattened = [
                hit for dataset in sorted(bm25_by_dataset) for hit in bm25_by_dataset[dataset]
            ]
            try:
                visible = await self._readiness.filter_visible_hits(
                    flattened, user_id=scope.user_id
                )
            except Exception as exc:
                raise RecallApiError(
                    500, CODE_INTERNAL_ERROR, "Wiki readiness check failed"
                ) from exc
            allowed_docs = set(scope.doc_ids) if scope.doc_ids is not None else None
            visible_ids = {
                hit.chunk_id
                for hit in visible
                if hit.dataset_id in scope.dataset_ids
                and (allowed_docs is None or hit.doc_id in allowed_docs)
            }
            bm25_by_dataset = {
                dataset: [hit for hit in hits if hit.chunk_id in visible_ids]
                for dataset, hits in bm25_by_dataset.items()
            }

        logger.bind(
            event="wiki_search_candidates_collected",
            branch=BRANCH_MIXED,
            exact_candidate_count=0,
            prefix_candidate_count=len(prefix_items),
            bm25_candidate_count=sum(len(hits) for hits in bm25_by_dataset.values()),
            failed_sources=failures,
        ).info("Wiki search candidates collected")

        prefix_previews: dict[int, WikiHeadingPreview] = {}
        if prefix_items:
            try:
                async with get_db_context() as db:
                    prefix_previews = await self._repository.load_heading_previews(
                        db, prefix_items, scope=scope
                    )
            except Exception as exc:
                raise RecallApiError(
                    500, CODE_INTERNAL_ERROR, "Wiki heading preview read failed"
                ) from exc

        merged = WikiResultMerger.merge_page(
            prefix_items,
            bm25_by_dataset,
            page_size=self._page_size,
            prefix_offset=0,
            bm25_position=bm25_position,
        )
        (
            selected_headings,
            selected_bm25,
            next_prefix_offset,
            next_bm25_position,
        ) = self._deduplicate_mixed_page(
            prefix_items=prefix_items,
            bm25_by_dataset=bm25_by_dataset,
            selected_headings=merged.prefix_items,
            selected_bm25=merged.bm25_items,
            next_prefix_offset=merged.next_prefix_offset,
            next_bm25_position=merged.next_bm25_position,
            previews=prefix_previews,
        )
        next_prefix_after = prefix_after
        if selected_headings:
            last = selected_headings[-1]
            next_prefix_after = (last.dataset_id, last.doc_id, last.id)
        prefix_remaining = prefix_has_more or next_prefix_offset < len(prefix_items)
        has_more = prefix_remaining or Bm25RoundRobin._has_more(bm25_by_dataset, next_bm25_position)
        next_cursor = None
        if has_more:
            next_cursor = self._cursor.encode(
                branch=BRANCH_MIXED,
                binding=binding,
                state={
                    "prefix_after": list(next_prefix_after) if next_prefix_after else None,
                    "bm25_rank": next_bm25_position.rank,
                    "bm25_dataset_index": next_bm25_position.dataset_index,
                },
            )
        return await self._hydrate_search_page(
            headings=selected_headings,
            bm25_hits=selected_bm25,
            source=SOURCE_PREFIX,
            scope=scope,
            failed_sources=failures,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    def _deduplicate_mixed_page(
        self,
        *,
        prefix_items: Sequence[WikiHeadingRecord],
        bm25_by_dataset: Mapping[int, Sequence[RetrieverHit]],
        selected_headings: Sequence[WikiHeadingRecord],
        selected_bm25: Sequence[RetrieverHit],
        next_prefix_offset: int,
        next_bm25_position: RoundRobinPosition,
        previews: Mapping[int, WikiHeadingPreview],
    ) -> tuple[
        tuple[WikiHeadingRecord, ...],
        tuple[RetrieverHit, ...],
        int,
        RoundRobinPosition,
    ]:
        """消费后续候选补位，同时抑制标题预览与 BM25 正文重复。"""

        headings = list(selected_headings)
        blocked_chunk_ids = {
            preview.chunk_id
            for heading in headings
            if (preview := previews.get(heading.id)) is not None and preview.chunk_id is not None
        }
        seen_bm25: set[str] = set()
        bm25_hits: list[RetrieverHit] = []
        for hit in selected_bm25:
            if hit.chunk_id not in blocked_chunk_ids and hit.chunk_id not in seen_bm25:
                seen_bm25.add(hit.chunk_id)
                bm25_hits.append(hit)

        while len(headings) + len(bm25_hits) < self._page_size:
            missing = self._page_size - len(headings) - len(bm25_hits)
            if Bm25RoundRobin._has_more(bm25_by_dataset, next_bm25_position):
                page = Bm25RoundRobin.page(
                    bm25_by_dataset,
                    position=next_bm25_position,
                    limit=missing,
                )
                next_bm25_position = page.next_position
                for hit in page.items:
                    if hit.chunk_id in blocked_chunk_ids or hit.chunk_id in seen_bm25:
                        continue
                    seen_bm25.add(hit.chunk_id)
                    bm25_hits.append(hit)
                continue

            if next_prefix_offset >= len(prefix_items):
                break
            heading = prefix_items[next_prefix_offset]
            next_prefix_offset += 1
            headings.append(heading)
            preview = previews.get(heading.id)
            if preview is not None and preview.chunk_id is not None:
                blocked_chunk_ids.add(preview.chunk_id)
                bm25_hits = [hit for hit in bm25_hits if hit.chunk_id != preview.chunk_id]

        return (
            tuple(headings),
            tuple(bm25_hits),
            next_prefix_offset,
            next_bm25_position,
        )

    async def _hydrate_search_page(
        self,
        *,
        headings: Sequence[WikiHeadingRecord],
        bm25_hits: Sequence[RetrieverHit],
        source: str,
        scope: EffectiveWikiScope,
        failed_sources: Sequence[str],
        has_more: bool,
        next_cursor: str | None,
    ) -> dict[str, Any]:
        """重新校验当前可见性，并批量回填标题路径、预览和 Chunk 真值。

        候选产生和正文回填之间可能发生重解析或删除，因此这里必须再次通过
        current SUCCESS 与 ACTIVE 门禁，不能直接信任前一阶段的候选快照。
        """

        try:
            async with get_db_context() as db:
                headings = await self._repository.revalidate_visible_headings(
                    db, headings, scope=scope
                )
                paths = await self._repository.load_heading_paths(db, headings)
                previews = await self._repository.load_heading_previews(db, headings, scope=scope)
                preview_ids: list[str] = []
                for item in headings:
                    preview_chunk_id = previews[item.id].chunk_id
                    if preview_chunk_id is not None:
                        preview_ids.append(preview_chunk_id)
                chunk_ids = list(
                    dict.fromkeys([*preview_ids, *(hit.chunk_id for hit in bm25_hits)])
                )
                locations = (
                    await self._repository.load_chunk_locations(
                        db,
                        chunk_ids,
                        scope=scope,
                        max_positions=MAX_SEARCH_POSITIONS_PER_CHUNK,
                    )
                    if chunk_ids
                    else ()
                )
                all_heading_ids = [
                    heading_id for location in locations for heading_id in location.heading_ids
                ]
                location_headings = await self._repository.load_headings_by_ids(db, all_heading_ids)
                location_paths = await self._repository.load_heading_paths(db, location_headings)
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_INTERNAL_ERROR, "Wiki hydration failed") from exc

        results: list[dict[str, Any]] = []
        for heading in headings:
            preview = previews[heading.id]
            heading_binding = self._heading_binding(scope, heading.doc_id, heading.heading_key)
            direct_cursor = None
            if preview.direct_chunk_count > 1:
                direct_cursor = self._cursor.encode(
                    branch=BRANCH_HEADING_CHUNKS,
                    binding=heading_binding,
                    state={"after": [preview.first_ref_sort_order, preview.first_ref_id]},
                )
            heading_payload = {
                "heading_key": heading.heading_key,
                "doc_id": heading.doc_id,
                "dataset_id": heading.dataset_id,
                "title": heading.title,
                "heading_level": heading.heading_level,
                "path": [self._path_item(item) for item in paths.get(heading.id, ())],
                "direct_chunk_count": preview.direct_chunk_count,
                "direct_chunks_has_more": preview.direct_chunk_count > 1,
            }
            if preview.chunk_id is not None:
                heading_payload["direct_chunk_preview_id"] = preview.chunk_id
            if direct_cursor is not None:
                heading_payload["next_direct_chunk_cursor"] = direct_cursor
            results.append(
                {
                    "result_type": "HEADING",
                    "source": source,
                    "heading": heading_payload,
                    "chunk_id": None,
                    "bm25_score": None,
                }
            )
        results.extend(
            {
                "result_type": "CHUNK",
                "source": SOURCE_BM25,
                "heading": None,
                "chunk_id": hit.chunk_id,
                "bm25_score": hit.score,
            }
            for hit in bm25_hits
        )
        chunks = self._serialize_locations(locations, location_paths=location_paths)
        payload: dict[str, Any] = {
            "results": results,
            "chunks": chunks,
            "failed_sources": list(failed_sources),
            "page_size": self._page_size,
            "has_more": has_more,
        }
        if next_cursor is not None:
            payload["next_cursor"] = next_cursor
        return payload

    async def expand_heading_chunks(
        self,
        ctx: SessionAuthContext,
        *,
        doc_id: int,
        heading_key: str,
        cursor: str | None,
    ) -> dict[str, Any]:
        """分页展开一个授权标题的直属 Chunk，不读取子标题正文。"""

        scope = await self._resolve_scope(ctx, dataset_ids=None, doc_ids=(doc_id,))
        binding = self._heading_binding(scope, doc_id, heading_key)
        after: tuple[int, int] | None = None
        if cursor is not None:
            try:
                state = self._cursor.decode_and_validate(
                    cursor,
                    expected_branch=BRANCH_HEADING_CHUNKS,
                    expected_binding=binding,
                )
                after = self._pair_state(state.get("after"), "heading chunk after")
            except WikiCursorError as exc:
                raise RecallApiError(422, CODE_INVALID_REQUEST, "invalid Wiki cursor") from exc
        try:
            async with get_db_context() as db:
                refs, has_more = await self._repository.load_heading_chunk_page(
                    db,
                    doc_id=doc_id,
                    heading_key=heading_key,
                    scope=scope,
                    after=after,
                    limit=self._page_size,
                )
                locations = (
                    await self._repository.load_chunk_locations(
                        db,
                        [item.chunk_id for item in refs],
                        scope=scope,
                        max_positions=MAX_SEARCH_POSITIONS_PER_CHUNK,
                    )
                    if refs
                    else ()
                )
                heading_ids = [item for loc in locations for item in loc.heading_ids]
                headings = await self._repository.load_headings_by_ids(db, heading_ids)
                paths = await self._repository.load_heading_paths(db, headings)
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_INTERNAL_ERROR, "Wiki heading read failed") from exc
        next_direct_cursor = None
        if has_more and refs:
            last = refs[-1]
            next_direct_cursor = self._cursor.encode(
                branch=BRANCH_HEADING_CHUNKS,
                binding=binding,
                state={"after": [last.sort_order, last.ref_id]},
            )
        payload: dict[str, Any] = {
            "doc_id": doc_id,
            "heading_key": heading_key,
            "chunks": self._serialize_locations(locations, location_paths=paths),
            "page_size": self._page_size,
            "direct_chunks_has_more": has_more,
        }
        if next_direct_cursor:
            payload["next_direct_chunk_cursor"] = next_direct_cursor
        return payload

    async def locate_chunks(
        self,
        ctx: SessionAuthContext,
        *,
        chunk_ids: Sequence[str],
        dataset_ids: Sequence[int] | None,
    ) -> dict[str, Any]:
        """批量反查授权 Chunk 的全部直接标题位置。"""

        scope = await self._resolve_scope(ctx, dataset_ids=dataset_ids, doc_ids=None)
        try:
            async with get_db_context() as db:
                locations = await self._repository.load_chunk_locations(db, chunk_ids, scope=scope)
                heading_ids = [item for loc in locations for item in loc.heading_ids]
                headings = await self._repository.load_headings_by_ids(db, heading_ids)
                paths = await self._repository.load_heading_paths(db, headings)
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_INTERNAL_ERROR, "Wiki location read failed") from exc
        return {
            "locations": [
                {
                    "chunk_id": location.chunk.chunk_id,
                    "doc_id": location.chunk.doc_id,
                    "dataset_id": location.chunk.dataset_id,
                    "positions": [
                        {"path": [self._path_item(item) for item in paths.get(heading_id, ())]}
                        for heading_id in location.heading_ids
                    ],
                }
                for location in locations
            ]
        }

    async def get_document_tree(
        self,
        ctx: SessionAuthContext,
        *,
        doc_id: int,
    ) -> dict[str, Any]:
        """读取一篇授权文档的全部结构节点并组装递归标题树。"""

        scope = await self._resolve_scope(ctx, dataset_ids=None, doc_ids=(doc_id,))
        try:
            async with get_db_context() as db:
                tree = await self._repository.load_document_tree(db, doc_id=doc_id, scope=scope)
                locations = (
                    await self._repository.load_chunk_locations(
                        db, [chunk.chunk_id for chunk in tree.chunks], scope=scope
                    )
                    if tree.chunks
                    else ()
                )
                position_heading_ids = [item for loc in locations for item in loc.heading_ids]
                position_headings = await self._repository.load_headings_by_ids(
                    db, position_heading_ids
                )
                paths = await self._repository.load_heading_paths(db, position_headings)
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_INTERNAL_ERROR, "Wiki tree read failed") from exc
        children: dict[int | None, list[WikiHeadingRecord]] = defaultdict(list)
        for heading in tree.headings:
            children[heading.parent_id].append(heading)
        for siblings in children.values():
            siblings.sort(key=lambda item: (item.sort_order, item.id))

        def build_heading(heading: WikiHeadingRecord) -> dict[str, Any]:
            """把已分组的标题记录递归序列化为公共树节点。"""

            return {
                "heading_key": heading.heading_key,
                "title": heading.title,
                "heading_level": heading.heading_level,
                "direct_chunk_ids": list(tree.direct_chunk_ids_by_heading.get(heading.id, ())),
                "children": [build_heading(item) for item in children.get(heading.id, ())],
            }

        return {
            "doc_id": tree.doc_id,
            "dataset_id": tree.dataset_id,
            "original_filename": tree.original_filename,
            "headings": [build_heading(item) for item in children.get(None, ())],
            "root_chunk_ids": list(tree.root_chunk_ids),
            "chunks": self._serialize_locations(locations, location_paths=paths),
        }

    async def _resolve_scope(
        self,
        ctx: SessionAuthContext,
        *,
        dataset_ids: Sequence[int] | None,
        doc_ids: Sequence[int] | None,
    ) -> EffectiveWikiScope:
        """把 token claims 与请求范围收敛为仓储可执行的规范授权范围。"""

        try:
            async with get_db_context() as db:
                return await self._repository.resolve_scope(
                    db,
                    user_id=ctx.user_id,
                    claims_dataset_ids=ctx.dataset_ids,
                    requested_dataset_ids=dataset_ids,
                    requested_doc_ids=doc_ids,
                )
        except RecallApiError:
            raise
        except Exception as exc:
            raise RecallApiError(500, CODE_INTERNAL_ERROR, "Wiki scope resolution failed") from exc

    def _decode_search_cursor(
        self,
        cursor: str,
        *,
        binding: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        """依次验证 exact/mixed 分支绑定，拒绝跨查询复用游标。"""

        for branch in (BRANCH_EXACT, BRANCH_MIXED):
            try:
                return branch, self._cursor.decode_and_validate(
                    cursor, expected_branch=branch, expected_binding=binding
                )
            except WikiCursorError:
                continue
        raise RecallApiError(422, CODE_INVALID_REQUEST, "invalid Wiki cursor")

    def _encode_exact_cursor(
        self,
        binding: dict[str, object],
        heading: WikiHeadingRecord,
    ) -> str:
        """编码精确标题分页下一条三元 keyset。"""

        return self._cursor.encode(
            branch=BRANCH_EXACT,
            binding=binding,
            state={"after": [heading.dataset_id, heading.doc_id, heading.id]},
        )

    @staticmethod
    def _search_binding(
        normalized_query: str,
        scope: EffectiveWikiScope,
    ) -> dict[str, object]:
        """生成绑定用户、规范查询词和授权范围的搜索游标指纹。"""

        return {
            "user_id": scope.user_id,
            "query": normalized_query.casefold(),
            "scope": make_scope_fingerprint(
                user_id=scope.user_id,
                dataset_ids=scope.dataset_ids,
                doc_ids=scope.doc_ids,
            ),
        }

    @staticmethod
    def _heading_binding(
        scope: EffectiveWikiScope,
        doc_id: int,
        heading_key: str,
    ) -> dict[str, object]:
        """生成绑定用户、文档、标题和授权范围的展开游标指纹。"""

        return {
            "user_id": scope.user_id,
            "doc_id": doc_id,
            "heading_key": heading_key,
            "scope": make_scope_fingerprint(
                user_id=scope.user_id,
                dataset_ids=scope.dataset_ids,
                doc_ids=(doc_id,),
            ),
        }

    @staticmethod
    def _path_item(item: object) -> dict[str, object]:
        """把领域标题路径节点转换为公共响应字段。"""

        return {
            "heading_key": getattr(item, "heading_key"),
            "title": getattr(item, "title"),
            "heading_level": getattr(item, "heading_level"),
        }

    def _serialize_locations(
        self,
        locations: Sequence[WikiChunkLocationRecord],
        *,
        location_paths: Mapping[int, Sequence[object]],
    ) -> list[dict[str, Any]]:
        """序列化仓储已按场景加载的 Chunk 真值、标题位置及完整计数。"""

        serialized: list[dict[str, Any]] = []
        for location in locations:
            positions = [
                {"path": [self._path_item(item) for item in location_paths.get(heading_id, ())]}
                for heading_id in location.heading_ids
            ]
            chunk = location.chunk
            serialized.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "dataset_id": chunk.dataset_id,
                    "content": chunk.content,
                    "chunk_type": chunk.chunk_type,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "positions": positions,
                    "position_count": location.position_count,
                    "positions_truncated": len(positions) < location.position_count,
                }
            )
        return serialized

    @staticmethod
    def _non_negative_int(value: object, name: str) -> int:
        """从不可信游标状态读取非负整数，拒绝 bool 等隐式整数。"""

        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid {name}")
        return value

    @classmethod
    def _pair_state(cls, value: object, name: str) -> tuple[int, int]:
        """校验直属 Chunk 游标使用的二元 keyset。"""

        if not isinstance(value, list) or len(value) != 2:
            raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid {name}")
        return (
            cls._non_negative_int(value[0], name),
            cls._non_negative_int(value[1], name),
        )

    @classmethod
    def _triple_state(cls, value: object, name: str) -> tuple[int, int, int]:
        """校验标题搜索游标使用的三元 keyset。"""

        if not isinstance(value, list) or len(value) != 3:
            raise RecallApiError(422, CODE_INVALID_REQUEST, f"invalid {name}")
        return (
            cls._non_negative_int(value[0], name),
            cls._non_negative_int(value[1], name),
            cls._non_negative_int(value[2], name),
        )


@lru_cache(maxsize=1)
def get_wiki_runtime() -> WikiRuntime:
    """按进程单例装配 Wiki 应用运行时及其固定策略。"""

    return WikiRuntime(
        repository=WikiTreeRepository(),
        bm25_retriever=Bm25Retriever(
            backend=build_bm25_recall_backend(),
            tokenizer=RagFlowTokenizer(),
        ),
        readiness_gate=MySqlDocumentReadinessGate(),
        cursor_codec=WikiCursorCodec(settings.RECALL_SESSION_JWT_SECRET),
        page_size=settings.WIKI_SEARCH_PAGE_SIZE,
        bm25_top_k_per_dataset=settings.WIKI_BM25_TOP_K_PER_DATASET,
        strict=settings.RECALL_STRICT_DEFAULT,
    )
