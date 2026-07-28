"""Wiki 搜索使用的纯分页、配额、轮询和游标原语。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from .exceptions import WikiCursorError

WIKI_CURSOR_TTL_SECONDS = 600
MAX_SEARCH_POSITIONS_PER_CHUNK = 10
WIKI_CURSOR_VERSION = 1

T = TypeVar("T")
P = TypeVar("P")
B = TypeVar("B")


def normalize_wiki_query(value: str) -> str:
    """使用与标题展示值一致的规则折叠查询词空白。"""

    return " ".join(value.split())


def make_scope_fingerprint(
    *,
    user_id: int,
    dataset_ids: Sequence[int],
    doc_ids: Sequence[int] | None,
) -> str:
    """为已经授权并规范化的有效范围生成稳定指纹。"""

    payload = {
        "user_id": user_id,
        "dataset_ids": sorted(set(dataset_ids)),
        "doc_ids": sorted(set(doc_ids)) if doc_ids is not None else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _b64encode(value: bytes) -> str:
    """编码为不带填充符的 URL-safe Base64 文本。"""

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    """严格解码规范 URL-safe Base64，拒绝替代编码和非法字符。"""

    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise WikiCursorError("invalid cursor encoding")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise WikiCursorError("invalid cursor encoding") from exc
    if _b64encode(decoded) != value:
        raise WikiCursorError("invalid cursor encoding")
    return decoded


class WikiCursorCodec:
    """使用 Wiki 领域隔离密钥的无状态 HMAC 游标编解码器。"""

    def __init__(self, secret: str, *, clock: Callable[[], float] = time.time) -> None:
        """从会话密钥派生 Wiki 专用签名密钥，并允许测试注入时钟。"""

        if not secret:
            raise ValueError("cursor signing secret must not be empty")
        self._signing_key = hmac.new(
            secret.encode("utf-8"),
            b"wiki-search-cursor:v1",
            hashlib.sha256,
        ).digest()
        self._clock = clock

    def encode(
        self,
        *,
        branch: str,
        binding: Mapping[str, object],
        state: Mapping[str, object],
    ) -> str:
        """签发绑定分支、请求指纹和下一消费位置的 10 分钟游标。"""

        issued_at = int(self._clock())
        payload = {
            "version": WIKI_CURSOR_VERSION,
            "iat": issued_at,
            "exp": issued_at + WIKI_CURSOR_TTL_SECONDS,
            "branch": branch,
            "binding": dict(binding),
            "state": dict(state),
        }
        payload_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._signing_key, payload_bytes, hashlib.sha256).digest()
        return f"{_b64encode(payload_bytes)}.{_b64encode(signature)}"

    def decode_and_validate(
        self,
        cursor: str,
        *,
        expected_branch: str,
        expected_binding: Mapping[str, object],
    ) -> dict[str, object]:
        """验签并校验版本、期限、分支和请求绑定，返回可信游标状态。

        Raises:
            WikiCursorError: 游标格式、签名、版本、期限或绑定任一项不合法。
        """

        try:
            payload_part, signature_part = cursor.split(".", 1)
        except ValueError as exc:
            raise WikiCursorError("invalid cursor format") from exc
        payload_bytes = _b64decode(payload_part)
        supplied_signature = _b64decode(signature_part)
        expected_signature = hmac.new(self._signing_key, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise WikiCursorError("invalid cursor signature")
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WikiCursorError("invalid cursor payload") from exc
        if not isinstance(payload, dict) or payload.get("version") != WIKI_CURSOR_VERSION:
            raise WikiCursorError("unsupported cursor version")
        if payload.get("branch") != expected_branch:
            raise WikiCursorError("cursor branch mismatch")
        if payload.get("binding") != dict(expected_binding):
            raise WikiCursorError("cursor request binding mismatch")
        exp = payload.get("exp")
        if not isinstance(exp, int) or int(self._clock()) >= exp:
            raise WikiCursorError("cursor expired")
        state = payload.get("state")
        if not isinstance(state, dict):
            raise WikiCursorError("invalid cursor state")
        return state


@dataclass(frozen=True, slots=True)
class RoundRobinPosition:
    """BM25 跨数据集轮询的下一库内名次与数据集下标。"""

    rank: int = 0
    dataset_index: int = 0


@dataclass(frozen=True, slots=True)
class RoundRobinPage(Generic[T]):
    """一次跨数据集轮询得到的结果、下一位置和剩余状态。"""

    items: tuple[T, ...]
    next_position: RoundRobinPosition
    has_more: bool


class Bm25RoundRobin:
    """按库内名次优先，从各数据集稳定 BM25 排名中轮询分页。"""

    @classmethod
    def page(
        cls,
        by_dataset: Mapping[int, Sequence[T]],
        *,
        position: RoundRobinPosition = RoundRobinPosition(),
        limit: int,
    ) -> RoundRobinPage[T]:
        """从指定位置读取最多 limit 条候选，并返回精确下一消费位置。"""

        if limit < 0:
            raise ValueError("limit must not be negative")
        datasets = sorted(by_dataset)
        rank = position.rank
        dataset_index = position.dataset_index
        items: list[T] = []
        max_rank = max((len(by_dataset[dataset_id]) for dataset_id in datasets), default=0)

        while len(items) < limit and rank < max_rank and datasets:
            if dataset_index >= len(datasets):
                rank += 1
                dataset_index = 0
                continue
            dataset_id = datasets[dataset_index]
            dataset_index += 1
            hits = by_dataset[dataset_id]
            if rank < len(hits):
                items.append(hits[rank])

        if dataset_index >= len(datasets) and rank < max_rank:
            rank += 1
            dataset_index = 0
        next_position = RoundRobinPosition(rank=rank, dataset_index=dataset_index)
        has_more = cls._has_more(by_dataset, next_position)
        return RoundRobinPage(tuple(items), next_position, has_more)

    @staticmethod
    def _has_more(
        by_dataset: Mapping[int, Sequence[object]],
        position: RoundRobinPosition,
    ) -> bool:
        """判断轮询位置之后是否仍有任一数据集候选。"""

        datasets = sorted(by_dataset)
        for rank in range(position.rank, max((len(v) for v in by_dataset.values()), default=0)):
            start = position.dataset_index if rank == position.rank else 0
            if any(rank < len(by_dataset[dataset_id]) for dataset_id in datasets[start:]):
                return True
        return False


@dataclass(frozen=True, slots=True)
class WikiMergedPage(Generic[P, B]):
    """标题前缀与 BM25 两路合并后的单页及各自续读位置。"""

    prefix_items: tuple[P, ...]
    bm25_items: tuple[B, ...]
    next_prefix_offset: int
    next_bm25_position: RoundRobinPosition
    has_more: bool


class WikiResultMerger:
    """应用冻结的一比二配额，并允许两路候选相互补位。"""

    @staticmethod
    def _identity(item: object, attribute: str) -> Hashable:
        """取得候选去重键，并拒绝不可哈希的错误模型。"""

        value = getattr(item, attribute, item)
        if not isinstance(value, Hashable):
            raise TypeError(f"{attribute} identity must be hashable")
        return value

    @classmethod
    def _unique(cls, items: Sequence[T], attribute: str) -> list[T]:
        """按首次出现顺序对候选指定属性去重。"""

        unique: list[T] = []
        seen: set[Hashable] = set()
        for item in items:
            identity = cls._identity(item, attribute)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(item)
        return unique

    @classmethod
    def merge_page(
        cls,
        prefix_items: Sequence[P],
        bm25_by_dataset: Mapping[int, Sequence[B]],
        *,
        page_size: int,
        prefix_offset: int = 0,
        bm25_position: RoundRobinPosition = RoundRobinPosition(),
    ) -> WikiMergedPage[P, B]:
        """按标题三分之一、BM25 三分之二选取单页并执行双向补位。"""

        if page_size <= 0:
            raise ValueError("page_size must be positive")
        unique_prefix_items = cls._unique(prefix_items, "id")
        seen_bm25: set[Hashable] = set()
        unique_bm25_by_dataset: dict[int, list[B]] = {}
        for dataset_id in sorted(bm25_by_dataset):
            unique_bm25_by_dataset[dataset_id] = []
            for item in bm25_by_dataset[dataset_id]:
                identity = cls._identity(item, "chunk_id")
                if identity in seen_bm25:
                    continue
                seen_bm25.add(identity)
                unique_bm25_by_dataset[dataset_id].append(item)
        prefix_target = math.ceil(page_size / 3)
        bm25_target = page_size - prefix_target

        selected_prefix = list(unique_prefix_items[prefix_offset : prefix_offset + prefix_target])
        next_prefix_offset = prefix_offset + len(selected_prefix)
        bm25_page = Bm25RoundRobin.page(
            unique_bm25_by_dataset,
            position=bm25_position,
            limit=bm25_target,
        )
        selected_bm25 = list(bm25_page.items)

        remaining = page_size - len(selected_prefix) - len(selected_bm25)
        if remaining and next_prefix_offset < len(unique_prefix_items):
            extra_prefix = list(
                unique_prefix_items[next_prefix_offset : next_prefix_offset + remaining]
            )
            selected_prefix.extend(extra_prefix)
            next_prefix_offset += len(extra_prefix)
            remaining -= len(extra_prefix)
        next_bm25_position = bm25_page.next_position
        if remaining and Bm25RoundRobin._has_more(unique_bm25_by_dataset, next_bm25_position):
            extra_bm25 = Bm25RoundRobin.page(
                unique_bm25_by_dataset,
                position=next_bm25_position,
                limit=remaining,
            )
            selected_bm25.extend(extra_bm25.items)
            next_bm25_position = extra_bm25.next_position

        has_more = next_prefix_offset < len(unique_prefix_items) or Bm25RoundRobin._has_more(
            unique_bm25_by_dataset,
            next_bm25_position,
        )
        return WikiMergedPage(
            prefix_items=tuple(selected_prefix),
            bm25_items=tuple(selected_bm25),
            next_prefix_offset=next_prefix_offset,
            next_bm25_position=next_bm25_position,
            has_more=has_more,
        )
