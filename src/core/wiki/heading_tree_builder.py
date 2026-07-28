"""纯内存、确定性构建 Wiki 标题节点与 Chunk 引用。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from src.core.markdown_parser import ElementType, ParseResult
from src.core.splitter.models import Chunk
from src.utils.logger import logger

from .exceptions import WikiTreeBuildError
from .models import WikiChunkRefDraft, WikiHeadingDraft, WikiTreeBuildStats, WikiTreeDraft

_HEADING_KEY_DOMAIN = "wiki-heading:v1\0"
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class HeadingIdentity:
    """标题经规范化后得到的条件稳定身份。"""

    display_title: str
    identity_path: tuple[tuple[int, str], ...]
    occurrence: int
    heading_key: str

    @staticmethod
    def normalize_title(title: str) -> str:
        """折叠展示标题中的连续空白，同时保留原始字母大小写。"""

        return _WHITESPACE_RE.sub(" ", title.strip())

    @classmethod
    def make_key(
        cls,
        *,
        doc_id: int,
        identity_path: Sequence[tuple[int, str]],
        occurrence: int,
    ) -> str:
        """按冻结规范生成带领域版本隔离的 SHA-256 标题身份。"""

        canonical_path = json.dumps(
            [[level, title] for level, title in identity_path],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        material = (
            _HEADING_KEY_DOMAIN + str(doc_id) + "\0" + canonical_path + "\0" + str(occurrence)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _HeadingPosition:
    """标题在 ParseResult 中的元素位置及其稳定业务键。"""

    element_index: int
    start_line: int
    heading_key: str


class ChunkDraftLike(Protocol):
    """构建 Wiki 引用所需的最小 Chunk 持久化草稿协议。"""

    chunk_id: str
    doc_id: int
    content: str
    start_line: int | None
    end_line: int | None
    chunk_index: int | None


class HeadingTreeBuilder:
    """不访问数据库或共享可变状态，构建单篇文档的 Wiki 树。"""

    def build(
        self,
        *,
        doc_id: int,
        parse_result: ParseResult,
        chunks: Sequence[Chunk],
        chunk_drafts: Sequence[ChunkDraftLike],
    ) -> WikiTreeDraft:
        """构建按拓扑排序的标题和直属 Chunk 引用。

        非标题 ParseResult 元素与 Chunk 的物理行区间交集是结构归属真值。
        heading trail 只作诊断和唯一可判定时的兜底，禁止按标题文本全局匹配，
        以免同名标题把 Chunk 挂到错误位置。

        Raises:
            WikiTreeBuildError: 输入数量、文档归属、位置或标题层级不合法。
        """

        self._validate_inputs(doc_id, chunks, chunk_drafts)
        headings, terminal_by_element, heading_by_trail = self._build_headings(doc_id, parse_result)

        refs_by_parent: dict[str | None, dict[str, tuple[int, int]]] = defaultdict(dict)
        for sequence, (chunk, draft) in enumerate(zip(chunks, chunk_drafts)):
            parents = self._parents_for_chunk(
                chunk,
                parse_result,
                terminal_by_element,
                heading_by_trail,
            )
            if not parents:
                # 只覆盖标题元素、没有正文交集的 Chunk 不建立结构归属，避免把
                # 末尾标题因 overlap 合并进前一个正文 Chunk 后误挂载。
                continue
            ordering = draft.chunk_index if draft.chunk_index is not None else sequence
            for parent_key in parents:
                current = refs_by_parent[parent_key].get(draft.chunk_id)
                candidate = (ordering, sequence)
                if current is None or candidate < current:
                    refs_by_parent[parent_key][draft.chunk_id] = candidate

        chunk_refs: list[WikiChunkRefDraft] = []
        for parent_key, chunk_order in refs_by_parent.items():
            ordered = sorted(chunk_order.items(), key=lambda item: (item[1], item[0]))
            chunk_refs.extend(
                WikiChunkRefDraft(
                    chunk_id=chunk_id,
                    parent_heading_key=parent_key,
                    sort_order=sort_order,
                )
                for sort_order, (chunk_id, _order) in enumerate(ordered)
            )

        stats = WikiTreeBuildStats(
            heading_count=len(headings),
            chunk_ref_count=len(chunk_refs),
            root_chunk_ref_count=sum(ref.parent_heading_key is None for ref in chunk_refs),
        )
        tree = WikiTreeDraft(headings=tuple(headings), chunk_refs=tuple(chunk_refs), stats=stats)
        logger.bind(
            event="wiki_tree_built",
            doc_id=doc_id,
            heading_count=stats.heading_count,
            chunk_ref_count=stats.chunk_ref_count,
            root_chunk_ref_count=stats.root_chunk_ref_count,
        ).info("Wiki heading tree built")
        return tree

    @staticmethod
    def _validate_inputs(
        doc_id: int,
        chunks: Sequence[Chunk],
        chunk_drafts: Sequence[ChunkDraftLike],
    ) -> None:
        """在建树前校验 Chunk 与持久化草稿一一同序且结构字段一致。"""

        if doc_id <= 0:
            raise WikiTreeBuildError("doc_id must be positive")
        if len(chunks) != len(chunk_drafts):
            raise WikiTreeBuildError("chunks and chunk_drafts must have the same length")
        for index, (chunk, draft) in enumerate(zip(chunks, chunk_drafts)):
            if draft.doc_id != doc_id:
                raise WikiTreeBuildError(
                    f"chunk draft {index} belongs to doc_id={draft.doc_id}, expected {doc_id}"
                )
            if draft.start_line != chunk.start_line or draft.end_line != chunk.end_line:
                raise WikiTreeBuildError(f"chunk and draft line range differ at index {index}")
            if draft.content != chunk.content:
                raise WikiTreeBuildError(f"chunk and draft content differ at index {index}")
            chunk_index = (chunk.metadata or {}).get("chunk_index")
            if chunk_index is not None and draft.chunk_index != int(chunk_index):
                raise WikiTreeBuildError(f"chunk and draft order differ at index {index}")
            if chunk.start_line < 0 or chunk.end_line < chunk.start_line:
                raise WikiTreeBuildError(f"invalid chunk line range at index {index}")

    def _build_headings(
        self,
        doc_id: int,
        parse_result: ParseResult,
    ) -> tuple[
        list[WikiHeadingDraft],
        dict[int, str | None],
        dict[tuple[str, ...], str | None],
    ]:
        """按元素物理顺序维护标题栈，生成稳定身份和末端标题映射。"""

        headings: list[WikiHeadingDraft] = []
        terminal_by_element: dict[int, str | None] = {}
        stack: list[tuple[int, str, tuple[tuple[int, str], ...], tuple[str, ...]]] = []
        occurrence_by_path: dict[tuple[tuple[int, str], ...], int] = defaultdict(int)
        sibling_count: dict[str | None, int] = defaultdict(int)
        heading_by_trail: dict[tuple[str, ...], str | None] = {}

        ordered_elements = sorted(
            enumerate(parse_result.elements),
            key=lambda item: (item[1].start_line, item[1].end_line, item[0]),
        )
        for element_index, element in ordered_elements:
            if element.type != ElementType.HEADING:
                terminal_by_element[element_index] = stack[-1][1] if stack else None
                continue

            try:
                level = int(element.metadata.get("heading_level", 0))
            except (TypeError, ValueError) as exc:
                raise WikiTreeBuildError("heading_level must be an integer from 1 to 6") from exc
            if not 1 <= level <= 6:
                raise WikiTreeBuildError(f"heading_level out of range: {level}")

            metadata_title = element.metadata.get("heading_text")
            raw_title = str(
                metadata_title
                if metadata_title is not None
                else element.content.lstrip("#").strip()
            )
            display_title = HeadingIdentity.normalize_title(raw_title)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent_key = stack[-1][1] if stack else None
            parent_path = stack[-1][2] if stack else ()
            parent_trail = stack[-1][3] if stack else ()
            identity_path = parent_path + ((level, display_title.casefold()),)
            display_trail = parent_trail + (display_title.casefold(),)
            occurrence = occurrence_by_path[identity_path]
            occurrence_by_path[identity_path] += 1
            heading_key = HeadingIdentity.make_key(
                doc_id=doc_id,
                identity_path=identity_path,
                occurrence=occurrence,
            )
            sort_order = sibling_count[parent_key]
            sibling_count[parent_key] += 1
            headings.append(
                WikiHeadingDraft(
                    heading_key=heading_key,
                    title=display_title,
                    heading_level=level,
                    parent_heading_key=parent_key,
                    sort_order=sort_order,
                )
            )
            stack.append((level, heading_key, identity_path, display_trail))
            if display_trail in heading_by_trail:
                if heading_by_trail[display_trail] != heading_key:
                    heading_by_trail[display_trail] = None
            else:
                heading_by_trail[display_trail] = heading_key

        return headings, terminal_by_element, heading_by_trail

    @staticmethod
    def _parents_for_chunk(
        chunk: Chunk,
        parse_result: ParseResult,
        terminal_by_element: dict[int, str | None],
        heading_by_trail: dict[tuple[str, ...], str | None],
    ) -> tuple[str | None, ...]:
        """依据正文元素交集确定 Chunk 的全部末端标题或虚拟根位置。"""

        parents: list[str | None] = []
        seen: set[str | None] = set()
        intersects_heading = False
        for element_index, element in enumerate(parse_result.elements):
            if element.type == ElementType.HEADING:
                if element.start_line <= chunk.end_line and element.end_line >= chunk.start_line:
                    intersects_heading = True
                continue
            intersects = (
                element.start_line <= chunk.end_line and element.end_line >= chunk.start_line
            )
            if not intersects:
                continue
            parent_key = terminal_by_element.get(element_index)
            if parent_key not in seen:
                parents.append(parent_key)
                seen.add(parent_key)
        if parents or intersects_heading:
            return tuple(parents)

        metadata = chunk.metadata or {}
        raw_trails = metadata.get("heading_trails")
        if not isinstance(raw_trails, list):
            single_trail = metadata.get("heading_trail")
            raw_trails = [single_trail] if isinstance(single_trail, list) else []
        for raw_trail in raw_trails:
            if not isinstance(raw_trail, list) or not raw_trail:
                continue
            if not all(isinstance(segment, str) for segment in raw_trail):
                continue
            trail = tuple(
                HeadingIdentity.normalize_title(segment).casefold() for segment in raw_trail
            )
            parent_key = heading_by_trail.get(trail)
            if parent_key is not None and parent_key not in seen:
                parents.append(parent_key)
                seen.add(parent_key)
        return tuple(parents)
