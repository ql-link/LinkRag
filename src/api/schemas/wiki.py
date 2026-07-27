"""Wiki 对外接口使用的严格请求与响应 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    """禁止未声明字段进入 Wiki 公共契约的基础模型。"""

    model_config = ConfigDict(extra="forbid")


def _positive_sorted(values: object) -> list[int] | None:
    """校验 ID 列表为正整数，并返回去重后的稳定升序结果。"""

    if values is None:
        return None
    if not isinstance(values, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in values
    ):
        raise ValueError("IDs must be strict integers")
    if any(value <= 0 for value in values):
        raise ValueError("IDs must be positive integers")
    return sorted(set(values))


class WikiSearchRequest(_StrictModel):
    """Wiki 搜索请求，支持授权数据集、文档范围和续页游标。"""

    query: str
    dataset_ids: list[int] | None = None
    doc_ids: list[int] | None = None
    cursor: str | None = None

    @field_validator("dataset_ids", "doc_ids", mode="before")
    @classmethod
    def validate_ids(cls, value: list[int] | None) -> list[int] | None:
        """统一规范化可选的数据集和文档 ID 列表。"""

        return _positive_sorted(value)


class WikiChunkLocationsRequest(_StrictModel):
    """Chunk 批量反向定位请求，一次最多提交 100 个唯一 ID。"""

    chunk_ids: list[str] = Field(min_length=1, max_length=100)
    dataset_ids: list[int] | None = None

    @field_validator("chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, values: list[str]) -> list[str]:
        """去除 Chunk ID 首尾空白并按首次出现顺序去重。"""

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if not item:
                raise ValueError("chunk_ids must not contain blank values")
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        if len(normalized) > 100:
            raise ValueError("chunk_ids must contain at most 100 unique values")
        return normalized

    @field_validator("dataset_ids", mode="before")
    @classmethod
    def validate_dataset_ids(cls, value: list[int] | None) -> list[int] | None:
        """规范化 Chunk 定位请求的可选数据集范围。"""

        return _positive_sorted(value)


class WikiHeadingPathItem(_StrictModel):
    """标题路径中的单级稳定身份与展示信息。"""

    heading_key: str
    title: str
    heading_level: int


class WikiHeadingPosition(_StrictModel):
    """Chunk 在标题树中的一个完整路径位置。"""

    path: list[WikiHeadingPathItem]


class WikiHeadingSummary(_StrictModel):
    """搜索结果中的标题摘要、直属 Chunk 预览及展开状态。"""

    heading_key: str
    doc_id: int
    dataset_id: int
    title: str
    heading_level: int
    path: list[WikiHeadingPathItem]
    direct_chunk_count: int
    direct_chunk_preview_id: str | None = None
    direct_chunks_has_more: bool
    next_direct_chunk_cursor: str | None = None


class WikiSearchResult(_StrictModel):
    """标题或正文 Chunk 两种搜索结果的联合载体。"""

    result_type: str
    source: str
    heading: WikiHeadingSummary | None = None
    chunk_id: str | None = None
    bm25_score: float | None = None


class WikiChunk(_StrictModel):
    """从 Chunk 真值表回填的正文及其可见标题位置。"""

    chunk_id: str
    doc_id: int
    dataset_id: int
    content: str
    chunk_type: str
    start_line: int | None = None
    end_line: int | None = None
    positions: list[WikiHeadingPosition]
    position_count: int
    positions_truncated: bool


class WikiSearchResponse(_StrictModel):
    """Wiki 搜索结果页、正文展开区、降级来源和续页状态。"""

    results: list[WikiSearchResult]
    chunks: list[WikiChunk]
    failed_sources: list[str]
    page_size: int
    has_more: bool
    next_cursor: str | None = None


class WikiHeadingChunksResponse(_StrictModel):
    """单个标题的直属 Chunk 独立分页响应。"""

    doc_id: int
    heading_key: str
    chunks: list[WikiChunk]
    page_size: int
    direct_chunks_has_more: bool
    next_direct_chunk_cursor: str | None = None


class WikiChunkLocation(_StrictModel):
    """一个 Chunk 的文档归属及全部直接标题位置。"""

    chunk_id: str
    doc_id: int
    dataset_id: int
    positions: list[WikiHeadingPosition]


class WikiChunkLocationsResponse(_StrictModel):
    """Chunk 批量反向定位响应。"""

    locations: list[WikiChunkLocation]


class WikiTreeHeading(_StrictModel):
    """文档整树响应中的递归标题节点。"""

    heading_key: str
    title: str
    heading_level: int
    direct_chunk_ids: list[str]
    children: list["WikiTreeHeading"]


class WikiDocumentTreeResponse(_StrictModel):
    """文档标题树、根 Chunk 和去重正文的完整响应。"""

    doc_id: int
    dataset_id: int
    original_filename: str
    headings: list[WikiTreeHeading]
    root_chunk_ids: list[str]
    chunks: list[WikiChunk]
