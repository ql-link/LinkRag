from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.core.sparse_vector.models import SparseVector


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

    未来 dense 召回扩展时新增 ``DenseQueryVectorSpec`` 同形对仗，并把
    ``QueryVectorSpec`` 升级为 ``Union[SparseQueryVectorSpec, DenseQueryVectorSpec]``。
    本类**不进 ``vector_storage`` 包的对外 ``__all__``**——它属于 store 层私有契约，
    上游业务通过 ``VectorStorageFacade.search_sparse_chunks`` 的散参签名间接驱动。
    """

    vector_name: str
    indices: list[int]
    values: list[float]
    kind: Literal["sparse"] = "sparse"


# 类型别名：搜索底座入参的联合类型；本次只有 sparse，后续 dense / hybrid 接入时升级。
QueryVectorSpec = SparseQueryVectorSpec
