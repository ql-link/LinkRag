#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run splitter diagnostics and emit chunk cards plus quality metrics.

This script is intentionally outside the runtime pipeline. It exposes the
splitter's intermediate stages so chunking behavior can be reviewed on real
documents without touching network or database resources.

Example:
    .venv/bin/python scripts/dev/splitter_diagnostics.py .papers/test_docs \
      --output-dir .specs/splitter-enhancement-stage2-texttilling \
      --name blog_splitter_diagnostics
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import math
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.core.llm.tokenizer import Tokenizer
from src.core.markdown_parser import MarkdownParser
from src.core.splitter.candidate_boundary_chunker import CandidateBoundaryChunker
from src.core.splitter.chunk_exporter import ChunkExporter
from src.core.splitter.input_adapter import InputAdapter
from src.core.splitter.overlap import ChunkOverlapConfig, ChunkOverlapper
from src.core.splitter.stage_models import CoarseChunk, FinalChunk
from src.core.splitter.stage_two_noop import NoopStageTwoAlgorithm
from src.core.splitter.stage_two_semantic_depth import (
    MD_CONTAINED_ELEMENT_IDS,
    MD_ORIGINAL_TOKEN_COUNT,
    MD_OVERSIZED,
    MD_OVERSIZED_REASON,
    MD_TRUNCATED,
    MD_TRUNCATED_REASON,
    SemanticDepthWindowStageTwo,
)
from src.core.splitter.validators import (
    CoarseChunkSetValidator,
    FinalChunkSetValidator,
    SplitterOutputValidationError,
)

PROTECTED_TYPES = frozenset(["code_block", "math_block", "table", "image"])
TEXT_EXTENSIONS = frozenset([".md", ".markdown", ".txt"])
DEFAULT_VECTOR_DIMS = 384


@dataclass(slots=True)
class LocalEmbeddingResponse:
    embeddings: list[list[float]]


class LocalLexicalEmbedder:
    """Offline lexical embedding for diagnostics.

    It hashes English-ish tokens plus Chinese bigrams/trigrams into a fixed
    vector. The scores are not meant to mirror production embeddings; they are
    stable, local, and good enough to surface suspicious semantic boundaries.
    """

    def __init__(self, dims: int = DEFAULT_VECTOR_DIMS) -> None:
        self.dims = dims
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str], model: str | None = None) -> LocalEmbeddingResponse:
        self.calls.append(list(texts))
        return LocalEmbeddingResponse([self.vectorize(text) for text in texts])

    def vectorize(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in self._tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(value * value for value in vec))
        if norm:
            return [value / norm for value in vec]
        return vec

    @staticmethod
    def _tokens(text: str) -> list[str]:
        lower = text.lower()
        tokens = re.findall(r"[a-z0-9_]+", lower)
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            for n in (2, 3):
                if len(run) >= n:
                    tokens.extend(run[i : i + n] for i in range(len(run) - n + 1))
        return tokens or [lower[:64] or "empty"]


def _count_tokens(tokenizer: Tokenizer, text: str) -> int:
    return tokenizer.count_tokens(text.strip()) if text else 0


