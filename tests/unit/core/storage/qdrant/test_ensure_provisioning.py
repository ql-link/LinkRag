"""QdrantIndexStore 建表/连接配置回归。

锁定两个曾导致解析链路向量阶段失败的修复：
  1. 空串 api_key 归一为 None —— 否则 qdrant-client 对明文 HTTP 强制 https。
  2. collection 创建时即带 named sparse vector —— 否则 dense-only collection 无法
     事后追加 sparse 向量，稀疏索引阶段必失败。
"""

from src.core.storage.qdrant import QdrantIndexStore


class _FakeClient:
    """记录 create_collection 入参的最小异步 client。"""

    def __init__(self) -> None:
        self.create_calls: list[dict] = []

    async def collection_exists(self, collection_name: str) -> bool:
        return False

    async def create_collection(self, **kwargs) -> None:
        self.create_calls.append(kwargs)

    async def create_payload_index(self, **kwargs) -> None:
        return None


def test_empty_api_key_is_normalized_to_none():
    # 空串与 None 都应落到 None：qdrant-client 见到非 None api_key（含 ""）会强制 https。
    assert QdrantIndexStore(api_key="").api_key is None
    assert QdrantIndexStore(api_key=None).api_key is None


async def test_ensure_collection_provisions_named_sparse_vector():
    fake = _FakeClient()
    store = QdrantIndexStore(client=fake)

    await store.ensure_collection(bucket_id=0, vector_size=8)

    assert fake.create_calls, "collection 不存在时应调用 create_collection"
    sparse_cfg = fake.create_calls[0].get("sparse_vectors_config")
    assert sparse_cfg, "create_collection 必须带 sparse_vectors_config（hybrid-ready）"
    assert "sparse_text" in sparse_cfg
