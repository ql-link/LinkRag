import pytest

from src.core.storage.es.document_factory import EsDocumentFactory
from src.core.storage.es.exceptions import EsDocumentValidationError
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta


def build_meta() -> FileIndexMeta:
    return FileIndexMeta(user_id=20, dataset_id=30, doc_id=10, task_id="t-001")


def build_chunk(**overrides) -> ChunkWithTokens:
    base = dict(
        chunk_id="chunk-001",
        chunk_index=0,
        coarse_tokens="合同 付款 违约责任",
        fine_tokens="合同 付款 违约 责任",
    )
    base.update(overrides)
    return ChunkWithTokens(**base)


class TestEsDocumentFactory:
    def test_should_build_action_with_id_routing_and_thin_document(self):
        factory = EsDocumentFactory(max_document_bytes=131072)

        action = factory.build_action(build_meta(), build_chunk())

        assert action.chunk_id == "chunk-001"
        assert action.operation["index"]["_id"] == "20-30-10-chunk-001"
        assert action.operation["index"]["routing"] == "30"
        assert action.document["chunk_id"] == "chunk-001"
        assert action.document["user_id"] == 20
        assert action.document["coarse_tokens"] == "合同 付款 违约责任"
        assert "content" not in action.document
        assert "source_filename" not in action.document
        assert action.estimated_bytes > 0

    def test_should_raise_when_chunk_id_empty(self):
        factory = EsDocumentFactory(max_document_bytes=131072)

        with pytest.raises(EsDocumentValidationError):
            factory.build_action(build_meta(), build_chunk(chunk_id=""))

    def test_should_raise_when_tokens_empty(self):
        factory = EsDocumentFactory(max_document_bytes=131072)

        with pytest.raises(EsDocumentValidationError):
            factory.build_action(build_meta(), build_chunk(coarse_tokens="   "))

    def test_should_raise_when_chunk_index_none(self):
        factory = EsDocumentFactory(max_document_bytes=131072)

        with pytest.raises(EsDocumentValidationError):
            factory.build_action(build_meta(), build_chunk(chunk_index=None))

    def test_should_raise_when_chunk_index_negative(self):
        factory = EsDocumentFactory(max_document_bytes=131072)

        with pytest.raises(EsDocumentValidationError):
            factory.build_action(build_meta(), build_chunk(chunk_index=-1))

    def test_should_raise_when_document_too_large(self):
        factory = EsDocumentFactory(max_document_bytes=10)

        with pytest.raises(EsDocumentValidationError) as exc_info:
            factory.build_action(build_meta(), build_chunk())

        assert exc_info.value.chunk_id == "chunk-001"
        assert str(exc_info.value).startswith("validation:")
