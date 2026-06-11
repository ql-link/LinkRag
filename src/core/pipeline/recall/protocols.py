"""召回路统一契约。

pipeline 只认"满足契约的召回方式"，不限制路数。本期默认装稠密 / 稀疏 / 关键词
三路；后续要加 GraphRag / wiki 等，只要新路满足本契约就能直接挂进来。
"""

from typing import Protocol, runtime_checkable

from src.core.pipeline.recall.models import RetrieverHit

# 本期内置三路 source 名常量；调用方自由选用，pipeline 不依赖具体取值。
SOURCE_DENSE = "dense"
SOURCE_SPARSE = "sparse"
SOURCE_BM25 = "bm25"


@runtime_checkable
class Retriever(Protocol):
    """召回方法契约。

    实现方在自己的存储模块（storage.qdrant / storage.vector /
    storage.es）内自包含完成 query 预处理（embedding / 稀疏化 / 分词）、
    存储查询、打分排序，最终返回一份按自己打分降序排好的候选列表。

    实现要求：
    - ``source`` 必须是常量字符串，pipeline 内部用它作为 dict 键。
    - ``recall`` 返回的列表必须按 score 降序排序——pipeline 信任此前提，不会重排。
    - 合法但无命中应返回 ``[]``，不要抛异常。
    - 不可恢复的查询失败（模型不可达、ES 超时等）应抛任意 Exception，由 pipeline
      按严格 / 宽松策略处理。
    - ``user_id`` 与 ``top_k`` 在**执行期**由 pipeline 透传（来自 ``RecallRequest``），
      retriever 不在装配期持有它们——这样 pipeline 与 retriever 可单例复用。
    """

    source: str

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
        *,
        user_id: int,
        top_k: int,
    ) -> list[RetrieverHit]:
        ...
