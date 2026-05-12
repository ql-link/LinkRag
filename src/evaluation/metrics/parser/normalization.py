# -*- coding: utf-8 -*-
"""Markdown normalization helpers for parser quality metrics."""
from __future__ import annotations

import re
import unicodedata


_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")


def normalize_markdown(md: str | None) -> str:
    """Normalize Markdown without erasing structural syntax."""
    if not md:
        return ""
    text = unicodedata.normalize("NFKC", str(md))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_plain_text(md: str | None) -> str:
    """Normalize Markdown into text-like content for text completeness metrics."""
    text = normalize_markdown(md)
    text = _IMAGE_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("|", " ")
    text = re.sub(r"[#*_`>\-\[\]().,;:!?/\\]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize_markdown_text(md: str | None) -> list[str]:
    """Tokenize Chinese and latin text with lightweight, deterministic rules."""
    text = normalize_plain_text(md)
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def calculate_lcs_ratio(expected: str | None, actual: str | None, max_chars: int = 5000) -> float:
    """Calculate expected-side character LCS recall.

    Large documents can make classic LCS expensive, so both sides are capped
    consistently. The metric is still useful as a secondary signal while token
    recall remains the primary completeness score.
    """
    expected_text = normalize_plain_text(expected)
    actual_text = normalize_plain_text(actual)
    if not expected_text:
        return 1.0
    expected_text = expected_text[:max_chars]
    actual_text = actual_text[:max_chars]
    previous = [0] * (len(actual_text) + 1)
    for expected_char in expected_text:
        current = [0]
        for j, actual_char in enumerate(actual_text, start=1):
            if expected_char == actual_char:
                current.append(previous[j - 1] + 1)
            else:
                current.append(max(previous[j], current[-1]))
        previous = current
    return round(previous[-1] / len(expected_text), 4)


def token_recall(expected_tokens: list[str], actual_tokens: list[str]) -> float:
    """Calculate multiset recall for expected tokens."""
    if not expected_tokens:
        return 1.0
    remaining: dict[str, int] = {}
    for token in actual_tokens:
        remaining[token] = remaining.get(token, 0) + 1
    matched = 0
    for token in expected_tokens:
        count = remaining.get(token, 0)
        if count > 0:
            matched += 1
            remaining[token] = count - 1
    return round(matched / len(expected_tokens), 4)
