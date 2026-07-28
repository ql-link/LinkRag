"""Wiki 冻结验收场景的 pytest-bdd 步骤与可复现测试夹具。"""

from __future__ import annotations

import asyncio
import inspect
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from pytest_bdd import parsers, step

import src.application.wiki_runtime as runtime_module
import src.core.pipeline.document_delete.purger as purger_module
from src.api.recall_session_auth import SessionAuthContext, verify_session_token
from src.api.routes import wiki as wiki_routes
from src.api.schemas.wiki import WikiChunkLocationsRequest, WikiSearchRequest
from src.application.recall_errors import RecallApiError
from src.application.wiki_runtime import WikiRuntime, get_wiki_runtime
from src.config import settings
from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.pipeline.document_delete.purger import DocumentDeletePurger
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.pipeline.recall.document_readiness import MySqlDocumentReadinessGate
from src.core.pipeline.recall.models import RetrieverHit
from src.core.splitter.models import Chunk
from src.core.storage.bm25_models import Bm25ChunkHit
from src.core.storage.bm25_retriever import Bm25Retriever
from src.core.storage.index_mutation_guard import NoopIndexMutationGuard
from src.core.storage.vector.exceptions import ChunkStructuralUpdateNotAllowedError
from src.core.storage.vector.management_pipeline import VectorStorageManagementPipeline
from src.core.storage.vector.models import ChunkUpdateRequest, StoredChunkDraft
from src.core.storage.wiki_tree.repository import WikiTreeRepository
from src.core.wiki import HeadingIdentity, HeadingTreeBuilder
from src.core.wiki.exceptions import WikiCursorError
from src.core.wiki.models import (
    EffectiveWikiScope,
    WikiChunkLocationRecord,
    WikiChunkRecord,
    WikiChunkRefRecord,
    WikiDocumentTreeRows,
    WikiHeadingPathItem,
    WikiHeadingPreview,
    WikiHeadingRecord,
)
from src.core.wiki.search_service import (
    MAX_SEARCH_POSITIONS_PER_CHUNK,
    Bm25RoundRobin,
    RoundRobinPosition,
    WikiCursorCodec,
    WikiResultMerger,
    make_scope_fingerprint,
    normalize_wiki_query,
)


@dataclass
class WikiAcceptanceState:
    givens: list[str] = field(default_factory=list)
    whens: list[str] = field(default_factory=list)
    thens: list[str] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)


@pytest.fixture
def wiki_acceptance_state() -> WikiAcceptanceState:
    return WikiAcceptanceState()


def _heading(line: int, level: int, title: str) -> MarkdownElement:
    return MarkdownElement(
        type=ElementType.HEADING,
        content=f"{'#' * level} {title}",
        start_line=line,
        end_line=line,
        metadata={"heading_level": level, "heading_text": title},
    )


def _body(line: int) -> MarkdownElement:
    return MarkdownElement(
        type=ElementType.PARAGRAPH,
        content=f"body-{line}",
        start_line=line,
        end_line=line,
    )


def _assert_builder_contract() -> None:
    elements: list[MarkdownElement] = []
    for level in range(1, 7):
        elements.extend((_heading(level * 2, level, f"H{level}"), _body(level * 2 + 1)))
    parse_result = ParseResult(elements=elements, tables=[], images=[])
    chunk = Chunk(
        content="terminal",
        start_line=13,
        end_line=13,
        metadata={"chunk_index": 0, "element_types": ["paragraph"]},
    )
    draft = StoredChunkDraft(
        chunk_id="C1",
        user_id=123,
        set_id=10,
        doc_id=10001,
        bucket_id=0,
        content=chunk.content,
        content_hash="hash",
        chunk_type="paragraph",
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        chunk_index=0,
    )
    tree = HeadingTreeBuilder().build(
        doc_id=10001,
        parse_result=parse_result,
        chunks=[chunk],
        chunk_drafts=[draft],
    )
    assert [item.heading_level for item in tree.headings] == [1, 2, 3, 4, 5, 6]
    assert tree.headings[0].parent_heading_key is None
    assert tree.chunk_refs[0].parent_heading_key == tree.headings[-1].heading_key

    identity_path = ((1, "guide"), (2, "install"))
    original_key = HeadingIdentity.make_key(doc_id=10001, identity_path=identity_path, occurrence=0)
    assert original_key == HeadingIdentity.make_key(
        doc_id=10001, identity_path=identity_path, occurrence=0
    )
    assert original_key != HeadingIdentity.make_key(
        doc_id=10001, identity_path=((1, "guide"), (2, "setup")), occurrence=0
    )

    assert original_key != HeadingIdentity.make_key(
        doc_id=10002, identity_path=identity_path, occurrence=0
    )


def _assert_search_contract() -> None:
    by_dataset = {30: ["30-1", "30-2"], 10: ["10-1", "10-2"], 20: ["20-1"]}
    round_robin = Bm25RoundRobin.page(by_dataset, limit=5)
    assert round_robin.items == ("10-1", "20-1", "30-1", "10-2", "30-2")
    merged = WikiResultMerger.merge_page(list(range(20)), {10: list(range(20, 40))}, page_size=15)
    assert len(merged.prefix_items) == 5
    assert len(merged.bm25_items) == 10

    codec = WikiCursorCodec("acceptance-secret", clock=lambda: 1000)
    binding = {
        "user_id": 123,
        "query": "快速 开始",
        "scope": make_scope_fingerprint(user_id=123, dataset_ids=[20, 10], doc_ids=None),
    }
    cursor = codec.encode(
        branch="mixed",
        binding=binding,
        state={"bm25_rank": 0, "bm25_dataset_index": 10},
    )
    assert (
        codec.decode_and_validate(cursor, expected_branch="mixed", expected_binding=binding)[
            "bm25_dataset_index"
        ]
        == 10
    )
    with pytest.raises(WikiCursorError):
        codec.decode_and_validate(cursor + "x", expected_branch="mixed", expected_binding=binding)


def _assert_api_contract() -> None:
    assert normalize_wiki_query("  快速   开始  ") == "快速 开始"
    assert settings.WIKI_SEARCH_PAGE_SIZE > 0
    assert settings.WIKI_BM25_TOP_K_PER_DATASET > 0
    assert MAX_SEARCH_POSITIONS_PER_CHUNK == 10
    assert WikiSearchRequest(
        query="x", dataset_ids=[20, 10, 20], doc_ids=[2, 1, 2]
    ).dataset_ids == [10, 20]
    assert WikiChunkLocationsRequest(chunk_ids=["C1", "C1"]).chunk_ids == ["C1"]
    with pytest.raises(ValidationError):
        WikiSearchRequest.model_validate({"query": "x", "top_k": 999})


def _assert_lifecycle_contract(field_name: str = "start_line") -> None:
    error = ChunkStructuralUpdateNotAllowedError({field_name})
    assert error.fields == {field_name}
    assert "reparse the whole document" in str(error)
    assert RoundRobinPosition().rank == 0


def _build_tree(
    elements: list[MarkdownElement],
    chunk_specs: list[tuple[str, int, int, str]],
):
    chunks: list[Chunk] = []
    drafts: list[StoredChunkDraft] = []
    for index, (chunk_id, start_line, end_line, chunk_type) in enumerate(chunk_specs):
        chunk = Chunk(
            content=f"body-{chunk_id}",
            start_line=start_line,
            end_line=end_line,
            metadata={"chunk_index": index, "chunk_type": chunk_type},
        )
        chunks.append(chunk)
        drafts.append(
            StoredChunkDraft(
                chunk_id=chunk_id,
                user_id=123,
                set_id=10,
                doc_id=10001,
                bucket_id=0,
                content=chunk.content,
                content_hash=f"hash-{chunk_id}",
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=index,
            )
        )
    return HeadingTreeBuilder().build(
        doc_id=10001,
        parse_result=ParseResult(elements=elements, tables=[], images=[]),
        chunks=chunks,
        chunk_drafts=drafts,
    )


