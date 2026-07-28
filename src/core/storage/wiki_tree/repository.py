"""Wiki 标题树的事务持久化与授权读取原语。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.application.recall_errors import CODE_SCOPE_FORBIDDEN, RecallApiError
from src.core.storage.chunks.constants import CHUNK_LIFECYCLE_ACTIVE
from src.core.storage.document_visibility import (
    current_document_join_condition,
    current_successful_document_conditions,
    dataset_table,
    document_original_file_table,
    visible_chunk_conditions,
)
from src.core.wiki.models import (
    WIKI_NODE_CHUNK_REF,
    WIKI_NODE_HEADING,
    EffectiveWikiScope,
    WikiChunkLocationRecord,
    WikiChunkRecord,
    WikiChunkRefRecord,
    WikiDocumentTreeRows,
    WikiHeadingDraft,
    WikiHeadingPathItem,
    WikiHeadingPreview,
    WikiHeadingRecord,
    WikiTreeDraft,
)
from src.models.chunk_record import ChunkRecordDB
from src.models.parse_task import DocumentParsePipeline, DocumentParseTask
from src.models.wiki_tree import WikiTreeNodeDB


@dataclass(frozen=True, slots=True)
class WikiTreeWriteResult:
    """替换一篇文档标题树时产生的删除和写入计数。"""

    deleted_count: int
    heading_count: int
    chunk_ref_count: int


class WikiTreeRepository:
    """执行 Wiki SQL，但不接管调用方事务的提交或回滚。"""

    def __init__(self, model_cls: type[WikiTreeNodeDB] = WikiTreeNodeDB) -> None:
        """允许测试替换 ORM 模型，生产默认使用 WikiTreeNodeDB。"""

        self.model_cls = model_cls

    async def resolve_scope(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        claims_dataset_ids: Sequence[int] | None,
        requested_dataset_ids: Sequence[int] | None,
        requested_doc_ids: Sequence[int] | None,
    ) -> EffectiveWikiScope:
        """解析全库或受限 claims，并拒绝任何跨用户、数据集或文档范围。

        空 claims 表示在当前用户拥有的数据集内检索，而不是跳过授权。请求显式
        提交的 dataset/doc ID 必须全部属于最终有效范围，否则整体返回 403。
        """

        claims = tuple(sorted(set(claims_dataset_ids or ())))
        requested_datasets = tuple(sorted(set(requested_dataset_ids or ())))
        requested_docs = tuple(sorted(set(requested_doc_ids or ())))
        if requested_datasets and claims and not set(requested_datasets) <= set(claims):
            raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "dataset_ids exceed authorized scope")

        candidate_datasets = requested_datasets or claims
        # 即使 token 是“全库授权”，也必须从 Java 侧真值表重新求当前用户拥有且
        # ACTIVE 的数据集，不能把空 claims 解释为无条件访问。
        dataset_stmt = select(dataset_table.c.id).where(
            dataset_table.c.user_id == user_id,
            dataset_table.c.status.collate("utf8mb4_unicode_ci") == "ACTIVE",
            dataset_table.c.is_deleted.is_(False),
        )
        if candidate_datasets:
            dataset_stmt = dataset_stmt.where(dataset_table.c.id.in_(candidate_datasets))
        owned_datasets = tuple(sorted(int(row[0]) for row in (await session.execute(dataset_stmt))))
        if requested_datasets and set(owned_datasets) != set(requested_datasets):
            raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "dataset scope is not authorized")
        if not owned_datasets:
            if requested_docs:
                raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "document scope is not authorized")
            return EffectiveWikiScope(user_id, (), requested_docs or None, {})

        doc_ids_by_dataset: dict[int, list[int]] = defaultdict(list)
        if requested_docs:
            doc_stmt = select(
                document_original_file_table.c.id,
                document_original_file_table.c.dataset_id,
            ).where(
                document_original_file_table.c.user_id == user_id,
                document_original_file_table.c.is_deleted.is_(False),
                document_original_file_table.c.dataset_id.in_(owned_datasets),
                document_original_file_table.c.id.in_(requested_docs),
            )
            found_docs = [(int(row[0]), int(row[1])) for row in await session.execute(doc_stmt)]
            if {doc_id for doc_id, _ in found_docs} != set(requested_docs):
                raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "document scope is not authorized")
            for doc_id, dataset_id in found_docs:
                doc_ids_by_dataset[dataset_id].append(doc_id)
        effective_dataset_ids = (
            tuple(sorted(doc_ids_by_dataset))
            if requested_docs and not requested_datasets
            else owned_datasets
        )
        return EffectiveWikiScope(
            user_id=user_id,
            dataset_ids=effective_dataset_ids,
            doc_ids=requested_docs or None,
            doc_ids_by_dataset={
                dataset_id: tuple(sorted(doc_ids))
                for dataset_id, doc_ids in doc_ids_by_dataset.items()
            },
        )

    async def find_heading_page(
        self,
        session: AsyncSession,
        *,
        mode: str,
        normalized_title: str,
        scope: EffectiveWikiScope,
        after: tuple[int, int, int] | None,
        limit: int,
    ) -> tuple[tuple[WikiHeadingRecord, ...], bool]:
        """按确定性 keyset 顺序读取 exact 或 prefix 标题页。

        SQL 阶段同时完成所有权、有效数据集、指定文档和 current SUCCESS 过滤，
        防止先取候选再在应用层过滤造成越权标题泄漏。
        """

        if mode not in {"exact", "prefix"}:
            raise ValueError("mode must be exact or prefix")
        if limit <= 0 or not scope.dataset_ids:
            return (), False
        node = self.model_cls
        statement = (
            select(
                node.id,
                node.heading_key,
                node.doc_id,
                DocumentParseTask.dataset_id,
                DocumentParseTask.original_filename,
                node.parent_id,
                node.title,
                node.heading_level,
                node.sort_order,
            )
            .select_from(node)
            .join(
                DocumentParseTask,
                DocumentParseTask.document_original_file_id == node.doc_id,
            )
            .join(
                DocumentParsePipeline,
                current_document_join_condition(),
            )
            .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
            .join(
                document_original_file_table,
                document_original_file_table.c.id == DocumentParseTask.document_original_file_id,
            )
            .where(
                node.node_type == WIKI_NODE_HEADING,
                *current_successful_document_conditions(
                    user_id=scope.user_id,
                    dataset_ids=scope.dataset_ids,
                    doc_ids=scope.doc_ids,
                ),
            )
        )
        # title 继承表级 utf8mb4_unicode_ci，直接比较即可保持英文大小写不敏感，
        # 同时让联合索引继续使用 title 键；prefix 仍转义通配符，只开放字面前缀。
        if mode == "exact":
            statement = statement.where(node.title == normalized_title)
        else:
            escaped = normalized_title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(node.title.like(f"{escaped}%", escape="\\"))
        # 使用 (dataset_id, doc_id, node.id) keyset，避免 offset 在跨库结果页上
        # 因并发插入产生大范围漂移，也让游标只保存下一未消费位置。
        if after is not None:
            dataset_id, doc_id, node_id = after
            statement = statement.where(
                or_(
                    DocumentParseTask.dataset_id > dataset_id,
                    and_(DocumentParseTask.dataset_id == dataset_id, node.doc_id > doc_id),
                    and_(
                        DocumentParseTask.dataset_id == dataset_id,
                        node.doc_id == doc_id,
                        node.id > node_id,
                    ),
                )
            )
        rows = (
            await session.execute(
                statement.order_by(DocumentParseTask.dataset_id, node.doc_id, node.id).limit(
                    limit + 1
                )
            )
        ).all()
        has_more = len(rows) > limit
        return tuple(self._heading_from_row(row) for row in rows[:limit]), has_more

    async def load_heading_paths(
        self,
        session: AsyncSession,
        headings: Sequence[WikiHeadingRecord],
    ) -> dict[int, tuple[WikiHeadingPathItem, ...]]:
        """最多用六轮批量 SQL 回溯 H1～H6 父链。

        查询键包含 ``(id, doc_id)``，即使存在脏 parent_id 也不能跨文档拼接路径。
        """

        node_by_id: dict[int, tuple[int | None, WikiHeadingPathItem]] = {
            item.id: (
                item.parent_id,
                WikiHeadingPathItem(item.heading_key, item.title, item.heading_level),
            )
            for item in headings
        }
        pending = {(item.parent_id, item.doc_id) for item in headings if item.parent_id is not None}
        for _ in range(6):
            missing = {
                (node_id, doc_id) for node_id, doc_id in pending if node_id not in node_by_id
            }
            if not missing:
                break
            rows = (
                await session.execute(
                    select(
                        self.model_cls.id,
                        self.model_cls.parent_id,
                        self.model_cls.heading_key,
                        self.model_cls.title,
                        self.model_cls.heading_level,
                        self.model_cls.doc_id,
                    ).where(
                        tuple_(self.model_cls.id, self.model_cls.doc_id).in_(tuple(missing)),
                        self.model_cls.node_type == WIKI_NODE_HEADING,
                    )
                )
            ).all()
            pending = set()
            for row in rows:
                node_id = int(row[0])
                parent_id = int(row[1]) if row[1] is not None else None
                node_by_id[node_id] = (
                    parent_id,
                    WikiHeadingPathItem(str(row[2]), str(row[3]), int(row[4])),
                )
                if parent_id is not None:
                    pending.add((parent_id, int(row[5])))

        paths: dict[int, tuple[WikiHeadingPathItem, ...]] = {}
        for heading in headings:
            chain: list[WikiHeadingPathItem] = []
            current_id: int | None = heading.id
            visited: set[int] = set()
            while current_id is not None and current_id not in visited:
                visited.add(current_id)
                current = node_by_id.get(current_id)
                if current is None:
                    break
                current_id, item = current
                chain.append(item)
            paths[heading.id] = tuple(reversed(chain))
        return paths

    async def revalidate_visible_headings(
        self,
        session: AsyncSession,
        headings: Sequence[WikiHeadingRecord],
        *,
        scope: EffectiveWikiScope,
    ) -> tuple[WikiHeadingRecord, ...]:
        """在正文回填前重新通过 current SUCCESS 门禁读取标题候选。

        该二次 SQL 校验关闭“候选查询后文档切换 current task”的时间窗口；失去
        可见性的标题直接丢弃，不信任前一阶段缓存的文档状态。
        """

        ordered_ids = tuple(dict.fromkeys(item.id for item in headings))
        if not ordered_ids or not scope.dataset_ids:
            return ()
        node = self.model_cls
        rows = (
            await session.execute(
                select(
                    node.id,
                    node.heading_key,
                    node.doc_id,
                    DocumentParseTask.dataset_id,
                    DocumentParseTask.original_filename,
                    node.parent_id,
                    node.title,
                    node.heading_level,
                    node.sort_order,
                )
                .select_from(node)
                .join(DocumentParseTask, DocumentParseTask.document_original_file_id == node.doc_id)
                .join(DocumentParsePipeline, current_document_join_condition())
                .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
                .join(
                    document_original_file_table,
                    document_original_file_table.c.id
                    == DocumentParseTask.document_original_file_id,
                )
                .where(
                    node.id.in_(ordered_ids),
                    node.node_type == WIKI_NODE_HEADING,
                    *current_successful_document_conditions(
                        user_id=scope.user_id,
                        dataset_ids=scope.dataset_ids,
                        doc_ids=scope.doc_ids,
                    ),
                )
            )
        ).all()
        by_id = {int(row[0]): self._heading_from_row(row) for row in rows}
        return tuple(by_id[node_id] for node_id in ordered_ids if node_id in by_id)

    async def load_headings_by_ids(
        self,
        session: AsyncSession,
        heading_ids: Sequence[int],
    ) -> tuple[WikiHeadingRecord, ...]:
        """批量读取构建完整路径所需的标题记录，并保持输入顺序。"""

        ordered_ids = tuple(dict.fromkeys(heading_ids))
        if not ordered_ids:
            return ()
        node = self.model_cls
        rows = (
            await session.execute(
                select(
                    node.id,
                    node.heading_key,
                    node.doc_id,
                    DocumentParseTask.dataset_id,
                    DocumentParseTask.original_filename,
                    node.parent_id,
                    node.title,
                    node.heading_level,
                    node.sort_order,
                )
                .select_from(node)
                .join(DocumentParseTask, DocumentParseTask.document_original_file_id == node.doc_id)
                .where(node.id.in_(ordered_ids), node.node_type == WIKI_NODE_HEADING)
            )
        ).all()
        by_id = {int(row[0]): self._heading_from_row(row) for row in rows}
        return tuple(by_id[node_id] for node_id in ordered_ids if node_id in by_id)

    async def load_heading_previews(
        self,
        session: AsyncSession,
        headings: Sequence[WikiHeadingRecord],
        *,
        scope: EffectiveWikiScope,
    ) -> dict[int, WikiHeadingPreview]:
        """批量读取标题的可见直属引用总数及首条预览。

        父标题、引用和 Chunk 必须属于同一文档，正文还必须属于当前用户、有效
        数据集且处于 ACTIVE，避免脏引用成为越权预览。
        """

        if not headings:
            return {}
        heading_ids = tuple(item.id for item in headings)
        ref = self.model_cls
        parent = aliased(self.model_cls)
        # 子查询在 MySQL 内按标题完成总数与稳定排名，外层只保留 rank=1；因此高扇出
        # 标题不会把全部引用行传给 Python，同时首条预览与完整计数来自同一快照。
        ranked = (
            select(
                ref.parent_id.label("heading_id"),
                ref.id.label("ref_id"),
                ref.sort_order.label("sort_order"),
                ref.chunk_id.label("chunk_id"),
                func.count().over(partition_by=ref.parent_id).label("direct_chunk_count"),
                func.row_number()
                .over(partition_by=ref.parent_id, order_by=(ref.sort_order, ref.id))
                .label("position_rank"),
            )
            .join(ChunkRecordDB, ChunkRecordDB.chunk_id == ref.chunk_id)
            .join(
                parent,
                and_(
                    parent.id == ref.parent_id,
                    parent.doc_id == ref.doc_id,
                    parent.node_type == WIKI_NODE_HEADING,
                ),
            )
            .where(
                ref.node_type == WIKI_NODE_CHUNK_REF,
                ref.parent_id.in_(heading_ids),
                ChunkRecordDB.user_id == scope.user_id,
                ChunkRecordDB.set_id.in_(scope.dataset_ids),
                ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
                ChunkRecordDB.doc_id == ref.doc_id,
            )
            .subquery("ranked_heading_previews")
        )
        rows = (
            await session.execute(
                select(
                    ranked.c.heading_id,
                    ranked.c.ref_id,
                    ranked.c.sort_order,
                    ranked.c.chunk_id,
                    ranked.c.direct_chunk_count,
                )
                .where(ranked.c.position_rank == 1)
                .order_by(ranked.c.heading_id)
            )
        ).all()
        by_heading = {
            int(heading_id): (int(ref_id), int(sort_order), str(chunk_id), int(count))
            for heading_id, ref_id, sort_order, chunk_id, count in rows
        }
        return {
            heading.id: WikiHeadingPreview(
                heading_id=heading.id,
                direct_chunk_count=by_heading[heading.id][3] if heading.id in by_heading else 0,
                chunk_id=by_heading[heading.id][2] if heading.id in by_heading else None,
                first_ref_sort_order=(
                    by_heading[heading.id][1] if heading.id in by_heading else None
                ),
                first_ref_id=by_heading[heading.id][0] if heading.id in by_heading else None,
            )
            for heading in headings
        }

    async def find_matching_preview_chunk_ids(
        self,
        session: AsyncSession,
        *,
        normalized_title: str,
        candidate_chunk_ids: Sequence[str],
        scope: EffectiveWikiScope,
    ) -> frozenset[str]:
        """找出属于任意匹配标题首个可见直属预览的 BM25 候选。

        该查询为整个无状态搜索链建立稳定正文归属：只要候选 Chunk 是当前
        query/scope 下某个前缀标题的首个预览，就固定由标题结果返回，不能先在
        前页作为 BM25 正文出现。查询从有界 candidate ID 出发，再用 NOT EXISTS
        确认同一标题下不存在排序更早的可见引用；不能先过滤同标题其他引用后再
        排名，否则第二条引用会被错误提升为首条预览。
        """

        ordered_ids = tuple(dict.fromkeys(candidate_chunk_ids))
        if not ordered_ids or not scope.dataset_ids:
            return frozenset()

        heading = aliased(self.model_cls, name="preview_owner_heading")
        ref = aliased(self.model_cls, name="preview_owner_ref")
        earlier_ref = aliased(self.model_cls, name="earlier_preview_ref")
        earlier_chunk = aliased(ChunkRecordDB, name="earlier_preview_chunk")
        escaped = normalized_title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        earlier_visible_ref_exists = (
            select(1)
            .select_from(earlier_ref)
            .join(
                earlier_chunk,
                and_(
                    earlier_chunk.chunk_id == earlier_ref.chunk_id,
                    earlier_chunk.doc_id == earlier_ref.doc_id,
                ),
            )
            .where(
                earlier_ref.node_type == WIKI_NODE_CHUNK_REF,
                earlier_ref.doc_id == ref.doc_id,
                earlier_ref.parent_id == ref.parent_id,
                earlier_chunk.user_id == scope.user_id,
                earlier_chunk.set_id == DocumentParseTask.dataset_id,
                earlier_chunk.doc_id == DocumentParseTask.document_original_file_id,
                earlier_chunk.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
                or_(
                    earlier_ref.sort_order < ref.sort_order,
                    and_(
                        earlier_ref.sort_order == ref.sort_order,
                        earlier_ref.id < ref.id,
                    ),
                ),
            )
            .exists()
        )
        statement = (
            select(ref.chunk_id)
            .select_from(ref)
            .join(
                heading,
                and_(
                    heading.id == ref.parent_id,
                    heading.doc_id == ref.doc_id,
                    heading.node_type == WIKI_NODE_HEADING,
                ),
            )
            .join(
                ChunkRecordDB,
                and_(
                    ChunkRecordDB.chunk_id == ref.chunk_id,
                    ChunkRecordDB.doc_id == ref.doc_id,
                ),
            )
            .join(
                DocumentParseTask,
                DocumentParseTask.document_original_file_id == heading.doc_id,
            )
            .join(DocumentParsePipeline, current_document_join_condition())
            .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
            .join(
                document_original_file_table,
                document_original_file_table.c.id == DocumentParseTask.document_original_file_id,
            )
            .where(
                ref.node_type == WIKI_NODE_CHUNK_REF,
                ref.chunk_id.in_(ordered_ids),
                heading.title.like(f"{escaped}%", escape="\\"),
                *current_successful_document_conditions(
                    user_id=scope.user_id,
                    dataset_ids=scope.dataset_ids,
                    doc_ids=scope.doc_ids,
                ),
                *visible_chunk_conditions(user_id=scope.user_id),
                ~earlier_visible_ref_exists,
            )
            .distinct()
        )
        rows = (await session.execute(statement)).all()
        return frozenset(str(row[0]) for row in rows)

    async def load_heading_chunk_page(
        self,
        session: AsyncSession,
        *,
        doc_id: int,
        heading_key: str,
        scope: EffectiveWikiScope,
        after: tuple[int, int] | None,
        limit: int,
    ) -> tuple[tuple[WikiChunkRefRecord, ...], bool]:
        """按 keyset 分页读取一个授权标题的可见直属 Chunk。

        只查询 parent_id 等于当前标题的 CHUNK_REF，不递归子标题；多读一条仅用于
        判断是否还有下一页，返回仍严格限制为 limit 条。
        """

        heading = await self._authorized_heading(
            session, doc_id=doc_id, heading_key=heading_key, scope=scope
        )
        if heading is None:
            raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "heading is not authorized")
        ref = self.model_cls
        statement = (
            select(ref.id, ref.sort_order, ref.chunk_id)
            .join(ChunkRecordDB, ChunkRecordDB.chunk_id == ref.chunk_id)
            .where(
                ref.node_type == WIKI_NODE_CHUNK_REF,
                ref.doc_id == doc_id,
                ref.parent_id == heading.id,
                ChunkRecordDB.user_id == scope.user_id,
                ChunkRecordDB.set_id == heading.dataset_id,
                ChunkRecordDB.doc_id == doc_id,
                ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
            )
        )
        if after is not None:
            sort_order, ref_id = after
            statement = statement.where(
                or_(
                    ref.sort_order > sort_order, and_(ref.sort_order == sort_order, ref.id > ref_id)
                )
            )
        rows = (
            await session.execute(statement.order_by(ref.sort_order, ref.id).limit(limit + 1))
        ).all()
        return (
            tuple(WikiChunkRefRecord(int(r[0]), int(r[1]), str(r[2])) for r in rows[:limit]),
            len(rows) > limit,
        )

    async def load_chunks(
        self,
        session: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        scope: EffectiveWikiScope,
    ) -> tuple[WikiChunkRecord, ...]:
        """按调用方顺序批量读取通过所有权、current SUCCESS 和 ACTIVE 门禁的 Chunk 真值。"""

        ordered = tuple(dict.fromkeys(chunk_ids))
        if not ordered:
            return ()
        rows = (
            await session.execute(
                select(
                    ChunkRecordDB.chunk_id,
                    ChunkRecordDB.doc_id,
                    ChunkRecordDB.set_id,
                    ChunkRecordDB.content,
                    ChunkRecordDB.chunk_type,
                    ChunkRecordDB.start_line,
                    ChunkRecordDB.end_line,
                )
                .select_from(ChunkRecordDB)
                .join(
                    DocumentParseTask,
                    and_(
                        DocumentParseTask.document_original_file_id == ChunkRecordDB.doc_id,
                        DocumentParseTask.dataset_id == ChunkRecordDB.set_id,
                        DocumentParseTask.user_id == ChunkRecordDB.user_id,
                    ),
                )
                .join(
                    DocumentParsePipeline,
                    current_document_join_condition(),
                )
                .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
                .join(
                    document_original_file_table,
                    document_original_file_table.c.id
                    == DocumentParseTask.document_original_file_id,
                )
                .where(
                    ChunkRecordDB.chunk_id.in_(ordered),
                    ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE,
                    *current_successful_document_conditions(
                        user_id=scope.user_id,
                        dataset_ids=scope.dataset_ids,
                        doc_ids=scope.doc_ids,
                    ),
                )
            )
        ).all()
        by_id = {str(row[0]): self._chunk_from_row(row) for row in rows}
        return tuple(by_id[chunk_id] for chunk_id in ordered if chunk_id in by_id)

    async def load_chunk_locations(
        self,
        session: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        scope: EffectiveWikiScope,
        max_positions: int | None = None,
    ) -> tuple[WikiChunkLocationRecord, ...]:
        """返回每个请求 Chunk 的直接父标题 ID 及未截断位置总数。

        必须先确认所有 Chunk 均可见；随后用 ``(chunk_id, doc_id)`` 查询引用并要求
        父 HEADING 同文档，使跨文档脏引用无法泄漏其他文档标题。搜索和标题展开
        传入上限时只把稳定排序的前 N 个标题 ID 送入父链水合；批量定位不传上限，
        因而仍返回全部位置。
        """

        if max_positions is not None and max_positions <= 0:
            raise ValueError("max_positions must be positive")
        chunks = await self.load_chunks(session, chunk_ids, scope=scope)
        if len(chunks) != len(tuple(dict.fromkeys(chunk_ids))):
            raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "one or more chunks are not authorized")
        ref = self.model_cls
        parent = aliased(self.model_cls)
        # 先在数据库按 Chunk 分区计数和排名，再由外层应用可选上限；搜索/展开只会
        # 水合前 N 个父标题，完整定位不加外层 rank 条件，仍得到全部直接位置。
        ranked = (
            select(
                ref.chunk_id.label("chunk_id"),
                ref.doc_id.label("doc_id"),
                ref.parent_id.label("parent_id"),
                func.count().over(partition_by=(ref.chunk_id, ref.doc_id)).label("position_count"),
                func.row_number()
                .over(
                    partition_by=(ref.chunk_id, ref.doc_id),
                    order_by=(ref.sort_order, ref.id),
                )
                .label("position_rank"),
            )
            .join(
                parent,
                and_(
                    parent.id == ref.parent_id,
                    parent.doc_id == ref.doc_id,
                    parent.node_type == WIKI_NODE_HEADING,
                ),
            )
            .where(
                ref.node_type == WIKI_NODE_CHUNK_REF,
                tuple_(ref.chunk_id, ref.doc_id).in_(
                    tuple((item.chunk_id, item.doc_id) for item in chunks)
                ),
            )
            .subquery("ranked_chunk_locations")
        )
        statement = select(
            ranked.c.chunk_id,
            ranked.c.parent_id,
            ranked.c.position_count,
            ranked.c.position_rank,
        )
        if max_positions is not None:
            statement = statement.where(ranked.c.position_rank <= max_positions)
        rows = (
            await session.execute(statement.order_by(ranked.c.chunk_id, ranked.c.position_rank))
        ).all()
        headings: dict[str, list[int]] = defaultdict(list)
        position_counts: dict[str, int] = {}
        for chunk_id, parent_id, position_count, _position_rank in rows:
            position_counts[str(chunk_id)] = int(position_count)
            if parent_id is not None:
                headings[str(chunk_id)].append(int(parent_id))
        return tuple(
            WikiChunkLocationRecord(
                chunk,
                tuple(dict.fromkeys(headings[chunk.chunk_id])),
                position_counts.get(chunk.chunk_id, 0),
            )
            for chunk in chunks
        )

    async def load_document_tree(
        self,
        session: AsyncSession,
        *,
        doc_id: int,
        scope: EffectiveWikiScope,
    ) -> WikiDocumentTreeRows:
        """授权文档后单次扫描全部节点，返回可组装的完整树记录。

        结构节点可以整文档读取，但 root/direct Chunk ID 最终仍以 ACTIVE Chunk 真值
        交集为准，避免生命周期清理竞态把失效正文带入响应。
        """

        doc_row = (
            await session.execute(
                select(DocumentParseTask.dataset_id, DocumentParseTask.original_filename)
                .select_from(DocumentParseTask)
                .join(
                    DocumentParsePipeline,
                    current_document_join_condition(),
                )
                .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
                .join(
                    document_original_file_table,
                    document_original_file_table.c.id
                    == DocumentParseTask.document_original_file_id,
                )
                .where(
                    DocumentParseTask.document_original_file_id == doc_id,
                    *current_successful_document_conditions(
                        user_id=scope.user_id,
                        dataset_ids=scope.dataset_ids,
                        doc_ids=(doc_id,),
                    ),
                )
            )
        ).first()
        if doc_row is None:
            raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "document is not authorized")
        dataset_id, original_filename = int(doc_row[0]), str(doc_row[1])
        node_rows = (
            await session.execute(
                select(
                    self.model_cls.id,
                    self.model_cls.heading_key,
                    self.model_cls.parent_id,
                    self.model_cls.node_type,
                    self.model_cls.title,
                    self.model_cls.heading_level,
                    self.model_cls.chunk_id,
                    self.model_cls.sort_order,
                )
                .where(self.model_cls.doc_id == doc_id)
                .order_by(
                    self.model_cls.node_type.desc(), self.model_cls.sort_order, self.model_cls.id
                )
            )
        ).all()
        headings = tuple(
            WikiHeadingRecord(
                id=int(row[0]),
                heading_key=str(row[1]),
                doc_id=doc_id,
                dataset_id=dataset_id,
                original_filename=original_filename,
                parent_id=int(row[2]) if row[2] is not None else None,
                title=str(row[4]),
                heading_level=int(row[5]),
                sort_order=int(row[7]),
            )
            for row in node_rows
            if row[3] == WIKI_NODE_HEADING
        )
        raw_root_chunk_ids = tuple(
            str(row[6])
            for row in node_rows
            if row[3] == WIKI_NODE_CHUNK_REF and row[2] is None and row[6] is not None
        )
        all_chunk_ids = tuple(dict.fromkeys(str(row[6]) for row in node_rows if row[6] is not None))
        direct_chunk_ids_by_heading: dict[int, list[str]] = defaultdict(list)
        for row in node_rows:
            if row[3] == WIKI_NODE_CHUNK_REF and row[2] is not None and row[6] is not None:
                direct_chunk_ids_by_heading[int(row[2])].append(str(row[6]))
        chunks = await self.load_chunks(session, all_chunk_ids, scope=scope)
        visible_chunk_ids = {chunk.chunk_id for chunk in chunks}
        return WikiDocumentTreeRows(
            doc_id,
            dataset_id,
            original_filename,
            headings,
            tuple(chunk_id for chunk_id in raw_root_chunk_ids if chunk_id in visible_chunk_ids),
            {
                key: tuple(
                    chunk_id for chunk_id in dict.fromkeys(values) if chunk_id in visible_chunk_ids
                )
                for key, values in direct_chunk_ids_by_heading.items()
            },
            chunks,
        )

    async def _authorized_heading(
        self,
        session: AsyncSession,
        *,
        doc_id: int,
        heading_key: str,
        scope: EffectiveWikiScope,
    ) -> WikiHeadingRecord | None:
        """在 SQL 中同时按文档、稳定键和授权状态定位唯一标题。"""

        node = self.model_cls
        row = (
            await session.execute(
                select(
                    node.id,
                    node.heading_key,
                    node.doc_id,
                    DocumentParseTask.dataset_id,
                    DocumentParseTask.original_filename,
                    node.parent_id,
                    node.title,
                    node.heading_level,
                    node.sort_order,
                )
                .select_from(node)
                .join(DocumentParseTask, DocumentParseTask.document_original_file_id == node.doc_id)
                .join(DocumentParsePipeline, current_document_join_condition())
                .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
                .join(
                    document_original_file_table,
                    document_original_file_table.c.id
                    == DocumentParseTask.document_original_file_id,
                )
                .where(
                    node.node_type == WIKI_NODE_HEADING,
                    node.doc_id == doc_id,
                    node.heading_key == heading_key,
                    *current_successful_document_conditions(
                        user_id=scope.user_id, dataset_ids=scope.dataset_ids, doc_ids=(doc_id,)
                    ),
                )
            )
        ).first()
        return self._heading_from_row(row) if row is not None else None

    @staticmethod
    def _heading_from_row(row: object) -> WikiHeadingRecord:
        """把固定列序的 SQL 行转换为标题领域记录。"""

        values: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
        return WikiHeadingRecord(
            id=int(values[0]),
            heading_key=str(values[1]),
            doc_id=int(values[2]),
            dataset_id=int(values[3]),
            original_filename=str(values[4]),
            parent_id=int(values[5]) if values[5] is not None else None,
            title=str(values[6]),
            heading_level=int(values[7]),
            sort_order=int(values[8]),
        )

    @staticmethod
    def _chunk_from_row(row: object) -> WikiChunkRecord:
        """把固定列序的 SQL 行转换为 Chunk 真值记录。"""

        values: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
        return WikiChunkRecord(
            chunk_id=str(values[0]),
            doc_id=int(values[1]),
            dataset_id=int(values[2]),
            content=str(values[3]),
            chunk_type=str(values[4]),
            start_line=int(values[5]) if values[5] is not None else None,
            end_line=int(values[6]) if values[6] is not None else None,
        )

    async def replace_document_tree(
        self,
        session: AsyncSession,
        doc_id: int,
        tree_draft: WikiTreeDraft,
    ) -> WikiTreeWriteResult:
        """在调用方事务内批量替换一篇文档的整棵树。

        标题输入可以不是拓扑顺序；本方法会按层级分组，但父标题必须存在且层级
        更低。方法只执行 SQL，不主动 commit/rollback，确保 Chunk 真值与 Wiki 树
        由调用方在同一事务中共同提交或共同回滚。
        """

        drafts_by_key: dict[str, WikiHeadingDraft] = {}
        headings_by_level: dict[int, list[WikiHeadingDraft]] = defaultdict(list)
        for heading in tree_draft.headings:
            if heading.heading_key in drafts_by_key:
                raise ValueError(f"duplicate heading_key in tree draft: {heading.heading_key}")
            if not 1 <= heading.heading_level <= 6:
                raise ValueError(f"invalid heading level: {heading.heading_level}")
            drafts_by_key[heading.heading_key] = heading
            headings_by_level[heading.heading_level].append(heading)
        for heading in tree_draft.headings:
            if heading.parent_heading_key is None:
                continue
            parent = drafts_by_key.get(heading.parent_heading_key)
            if parent is None or parent.heading_level >= heading.heading_level:
                raise ValueError(
                    "tree draft has an invalid parent: "
                    f"{heading.parent_heading_key} -> {heading.heading_key}"
                )
        for chunk_ref in tree_draft.chunk_refs:
            if (
                chunk_ref.parent_heading_key is not None
                and chunk_ref.parent_heading_key not in drafts_by_key
            ):
                raise ValueError(
                    "chunk reference points to unknown heading: " f"{chunk_ref.parent_heading_key}"
                )

        deleted_count = await self.delete_by_doc_id(session, doc_id)
        heading_ids: dict[str, int] = {}

        # ORM add_all 会为自增主键逐对象发送 INSERT。这里每层显式生成一条多值
        # INSERT，再批量反查 heading_key 对应的物理 ID，使真实数据库往返只随
        # H1～H6 非空层级增长，而不随标题节点数量增长。
        for heading_level in sorted(headings_by_level):
            level_headings = headings_by_level[heading_level]
            heading_values: list[dict[str, object]] = []
            for heading in level_headings:
                parent_id = (
                    heading_ids[heading.parent_heading_key]
                    if heading.parent_heading_key is not None
                    else None
                )
                heading_values.append(
                    {
                        "heading_key": heading.heading_key,
                        "doc_id": doc_id,
                        "parent_id": parent_id,
                        "node_type": WIKI_NODE_HEADING,
                        "title": heading.title,
                        "heading_level": heading.heading_level,
                        "chunk_id": None,
                        "sort_order": heading.sort_order,
                    }
                )
            await session.execute(insert(self.model_cls).values(heading_values))

            level_keys = tuple(heading.heading_key for heading in level_headings)
            id_rows = await session.execute(
                select(self.model_cls.heading_key, self.model_cls.id).where(
                    self.model_cls.doc_id == doc_id,
                    self.model_cls.heading_key.in_(level_keys),
                )
            )
            resolved_ids = {str(row[0]): int(row[1]) for row in id_rows.all()}
            missing_keys = set(level_keys) - resolved_ids.keys()
            if missing_keys:
                raise RuntimeError(
                    "failed to resolve inserted wiki heading ids: " f"{sorted(missing_keys)}"
                )
            heading_ids.update(resolved_ids)

        ref_values: list[dict[str, object]] = []
        for chunk_ref in tree_draft.chunk_refs:
            parent_id = (
                heading_ids[chunk_ref.parent_heading_key]
                if chunk_ref.parent_heading_key is not None
                else None
            )
            ref_values.append(
                {
                    "heading_key": None,
                    "doc_id": doc_id,
                    "parent_id": parent_id,
                    "node_type": WIKI_NODE_CHUNK_REF,
                    "title": None,
                    "heading_level": None,
                    "chunk_id": chunk_ref.chunk_id,
                    "sort_order": chunk_ref.sort_order,
                }
            )

        if ref_values:
            await session.execute(insert(self.model_cls).values(ref_values))

        return WikiTreeWriteResult(
            deleted_count=deleted_count,
            heading_count=len(tree_draft.headings),
            chunk_ref_count=len(ref_values),
        )

    async def delete_by_doc_id(self, session: AsyncSession, doc_id: int) -> int:
        """幂等删除一篇文档所属的全部 Wiki 节点。"""

        result = await session.execute(
            delete(self.model_cls).where(self.model_cls.doc_id == doc_id)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def delete_refs_by_chunk_ids(
        self,
        session: AsyncSession,
        chunk_ids: Sequence[str],
    ) -> int:
        """幂等删除指向给定 Chunk 的全部 CHUNK_REF。"""

        unique_chunk_ids = tuple(dict.fromkeys(chunk_ids))
        if not unique_chunk_ids:
            return 0
        result = await session.execute(
            delete(self.model_cls)
            .where(self.model_cls.node_type == WIKI_NODE_CHUNK_REF)
            .where(self.model_cls.chunk_id.in_(unique_chunk_ids))
        )
        return int(getattr(result, "rowcount", 0) or 0)
