# -*- coding: utf-8 -*-
"""Chunk overlap 配置与文本上下文处理工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer
else:
    Tokenizer = Any


@dataclass(slots=True)
class ChunkOverlapConfig:
    """
        描述 chunk overlap 的独立配置。

    Args:
        None.

    Returns:
        None.
    """

    enabled: bool = True
    tokens: int = 64

    def __post_init__(self) -> None:
        """
            校验 overlap token 配置范围。

        Args:
            None.

        Returns:
            None.
        """
        if self.tokens < 0 or self.tokens > 64:
            raise ValueError("overlap tokens must be between 0 and 64.")


class ChunkOverlapper:
    """
        集中处理 chunk overlap 的 token 截取与上下文拼接。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        tokenizer: Tokenizer,
        config: ChunkOverlapConfig | None = None,
    ) -> None:
        """
            初始化 chunk overlap 工具。

        Args:
            tokenizer: 用于统计与截断 token 的分词器。
            config: overlap 开关与 token 数配置；为空时使用默认配置。

        Returns:
            None.
        """
        self.tokenizer = tokenizer
        self.config = config or ChunkOverlapConfig()

    @property
    def effective_tokens(self) -> int:
        """
            返回当前实际启用的 overlap token 数。

        Args:
            None.

        Returns:
            int: overlap 关闭时返回 0，否则返回配置 token 数。
        """
        if not self.config.enabled:
            return 0
        return self.config.tokens

    def count_tokens(self, text: str) -> int:
        """
            统计文本 token 数。

        Args:
            text: 待统计文本。

        Returns:
            int: token 数。
        """
        return self.tokenizer.count_tokens(text.strip()) if text else 0

    def take_first_tokens(self, text: str, token_limit: int) -> str:
        """
            取出文本开头的指定数量 token。

        Args:
            text: 待截取文本。
            token_limit: 最大 token 数。

        Returns:
            str: 从文本开头截取的内容。
        """
        if not text or token_limit <= 0:
            return ""
        truncated, _ = self.tokenizer.truncate_text(text, token_limit)
        return truncated.strip()

    def take_last_tokens(self, text: str, token_limit: int) -> str:
        """
            取出文本末尾的指定数量 token。

        Args:
            text: 待截取文本。
            token_limit: 最大 token 数。

        Returns:
            str: 从文本末尾截取的内容。
        """
        cleaned = text.strip()
        if not cleaned or token_limit <= 0:
            return ""
        if self.count_tokens(cleaned) <= token_limit:
            return cleaned

        left = 0
        right = len(cleaned) - 1
        best_start = right

        while left <= right:
            mid = (left + right) // 2
            candidate = cleaned[mid:].lstrip()
            tokens = self.count_tokens(candidate)
            if tokens <= token_limit:
                best_start = mid
                right = mid - 1
            else:
                left = mid + 1

        return cleaned[best_start:].lstrip()

    def build_next_chunk(
        self,
        previous_chunk: str,
        next_atom: str,
        *,
        max_chunk_tokens: int,
    ) -> str:
        """
            在切分发生时，为下一块追加上一块尾部 overlap。

        Args:
            previous_chunk: 刚完成的上一块文本。
            next_atom: 下一块起始文本。
            max_chunk_tokens: 下一块允许的最大 token 数。

        Returns:
            str: 带可用 overlap 前缀的下一块文本。
        """
        overlap_budget = self.effective_tokens
        if overlap_budget <= 0:
            return next_atom

        next_tokens = self.count_tokens(next_atom)
        available_for_overlap = max(0, max_chunk_tokens - next_tokens)
        if available_for_overlap <= 0:
            return next_atom

        overlap_tail = self.take_last_tokens(
            previous_chunk,
            min(overlap_budget, available_for_overlap),
        )
        if not overlap_tail:
            return next_atom

        return f"{overlap_tail}\n\n{next_atom}".strip()

    def build_neighbor_context(
        self,
        *,
        previous_content: str | None,
        current_content: str,
        next_content: str | None,
    ) -> tuple[str, int, int]:
        """
            为最终 chunk 构造相邻上下文，并返回实际追加的前后 token 数。

        Args:
            previous_content: 当前 chunk 的前一个 chunk 内容。
            current_content: 当前 chunk 原始内容。
            next_content: 当前 chunk 的后一个 chunk 内容。

        Returns:
            tuple[str, int, int]: 带上下文的内容、前置 token 数、后置 token 数。
        """
        overlap_budget = self.effective_tokens
        if overlap_budget <= 0:
            return current_content, 0, 0

        contextual_parts: list[str] = []
        previous_tokens = 0
        next_tokens = 0

        if previous_content:
            previous_context = self.take_last_tokens(previous_content, overlap_budget)
            if previous_context:
                previous_tokens = self.count_tokens(previous_context)
                contextual_parts.append(previous_context)

        contextual_parts.append(current_content)

        if next_content:
            next_context = self.take_first_tokens(next_content, overlap_budget)
            if next_context:
                next_tokens = self.count_tokens(next_context)
                contextual_parts.append(next_context)

        return "\n\n".join(contextual_parts).strip(), previous_tokens, next_tokens
