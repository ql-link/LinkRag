from __future__ import annotations

from unittest.mock import Mock

from src.core.markdown_parser import ParseResult
from src.core.splitter.chunking_engine import ChunkingEngine
from src.core.splitter.models import Chunk, ChunkingResult


def test_process_with_parse_result_returns_exact_parser_output_and_chunks() -> None:
    parse_result = ParseResult(elements=[], tables=[], images=[], source_file="source.md")
    chunks = [Chunk(content="body", start_line=0, end_line=0)]
    parser = Mock()
    parser.parse.return_value = parse_result
    chunker = Mock()
    chunker.chunk_from_parse_result.return_value = chunks
    engine = ChunkingEngine(chunker=chunker, parser=parser)

    result = engine.process_with_parse_result("body", source_file="source.md")

    assert result.parse_result is parse_result
    assert result.chunks is chunks
    parser.parse.assert_called_once_with("body", source_file="source.md")
    chunker.chunk_from_parse_result.assert_called_once_with(parse_result)


def test_legacy_entrypoints_keep_list_return_contract() -> None:
    parse_result = ParseResult(elements=[], tables=[], images=[])
    chunks = [Chunk(content="body", start_line=0, end_line=0)]
    parser = Mock()
    parser.parse.return_value = parse_result
    chunker = Mock()
    chunker.chunk_from_parse_result.return_value = chunks
    engine = ChunkingEngine(chunker=chunker, parser=parser)

    assert engine.process("body") is chunks
    assert engine.process_parse_result(parse_result) is chunks


def test_process_parse_result_delegates_to_structured_entry_with_exact_parse_result() -> None:
    parse_result = ParseResult(elements=[], tables=[], images=[])
    chunks = [Chunk(content="body", start_line=0, end_line=0)]
    engine = ChunkingEngine(chunker=Mock(), parser=Mock())
    engine.process_with_parse_result = Mock(
        return_value=ChunkingResult(parse_result=parse_result, chunks=chunks)
    )

    assert engine.process_parse_result(parse_result, heading_break_level=4) is chunks
    engine.process_with_parse_result.assert_called_once_with(parse_result, heading_break_level=4)
