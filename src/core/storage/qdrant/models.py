from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.core.encoding.sparse.models import SparseVector


@dataclass(slots=True)
class IndexedPoint:
    chunk_id: str
    bucket_id: int
    vector: list[float]
    payload: dict[str, int | str]


@dataclass(slots=True)
class SparseIndexedPoint:
    chunk_id: str
    bucket_id: int
    vector_name: str
    sparse_vector: SparseVector
    payload: dict[str, int | str]


@dataclass(slots=True)
class SparseQueryVectorSpec:
    """store 层私有：稀疏向量查询规格。

    供 ``QdrantIndexStore._search_chunks`` 使用，向 Qdrant 提交搜索时透传给
    ``query_points(query=SparseVector(...), using=vector_name)``。

    本类**不进 ``vector_storage`` 包的对外 ``__all__``**——它属于 store 层私有契约，
    上游业务通过 ``VectorStorageFacade.search_sparse_chunks`` 的散参签名间接驱动。
    """

    vector_name: str
    indices: list[int]
    values: list[float]
    kind: Literal["sparse"] = "sparse"


@dataclass(slots=True)
class DenseQueryVectorSpec:
    """store 层私有：稠密向量查询规格。

    供 ``QdrantIndexStore._search_chunks`` 的 dense 分支使用，向 Qdrant 提交搜索
    时透传给 ``query_points(query=[float, ...], using=None)``——dense 在本项目
    Qdrant 是 unnamed vector（写入侧 ``ensure_collection`` 用
    ``vectors_config=VectorParams(size, distance=COSINE)``，``PointStruct(vector=[...])``
    裸传），所以 spec **不带 ``vector_name``** 字段。

    与 ``SparseQueryVectorSpec`` 形成 union dispatch；store 层依据 spec 实际类型
    选择 SDK 调用形态。本类**不进 ``vector_storage`` 包的对外 ``__all__``**。
    """

    vector: list[float]
    kind: Literal["dense"] = "dense"


# 类型别名：搜索底座入参的联合类型。
# sparse-vector-recall 阶段引入 sparse 形态；本次（dense-vector-recall）补 dense。
# 未来 hybrid 接入时再升级（届时由该 issue 修订此处类型）。
QueryVectorSpec = SparseQueryVectorSpec | DenseQueryVectorSpec
