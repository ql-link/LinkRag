"""Qdrant BM25 store provisioning regressions."""

from src.core.storage.qdrant_bm25.store import QdrantBm25Store


class _FakeClient:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.payload_index_calls: list[dict] = []

    async def collection_exists(self, collection_name: str) -> bool:
        return False

    async def create_collection(self, **kwargs) -> None:
        self.create_calls.append(kwargs)

    async def create_payload_index(self, **kwargs) -> None:
        self.payload_index_calls.append(kwargs)


async def test_ensure_collection_passes_empty_dense_vectors_config_for_sparse_only() -> None:
    fake = _FakeClient()
    store = QdrantBm25Store(client=fake)

    await store.ensure_collection()

    assert fake.create_calls, "collection 不存在时应创建 BM25 collection"
    create_kwargs = fake.create_calls[0]
    assert create_kwargs["vectors_config"] == {}
    assert "bm25_text" in create_kwargs["sparse_vectors_config"]
