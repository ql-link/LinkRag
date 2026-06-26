"""BM25 sparse 向量编码器（路 A：客户端补算 TF 部分 + 服务端 Modifier.IDF）。

把 RagFlowTokenizer 预分词的 token 串编码成 Qdrant sparse 向量：

- **文档侧**：每个 term 一维，value = BM25 的 TF 部分
  ``f·(k1+1) / (f + k1·(1−b+b·dl/avgdl))``——即词频饱和(k1)+长度归一(b)。
  IDF 不在此处算，留给 Qdrant 服务端的 ``Modifier.IDF`` 在查询时按全库文档频率补上。
- **查询侧**：每个 query term 一维，value=1.0（IDF 同样由服务端补）。

二者点积 = ``Σ 1 · [BM25 TF 部分] · IDF`` = 真 BM25 主分，与 ES 对齐。

设计要点：

- **term→维度 用确定性 hash**（blake2b 取满 32-bit），无状态、跨进程全局一致、
  免持久化。精准召回只依赖"同一个词永远映射到同一维度"，hash 满足；中文词表
  规模下碰撞概率 ~ N²/2³³ 可忽略，且 IDF 摊薄。映射封装为
  :func:`term_to_dimension`，未来若要零冲突词表可平滑替换。
- **avgdl（长度归一所需的全库平均文档长度）** 由构造方注入。增量写入下用配置
  常数（``settings.BM25_AVGDL``）起步，接受"avgdl 写入时冻结、与动态 IDF 之间
  存在轻微漂移"的 caveat（见迁移文档）。
- 编码器不依赖 ``settings`` / qdrant-client，纯计算，便于单测；生产用
  :func:`build_encoder_from_settings` 从配置装配。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EncodedSparseVector:
    """中立的 sparse 向量载体（不依赖 qdrant-client，便于跨层传递与单测）。"""

    indices: list[int]
    values: list[float]


def term_to_dimension(term: str) -> int:
    """term → uint32 维度编号（确定性 hash）。同一个词永远映射到同一维度。

    用 blake2b 取 4 字节（满 32-bit，对齐 Qdrant sparse vector 的 uint32 index），
    分布均匀、跨进程稳定（不受 Python ``hash`` 随机化影响）。
    """

    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big")


class Bm25SparseEncoder:
    """把预分词 token 串编码成 BM25 sparse 向量（路 A）。"""

    def __init__(self, *, k1: float, b: float, avgdl: float) -> None:
        if avgdl <= 0:
            raise ValueError("avgdl must be positive")
        if k1 < 0:
            raise ValueError("k1 must be non-negative")
        if not 0.0 <= b <= 1.0:
            raise ValueError("b must be in [0, 1]")
        self._k1 = float(k1)
        self._b = float(b)
        self._avgdl = float(avgdl)

    def encode_document(self, tokens: Sequence[str]) -> EncodedSparseVector:
        """文档侧：词频饱和 + 长度归一，产出 BM25-TF 权重向量。

        空 token 被过滤；空文档返回空向量（调用方据此判失败/跳过）。同一文档内
        不同 term 万一 hash 到同一维度（极罕见），权重累加而非丢弃。
        """

        cleaned = [t for token in tokens if (t := str(token).strip())]
        if not cleaned:
            return EncodedSparseVector(indices=[], values=[])

        dl = len(cleaned)
        # 长度归一项：dl 越大、norm 越大、TF 部分被压得越低（长文档惩罚）。
        norm = self._k1 * (1.0 - self._b + self._b * dl / self._avgdl)

        by_dim: dict[int, float] = {}
        for term, f in Counter(cleaned).items():
            weight = f * (self._k1 + 1.0) / (f + norm)
            dim = term_to_dimension(term)
            by_dim[dim] = by_dim.get(dim, 0.0) + weight

        indices = list(by_dim.keys())
        values = [by_dim[i] for i in indices]
        return EncodedSparseVector(indices=indices, values=values)

    def encode_query(self, tokens: Sequence[str]) -> EncodedSparseVector:
        """查询侧：每个不同 term 一维，value=1.0（IDF 由 Qdrant 服务端补）。"""

        dims = {term_to_dimension(t) for token in tokens if (t := str(token).strip())}
        indices = list(dims)
        return EncodedSparseVector(indices=indices, values=[1.0] * len(indices))


def build_encoder_from_settings() -> Bm25SparseEncoder:
    """从 ``settings`` 装配生产用编码器（k1/b/avgdl 走配置）。"""

    from src.config import settings

    return Bm25SparseEncoder(
        k1=settings.BM25_K1,
        b=settings.BM25_B,
        avgdl=settings.BM25_AVGDL,
    )