def _preview(text: str, limit: int = 180) -> str:
    compact = " / ".join(line.strip() for line in text.strip().splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _percentile(values: list[int], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _stats(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "p95": _percentile(values, 0.95),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


def _heading_for_line(lines: list[str], line: int) -> str:
    current = "preamble"
    for idx, value in enumerate(lines):
        if idx > line:
            break
        stripped = value.strip()
        if stripped.startswith("#") and " " in stripped:
            current = stripped.lstrip("#").strip()
    return current


def _badges(metadata: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    if metadata.get(MD_CONTAINED_ELEMENT_IDS):
        badges.append("anchors=" + ",".join(str(v) for v in metadata[MD_CONTAINED_ELEMENT_IDS]))
    if metadata.get("protected_element_types"):
        badges.append("protected=" + ",".join(str(v) for v in metadata["protected_element_types"]))
    if metadata.get(MD_OVERSIZED):
        badges.append("OVERSIZED=" + str(metadata.get(MD_OVERSIZED_REASON)))
    if metadata.get(MD_TRUNCATED):
        badges.append("TRUNCATED=" + str(metadata.get(MD_TRUNCATED_REASON)))
        if metadata.get(MD_ORIGINAL_TOKEN_COUNT) is not None:
            badges.append("original_tokens=" + str(metadata.get(MD_ORIGINAL_TOKEN_COUNT)))
    if metadata.get("source_chunk_index") is not None:
        badges.append("derived->source " + str(metadata.get("source_chunk_index")))
    return badges


def _chunk_semantic_units(content: str) -> list[str]:
    content = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
    units = [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]
    if len(units) > 1:
        return units
    return [line.strip() for line in content.splitlines() if line.strip()]


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _discover_inputs(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        resolved = path if path.is_absolute() else REPO_ROOT / path
        if resolved.is_dir():
            files.extend(
                p
                for p in sorted(resolved.rglob("*"))
                if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS
            )
        elif resolved.is_file():
            if resolved.suffix.lower() in TEXT_EXTENSIONS:
                files.append(resolved)
        else:
            raise FileNotFoundError(f"input path does not exist: {path}")
    unique: dict[Path, None] = {}
    for file_path in files:
        unique[file_path.resolve()] = None
    return list(unique.keys())


def _final_spans_by_coarse(
    coarse_by_id: dict[str, CoarseChunk],
    finals_by_coarse: dict[str, list[FinalChunk]],
) -> dict[str, list[dict[str, Any]]]:
    spans_by_coarse: dict[str, list[dict[str, Any]]] = {}
    for coarse_id, finals in finals_by_coarse.items():
        coarse = coarse_by_id.get(coarse_id)
        if coarse is None:
            continue
        cursor = 0
        spans: list[dict[str, Any]] = []
        for final in finals:
            start = coarse.content.find(final.content, cursor)
            if start < 0:
                start = coarse.content.find(final.content)
            end = start + len(final.content) if start >= 0 else -1
            spans.append(
                {
                    "final_id": final.id,
                    "final_index": None,
                    "start": start,
                    "end": end,
                    "truncated": bool(final.metadata.get(MD_TRUNCATED)),
                }
            )
            if start >= 0:
                cursor = end
        spans_by_coarse[coarse_id] = spans
    return spans_by_coarse


def _source_groups(finals: list[FinalChunk]) -> dict[str, list[FinalChunk]]:
    groups: dict[str, list[FinalChunk]] = {}
    for final in finals:
        if final.role == "derived_element" or not final.source_coarse_chunk_id:
            continue
        groups.setdefault(str(final.source_coarse_chunk_id), []).append(final)
    return groups


def _constraint_metrics(
    *,
    tokenizer: Tokenizer,
    coarse_chunks: list[CoarseChunk],
    final_chunks: list[FinalChunk],
    exported_chunks: list[Any],
    hard_max_tokens: int,
    validator_error: str | None,
) -> dict[str, Any]:
    coarse_by_id = {coarse.id: coarse for coarse in coarse_chunks}
    finals_by_coarse = _source_groups(final_chunks)
    spans_by_coarse = _final_spans_by_coarse(coarse_by_id, finals_by_coarse)
    index_by_final_id = {final.id: idx for idx, final in enumerate(final_chunks)}
    for spans in spans_by_coarse.values():
        for span in spans:
            span["final_index"] = index_by_final_id.get(span["final_id"])

    hard_max_violations = []
    for index, final in enumerate(final_chunks):
        if final.role == "derived_element":
            continue
        tokens = _count_tokens(tokenizer, final.content)
        if tokens > hard_max_tokens:
            hard_max_violations.append(
                {"final_index": index, "tokens": tokens, "hard_max_tokens": hard_max_tokens}
            )

    overlap_violations = []
    lossless_violations = []
    for coarse_id, spans in spans_by_coarse.items():
        coarse = coarse_by_id[coarse_id]
        has_truncated = any(span["truncated"] for span in spans)
        cursor = 0
        for span in spans:
            start = span["start"]
            end = span["end"]
            if start < 0:
                lossless_violations.append(
                    {
                        "coarse_id": coarse_id,
                        "final_index": span["final_index"],
                        "reason": "final content is not a slice of source coarse",
                    }
                )
                continue
            if start < cursor:
                overlap_violations.append(
                    {
                        "coarse_id": coarse_id,
                        "final_index": span["final_index"],
                        "previous_cursor": cursor,
                        "start": start,
                    }
                )
            if not has_truncated and start != cursor:
                lossless_violations.append(
                    {
                        "coarse_id": coarse_id,
                        "final_index": span["final_index"],
                        "reason": "gap or non-contiguous slice",
                        "expected_start": cursor,
                        "actual_start": start,
                    }
                )
            cursor = max(cursor, end)
        if not has_truncated and cursor != len(coarse.content):
            lossless_violations.append(
                {
                    "coarse_id": coarse_id,
                    "reason": "source coarse content is not fully covered",
                    "covered_until": cursor,
                    "source_length": len(coarse.content),
                }
            )

    protected_split_violations = []
    protected_missing_violations = []
    for coarse in coarse_chunks:
        if coarse.role != "mixed":
            continue
        spans = spans_by_coarse.get(coarse.id, [])
        for view in coarse.element_views:
            if view.element_type not in PROTECTED_TYPES:
                continue
            intersecting = [
                span
                for span in spans
                if span["start"] >= 0
                and span["start"] < view.content_end
                and span["end"] > view.content_start
            ]
            if not intersecting:
                protected_missing_violations.append(
                    {
                        "coarse_id": coarse.id,
                        "element_index": view.element_index,
                        "element_type": view.element_type,
                        "element_id": view.element_id,
                    }
                )
            elif len(intersecting) > 1:
                protected_split_violations.append(
                    {
                        "coarse_id": coarse.id,
                        "element_index": view.element_index,
                        "element_type": view.element_type,
                        "element_id": view.element_id,
                        "final_indexes": [span["final_index"] for span in intersecting],
                    }
                )

    contained: dict[str, list[int]] = {}
    for index, final in enumerate(final_chunks):
        if final.role == "derived_element":
            continue
        for element_id in final.metadata.get(MD_CONTAINED_ELEMENT_IDS) or []:
            contained.setdefault(str(element_id), []).append(index)

    derived_anchor_misses = []
    if contained:
        for index, final in enumerate(final_chunks):
            if final.role != "derived_element":
                continue
            element_id = final.metadata.get("element_id")
            if element_id is not None and str(element_id) not in contained:
                derived_anchor_misses.append({"final_index": index, "element_id": str(element_id)})

    exported_mapping_misses = []
    for index, chunk in enumerate(exported_chunks):
        metadata = getattr(chunk, "metadata", {})
        if (
            metadata.get("chunk_role") == "derived_element"
            and metadata.get("source_chunk_index") is None
        ):
            exported_mapping_misses.append({"exported_index": index})

    return {
        "validator_error": validator_error,
        "lossless_ok": not lossless_violations and validator_error is None,
        "lossless_violations": lossless_violations,
        "hard_max_violations": hard_max_violations,
        "protected_split_violations": protected_split_violations,
        "protected_missing_violations": protected_missing_violations,
        "derived_anchor_misses": derived_anchor_misses,
        "exported_mapping_misses": exported_mapping_misses,
        "stage2_overlap_violations": overlap_violations,
    }


def _shape_metrics(
    *,
    final_items: list[dict[str, Any]],
    max_tokens: int,
    hard_max_tokens: int,
    min_candidate_tokens: int,
) -> dict[str, Any]:
    mixed_items = [item for item in final_items if item["role"] != "derived_element"]
    mixed_tokens = [int(item["tokens"]) for item in mixed_items]
    all_tokens = [int(item["tokens"]) for item in final_items]

    heading_orphans = []
    protected_only = []
    protected_with_context = []
    for item in mixed_items:
        element_types = set(item["element_types"])
        nonempty_lines = [line.strip() for line in item["content"].splitlines() if line.strip()]
        if element_types == {"heading"} or (
            nonempty_lines and all(line.startswith("#") for line in nonempty_lines)
        ):
            heading_orphans.append(item["index"])
        if element_types and element_types <= PROTECTED_TYPES:
            protected_only.append(item["index"])
        elif element_types & PROTECTED_TYPES:
            protected_with_context.append(item["index"])

    return {
        "final_count": len(final_items),
        "mixed_final_count": len(mixed_items),
        "derived_final_count": len(final_items) - len(mixed_items),
        "all_token_stats": _stats(all_tokens),
        "mixed_token_stats": _stats(mixed_tokens),
        "short_mixed_chunks": [
            item["index"] for item in mixed_items if int(item["tokens"]) < min_candidate_tokens
        ],
        "soft_over_mixed_chunks": [
            item["index"] for item in mixed_items if int(item["tokens"]) > max_tokens
        ],
        "near_hard_max_mixed_chunks": [
            item["index"]
            for item in mixed_items
            if int(item["tokens"]) >= int(hard_max_tokens * 0.9)
        ],
        "heading_orphan_chunks": heading_orphans,
        "protected_only_chunks": protected_only,
        "protected_with_context_chunks": protected_with_context,
        "oversized_chunks": [
            item["index"] for item in mixed_items if item["export_metadata"].get(MD_OVERSIZED)
        ],
        "truncated_chunks": [
            item["index"] for item in mixed_items if item["export_metadata"].get(MD_TRUNCATED)
        ],
    }


def _semantic_metrics(
    *,
    final_items: list[dict[str, Any]],
    embedder: LocalLexicalEmbedder,
    boundary_threshold: float,
    mixed_threshold: float,
) -> dict[str, Any]:
    mixed_items = [item for item in final_items if item["role"] != "derived_element"]
    vectors_by_index = {
        item["index"]: embedder.vectorize(item["content"])
        for item in mixed_items
        if item["content"].strip()
    }

    adjacent = []
    for left, right in zip(mixed_items, mixed_items[1:]):
        left_vec = vectors_by_index.get(left["index"])
        right_vec = vectors_by_index.get(right["index"])
        if left_vec is None or right_vec is None:
            continue
        similarity = _cosine(left_vec, right_vec)
        adjacent.append(
            {
                "left_index": left["index"],
                "right_index": right["index"],
                "similarity": similarity,
                "left_section": left["section"],
                "right_section": right["section"],
            }
        )

    intra_scores = []
    mixed_low_internal = []
    for item in mixed_items:
        units = _chunk_semantic_units(item["content"])
        if len(units) < 2:
            continue
        unit_vectors = [embedder.vectorize(unit) for unit in units]
        similarities = [_cosine(left, right) for left, right in zip(unit_vectors, unit_vectors[1:])]
        if not similarities:
            continue
        avg_similarity = statistics.fmean(similarities)
        intra_scores.append(avg_similarity)
        if len(units) >= 3 and avg_similarity <= mixed_threshold:
            mixed_low_internal.append(
                {
                    "final_index": item["index"],
                    "section": item["section"],
                    "avg_similarity": avg_similarity,
                    "unit_count": len(units),
                    "tokens": item["tokens"],
                    "preview": item["preview"],
                }
            )

    adjacent_scores = [item["similarity"] for item in adjacent]
    suspicious_boundaries = sorted(
        [item for item in adjacent if item["similarity"] >= boundary_threshold],
        key=lambda item: item["similarity"],
        reverse=True,
    )
    mixed_low_internal = sorted(mixed_low_internal, key=lambda item: item["avg_similarity"])

    avg_intra = statistics.fmean(intra_scores) if intra_scores else None
    avg_adjacent = statistics.fmean(adjacent_scores) if adjacent_scores else None
    cohesion_gap = None
    if avg_intra is not None and avg_adjacent is not None:
        cohesion_gap = avg_intra - avg_adjacent

    return {
        "avg_intra_chunk_similarity": avg_intra,
        "avg_adjacent_chunk_similarity": avg_adjacent,
        "cohesion_gap": cohesion_gap,
        "boundary_threshold": boundary_threshold,
        "mixed_threshold": mixed_threshold,
        "suspicious_high_similarity_boundaries": suspicious_boundaries[:30],
        "suspicious_low_internal_chunks": mixed_low_internal[:30],
        "all_adjacent_boundary_scores": adjacent,
    }


async def _run_one_document(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    source_lines = text.splitlines()
    tokenizer = Tokenizer()
    parser = MarkdownParser()
    parse_result = parser.parse(text, source_file=_relative(path))
    split_input = InputAdapter.from_parse_result(parse_result)

    overlapper = ChunkOverlapper(
        tokenizer=tokenizer,
        config=ChunkOverlapConfig(tokens=args.overlap_tokens),
    )
    stage1 = CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=args.min_candidate_tokens,
        heading_break_level=args.heading_break_level,
        overlapper=overlapper,
    )
    coarse_set = stage1.run(split_input)
    coarse_validator_error: str | None = None
    try:
        CoarseChunkSetValidator().validate(coarse_set, split_input)
    except SplitterOutputValidationError as exc:
        coarse_validator_error = str(exc)

    lexical_embedder = LocalLexicalEmbedder(dims=args.vector_dims)
    if args.algorithm == "noop":
        stage2 = NoopStageTwoAlgorithm()
    else:
        stage2 = SemanticDepthWindowStageTwo(
            tokenizer=tokenizer,
            embedder=lexical_embedder,
            max_chunk_tokens=args.max_tokens,
            hard_max_tokens=args.hard_max_tokens,
            min_chunk_tokens=args.min_candidate_tokens,
        )
    final_set = await stage2.run(coarse_set)

    final_validator_error: str | None = None
    try:
        FinalChunkSetValidator(
            tokenizer=tokenizer,
            hard_max_tokens=args.hard_max_tokens,
        ).validate(final_set, coarse_set)
    except SplitterOutputValidationError as exc:
        final_validator_error = str(exc)

    exporter_error: str | None = None
    try:
        exported_chunks = ChunkExporter().export(final_set)
    except SplitterOutputValidationError as exc:
        exporter_error = str(exc)
        exported_chunks = []

    parsed_items = [
        {
            "index": index,
            "type": element.type.value,
            "tokens": _count_tokens(tokenizer, element.content),
            "start_line": element.start_line,
            "end_line": element.end_line,
            "metadata": dict(element.metadata),
            "preview": _preview(element.content),
        }
        for index, element in enumerate(parse_result.elements)
    ]
    type_counts: dict[str, int] = {}
    for item in parsed_items:
        type_counts[item["type"]] = type_counts.get(item["type"], 0) + 1

    coarse_items = [
        {
            "index": index,
            "id": coarse.id,
            "role": coarse.role,
            "tokens": coarse.token_count,
            "start_line": coarse.start_line,
            "end_line": coarse.end_line,
            "section": _heading_for_line(source_lines, coarse.start_line),
            "element_types": list(coarse.element_types),
            "source_coarse_chunk_id": coarse.source_coarse_chunk_id,
            "source_element_indexes": list(coarse.source_element_indexes),
            "protected_ranges": [asdict(item) for item in coarse.protected_ranges],
            "element_views": [asdict(item) for item in coarse.element_views],
            "metadata": dict(coarse.metadata),
            "preview": _preview(coarse.content),
        }
        for index, coarse in enumerate(coarse_set.chunks)
    ]

    exported_metadata_by_index = [dict(getattr(chunk, "metadata", {})) for chunk in exported_chunks]
    final_items = []
    for index, final in enumerate(final_set.chunks):
        export_metadata = (
            exported_metadata_by_index[index]
            if index < len(exported_metadata_by_index)
            else dict(final.metadata)
        )
        item = {
            "index": index,
            "id": final.id,
            "role": final.role,
            "tokens": _count_tokens(tokenizer, final.content),
            "start_line": final.start_line,
            "end_line": final.end_line,
            "section": _heading_for_line(source_lines, final.start_line),
            "source_coarse_chunk_id": final.source_coarse_chunk_id,
            "element_types": list(final.element_types),
            "heading_trail": list(final.heading_trail),
            "heading_trails": [list(trail) for trail in final.heading_trails],
            "final_metadata": dict(final.metadata),
            "export_metadata": export_metadata,
            "content": final.content if not args.no_json_content else None,
            "preview": _preview(final.content),
        }
        item["badges"] = _badges(export_metadata)
        final_items.append(item)

    final_items_with_content = [
        {**item, "content": final_set.chunks[item["index"]].content} for item in final_items
    ]
    constraints = _constraint_metrics(
        tokenizer=tokenizer,
        coarse_chunks=coarse_set.chunks,
        final_chunks=final_set.chunks,
        exported_chunks=exported_chunks,
        hard_max_tokens=args.hard_max_tokens,
        validator_error=final_validator_error,
    )
    shape = _shape_metrics(
        final_items=final_items_with_content,
        max_tokens=args.max_tokens,
        hard_max_tokens=args.hard_max_tokens,
        min_candidate_tokens=args.min_candidate_tokens,
    )
    semantic = _semantic_metrics(
        final_items=final_items_with_content,
        embedder=lexical_embedder,
        boundary_threshold=args.boundary_similarity_threshold,
        mixed_threshold=args.mixed_similarity_threshold,
    )

    finals_by_coarse: dict[str, list[int]] = {}
    flags_by_coarse: dict[str, list[str]] = {}
    for item in final_items:
        source_id = item["source_coarse_chunk_id"]
        if source_id:
            finals_by_coarse.setdefault(str(source_id), []).append(int(item["index"]))
            flags_by_coarse.setdefault(str(source_id), []).extend(item["badges"])
    for item in coarse_items:
        item["final_indexes"] = finals_by_coarse.get(item["id"], [])
        item["flags"] = sorted(set(flags_by_coarse.get(item["id"], [])))

    summary = {
        "source_file": _relative(path),
        "source_name": path.name,
        "source_tokens": _count_tokens(tokenizer, text),
        "source_lines": text.count("\n") + 1,
        "parsed_elements": len(parsed_items),
        "element_type_counts": type_counts,
        "coarse_chunks": len(coarse_items),
        "final_chunks": len(final_items),
        "exported_chunks": len(exported_chunks),
        "stage1_strategy": coarse_set.strategy,
        "stage2_strategy": final_set.stage2_strategy,
        "embed_calls": len(lexical_embedder.calls),
        "embed_batch_sizes": [len(call) for call in lexical_embedder.calls],
        "coarse_validator_error": coarse_validator_error,
        "final_validator_error": final_validator_error,
        "exporter_error": exporter_error,
    }
    return {
        "summary": summary,
        "metrics": {
            "constraints": constraints,
            "shape": shape,
            "semantic": semantic,
        },
        "parsed_elements": parsed_items,
        "coarse_chunks": coarse_items,
        "final_chunks": final_items,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _render_metric_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None:
        return "-"
    if isinstance(value, list):
        return str(value[:20]) + (" ..." if len(value) > 20 else "")
    return str(value)


def _render_html(report: dict[str, Any]) -> str:
    config = report["config"]
    doc_cards = []
    doc_sections = []
    for doc in report["documents"]:
        summary = doc["summary"]
        constraints = doc["metrics"]["constraints"]
        shape = doc["metrics"]["shape"]
        semantic = doc["metrics"]["semantic"]
        doc_cards.append(
            "<div class='metric'>"
            f"<b>{html.escape(summary['source_name'])}</b>"
            f"<span>{summary['source_tokens']}</span>"
            f"<small>{summary['final_chunks']} final / {summary['coarse_chunks']} coarse<br>"
            f"lossless={constraints['lossless_ok']} · "
            f"hard={len(constraints['hard_max_violations'])} · "
            f"protected_split={len(constraints['protected_split_violations'])}</small>"
            "</div>"
        )

        metric_rows = []
        metric_pairs = {
            "lossless_ok": constraints["lossless_ok"],
            "validator_error": constraints["validator_error"],
            "hard_max_violations": len(constraints["hard_max_violations"]),
            "protected_split_violations": len(constraints["protected_split_violations"]),
            "derived_anchor_misses": len(constraints["derived_anchor_misses"]),
            "stage2_overlap_violations": len(constraints["stage2_overlap_violations"]),
            "mixed_token_stats": shape["mixed_token_stats"],
            "short_mixed_chunks": shape["short_mixed_chunks"],
            "soft_over_mixed_chunks": shape["soft_over_mixed_chunks"],
            "heading_orphan_chunks": shape["heading_orphan_chunks"],
            "protected_only_chunks": shape["protected_only_chunks"],
            "avg_intra_chunk_similarity": semantic["avg_intra_chunk_similarity"],
            "avg_adjacent_chunk_similarity": semantic["avg_adjacent_chunk_similarity"],
            "cohesion_gap": semantic["cohesion_gap"],
            "high_similarity_boundaries": [
                [b["left_index"], b["right_index"], round(b["similarity"], 3)]
                for b in semantic["suspicious_high_similarity_boundaries"][:10]
            ],
            "low_internal_chunks": [
                [c["final_index"], round(c["avg_similarity"], 3)]
                for c in semantic["suspicious_low_internal_chunks"][:10]
            ],
        }
        for key, value in metric_pairs.items():
            metric_rows.append(
                f"<tr><th>{html.escape(key)}</th><td>{html.escape(_render_metric_value(value))}</td></tr>"
            )

        coarse_rows = []
        for item in doc["coarse_chunks"]:
            coarse_rows.append(
                "<tr>"
                f"<td>{item['index']}</td>"
                f"<td>{html.escape(item['section'])}</td>"
                f"<td>{html.escape(item['role'])}</td>"
                f"<td>{item['tokens']}</td>"
                f"<td>{item['start_line']}-{item['end_line']}</td>"
                f"<td>{html.escape(', '.join(item['element_types']))}</td>"
                f"<td>{html.escape(str(item['final_indexes']))}</td>"
                f"<td>{html.escape('; '.join(item['flags']))}</td>"
                f"<td>{html.escape(item['preview'])}</td>"
                "</tr>"
            )

        final_cards = []
        for item in doc["final_chunks"]:
            metadata = item["export_metadata"]
            cls = "chunk"
            if metadata.get(MD_TRUNCATED):
                cls += " truncated"
            elif metadata.get(MD_OVERSIZED):
                cls += " oversized"
            elif metadata.get("protected_element_types"):
                cls += " protected"
            if item["role"] == "derived_element":
                cls += " derived"
            badge_html = (
                "".join(f"<span>{html.escape(str(badge))}</span>" for badge in item["badges"])
                or "<span>normal</span>"
            )
            content = item["content"] if item["content"] is not None else item["preview"]
            final_cards.append(
                f"<details class='{cls}' open>"
                f"<summary><b>#{item['index']}</b> {html.escape(item['section'])} · "
                f"{html.escape(item['role'])} · {item['tokens']} tokens · "
                f"lines {item['start_line']}-{item['end_line']} {badge_html}</summary>"
                f"<pre>{html.escape(content)}</pre>"
                "</details>"
            )

        doc_sections.append(
            f"<section><h2>{html.escape(summary['source_name'])}</h2>"
            "<h3>指标</h3>"
            "<table class='metrics'><tbody>" + "".join(metric_rows) + "</tbody></table>"
            "<h3>Coarse Summary</h3>"
            "<table class='coarse'><thead><tr>"
            "<th>#</th><th>section</th><th>role</th><th>tokens</th><th>lines</th>"
            "<th>types</th><th>finals</th><th>flags</th><th>preview</th>"
            "</tr></thead><tbody>" + "".join(coarse_rows) + "</tbody></table>"
            "<h3>Final Chunk Cards</h3>" + "".join(final_cards) + "</section>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Splitter Diagnostics</title>
<style>
:root {{ --bg:#f6f7f9; --text:#17202a; --muted:#627083; --line:#d8dee8;
  --normal:#fff; --protected:#eef7ff; --oversized:#fff5dc; --truncated:#ffe9e6;
  --derived:#eef9f1; }}
body {{ margin:0; font:14px/1.58 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg); color:var(--text); }}
main {{ max-width:1220px; margin:0 auto; padding:28px 24px 56px; }}
h1 {{ margin:0 0 10px; font-size:26px; }}
h2 {{ margin-top:34px; padding-top:12px; border-top:1px solid var(--line); }}
h3 {{ margin-top:24px; }}
.path {{ color:var(--muted); }}
.summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:10px; margin:18px 0 24px; }}
.metric {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }}
.metric b {{ display:block; font-size:16px; margin-bottom:4px; }}
.metric span {{ font-size:22px; font-weight:700; }}
.metric small {{ display:block; color:var(--muted); margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); }}
th, td {{ border-bottom:1px solid var(--line); padding:7px 9px; text-align:left; vertical-align:top; }}
th {{ background:#eef1f5; }}
.metrics th {{ width:260px; }}
.chunk {{ border:1px solid var(--line); border-radius:8px; background:var(--normal);
  margin:12px 0; overflow:hidden; }}
.chunk.protected {{ background:var(--protected); }}
.chunk.oversized {{ background:var(--oversized); }}
.chunk.truncated {{ background:var(--truncated); }}
.chunk.derived {{ background:var(--derived); }}
summary {{ cursor:pointer; padding:10px 12px; }}
summary span {{ display:inline-block; margin-left:6px; padding:1px 6px; border-radius:999px;
  background:rgba(0,0,0,.08); font-size:12px; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; margin:0; padding:12px;
  border-top:1px solid var(--line); background:rgba(255,255,255,.58);
  font-family:'SFMono-Regular',Consolas,monospace; font-size:12px; line-height:1.45; }}
</style>
</head>
<body><main>
<h1>Splitter Diagnostics</h1>
<p class="path">Inputs: {html.escape(', '.join(report['inputs']))}<br>
JSON: {html.escape(report['json_path'])}<br>
Config: algorithm={html.escape(config['algorithm'])}, max={config['max_tokens']},
hard={config['hard_max_tokens']}, min_candidate={config['min_candidate_tokens']},
overlap={config['overlap_tokens']}<br>
Embedder: offline lexical hash embedding, no network/db</p>
<div class="summary">{''.join(doc_cards)}</div>
{''.join(doc_sections)}
</main></body></html>
"""


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    input_files = _discover_inputs([Path(value) for value in args.inputs])
    if not input_files:
        raise SystemExit("no input markdown/text files found")

    documents = []
    for path in input_files:
        documents.append(await _run_one_document(path, args))

    aggregate = {
        "doc_count": len(documents),
        "total_source_tokens": sum(doc["summary"]["source_tokens"] for doc in documents),
        "total_parsed_elements": sum(doc["summary"]["parsed_elements"] for doc in documents),
        "total_coarse_chunks": sum(doc["summary"]["coarse_chunks"] for doc in documents),
        "total_final_chunks": sum(doc["summary"]["final_chunks"] for doc in documents),
        "total_exported_chunks": sum(doc["summary"]["exported_chunks"] for doc in documents),
        "constraint_failures": sum(
            int(not doc["metrics"]["constraints"]["lossless_ok"])
            + len(doc["metrics"]["constraints"]["hard_max_violations"])
            + len(doc["metrics"]["constraints"]["protected_split_violations"])
            + len(doc["metrics"]["constraints"]["derived_anchor_misses"])
            + len(doc["metrics"]["constraints"]["stage2_overlap_violations"])
            for doc in documents
        ),
    }
    return {
        "inputs": [_relative(path) for path in input_files],
        "config": {
            "algorithm": args.algorithm,
            "max_tokens": args.max_tokens,
            "hard_max_tokens": args.hard_max_tokens,
            "min_candidate_tokens": args.min_candidate_tokens,
            "heading_break_level": args.heading_break_level,
            "overlap_tokens": args.overlap_tokens,
            "vector_dims": args.vector_dims,
            "boundary_similarity_threshold": args.boundary_similarity_threshold,
            "mixed_similarity_threshold": args.mixed_similarity_threshold,
        },
        "aggregate": aggregate,
        "documents": documents,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run splitter diagnostics on markdown files.")
    parser.add_argument("inputs", nargs="+", help="Markdown/text files or directories.")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for JSON/HTML outputs. Default: current directory.",
    )
    parser.add_argument("--name", default="splitter_diagnostics", help="Output filename prefix.")
    parser.add_argument(
        "--algorithm",
        choices=["semantic_depth_window", "noop"],
        default="semantic_depth_window",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--hard-max-tokens", type=int, default=1024)
    parser.add_argument("--min-candidate-tokens", type=int, default=128)
    parser.add_argument("--heading-break-level", type=int, default=5)
    parser.add_argument("--overlap-tokens", type=int, default=0)
    parser.add_argument("--vector-dims", type=int, default=DEFAULT_VECTOR_DIMS)
    parser.add_argument(
        "--boundary-similarity-threshold",
        type=float,
        default=0.72,
        help="Adjacent chunks above this lexical similarity are flagged.",
    )
    parser.add_argument(
        "--mixed-similarity-threshold",
        type=float,
        default=0.12,
        help="Chunks with internal average similarity below this are flagged.",
    )
    parser.add_argument(
        "--no-json-content",
        action="store_true",
        help="Omit full chunk content from JSON. HTML still contains content.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.name}.json"
    html_path = output_dir / f"{args.name}.html"

    report = asyncio.run(_run(args))
    report["json_path"] = _relative(json_path)
    report["html_path"] = _relative(html_path)

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    html_path.write_text(_render_html(report), encoding="utf-8")

    aggregate = report["aggregate"]
    print(f"JSON: {_relative(json_path)}")
    print(f"HTML: {_relative(html_path)}")
    print(
        "Summary: "
        f"{aggregate['doc_count']} docs, "
        f"{aggregate['total_source_tokens']} source tokens, "
        f"{aggregate['total_final_chunks']} final chunks, "
        f"{aggregate['constraint_failures']} constraint failures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