def _install_heading_key(tree) -> str:
    """从真实建树结果中取得规范标题为 install 的稳定业务键。"""

    return next(item.heading_key for item in tree.headings if item.title.casefold() == "install")


def _nonstructural_identity_keys(change: str) -> tuple[str, str]:
    """针对每种非结构变化分别重建树，返回变化前后的 Install 标题键。"""

    base_elements = [
        _heading(1, 1, "Guide"),
        _heading(2, 2, "Intro"),
        _body(3),
        _heading(4, 2, "Install"),
        _body(5),
    ]
    before = _build_tree(base_elements, [("C1", 5, 5, "paragraph")])
    if change == "正文增删导致行号变化":
        after = _build_tree(
            [
                _heading(10, 1, "Guide"),
                _heading(20, 2, "Intro"),
                _body(30),
                _heading(40, 2, "Install"),
                _body(50),
            ],
            [("C2", 50, 50, "paragraph")],
        )
    elif change == "Chunk 重新分块":
        after = _build_tree(
            base_elements,
            [("C2", 5, 5, "paragraph"), ("C3", 5, 5, "derived")],
        )
    elif change == "chunk_id 重新分配":
        after = _build_tree(base_elements, [("NEW-C1", 5, 5, "paragraph")])
    elif change == "标题仅改变英文大小写":
        after = _build_tree(
            [
                _heading(1, 1, "GUIDE"),
                _heading(2, 2, "Intro"),
                _body(3),
                _heading(4, 2, "INSTALL"),
                _body(5),
            ],
            [("C2", 5, 5, "paragraph")],
        )
    elif change == "同一父标题下普通兄弟重排":
        after = _build_tree(
            [
                _heading(1, 1, "Guide"),
                _heading(2, 2, "Install"),
                _body(3),
                _heading(4, 2, "Intro"),
                _body(5),
            ],
            [("C2", 3, 3, "paragraph")],
        )
    elif change == "标题删除后以相同结构重新出现":
        deleted = _build_tree(
            [_heading(1, 1, "Guide"), _heading(2, 2, "Intro"), _body(3)],
            [("C2", 3, 3, "paragraph")],
        )
        assert all(item.title.casefold() != "install" for item in deleted.headings)
        after = _build_tree(base_elements, [("C3", 5, 5, "paragraph")])
    elif change == "内容完全相同的重复解析":
        after = _build_tree(base_elements, [("C1", 5, 5, "paragraph")])
    else:
        raise AssertionError(f"unknown nonstructural identity change: {change}")
    return _install_heading_key(before), _install_heading_key(after)


def _parameter(state: WikiAcceptanceState, name: str, expected: object) -> None:
    if name in state.parameters:
        assert state.parameters[name] == str(expected)


@asynccontextmanager
async def _acceptance_db_context():
    yield object()


def _acceptance_heading(node_id: int, *, title: str = "Guide") -> WikiHeadingRecord:
    return WikiHeadingRecord(
        id=node_id,
        heading_key=f"{node_id:064x}",
        doc_id=10001,
        dataset_id=10,
        original_filename="guide.md",
        parent_id=None,
        title=title,
        heading_level=1,
        sort_order=node_id,
    )


def _acceptance_location(chunk_id: str, *, heading_ids: tuple[int, ...] = ()):
    return WikiChunkLocationRecord(
        chunk=WikiChunkRecord(
            chunk_id=chunk_id,
            doc_id=10001,
            dataset_id=10,
            content=f"content-{chunk_id}",
            chunk_type="paragraph",
            start_line=1,
            end_line=1,
        ),
        heading_ids=heading_ids,
        position_count=len(heading_ids),
    )


def _acceptance_runtime(
    monkeypatch,
    *,
    strict: bool = False,
    page_size: int = 15,
    dataset_ids: tuple[int, ...] = (10,),
):
    monkeypatch.setattr(runtime_module, "get_db_context", _acceptance_db_context)
    repository = AsyncMock()
    repository.resolve_scope.return_value = EffectiveWikiScope(123, dataset_ids, None, {})
    repository.revalidate_visible_headings.side_effect = lambda _db, headings, **_kw: tuple(
        headings
    )
    repository.load_heading_paths.side_effect = lambda _db, headings: {
        item.id: () for item in headings
    }
    repository.load_heading_previews.side_effect = lambda _db, headings, **_kw: {
        item.id: WikiHeadingPreview(item.id, 0, None, None, None) for item in headings
    }
    repository.find_matching_preview_chunk_ids.return_value = frozenset()
    repository.load_chunk_locations.return_value = ()
    repository.load_headings_by_ids.return_value = ()
    bm25 = AsyncMock()
    bm25.recall_by_dataset.return_value = {dataset_id: [] for dataset_id in dataset_ids}
    readiness = AsyncMock()
    readiness.filter_visible_hits.side_effect = lambda hits, **_kw: list(hits)
    runtime = WikiRuntime(
        repository=repository,
        bm25_retriever=bm25,
        readiness_gate=readiness,
        cursor_codec=WikiCursorCodec("acceptance-secret", clock=lambda: 1000),
        page_size=page_size,
        bm25_top_k_per_dataset=50,
        strict=strict,
    )
    return runtime, repository, bm25, readiness


def _acceptance_context() -> SessionAuthContext:
    return SessionAuthContext(user_id=123, dataset_ids=[10, 20], request_id="wiki-acceptance")


