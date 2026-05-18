from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.preprocessor.ragflow_tokenizer import TokenizedText
from src.core.preprocessor.service import Preprocessor, PreprocessorError


class StubExecuteResult:
    def __init__(self, records=None) -> None:
        self._records = records or []

    def scalars(self):
        return self

    def all(self):
        return self._records


class CapturingSession:
    def __init__(self, records=None) -> None:
        self.records = records or []
        self.statement = None
        self.commit = AsyncMock()

    async def execute(self, statement):
        self.statement = statement
        return StubExecuteResult(self.records)


class SessionContext:
    def __init__(self, session: CapturingSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StaticTokenizer:
    def tokenize(self, text: str) -> TokenizedText:
        return TokenizedText(
            coarse_tokens=f"coarse {text}",
            fine_tokens=f"fine {text}",
        )


class FailingTokenizer:
    def tokenize(self, text: str) -> TokenizedText:
        raise RuntimeError(f"tokenizer down for {text}")


def build_record(
    chunk_id: str = "chunk-1",
    chunk_index: int | None = 0,
    content: str = "contract",
):
    return SimpleNamespace(
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        content=content,
        user_id=20,
        set_id=30,
        doc_id=10,
    )


def build_preprocessor(session: CapturingSession, *, tokenizer=None):
    return Preprocessor(
        session_factory=lambda: SessionContext(session),
        tokenizer=tokenizer or StaticTokenizer(),
    )


async def test_should_build_file_post_index_plan_from_pending_chunks():
    session = CapturingSession(
        records=[
            build_record(chunk_id="chunk-2", chunk_index=1, content="payment"),
            build_record(chunk_id="chunk-1", chunk_index=0, content="contract"),
        ]
    )
    preprocessor = build_preprocessor(session)

    plan = await preprocessor.build_file_post_index_plan(doc_id=10, task_id="t-001")

    assert plan.file_meta.user_id == 20
    assert plan.file_meta.dataset_id == 30
    assert plan.file_meta.doc_id == 10
    assert plan.file_meta.task_id == "t-001"
    assert [chunk.chunk_id for chunk in plan.chunks_with_tokens] == ["chunk-2", "chunk-1"]
    assert plan.chunks_with_tokens[0].coarse_tokens == "coarse payment"
    assert plan.chunks_with_tokens[0].fine_tokens == "fine payment"


async def test_should_return_empty_plan_when_no_chunks_need_pretokenization():
    session = CapturingSession(records=[])
    preprocessor = build_preprocessor(session)

    plan = await preprocessor.build_file_post_index_plan(doc_id=10, task_id="t-001")

    assert plan.file_meta.doc_id == 10
    assert plan.file_meta.task_id == "t-001"
    assert plan.chunks_with_tokens == []
    session.commit.assert_not_awaited()


async def test_should_raise_without_touching_chunk_when_tokenizer_fails():
    """文件级 all-or-nothing：预分词失败只抛 PreprocessorError，零 DB 写、不标 chunk。"""
    session = CapturingSession(
        records=[
            build_record(chunk_id="chunk-1", chunk_index=0, content="contract"),
            build_record(chunk_id="chunk-2", chunk_index=1, content="payment"),
        ]
    )
    preprocessor = build_preprocessor(session, tokenizer=FailingTokenizer())

    with pytest.raises(PreprocessorError, match="tokenizer down"):
        await preprocessor.build_file_post_index_plan(doc_id=10, task_id="t-001")

    # 失败路径零 DB 写：不 commit、不写任何 chunk es_status。
    session.commit.assert_not_awaited()


async def test_should_raise_when_chunk_index_is_invalid():
    session = CapturingSession(records=[build_record(chunk_index=None)])
    preprocessor = build_preprocessor(session)

    with pytest.raises(PreprocessorError, match="invalid chunk_index"):
        await preprocessor.build_file_post_index_plan(doc_id=10, task_id="t-001")

    session.commit.assert_not_awaited()
