"""Wiki 标题树构建、持久化和读取共享的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field

WIKI_NODE_HEADING = "HEADING"
WIKI_NODE_CHUNK_REF = "CHUNK_REF"


@dataclass(frozen=True, slots=True)
class WikiHeadingDraft:
    """按父节点拓扑顺序持久化前的标题草稿。"""

    heading_key: str
    title: str
    heading_level: int
    parent_heading_key: str | None
    sort_order: int


@dataclass(frozen=True, slots=True)
class WikiChunkRefDraft:
    """从标题或文档虚拟根指向既有 Chunk 的引用草稿。"""

    chunk_id: str
    parent_heading_key: str | None
    sort_order: int


@dataclass(frozen=True, slots=True)
class WikiTreeBuildStats:
    """纯构建器输出的不含正文与用户信息的计数诊断。"""

    heading_count: int = 0
    chunk_ref_count: int = 0
    root_chunk_ref_count: int = 0


@dataclass(frozen=True, slots=True)
class WikiTreeDraft:
    """一篇文档完整且按拓扑顺序排列的替换树草稿。"""

    headings: tuple[WikiHeadingDraft, ...] = field(default_factory=tuple)
    chunk_refs: tuple[WikiChunkRefDraft, ...] = field(default_factory=tuple)
    stats: WikiTreeBuildStats = field(default_factory=WikiTreeBuildStats)


@dataclass(frozen=True, slots=True)
class EffectiveWikiScope:
    """所有 Wiki 读取来源共用的规范化授权范围。"""

    user_id: int
    dataset_ids: tuple[int, ...]
    doc_ids: tuple[int, ...] | None
    doc_ids_by_dataset: dict[int, tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class WikiHeadingRecord:
    """仓储查询返回的标题节点及其文档路由信息。"""

    id: int
    heading_key: str
    doc_id: int
    dataset_id: int
    original_filename: str
    parent_id: int | None
    title: str
    heading_level: int
    sort_order: int


@dataclass(frozen=True, slots=True)
class WikiHeadingPathItem:
    """从根到目标标题路径中的一个节点。"""

    heading_key: str
    title: str
    heading_level: int


@dataclass(frozen=True, slots=True)
class WikiHeadingPreview:
    """标题的可见直属 Chunk 数量和首条预览引用。"""

    heading_id: int
    direct_chunk_count: int
    chunk_id: str | None
    first_ref_sort_order: int | None
    first_ref_id: int | None


@dataclass(frozen=True, slots=True)
class WikiChunkRefRecord:
    """直属 Chunk 分页使用的引用主键、顺序和业务 ID。"""

    ref_id: int
    sort_order: int
    chunk_id: str


@dataclass(frozen=True, slots=True)
class WikiChunkRecord:
    """通过可见性门禁后从 Chunk 真值表读取的正文记录。"""

    chunk_id: str
    doc_id: int
    dataset_id: int
    content: str
    chunk_type: str
    start_line: int | None
    end_line: int | None


@dataclass(frozen=True, slots=True)
class WikiChunkLocationRecord:
    """一个可见 Chunk 及其全部直接父标题 ID。"""

    chunk: WikiChunkRecord
    heading_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WikiDocumentTreeRows:
    """一次文档树扫描得到的标题、引用映射和可见 Chunk。"""

    doc_id: int
    dataset_id: int
    original_filename: str
    headings: tuple[WikiHeadingRecord, ...]
    root_chunk_ids: tuple[str, ...]
    direct_chunk_ids_by_heading: dict[int, tuple[str, ...]]
    chunks: tuple[WikiChunkRecord, ...]