def _acceptance_app(runtime, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(wiki_routes.router)
    if authenticated:
        app.dependency_overrides[verify_session_token] = _acceptance_context
    app.dependency_overrides[get_wiki_runtime] = lambda: runtime

    @app.exception_handler(RecallApiError)
    async def handle_recall_error(_request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    return app


async def _post_search(app: FastAPI, body: object):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/v1/wiki/search", json=body)


class _AcceptanceTokenizer:
    def tokenize(self, text: str):
        return SimpleNamespace(coarse_tokens=text)


class _AcceptanceBm25Backend:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.call_count = 0

    async def recall_topk_chunks(self, _request):
        self.call_count += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _acceptance_stage_services(*, failure_point: str | None = None):
    parse_result = ParseResult(elements=[_heading(1, 1, "New"), _body(2)], tables=[], images=[])
    chunk = Chunk(
        content="body-C1",
        start_line=2,
        end_line=2,
        metadata={"chunk_index": 0},
    )
    draft = StoredChunkDraft(
        chunk_id="C1",
        user_id=123,
        set_id=10,
        doc_id=10001,
        bucket_id=0,
        content=chunk.content,
        content_hash="hash-C1",
        chunk_type="paragraph",
        start_line=2,
        end_line=2,
        chunk_index=0,
    )
    services = StageServices.__new__(StageServices)
    services._chunk_repository = AsyncMock()
    services._chunk_draft_factory = MagicMock()
    services._chunk_draft_factory.build_drafts.return_value = [draft]
    if failure_point == "Wiki 构建":
        builder = Mock()
        builder.build.side_effect = RuntimeError("Wiki build failure")
        services._wiki_tree_builder = builder
    else:
        services._wiki_tree_builder = HeadingTreeBuilder()
    services._wiki_tree_repository = AsyncMock()
    if failure_point == "Wiki 写入":
        services._wiki_tree_repository.replace_document_tree.side_effect = RuntimeError(
            "Wiki write failure"
        )
    db = AsyncMock()
    payload = SimpleNamespace(user_id=123, dataset_id=10, original_file_id=10001)
    return services, db, payload, [chunk], parse_result


def _acceptance_management_pipeline():
    pipeline = VectorStorageManagementPipeline.__new__(VectorStorageManagementPipeline)
    pipeline.repository = AsyncMock()
    pipeline.wiki_repository = AsyncMock()
    pipeline.qdrant_store = AsyncMock()
    pipeline.embedding_pipeline = AsyncMock()
    pipeline.sparse_vector_service = None

    async def run_transaction(operation):
        return await operation(object())

    pipeline._run_in_transaction_with_result = run_transaction
    return pipeline


async def _exercise_document_purge(monkeypatch, *, dataset: bool):
    db = AsyncMock()

    @asynccontextmanager
    async def db_context():
        yield db

    monkeypatch.setattr(purger_module, "get_db_context", db_context)
    chunk_repository = AsyncMock()
    chunk_repository.list_routing_by_doc_id.return_value = []
    parse_repository = AsyncMock()
    parse_repository.list_parsed_oss_keys_by_doc_id.return_value = []
    if dataset:
        parse_repository.list_doc_ids_by_dataset.side_effect = [[10001], []]
    wiki_repository = AsyncMock()
    qdrant = AsyncMock()
    es_pipeline = AsyncMock()
    storage = MagicMock()
    purger = DocumentDeletePurger(
        chunk_repository=chunk_repository,
        parse_repository=parse_repository,
        qdrant_store=qdrant,
        es_pipeline=es_pipeline,
        storage=storage,
        mutation_guard=NoopIndexMutationGuard(),
        wiki_repository=wiki_repository,
    )
    if dataset:
        await purger._purge_dataset(user_id=123, dataset_id=10)
    else:
        await purger._purge_file(user_id=123, dataset_id=10, doc_id=10001)
    return wiki_repository, chunk_repository, parse_repository, db


def _assert_builder_scenario(scenario: str) -> None:
    if scenario == "按原文顺序构建_h1_到_h6_标题树":
        _assert_builder_contract()
        return
    if scenario == "同一路径的重复同名标题保持为不同节点并按位置挂载":
        tree = _build_tree(
            [
                _heading(1, 1, "指南"),
                _heading(2, 2, "安装"),
                _body(3),
                _heading(4, 2, "安装"),
                _body(5),
            ],
            [("C1", 3, 3, "paragraph"), ("C2", 5, 5, "paragraph")],
        )
        installs = [heading for heading in tree.headings if heading.title == "安装"]
        assert len(installs) == 2
        assert installs[0].heading_key != installs[1].heading_key
        assert [(ref.chunk_id, ref.parent_heading_key) for ref in tree.chunk_refs] == [
            ("C1", installs[0].heading_key),
            ("C2", installs[1].heading_key),
        ]
        return
    if scenario == "chunk_只挂到标题路径的末端标题":
        tree = _build_tree(
            [_heading(1, 1, "指南"), _heading(2, 2, "安装"), _body(3)],
            [("C1", 3, 3, "paragraph")],
        )
        by_title = {heading.title: heading.heading_key for heading in tree.headings}
        assert [(ref.chunk_id, ref.parent_heading_key) for ref in tree.chunk_refs] == [
            ("C1", by_title["安装"])
        ]
        return
    if scenario == "跨越多条标题路径的_chunk_在每个末端标题下各有一个引用":
        tree = _build_tree(
            [
                _heading(1, 1, "指南"),
                _heading(2, 2, "安装"),
                _body(3),
                _heading(4, 2, "配置"),
                _body(5),
            ],
            [("C1", 3, 5, "paragraph")],
        )
        terminal_keys = {
            heading.heading_key for heading in tree.headings if heading.title in {"安装", "配置"}
        }
        assert {ref.parent_heading_key for ref in tree.chunk_refs} == terminal_keys
        assert {ref.chunk_id for ref in tree.chunk_refs} == {"C1"}
        return
    if scenario == "不完整_heading_trail_仍按_parseresult_位置挂到_h6":
        tree = _build_tree(
            [_heading(1, 6, "细节"), _body(2)],
            [("C1", 2, 2, "paragraph")],
        )
        assert tree.headings[0].heading_level == 6
        assert tree.chunk_refs[0].parent_heading_key == tree.headings[0].heading_key
        return
    if scenario == "overlap_文本不增加结构归属且派生_chunk_遵循相同挂载规则":
        tree = _build_tree(
            [_heading(1, 1, "正文"), _body(2)],
            [("C1", 2, 2, "paragraph"), ("C2", 2, 2, "derived")],
        )
        assert {heading.title for heading in tree.headings} == {"正文"}
        assert {ref.chunk_id for ref in tree.chunk_refs} == {"C1", "C2"}
        return
    if scenario == "没有直属正文的标题仍保留空_chunk_列表":
        tree = _build_tree(
            [_heading(1, 1, "概览"), _heading(2, 2, "细节"), _body(3)],
            [("C1", 3, 3, "paragraph")],
        )
        overview = next(item for item in tree.headings if item.title == "概览")
        assert overview in tree.headings
        assert all(ref.parent_heading_key != overview.heading_key for ref in tree.chunk_refs)
        return
    if scenario == "无标题文档不创建占位标题":
        tree = _build_tree([_body(1)], [("C1", 1, 1, "paragraph")])
        assert tree.headings == ()
        assert tree.chunk_refs[0].parent_heading_key is None
        return
    if scenario == "从_chunking_重试时重新获得同一_markdown_的结构化解析结果":
        structured = StageServices._chunk_markdown_with_parse_result(
            "# 概览\n###### 细节\n正文",
            "guide.md",
        )
        assert isinstance(structured.parse_result, ParseResult)
        assert any(
            item.type == ElementType.HEADING and item.metadata.get("heading_level") == 6
            for item in structured.parse_result.elements
        )
        tree = _build_tree(
            [_heading(1, 1, "概览"), _heading(2, 6, "细节"), _body(3)],
            [("C1", 3, 3, "paragraph")],
        )
        assert [(item.title, item.heading_level) for item in tree.headings] == [
            ("概览", 1),
            ("细节", 6),
        ]
        services, db, payload, chunks, parse_result = _acceptance_stage_services()
        asyncio.run(services._persist_chunk_facts(chunks, parse_result, payload, db))
        services._chunk_repository.delete_by_doc_id.assert_awaited_once()
        services._chunk_repository.bulk_insert_pending.assert_awaited_once()
        services._wiki_tree_repository.replace_document_tree.assert_awaited_once()
        db.commit.assert_awaited_once()
        return
    raise AssertionError(f"unknown builder scenario: {scenario}")


_BUILDER_SCENARIOS = {
    "按原文顺序构建_h1_到_h6_标题树",
    "同一路径的重复同名标题保持为不同节点并按位置挂载",
    "chunk_只挂到标题路径的末端标题",
    "跨越多条标题路径的_chunk_在每个末端标题下各有一个引用",
    "不完整_heading_trail_仍按_parseresult_位置挂到_h6",
    "overlap_文本不增加结构归属且派生_chunk_遵循相同挂载规则",
    "没有直属正文的标题仍保留空_chunk_列表",
    "无标题文档不创建占位标题",
    "从_chunking_重试时重新获得同一_markdown_的结构化解析结果",
}


def _scenario_base_name(node_name: str) -> str:
    return node_name.split("[", 1)[0].removeprefix("test_")


def _assert_scenario_contract(node_name: str, state: WikiAcceptanceState, monkeypatch) -> None:
    scenario = _scenario_base_name(node_name)
    assert state.givens and state.whens and state.thens
    assert all(value != "" for value in state.parameters.values())
    if scenario in _BUILDER_SCENARIOS:
        _assert_builder_scenario(scenario)
        return
    if scenario == "首次构建或重试替换失败时_chunk_与标题树共同回滚":
        allowed = {
            ("首次构建", "无旧数据", "Wiki 构建", "无旧数据"),
            ("首次构建", "无旧数据", "Wiki 写入", "无旧数据"),
            ("重试替换", "旧版本", "Wiki 构建", "旧版本"),
            ("重试替换", "旧版本", "Wiki 写入", "旧版本"),
        }
        assert (
            state.parameters["operation"],
            state.parameters["before_state"],
            state.parameters["failure_point"],
            state.parameters.get("after_state", state.parameters["before_state"]),
        ) in allowed
        services, db, payload, chunks, parse_result = _acceptance_stage_services(
            failure_point=state.parameters["failure_point"]
        )
        with pytest.raises(RuntimeError):
            asyncio.run(services._persist_chunk_facts(chunks, parse_result, payload, db))
        db.commit.assert_not_awaited()
        if state.parameters["failure_point"] == "Wiki 构建":
            services._chunk_repository.delete_by_doc_id.assert_not_awaited()
            services._chunk_repository.bulk_insert_pending.assert_not_awaited()
        else:
            services._chunk_repository.delete_by_doc_id.assert_awaited_once()
            services._chunk_repository.bulk_insert_pending.assert_awaited_once()
            db.rollback.assert_awaited_once()
        return
    if scenario == "非结构性变化不改变_heading_key":
        before_key, after_key = _nonstructural_identity_keys(state.parameters["change"])
        assert after_key == before_key
        return
    if scenario == "标题身份变化时生成新的_heading_key":
        change = state.parameters["change"]
        changed_identity = {
            "标题重命名": (10001, ((1, "指南"), (2, "部署")), 0),
            "标题级别改变": (10001, ((1, "指南"), (3, "安装")), 0),
            "移到另一个父标题下": (10001, ((1, "手册"), (2, "安装")), 0),
            "任一祖先标题改变": (10001, ((1, "新指南"), (2, "安装")), 0),
            "同路径同名出现次序改变": (10001, ((1, "指南"), (2, "安装")), 1),
            "使用新的 doc_id 创建文档": (10002, ((1, "指南"), (2, "安装")), 0),
        }[change]
        original = HeadingIdentity.make_key(
            doc_id=10001,
            identity_path=((1, "指南"), (2, "安装")),
            occurrence=0,
        )
        changed = HeadingIdentity.make_key(
            doc_id=changed_identity[0],
            identity_path=changed_identity[1],
            occurrence=changed_identity[2],
        )
        assert changed != original
        return
    if scenario == "精确标题不区分大小写并按服务端页大小返回":
        fixture = state.parameters["fixture"]
        total = 20 if fixture.startswith("20 个") else 1
        configured = state.parameters["configured_page_size"]
        page_size = 15 if configured == "DEFAULT" else int(configured)
        direct_chunks = total if "各有 1 个" in fixture else 0
        runtime, repository, bm25, _readiness = _acceptance_runtime(
            monkeypatch, page_size=page_size
        )
        headings = tuple(
            _acceptance_heading(index, title="快速 开始")
            for index in range(1, min(total, page_size) + 1)
        )
        repository.find_heading_page.return_value = (headings, total > page_size)
        if direct_chunks:
            repository.load_heading_previews.side_effect = lambda _db, items, **_kw: {
                item.id: WikiHeadingPreview(item.id, 1, f"C{item.id}", 0, item.id) for item in items
            }
            repository.load_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
                _acceptance_location(chunk_id) for chunk_id in chunk_ids
            )
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="  快速   开始  ",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        _parameter(state, "heading_count", len(payload["results"]))
        _parameter(state, "chunk_count", len(payload["chunks"]))
        _parameter(state, "effective_page_size", page_size)
        _parameter(state, "has_more", str(payload["has_more"]).lower())
        _parameter(state, "next_cursor", "PRESENT" if "next_cursor" in payload else "OMIT")
        assert normalize_wiki_query("  快速   开始  ").casefold() == "快速 开始".casefold()
        bm25.recall_by_dataset.assert_not_awaited()
        return
    if scenario == "精确标题续页始终保持_sql_短路且不启用_bm25":
        runtime, repository, bm25, _readiness = _acceptance_runtime(monkeypatch)
        first_headings = tuple(_acceptance_heading(index) for index in range(1, 16))
        second_headings = tuple(_acceptance_heading(index) for index in range(16, 21))
        repository.find_heading_page.side_effect = [
            (first_headings, True),
            (second_headings, False),
        ]

        async def load_exact_pages():
            first = await runtime.search(
                _acceptance_context(),
                query="介绍",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
            second = await runtime.search(
                _acceptance_context(),
                query="介绍",
                dataset_ids=None,
                doc_ids=None,
                cursor=first["next_cursor"],
            )
            return first, second

        first, second = asyncio.run(load_exact_pages())
        keys = [
            item["heading"]["heading_key"] for page in (first, second) for item in page["results"]
        ]
        assert [len(first["results"]), len(second["results"])] == [15, 5]
        assert len(keys) == len(set(keys)) == 20
        assert second["has_more"] is False and "next_cursor" not in second
        bm25.recall_by_dataset.assert_not_awaited()
        return
    if scenario == "精确未命中时同时执行标题前缀匹配和_chunk_bm25":
        runtime, repository, bm25, readiness = _acceptance_runtime(monkeypatch)
        heading = _acceptance_heading(1, title="Android")
        hit = RetrieverHit("C1", 10001, 10, 1.0, "bm25")
        repository.find_heading_page.side_effect = [((), False), ((heading,), False)]
        bm25.recall_by_dataset.return_value = {10: [hit]}
        readiness.filter_visible_hits.return_value = [hit]
        repository.load_chunk_locations.return_value = (_acceptance_location("C1"),)
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="AN",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        assert [item["source"] for item in payload["results"]] == ["title_prefix", "bm25"]
        assert repository.find_heading_page.await_count == 2
        bm25.recall_by_dataset.assert_awaited_once()
        assert "android".startswith(normalize_wiki_query("AN").casefold())
        return
    if scenario == "多知识库统一按系统配置分别取得_bm25_候选":
        runtime, repository, bm25, _readiness = _acceptance_runtime(
            monkeypatch, dataset_ids=(10, 20)
        )
        repository.find_heading_page.side_effect = [((), False), ((), False)]
        asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="guide",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        kwargs = bm25.recall_by_dataset.await_args.kwargs
        assert bm25.recall_by_dataset.await_args.args[1] == (10, 20)
        assert kwargs["top_k"] == 50
        assert kwargs["user_id"] == 123
        assert sum(len(items) for items in bm25.recall_by_dataset.return_value.values()) <= 100
        return
    if scenario == "单知识库_bm25_只对瞬时错误重试一次":
        outcome_name = state.parameters["attempt_results"]
        success = [Bm25ChunkHit(chunk_id="C1", doc_id=10001, score=1.0)]
        outcomes = {
            "[TRANSIENT_ERROR,SUCCESS]": [TimeoutError("temporary"), success],
            "[TRANSIENT_ERROR,TRANSIENT_ERROR]": [
                TimeoutError("temporary"),
                ConnectionError("temporary"),
            ],
            "[PERMANENT_ERROR]": [ValueError("bad request")],
        }[outcome_name]
        expected = {
            "[TRANSIENT_ERROR,SUCCESS]": ("2", "[]", "[title_prefix,bm25]"),
            "[TRANSIENT_ERROR,TRANSIENT_ERROR]": ("2", "[bm25]", "[title_prefix]"),
            "[PERMANENT_ERROR]": ("1", "[bm25]", "[title_prefix]"),
        }[outcome_name]
        runtime, repository, _bm25, readiness = _acceptance_runtime(monkeypatch, strict=False)
        heading = _acceptance_heading(1)
        repository.find_heading_page.side_effect = [((), False), ((heading,), False)]
        backend = _AcceptanceBm25Backend(outcomes)
        runtime._bm25 = Bm25Retriever(backend=backend, tokenizer=_AcceptanceTokenizer())
        readiness.filter_visible_hits.side_effect = lambda hits, **_kw: list(hits)
        repository.load_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
            _acceptance_location(chunk_id) for chunk_id in chunk_ids
        )
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="guide",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        _parameter(state, "attempt_count", expected[0])
        _parameter(state, "failed_sources", str(payload["failed_sources"]).replace("'", ""))
        sources = list(dict.fromkeys(item["source"] for item in payload["results"]))
        _parameter(state, "returned_sources", f"[{','.join(sources)}]")
        assert backend.call_count == int(expected[0]) <= 2
        return
    if scenario == "搜索异常沿用严格与宽松召回容错语义":
        key = tuple(
            state.parameters[name]
            for name in ("exact_result", "strict_mode", "prefix_result", "bm25_result")
        )
        expected = {
            ("ERROR", "false", "NOT_CALLED", "NOT_CALLED"): (
                "500",
                "RECALL_ALL_SOURCES_FAILED",
                "OMIT",
                "NONE",
            ),
            ("MISS", "false", "ERROR", "SUCCESS"): (
                "200",
                "NONE",
                "[title_prefix]",
                "[bm25]",
            ),
            ("MISS", "false", "SUCCESS", "ERROR"): (
                "200",
                "NONE",
                "[bm25]",
                "[title_prefix]",
            ),
            ("MISS", "true", "ERROR", "SUCCESS"): (
                "500",
                "RECALL_ALL_SOURCES_FAILED",
                "OMIT",
                "NONE",
            ),
            ("MISS", "false", "ERROR", "ERROR"): (
                "500",
                "RECALL_ALL_SOURCES_FAILED",
                "OMIT",
                "NONE",
            ),
        }[key]
        runtime, repository, bm25, readiness = _acceptance_runtime(
            monkeypatch, strict=state.parameters["strict_mode"] == "true"
        )
        if state.parameters["exact_result"] == "ERROR":
            repository.find_heading_page.side_effect = RuntimeError("exact failed")
        else:
            prefix_value: object
            if state.parameters["prefix_result"] == "ERROR":
                prefix_value = RuntimeError("prefix failed")
            else:
                prefix_value = ((_acceptance_heading(1),), False)
            repository.find_heading_page.side_effect = [((), False), prefix_value]
            if state.parameters["bm25_result"] == "ERROR":
                bm25.recall_by_dataset.side_effect = RuntimeError("bm25 failed")
            else:
                hit = RetrieverHit("C1", 10001, 10, 1.0, "bm25")
                bm25.recall_by_dataset.return_value = {10: [hit]}
                readiness.filter_visible_hits.return_value = [hit]
                repository.load_chunk_locations.return_value = (_acceptance_location("C1"),)

        try:
            payload = asyncio.run(
                runtime.search(
                    _acceptance_context(),
                    query="guide",
                    dataset_ids=None,
                    doc_ids=None,
                    cursor=None,
                )
            )
        except RecallApiError as exc:
            actual = (str(exc.status_code), exc.code, "OMIT", "NONE")
        else:
            failed = f"[{','.join(payload['failed_sources'])}]"
            sources = list(dict.fromkeys(item["source"] for item in payload["results"]))
            actual = ("200", "NONE", failed, f"[{','.join(sources)}]")
        assert actual == expected
        for name, value in zip(
            ("status", "error_code", "failed_sources", "returned_sources"), actual
        ):
            _parameter(state, name, value)
        return
    if scenario == "前缀标题优先合并并按节点和_chunk_去重":
        runtime, repository, bm25, readiness = _acceptance_runtime(monkeypatch)
        heading = _acceptance_heading(1)
        repository.find_heading_page.side_effect = [((), False), ((heading, heading), False)]
        repository.load_heading_previews.side_effect = lambda _db, items, **_kw: {
            item.id: WikiHeadingPreview(item.id, 1, "C1", 0, 1) for item in items
        }
        hits = [
            RetrieverHit("C1", 10001, 10, 2.0, "bm25"),
            RetrieverHit("C2", 10001, 10, 1.0, "bm25"),
        ]
        bm25.recall_by_dataset.return_value = {10: hits}
        readiness.filter_visible_hits.return_value = hits
        repository.load_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
            _acceptance_location(
                chunk_id,
                heading_ids=(1, 2) if chunk_id == "C1" else (),
            )
            for chunk_id in chunk_ids
        )
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="guide",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        assert [item["result_type"] for item in payload["results"]] == ["HEADING", "CHUNK"]
        assert payload["results"][1]["chunk_id"] == "C2"
        assert [chunk["chunk_id"] for chunk in payload["chunks"]].count("C1") == 1
        return
    if scenario == "匹配标题的首个预览在整个搜索链固定优先于_bm25":
        runtime, repository, bm25, readiness = _acceptance_runtime(monkeypatch)
        first_prefix_window = tuple(_acceptance_heading(index) for index in range(1, 16))
        second_prefix_window = tuple(_acceptance_heading(index) for index in range(6, 16))
        repository.find_heading_page.side_effect = [
            ((), False),
            (first_prefix_window, False),
            (second_prefix_window, False),
        ]
        repository.find_matching_preview_chunk_ids.return_value = frozenset({"C6"})
        repository.load_heading_previews.side_effect = lambda _db, headings, **_kw: {
            item.id: (
                WikiHeadingPreview(item.id, 1, "C6", 0, 600)
                if item.id == 6
                else WikiHeadingPreview(item.id, 0, None, None, None)
            )
            for item in headings
        }
        hits = [
            RetrieverHit(chunk_id, 10001, 10, float(30 - rank), "bm25")
            for rank, chunk_id in enumerate(["C6", *(f"C{i}" for i in range(7, 27))])
        ]
        bm25.recall_by_dataset.return_value = {10: hits}
        readiness.filter_visible_hits.return_value = hits

        async def load_two_pages():
            first = await runtime.search(
                _acceptance_context(),
                query="gui",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
            second = await runtime.search(
                _acceptance_context(),
                query="gui",
                dataset_ids=None,
                doc_ids=None,
                cursor=first["next_cursor"],
            )
            return first, second

        first, second = asyncio.run(load_two_pages())
        first_bm25 = [
            item["chunk_id"] for item in first["results"] if item["result_type"] == "CHUNK"
        ]
        second_preview_ids = [
            item["heading"].get("direct_chunk_preview_id")
            for item in second["results"]
            if item["result_type"] == "HEADING"
        ]
        assert "C6" not in first_bm25
        assert first_bm25[0] == "C7"
        assert len(first_bm25) == 10
        assert "C6" in second_preview_ids
        assert repository.find_matching_preview_chunk_ids.await_count == 2
        return
    if scenario == "标题前缀与_bm25_按每页三分之一和三分之二分配并互补空位":
        prefix_count = int(state.parameters["prefix_available"])
        bm25_count = int(state.parameters["bm25_available"])
        runtime, repository, bm25, readiness = _acceptance_runtime(monkeypatch)
        headings = tuple(_acceptance_heading(index) for index in range(1, prefix_count + 1))
        hits = [
            RetrieverHit(f"C{index}", 10001, 10, float(bm25_count - index), "bm25")
            for index in range(1, bm25_count + 1)
        ]
        repository.find_heading_page.side_effect = [((), False), (headings, False)]
        bm25.recall_by_dataset.return_value = {10: hits}
        readiness.filter_visible_hits.return_value = hits
        repository.load_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
            _acceptance_location(chunk_id) for chunk_id in chunk_ids
        )
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="guide",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        prefix_returned = sum(item["result_type"] == "HEADING" for item in payload["results"])
        bm25_returned = sum(item["result_type"] == "CHUNK" for item in payload["results"])
        _parameter(state, "prefix_returned", prefix_returned)
        _parameter(state, "bm25_returned", bm25_returned)
        _parameter(state, "page_count", len(payload["results"]))
        return
    if scenario == "bm25_在知识库内保持分数顺序并跨知识库按名次轮询":
        result = Bm25RoundRobin.page(
            {
                30: ["C30-1", "C30-2", "C30-3"],
                10: ["C10-1", "C10-2", "C10-3"],
                20: ["C20-1", "C20-2", "C20-3"],
            },
            limit=9,
        )
        assert result.items == tuple(
            f"C{dataset}-{rank}" for rank in range(1, 4) for dataset in (10, 20, 30)
        )
        return
    if scenario == "知识库数量超过当前页_bm25_名额时跨页继续轮询":
        candidates = {item: [f"C{item}-1", f"C{item}-2"] for item in range(1, 26)}
        first = Bm25RoundRobin.page(candidates, limit=10)
        second = Bm25RoundRobin.page(candidates, position=first.next_position, limit=10)
        third = Bm25RoundRobin.page(candidates, position=second.next_position, limit=10)
        assert first.items == tuple(f"C{i}-1" for i in range(1, 11))
        assert second.items == tuple(f"C{i}-1" for i in range(11, 21))
        assert third.items == tuple(
            [*(f"C{i}-1" for i in range(21, 26)), *(f"C{i}-2" for i in range(1, 6))]
        )
        return
    if scenario == "跨知识库轮询跳过空库并由其他知识库补足名额":
        result = Bm25RoundRobin.page({10: [], 20: ["C20-1", "C20-2"], 30: ["C30-1"]}, limit=3)
        assert result.items == ("C20-1", "C30-1", "C20-2")
        return
    if scenario == "精确未命中后的合并结果支持继续加载":
        prefixes = list(range(14))
        bm25 = {10: list(range(14, 27)), 20: list(range(27, 40))}
        sizes: list[int] = []
        prefix_offset = 0
        position = RoundRobinPosition()
        collected: list[tuple[str, int]] = []
        for _ in range(3):
            page = WikiResultMerger.merge_page(
                prefixes,
                bm25,
                page_size=15,
                prefix_offset=prefix_offset,
                bm25_position=position,
            )
            current = [
                *(("p", item) for item in page.prefix_items),
                *(("b", item) for item in page.bm25_items),
            ]
            sizes.append(len(current))
            collected.extend(current)
            prefix_offset, position = page.next_prefix_offset, page.next_bm25_position
        assert sizes == [15, 15, 10]
        assert len(collected) == len(set(collected)) == 40
        return
    if scenario == "bm25_保持完整_chunk_文本匹配语义":
        runtime, repository, bm25, readiness = _acceptance_runtime(monkeypatch)
        hits = [
            RetrieverHit("C1", 10001, 10, 2.0, "bm25"),
            RetrieverHit("C2", 10001, 10, 1.0, "bm25"),
        ]
        repository.find_heading_page.side_effect = [((), False), ((), False)]
        bm25.recall_by_dataset.return_value = {10: hits}
        readiness.filter_visible_hits.return_value = hits
        repository.load_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
            _acceptance_location(chunk_id) for chunk_id in chunk_ids
        )
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="title-or-body-term",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        assert [(item["chunk_id"], item["source"]) for item in payload["results"]] == [
            ("C1", "bm25"),
            ("C2", "bm25"),
        ]
        assert [chunk["content"] for chunk in payload["chunks"]] == [
            "content-C1",
            "content-C2",
        ]
        return
    if scenario == "标题搜索只返回直属_chunk_且默认不附带完整树":
        runtime, repository, bm25, _readiness = _acceptance_runtime(monkeypatch)
        guide = _acceptance_heading(1, title="指南")
        repository.find_heading_page.return_value = ((guide,), False)
        response = asyncio.run(_post_search(_acceptance_app(runtime), {"query": "指南"}))
        assert response.status_code == 200
        payload = response.json()
        assert payload["results"][0]["heading"]["heading_key"] == guide.heading_key
        assert payload["results"][0]["heading"]["direct_chunk_count"] == 0
        assert payload["chunks"] == []
        assert "headings" not in payload
        bm25.recall_by_dataset.assert_not_awaited()
        return
    if scenario == "标题搜索只预览首个直属_chunk_并独立加载当前标题的其余直属_chunk":
        runtime, repository, _bm25, _readiness = _acceptance_runtime(monkeypatch)
        heading = _acceptance_heading(1, title="H1")
        repository.find_heading_page.return_value = ((heading,), False)
        repository.load_heading_previews.side_effect = lambda _db, items, **_kw: {
            item.id: WikiHeadingPreview(item.id, 18, "C1", 0, 1) for item in items
        }
        repository.load_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
            _acceptance_location(chunk_id, heading_ids=(1,)) for chunk_id in chunk_ids
        )
        first_refs = tuple(
            WikiChunkRefRecord(index, index - 1, f"C{index}") for index in range(2, 17)
        )
        second_refs = tuple(
            WikiChunkRefRecord(index, index - 1, f"C{index}") for index in range(17, 19)
        )
        repository.load_heading_chunk_page.side_effect = [
            (first_refs, True),
            (second_refs, False),
        ]

        async def search_and_expand():
            search = await runtime.search(
                _acceptance_context(),
                query="H1",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
            cursor = search["results"][0]["heading"]["next_direct_chunk_cursor"]
            first = await runtime.expand_heading_chunks(
                _acceptance_context(),
                doc_id=10001,
                heading_key=heading.heading_key,
                cursor=cursor,
            )
            second = await runtime.expand_heading_chunks(
                _acceptance_context(),
                doc_id=10001,
                heading_key=heading.heading_key,
                cursor=first["next_direct_chunk_cursor"],
            )
            return search, first, second

        search, first, second = asyncio.run(search_and_expand())
        assert [chunk["chunk_id"] for chunk in search["chunks"]] == ["C1"]
        assert search["results"][0]["heading"]["direct_chunk_count"] == 18
        assert [chunk["chunk_id"] for chunk in first["chunks"]] == [f"C{i}" for i in range(2, 17)]
        assert [chunk["chunk_id"] for chunk in second["chunks"]] == ["C17", "C18"]
        assert second["direct_chunks_has_more"] is False
        assert "next_direct_chunk_cursor" not in second
        return
    if scenario == "同名精确标题只返回授权且就绪范围内的全部匹配":
        runtime, repository, bm25, _readiness = _acceptance_runtime(monkeypatch)
        authorized = _acceptance_heading(1, title="介绍")
        repository.find_heading_page.return_value = ((authorized,), False)
        payload = asyncio.run(
            runtime.search(
                _acceptance_context(),
                query="介绍",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
        )
        assert [item["heading"]["heading_key"] for item in payload["results"]] == [
            authorized.heading_key
        ]
        bm25.recall_by_dataset.assert_not_awaited()
        return
    if scenario == "wiki_搜索按用户知识库文档三级范围约束标题与_bm25":
        key = tuple(state.parameters[name] for name in ("claims", "dataset_ids", "doc_ids"))
        expected = {
            ("[10,20]", "OMIT", "OMIT"): ("[10,20]", "范围内全部可见文档"),
            ("[10,20]", "[20]", "OMIT"): ("[20]", "知识库 20 全部可见文档"),
            ("[10,20]", "OMIT", "[D1,D2]"): ("[10,20]", "[D1,D2]"),
            ("[10,20]", "[10]", "[D1]"): ("[10]", "[D1]"),
            ("FULL_LIBRARY", "OMIT", "OMIT"): ("[10,20]", "用户全部可见文档"),
        }[key]
        claims = None if key[0] == "FULL_LIBRARY" else (10, 20)
        requested_datasets = (
            None
            if key[1] == "OMIT"
            else tuple(int(value) for value in key[1].strip("[]").split(","))
        )
        doc_map = {"D1": (10001, 10), "D2": (20001, 20)}
        requested_docs = (
            None
            if key[2] == "OMIT"
            else tuple(doc_map[name][0] for name in key[2].strip("[]").split(","))
        )
        dataset_rows = [(dataset_id,) for dataset_id in (requested_datasets or (10, 20))]
        session = AsyncMock()
        session.execute.side_effect = [
            dataset_rows,
            *(
                [[doc_map[name] for name in key[2].strip("[]").split(",")]]
                if requested_docs
                else []
            ),
        ]
        scope = asyncio.run(
            WikiTreeRepository().resolve_scope(
                session,
                user_id=123,
                claims_dataset_ids=claims,
                requested_dataset_ids=requested_datasets,
                requested_doc_ids=requested_docs,
            )
        )
        actual_datasets = f"[{','.join(str(item) for item in scope.dataset_ids)}]"
        if scope.doc_ids is None:
            actual_docs = expected[1]
        else:
            by_id = {10001: "D1", 20001: "D2"}
            actual_docs = f"[{','.join(by_id[item] for item in scope.doc_ids)}]"
        _parameter(state, "effective_datasets", actual_datasets)
        _parameter(state, "effective_docs", actual_docs)
        assert actual_datasets == expected[0]
        assert actual_docs == expected[1]
        return
    if scenario == "无效凭证请求或越权范围在查询前被拒绝":
        condition = state.parameters["condition"]
        expected = {
            "缺少 session token": ("401", "RECALL_SESSION_UNAUTHORIZED"),
            "session token 无效或过期": ("401", "RECALL_SESSION_UNAUTHORIZED"),
            "query 为空或纯空白": ("400", "RECALL_INVALID_REQUEST"),
            "请求 JSON 非法": ("422", "RECALL_INVALID_REQUEST"),
            "请求含未知字段": ("422", "RECALL_INVALID_REQUEST"),
            "dataset_ids 含 claims 外的知识库 30": ("403", "RECALL_SCOPE_FORBIDDEN"),
            "doc_ids 含 claims 外知识库 30 的文档 D3": ("403", "RECALL_SCOPE_FORBIDDEN"),
            "dataset_ids=[10] 但 doc_ids=[D2@知识库20]": (
                "403",
                "RECALL_SCOPE_FORBIDDEN",
            ),
            "doc_ids 含其他用户的文档 D4": ("403", "RECALL_SCOPE_FORBIDDEN"),
        }[condition]
        runtime: object = AsyncMock()
        repository = None
        bm25 = None
        request_body: dict[str, object] = {"query": "x"}
        authenticated = condition not in {"缺少 session token", "session token 无效或过期"}
        if expected[0] == "403":
            runtime, repository, bm25, _readiness = _acceptance_runtime(monkeypatch)
            repository.resolve_scope.side_effect = RecallApiError(
                403, "RECALL_SCOPE_FORBIDDEN", "scope forbidden"
            )
            request_body = (
                {"query": "x", "dataset_ids": [30]}
                if condition.startswith("dataset_ids")
                else {"query": "x", "doc_ids": [30001]}
            )
        app = _acceptance_app(runtime, authenticated=authenticated)

        async def execute_invalid_request():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                if condition == "请求 JSON 非法":
                    return await client.post(
                        "/api/v1/wiki/search",
                        content=b"{",
                        headers={"content-type": "application/json"},
                    )
                if condition == "请求含未知字段":
                    return await client.post("/api/v1/wiki/search", json={"query": "x", "top_k": 5})
                if condition == "query 为空或纯空白":
                    return await client.post("/api/v1/wiki/search", json={"query": "  "})
                headers = (
                    {"Authorization": "Bearer invalid"}
                    if condition == "session token 无效或过期"
                    else None
                )
                return await client.post("/api/v1/wiki/search", json=request_body, headers=headers)

        response = asyncio.run(execute_invalid_request())
        assert response.status_code == int(expected[0])
        assert response.json()["code"] == expected[1]
        _parameter(state, "status", response.status_code)
        _parameter(state, "error_code", response.json()["code"])
        if response.status_code != 403:
            runtime.search.assert_not_awaited()
        else:
            repository.find_heading_page.assert_not_awaited()
            bm25.recall_by_dataset.assert_not_awaited()
        return
    if scenario == "不可见候选在返回前被_fail_closed":
        condition = state.parameters["condition"]
        runtime, repository, bm25, readiness = _acceptance_runtime(monkeypatch)
        del readiness
        hit_doc_id = 20001 if condition == "不在请求的文档范围内" else 10001
        hit_dataset_id = 20 if condition == "不在请求的数据集范围内" else 10
        hit = RetrieverHit("C1", hit_doc_id, hit_dataset_id, 1.0, "bm25")
        if condition == "不在请求的文档范围内":
            repository.resolve_scope.return_value = EffectiveWikiScope(
                123, (10,), (10001,), {10: (10001,)}
            )
        readiness_rows = {
            "归属其他用户": [],
            "不在请求的数据集范围内": [("C1", 10001, 20, "ACTIVE", "SUCCESS")],
            "不在请求的文档范围内": [("C1", 20001, 10, "ACTIVE", "SUCCESS")],
            "最新解析流水线不是 SUCCESS": [("C1", 10001, 10, "ACTIVE", "FAILED")],
            "Chunk 生命周期不是 ACTIVE": [("C1", 10001, 10, "REMOVED", "SUCCESS")],
        }[condition]
        readiness_db = AsyncMock()
        readiness_db.execute.return_value = SimpleNamespace(all=lambda: readiness_rows)

        @asynccontextmanager
        async def readiness_db_context():
            yield readiness_db

        runtime._readiness = MySqlDocumentReadinessGate(
            session_context_factory=readiness_db_context
        )
        repository.find_heading_page.side_effect = [((), False), ((), False)]
        bm25.recall_by_dataset.return_value = {10: [hit]}
        forbidden = RecallApiError(403, "RECALL_SCOPE_FORBIDDEN", "not visible")
        repository.load_chunk_locations.side_effect = forbidden
        repository.load_document_tree.side_effect = forbidden

        async def exercise_fail_closed_reads():
            search = await runtime.search(
                _acceptance_context(),
                query="hidden",
                dataset_ids=None,
                doc_ids=None,
                cursor=None,
            )
            errors = []
            for operation in (
                runtime.locate_chunks(_acceptance_context(), chunk_ids=["C1"], dataset_ids=None),
                runtime.get_document_tree(_acceptance_context(), doc_id=10001),
            ):
                try:
                    await operation
                except RecallApiError as exc:
                    errors.append(exc.status_code)
            return search, errors

        payload, errors = asyncio.run(exercise_fail_closed_reads())
        assert payload["results"] == [] and payload["chunks"] == []
        assert errors == [403, 403]
        readiness_db.execute.assert_awaited_once()
        return
    if scenario == "chunk_定位返回全部直接标题位置并支持批量读取":
        runtime, repository, _bm25, _readiness = _acceptance_runtime(monkeypatch)
        headings = tuple(_acceptance_heading(index, title=f"H{index}") for index in range(1, 4))
        repository.load_chunk_locations.return_value = (
            _acceptance_location("C1", heading_ids=(1, 2)),
            _acceptance_location("C2", heading_ids=(3,)),
        )
        repository.load_headings_by_ids.return_value = headings
        repository.load_heading_paths.return_value = {
            heading.id: (
                WikiHeadingPathItem(
                    heading_key=heading.heading_key,
                    title=heading.title,
                    heading_level=heading.heading_level,
                ),
            )
            for heading in headings
        }
        payload = asyncio.run(
            runtime.locate_chunks(_acceptance_context(), chunk_ids=["C1", "C2"], dataset_ids=None)
        )
        assert [len(item["positions"]) for item in payload["locations"]] == [2, 1]
        repository.load_chunk_locations.assert_awaited_once()
        repository.load_heading_paths.assert_awaited_once()
        return
    if scenario == "按文档读取完整树时校验授权并保持同类型节点顺序":
        runtime, repository, _bm25, _readiness = _acceptance_runtime(monkeypatch)
        h1 = _acceptance_heading(1, title="H1")
        h2 = _acceptance_heading(2, title="H2")
        repository.load_document_tree.return_value = WikiDocumentTreeRows(
            doc_id=10001,
            dataset_id=10,
            original_filename="guide.md",
            headings=(h1, h2),
            root_chunk_ids=(),
            direct_chunk_ids_by_heading={1: ("C1", "C2"), 2: ()},
            chunks=(
                _acceptance_location("C1").chunk,
                _acceptance_location("C2").chunk,
            ),
        )
        repository.load_chunk_locations.return_value = (
            _acceptance_location("C1", heading_ids=(1,)),
            _acceptance_location("C2", heading_ids=(1,)),
        )
        payload = asyncio.run(runtime.get_document_tree(_acceptance_context(), doc_id=10001))
        assert [item["title"] for item in payload["headings"]] == ["H1", "H2"]
        assert payload["headings"][0]["direct_chunk_ids"] == ["C1", "C2"]

        repository.load_document_tree.side_effect = RecallApiError(
            403, "RECALL_SCOPE_FORBIDDEN", "forbidden"
        )
        with pytest.raises(RecallApiError) as exc_info:
            asyncio.run(runtime.get_document_tree(_acceptance_context(), doc_id=20001))
        assert exc_info.value.status_code == 403
        return
    if scenario == "chunk_与文档生命周期变化同步维护_wiki_引用":
        expected = {
            "C1 正文更新": ("原有标题节点和引用保持不变", "返回更新后的完整 Chunk"),
            "C1 标记为 REMOVED": ("C1 的全部 CHUNK_REF 被删除", "不返回 C1"),
            "删除文档 D1": ("D1 的全部 Wiki 节点被删除", "不返回 D1 的树和 Chunk"),
            "删除 D1 所属的数据集": (
                "数据集内全部 Wiki 节点被删除",
                "不返回该数据集内容",
            ),
            "整文档结构改变后重新解析成功": (
                "旧 Chunk 与旧树被新版本原子替换",
                "只返回新 Chunk 与新标题树",
            ),
        }[state.parameters["action"]]
        action = state.parameters["action"]
        if action == "C1 正文更新":
            pipeline = _acceptance_management_pipeline()
            record = SimpleNamespace(
                chunk_id="C1",
                chunk_type="paragraph",
                start_line=1,
                end_line=1,
                chunk_index=0,
                dense_vector_status="SUCCESS",
                content="old body",
                content_hash=pipeline._content_hash("updated body"),
            )
            pipeline._load_single_active_record = AsyncMock(return_value=record)
            pipeline._update_chunk_metadata = AsyncMock(return_value=True)
            result = asyncio.run(
                pipeline.update_chunk(ChunkUpdateRequest(chunk_id="C1", content="updated body"))
            )
            assert result.affected_chunks == 1
            pipeline.wiki_repository.delete_refs_by_chunk_ids.assert_not_awaited()
            pipeline.qdrant_store.upsert_points.assert_not_awaited()
        elif action == "C1 标记为 REMOVED":
            pipeline = _acceptance_management_pipeline()
            pipeline.repository.mark_removed.return_value = 1
            assert asyncio.run(pipeline._mark_removed(["C1"])) == 1
            pipeline.wiki_repository.delete_refs_by_chunk_ids.assert_awaited_once()
        elif action == "删除文档 D1":
            wiki_repository, chunk_repository, parse_repository, db = asyncio.run(
                _exercise_document_purge(monkeypatch, dataset=False)
            )
            wiki_repository.delete_by_doc_id.assert_awaited_once_with(db, 10001)
            chunk_repository.delete_by_doc_id.assert_awaited_once_with(db, 10001)
            parse_repository.delete_parse_rows_by_doc_id.assert_awaited_once_with(db, 10001)
            db.commit.assert_awaited_once()
        elif action == "删除 D1 所属的数据集":
            wiki_repository, _chunk_repository, parse_repository, _db = asyncio.run(
                _exercise_document_purge(monkeypatch, dataset=True)
            )
            wiki_repository.delete_by_doc_id.assert_awaited_once()
            assert parse_repository.list_doc_ids_by_dataset.await_count == 2
        else:
            services, db, payload, chunks, parse_result = _acceptance_stage_services()
            asyncio.run(services._persist_chunk_facts(chunks, parse_result, payload, db))
            services._chunk_repository.delete_by_doc_id.assert_awaited_once()
            services._chunk_repository.bulk_insert_pending.assert_awaited_once()
            services._wiki_tree_repository.replace_document_tree.assert_awaited_once()
            db.commit.assert_awaited_once()
        _parameter(state, "wiki_result", expected[0])
        _parameter(state, "query_result", expected[1])
        return
    if scenario == "单_chunk_结构字段实际变化时在任何_mutation_前被拒绝":
        field_name = state.parameters["field"]
        assert field_name in {"start_line", "end_line", "chunk_index"}
        pipeline = _acceptance_management_pipeline()
        record = SimpleNamespace(
            chunk_id="C1",
            chunk_type="paragraph",
            start_line=10,
            end_line=20,
            chunk_index=3,
        )
        pipeline._load_single_active_record = AsyncMock(return_value=record)
        request = ChunkUpdateRequest(chunk_id="C1", content="updated")
        setattr(
            request, field_name, {"start_line": 11, "end_line": 21, "chunk_index": 4}[field_name]
        )
        with pytest.raises(ChunkStructuralUpdateNotAllowedError) as exc_info:
            asyncio.run(pipeline.update_chunk(request))
        assert exc_info.value.fields == {field_name}
        assert "reparse the whole document" in str(exc_info.value)
        assert pipeline.repository.method_calls == []
        assert pipeline.embedding_pipeline.method_calls == []
        assert pipeline.qdrant_store.method_calls == []
        assert pipeline.wiki_repository.method_calls == []
        return
    raise AssertionError(f"Wiki acceptance scenario has no executable contract: {scenario}")


_FEATURE_PATH = Path(__file__).resolve().parents[1] / "features" / "wiki.feature"
_KEYWORD_TYPES = {"假如": "given", "当": "when", "那么": "then"}
_PLACEHOLDER_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")


def _step_parser(template: str) -> tuple[str | object, tuple[str, ...]]:
    names = tuple(_PLACEHOLDER_RE.findall(template))
    if not names:
        return template, ()
    parts: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        parts.append(re.escape(template[cursor : match.start()]))
        parts.append(f"(?P<{match.group(1)}>.+?)")
        cursor = match.end()
    parts.append(re.escape(template[cursor:]))
    return parsers.re("^" + "".join(parts) + "$"), names


def _register_step(step_type: str, template: str, serial: int) -> None:
    parser, parameter_names = _step_parser(template)

    def handler(**kwargs) -> None:
        state: WikiAcceptanceState = kwargs["wiki_acceptance_state"]
        request = kwargs["request"]
        parameters = {name: str(kwargs[name]) for name in parameter_names}
        state.parameters.update(parameters)
        rendered = template
        for name, value in parameters.items():
            rendered = rendered.replace(f"<{name}>", value)
        target = {
            "given": state.givens,
            "when": state.whens,
            "then": state.thens,
        }[step_type]
        target.append(rendered)
        if step_type == "then":
            _assert_scenario_contract(request.node.name, state, kwargs["monkeypatch"])

    signature_names = ("wiki_acceptance_state", "request", "monkeypatch", *parameter_names)
    handler.__name__ = f"wiki_{step_type}_{serial}"
    handler.__signature__ = inspect.Signature(
        [
            inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for name in signature_names
        ]
    )
    step(parser, step_type, stacklevel=3)(handler)


def _install_frozen_steps() -> None:
    current_type: str | None = None
    seen: set[tuple[str, str]] = set()
    serial = 0
    for raw_line in _FEATURE_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(假如|当|那么|并且)\s+(.+?)\s*$", raw_line)
        if match is None:
            continue
        keyword, template = match.groups()
        if keyword != "并且":
            current_type = _KEYWORD_TYPES[keyword]
        if current_type is None or (current_type, template) in seen:
            continue
        seen.add((current_type, template))
        _register_step(current_type, template, serial)
        serial += 1


_install_frozen_steps()
