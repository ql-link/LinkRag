"""BM25 sparse 向量编码器（路 A：客户端补算 TF 部分 + 服务端 Modifier.IDF）。

把 RagFlowTokenizer 预分词的 coarse / fine 两套 token 编码成 Qdrant sparse 向量。
coarse 与 fine 各占一段**相互隔离的 hash 维度空间**（同一个词在两段落到不同维度，
互不污染），合并进同一个 sparse 向量——单次点积即同时算 coarse + fine 两路 BM25，
对齐 ES ``multi_match(["coarse_tokens^2", "fine_tokens"])`` 的双字段召回。

- **文档侧** ``encode_document(coarse, fine)``：
  - coarse 词 → coarse 段维度，value = BM25-TF（dl=coarse 长度，avgdl_coarse）
  - fine 词  → fine 段维度，  value = BM25-TF（dl=fine 长度，  avgdl_fine）
  IDF 不在此处算，留给 Qdrant 服务端 ``Modifier.IDF`` 按各维度全库文档频率补上——
  coarse 段与 fine 段维度不重叠，故两路 IDF 各自独立，正对齐 ES 两个字段。
- **查询侧** ``encode_query(coarse)``：query 只用 coarse 词（与 ES 召回侧一致），
  同一套词**同时点亮两段**：coarse 段 value=coarse_boost（对齐 ES coarse^2），
  fine 段 value=1.0。query 词命中文档 fine 段 = 命中"嵌在长词里被细分出的子词"。

二者点积 = ``coarse_boost·Σ(coarse BM25) + Σ(fine BM25)``（sum 融合）。ES 用
best_fields 取 max——sum 在"只 fine 命中"时与 ES 结果一致，"两边都命中"时给分略高，
覆盖面 ≥ ES；补 fine 路的目的（让只在 fine 命中的文档进结果集）两者完全一致。

设计要点：

- **term→维度 用确定性 hash**（blake2b 取满 32-bit），无状态、跨进程全局一致、
  免持久化。coarse / fine 两段用 blake2b 的 ``person`` 盐隔离（同词不同段 → 不同
  维度）。精准召回只依赖"同一个词在同一段永远映射到同一维度"，hash 满足；中文词表
  规模下碰撞概率可忽略，且 IDF 摊薄。映射封装为 :func:`term_to_dimension`。
- **两个 avgdl**：fine 切得更细、token 数更多，单独配 ``avgdl_fine``，避免与 coarse
  共用造成 fine 段长度归一系统性偏。增量写入下用配置常数起步，接受"avgdl 写入时冻结、
  与动态 IDF 之间轻微漂移"的 caveat（见迁移文档），后续按真实库统计校准。
- 编码器不依赖 ``settings`` / qdrant-client，纯计算，便于单测；生产用
  :func:`build_encoder_from_settings` 从配置装配。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

# coarse / fine 两段 hash 空间的隔离盐（blake2b person 参数，≤16 字节）。
_PERSON_COARSE = b"bm25-coarse"
_PERSON_FINE = b"bm25-fine"


@dataclass(frozen=True, slots=True)
class EncodedSparseVector:
    """中立的 sparse 向量载体（不依赖 qdrant-client，便于跨层传递与单测）。"""

    indices: list[int]
    values: list[float]


def term_to_dimension(term: str, *, person: bytes = _PERSON_COARSE) -> int:
    """term → uint32 维度编号（确定性 hash）。同一个词在同一段永远映射到同一维度。

    ``person`` 盐隔离 coarse / fine 两段空间：同一个词在 coarse 段与 fine 段落到不同
    维度，互不污染。用 blake2b 取 4 字节（满 32-bit，对齐 Qdrant sparse vector 的
    uint32 index），分布均匀、跨进程稳定（不受 Python ``hash`` 随机化影响）。
    """

    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=4, person=person).digest()
    return int.from_bytes(digest, "big")


class Bm25SparseEncoder:
    """把预分词 coarse / fine token 编码成 coarse+fine 双段 BM25 sparse 向量（路 A）。"""

    def __init__(
        self,
        *,
        k1: float,
        b: float,
        avgdl_coarse: float,
        avgdl_fine: float,
        coarse_boost: float = 2.0,
    ) -> None:
        if avgdl_coarse <= 0 or avgdl_fine <= 0:
            raise ValueError("avgdl_coarse / avgdl_fine must be positive")
        if k1 < 0:
            raise ValueError("k1 must be non-negative")
        if not 0.0 <= b <= 1.0:
            raise ValueError("b must be in [0, 1]")
        if coarse_boost < 0:
            raise ValueError("coarse_boost must be non-negative")
        self._k1 = float(k1)
        self._b = float(b)
        self._avgdl_coarse = float(avgdl_coarse)
        self._avgdl_fine = float(avgdl_fine)
        self._coarse_boost = float(coarse_boost)

    def encode_document(
        self, coarse_tokens: Sequence[str], fine_tokens: Sequence[str]
    ) -> EncodedSparseVector:
        """文档侧：coarse / fine 两段各自词频饱和 + 长度归一，合并成一个向量。

        两段都为空返回空向量（调用方据此判失败/跳过）。同段内不同 term 万一 hash 到
        同一维度（极罕见），权重累加而非丢弃。
        """

        by_dim: dict[int, float] = {}
        self._accumulate(by_dim, coarse_tokens, person=_PERSON_COARSE, avgdl=self._avgdl_coarse)
        self._accumulate(by_dim, fine_tokens, person=_PERSON_FINE, avgdl=self._avgdl_fine)
        if not by_dim:
            return EncodedSparseVector(indices=[], values=[])
        indices = list(by_dim.keys())
        return EncodedSparseVector(indices=indices, values=[by_dim[i] for i in indices])

    def _accumulate(
        self,
        by_dim: dict[int, float],
        tokens: Sequence[str],
        *,
        person: bytes,
        avgdl: float,
    ) -> None:
        """把一段 token 的 BM25-TF 权重累加进 ``by_dim``（落在 ``person`` 指定的 hash 空间）。"""

        cleaned = [t for token in tokens if (t := str(token).strip())]
        if not cleaned:
            return
        dl = len(cleaned)
        # 长度归一项：dl 越大、norm 越大、TF 部分被压得越低（长文档惩罚）。
        norm = self._k1 * (1.0 - self._b + self._b * dl / avgdl)
        for term, f in Counter(cleaned).items():
            weight = f * (self._k1 + 1.0) / (f + norm)
            dim = term_to_dimension(term, person=person)
            by_dim[dim] = by_dim.get(dim, 0.0) + weight

    def encode_query(self, coarse_tokens: Sequence[str]) -> EncodedSparseVector:
        """查询侧：query 的 coarse 词同时点亮 coarse 段(value=coarse_boost)与 fine 段(value=1)。

        与 ES 召回侧一致——只用 coarse 词，投到文档 coarse 字段(^coarse_boost)与 fine
        字段(×1)。IDF 由 Qdrant 服务端补。重复词去重（每词每段一维）。
        """

        terms = list(dict.fromkeys(t for token in coarse_tokens if (t := str(token).strip())))
        if not terms:
            return EncodedSparseVector(indices=[], values=[])
        by_dim: dict[int, float] = {}
        for term in terms:
            by_dim[term_to_dimension(term, person=_PERSON_COARSE)] = self._coarse_boost
            by_dim[term_to_dimension(term, person=_PERSON_FINE)] = 1.0
        indices = list(by_dim.keys())
        return EncodedSparseVector(indices=indices, values=[by_dim[i] for i in indices])


def build_encoder_from_settings() -> Bm25SparseEncoder:
    """从 ``settings`` 装配生产用编码器（k1/b/coarse+fine 两个 avgdl/coarse_boost 走配置）。"""

    from src.config import settings

    return Bm25SparseEncoder(
        k1=settings.BM25_K1,
        b=settings.BM25_B,
        avgdl_coarse=settings.BM25_AVGDL,
        avgdl_fine=settings.BM25_AVGDL_FINE,
        coarse_boost=settings.BM25_COARSE_BOOST,
    )
