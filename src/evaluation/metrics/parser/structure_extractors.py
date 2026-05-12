# -*- coding: utf-8 -*-
"""Markdown structure extraction for parser quality metrics."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .normalization import normalize_markdown, normalize_plain_text


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
_IMAGE_HTML_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
_ALT_RE = re.compile(r"\balt=[\"']([^\"']*)[\"']", re.IGNORECASE)


@dataclass(frozen=True)
class HeadingNode:
    index: int
    level: int
    text: str
    parent_index: int | None


@dataclass(frozen=True)
class ImageAnchor:
    index: int
    alt: str
    src: str
    nearest_heading: str
    context_hash: str


@dataclass(frozen=True)
class TableBlock:
    index: int
    nearest_heading: str
    row_count: int
    column_count: int
    header_cells: tuple[str, ...]
    structure_hash: str


def extract_headings(md: str | None) -> list[HeadingNode]:
    text = normalize_markdown(md)
    headings: list[HeadingNode] = []
    stack: list[HeadingNode] = []
    for match in _HEADING_RE.finditer(text):
        level = len(match.group(1))
        heading_text = normalize_plain_text(match.group(2))
        while stack and stack[-1].level >= level:
            stack.pop()
        parent_index = stack[-1].index if stack else None
        node = HeadingNode(
            index=len(headings),
            level=level,
            text=heading_text,
            parent_index=parent_index,
        )
        headings.append(node)
        stack.append(node)
    return headings


def extract_images(md: str | None) -> list[ImageAnchor]:
    text = normalize_markdown(md)
    images: list[ImageAnchor] = []
    for match in _IMAGE_MD_RE.finditer(text):
        images.append(_image_anchor(
            text=text,
            start=match.start(),
            alt=match.group(1),
            src=match.group(2),
            index=len(images),
        ))
    for match in _IMAGE_HTML_RE.finditer(text):
        tag = match.group(0)
        alt_match = _ALT_RE.search(tag)
        images.append(_image_anchor(
            text=text,
            start=match.start(),
            alt=alt_match.group(1) if alt_match else "",
            src=match.group(1),
            index=len(images),
        ))
    return sorted(images, key=lambda item: item.index)


def extract_tables(md: str | None) -> list[TableBlock]:
    text = normalize_markdown(md)
    lines = text.splitlines()
    tables: list[TableBlock] = []
    i = 0
    char_offset = 0
    while i < len(lines):
        if not _is_table_line(lines[i]):
            char_offset += len(lines[i]) + 1
            i += 1
            continue
        block_start_offset = char_offset
        block: list[str] = []
        while i < len(lines) and _is_table_line(lines[i]):
            block.append(lines[i])
            char_offset += len(lines[i]) + 1
            i += 1
        parsed_rows = [_split_table_row(row) for row in block if not _is_separator_row(row)]
        if not parsed_rows:
            continue
        column_count = max(len(row) for row in parsed_rows)
        header = tuple(parsed_rows[0])
        structure_payload = "|".join(
            f"{len(row)}:{','.join(row)}" for row in parsed_rows
        )
        tables.append(TableBlock(
            index=len(tables),
            nearest_heading=_nearest_heading_before(text, block_start_offset),
            row_count=len(parsed_rows),
            column_count=column_count,
            header_cells=header,
            structure_hash=_short_hash(structure_payload),
        ))
    return tables


def _image_anchor(text: str, start: int, alt: str, src: str, index: int) -> ImageAnchor:
    context = text[max(0, start - 120): start + 120]
    return ImageAnchor(
        index=index,
        alt=normalize_plain_text(alt),
        src=src.strip(),
        nearest_heading=_nearest_heading_before(text, start),
        context_hash=_short_hash(normalize_plain_text(context)),
    )


def _nearest_heading_before(text: str, offset: int) -> str:
    nearest = ""
    for match in _HEADING_RE.finditer(text[:offset]):
        nearest = normalize_plain_text(match.group(2))
    return nearest


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_separator_row(row: str) -> bool:
    cells = _split_table_row(row)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_table_row(row: str) -> list[str]:
    raw_cells = row.strip().strip("|").split("|")
    return [normalize_plain_text(cell.replace(r"\|", "|")) for cell in raw_cells]


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
