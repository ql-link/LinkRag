"""RAGFlow-compatible tokenizer adapter for ES pre-tokenization."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenizedText:
    """Coarse and fine token strings consumed by the ES indexing stage."""

    coarse_tokens: str
    fine_tokens: str


class RagFlowTokenizer:
    """Thin adapter around the tokenizer implementation used by RAGFlow."""

    TABLE_TAG_RE = re.compile(r"</?(table|td|caption|tr|th)( [^<>]{0,12})?>", re.IGNORECASE)

    def __init__(self) -> None:
        try:
            from infinity.rag_tokenizer import RagTokenizer
        except Exception as exc:  # pragma: no cover - exercised only when dependency is absent.
            raise RuntimeError(
                "RAGFlow tokenizer dependency is not available; install infinity-sdk "
                "or provide a tokenizer implementation."
            ) from exc

        self._tokenizer = RagTokenizer()

    def tokenize(self, text: str) -> TokenizedText:
        """Return RAGFlow coarse and fine token strings for one chunk."""

        cleaned = self.TABLE_TAG_RE.sub(" ", text or "")
        coarse_tokens = self._tokenizer.tokenize(cleaned)
        fine_tokens = self._tokenizer.fine_grained_tokenize(coarse_tokens)
        return TokenizedText(coarse_tokens=coarse_tokens, fine_tokens=fine_tokens)
