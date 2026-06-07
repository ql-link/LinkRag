"""多路召回 pipeline 编排骨架。

只做三件事：
1. 按配置（并行 / 串行）触发已装配的全部召回路；
2. 按容错策略（宽松 / 严格）收敛单路异常；
3. 对成功路结果做 RRF 粗融合并打包返回。

不做：query 预处理、向量化、分词、查存储、读 MySQL、跨路打分归一化、reranker
精排。这些要么在各路自己的实现里，要么留给下游。
"""

import asyncio
import time

from loguru import logger

from src.core.pipeline.recall.exceptions import (
    RecallError,
    RecallFatalError,
    RecallValidationError,
)
from src.core.pipeline.recall.fusion import fuse_with_rrf
from src.core.pipeline.recall.models import (
    RecallPipelineConfig,
    RecallRequest,
    RecallResponse,
    RetrieverHit,
)
from src.core.pipeline.recall.protocols import Retriever


class RecallPipeline:
    """多路召回 pipeline。

    构造期约束：
    - 至少装配一路；
    - 各路 ``source`` 名两两不重复（重复直接 ``ValueError``，把装配错误暴露在构造期）。

    本期默认装稠密 / 稀疏 / 关键词三路；pipeline 内部不写死路数，新增 GraphRag /
    wiki 等只需满足 ``Retriever`` 契约并加进 ``retrievers`` 列表即可。
    """

    def __init__(
        self,
        retrievers: list[Retriever],
        config: RecallPipelineConfig | None = None,
    ) -> None:
        if not retrievers:
            raise ValueError("RecallPipeline requires at least one retriever")
        sources = [r.source for r in retrievers]
        duplicates = _find_duplicates(sources)
        if duplicates:
            raise ValueError(
                f"RecallPipeline retriever sources must be unique, duplicates: {duplicates}"
            )
        self._retrievers = list(retrievers)
        self._sources = sources
        self._config = config or RecallPipelineConfig()

    async def execute(self, request: RecallRequest) -> RecallResponse:
        """顶层编排入口。

        失败语义：
        - 入参校验失败 → ``RecallValidationError``；
        - 严格模式下任一路异常 → ``RecallError``；
        - 宽松模式下已装配的全部路异常 → ``RecallError``。
        """
        started_at = time.monotonic()
        self._validate(request)

        # 入口日志：不记 query 原文（可能含用户敏感内容），只记可观测的元信息。
        logger.info(
            "[RecallPipeline] start user={} datasets={} docs={} top_k={} mode={}",
            request.user_id,
            len(request.dataset_ids or []),
            len(request.doc_ids or []),
            request.top_k,
            "parallel" if self._config.parallel else "serial",
        )

        if self._config.parallel:
            per_source_results = await self._run_parallel(request)
        else:
            per_source_results = await self._run_serial(request)

        success_hits, failed_sources = self._check_failures(per_source_results)
        fused_hits = fuse_with_rrf(
            per_source_hits=success_hits,
            all_sources=self._sources,
            k=self._config.rrf_k,
        )
        # 服务端固定返回候选上限：融合后按 top_k 截断（fuse 已按 fused_score 降序）。
        fused_hits = fused_hits[: request.top_k]
        elapsed_ms = int((time.monotonic() - started_at) * 1000)

        # 结果日志：耗时、融合命中数、各路命中分布、失败路（已有数据，原先只进响应不落日志）。
        logger.info(
            "[RecallPipeline] done user={} elapsed_ms={} hits={} per_source={} failed={}",
            request.user_id,
            elapsed_ms,
            len(fused_hits),
            {s: len(success_hits.get(s, [])) for s in self._sources},
            failed_sources,
        )
        return self._build_response(
            query=request.query,
            fused_hits=fused_hits,
            success_hits=success_hits,
            failed_sources=failed_sources,
            elapsed_ms=elapsed_ms,
        )

    def _validate(self, request: RecallRequest) -> None:
        """入参校验：query 非空非空白；user_id 为正；top_k 为正。

        dataset_ids 允许空（=全库召回）。HTTP 入口已在握手前做同等校验，这里是
        pipeline 自身的安全网，保证任何调用方都不能绕过。
        """
        if not isinstance(request.query, str) or not request.query.strip():
            raise RecallValidationError("query is empty or blank")
        if request.user_id is None or request.user_id <= 0:
            raise RecallValidationError("user_id must be a positive int")
        if request.top_k is None or request.top_k <= 0:
            raise RecallValidationError("top_k must be a positive int")

    async def _run_parallel(
        self,
        request: RecallRequest,
    ) -> dict[str, list[RetrieverHit] | BaseException]:
        """并行触发：``asyncio.gather(return_exceptions=True)`` 收异常成对象返回。"""
        tasks = [
            r.recall(
                request.query,
                request.dataset_ids,
                request.doc_ids,
                user_id=request.user_id,
                top_k=request.top_k,
            )
            for r in self._retrievers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {source: result for source, result in zip(self._sources, results)}

    async def _run_serial(
        self,
        request: RecallRequest,
    ) -> dict[str, list[RetrieverHit] | BaseException]:
        """串行触发：按 retrievers 构造顺序依次 await；前一路完成才触发下一路。

        单路异常不阻断后续路（与并行模式语义对齐——区别仅在触发模式）。
        """
        results: dict[str, list[RetrieverHit] | BaseException] = {}
        for retriever in self._retrievers:
            try:
                hits = await retriever.recall(
                    request.query,
                    request.dataset_ids,
                    request.doc_ids,
                    user_id=request.user_id,
                    top_k=request.top_k,
                )
                results[retriever.source] = hits
            except Exception as exc:
                results[retriever.source] = exc
        return results

    def _check_failures(
        self,
        per_source_results: dict[str, list[RetrieverHit] | BaseException],
    ) -> tuple[dict[str, list[RetrieverHit]], list[str]]:
        """分流：成功路收进 dict，失败路收成 list[source]。

        在两种情况下抛 ``RecallError``：
        - 严格模式且有任一路失败；
        - 已装配的全部路都失败（即便宽松模式也强制抛，避免"系统全挂"被误读为
          "没召回到东西"）。
        """
        success_hits: dict[str, list[RetrieverHit]] = {}
        failed: list[tuple[str, BaseException]] = []
        # 按 self._sources 顺序遍历，保持失败列表的稳定顺序。
        for source in self._sources:
            result = per_source_results[source]
            if isinstance(result, BaseException):
                failed.append((source, result))
                logger.warning(
                    "[RecallPipeline] retriever source={} failed: {}",
                    source, result,
                )
            else:
                success_hits[source] = result

        # 致命失败优先：必备前置缺失（如发起用户无默认 EMBEDDING 配置）必须让整请求失败，
        # **绕过** strict/lenient 逻辑——即便宽松模式也不降级为"少一路"。
        for _source, exc in failed:
            if isinstance(exc, RecallFatalError):
                raise exc

        if self._config.strict and failed:
            first_source, first_exc = failed[0]
            raise RecallError(
                f"strict mode: retriever source={first_source} failed: {first_exc!r}"
            )

        if len(failed) == len(self._sources):
            summary = "; ".join(f"{s}={exc!r}" for s, exc in failed)
            raise RecallError(f"all retrievers failed: {summary}")

        return success_hits, [s for s, _ in failed]

    def _build_response(
        self,
        *,
        query: str,
        fused_hits,
        success_hits: dict[str, list[RetrieverHit]],
        failed_sources: list[str],
        elapsed_ms: int,
    ) -> RecallResponse:
        """组装响应：per_source_counts 基于已装配 source 全集；空列表 / 失败路都计 0。"""
        per_source_counts = {
            source: len(success_hits.get(source, [])) for source in self._sources
        }
        return RecallResponse(
            query=query,
            hits=fused_hits,
            per_source_counts=per_source_counts,
            failed_sources=failed_sources,
            elapsed_ms=elapsed_ms,
        )


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for v in values:
        if v in seen and v not in duplicates:
            duplicates.append(v)
        seen.add(v)
    return duplicates
