"""多路召回 pipeline 编排骨架。

只做三件事：
1. 按配置（并行 / 串行）触发已装配的全部召回路；
2. 按容错策略（宽松 / 严格）收敛单路异常；
3. 对成功路结果做配置指定的粗融合并打包返回。

不做：query 预处理、向量化、分词、查存储、读 MySQL、reranker
精排。这些要么在各路自己的实现里，要么留给下游。
"""

import asyncio
import time

from loguru import logger
from src.observability.logging import safe_exception_stack, truncate_log_value

from src.core.pipeline.recall.exceptions import (
    RecallError,
    RecallFatalError,
    RecallValidationError,
)
from src.core.pipeline.recall.fusion import fuse_hits
from src.core.pipeline.recall.models import (
    RecallPipelineConfig,
    RecallRequest,
    RecallResponse,
    RetrieverHit,
    build_recall_diagnostics,
    normalize_fusion_strategy,
    validate_fusion_weight,
    validate_rrf_k,
)
from src.core.pipeline.recall.protocols import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    DocumentReadinessGate,
    Retriever,
)


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
        *,
        readiness_gate: DocumentReadinessGate,
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
        self._readiness_gate = readiness_gate

    async def execute(self, request: RecallRequest) -> RecallResponse:
        """顶层编排入口。

        失败语义：
        - 入参校验失败 → ``RecallValidationError``；
        - 严格模式下任一路异常 → ``RecallError``；
        - 宽松模式下已装配的全部路异常 → ``RecallError``。
        """
        started_at = time.monotonic()
        self._validate(request)

        # 本次生效的召回路：按数据集级 enabled_sources 在已装配路集合内收窄（见 _effective_sources）。
        effective_sources = self._effective_sources(request)
        fusion_strategy, fusion_weights, rrf_k = self._effective_fusion_config(request)
        # 容错模式：请求级覆盖优先，未指定时沿用装配期默认。
        strict = (
            request.strict_override if request.strict_override is not None else self._config.strict
        )

        # 入口日志：不记 query 原文（可能含用户敏感内容），只记可观测的元信息。
        logger.info(
            "[RecallPipeline] start user={} datasets={} docs={} fusion_limit={} "
            "route_top_k={} sources={} strict={} fusion={} rrf_k={} mode={}",
            request.user_id,
            len(request.dataset_ids or []),
            len(request.doc_ids or []),
            request.top_k,
            {s: self._top_k_for_source(s, request) for s in effective_sources},
            effective_sources,
            strict,
            fusion_strategy,
            rrf_k,
            "parallel" if self._config.parallel else "serial",
        )

        if self._config.parallel:
            per_source_results = await self._run_parallel(request, effective_sources)
        else:
            per_source_results = await self._run_serial(request, effective_sources)

        success_hits, failed_sources = self._check_failures(
            per_source_results, effective_sources, strict
        )
        fused_hits = fuse_hits(
            per_source_hits=success_hits,
            all_sources=effective_sources,
            strategy=fusion_strategy,
            rrf_k=rrf_k,
            weights=fusion_weights,
        )
        # 文档门禁必须在最终 top_k 之前执行，否则隐藏候选会占用窗口，
        # 导致后方的可见文档无法补位。门禁必须保持融合顺序。
        fused_hits = await self._readiness_gate.filter_visible_hits(
            fused_hits,
            user_id=request.user_id,
        )
        # 融合候选池窗口：门禁过滤后再按 request.top_k 截断，作为下游 rerank 输入池。
        fused_hits = fused_hits[: request.top_k]
        elapsed_ms = int((time.monotonic() - started_at) * 1000)

        # 结果日志：耗时、融合命中数、各路命中分布、失败路（已有数据，原先只进响应不落日志）。
        logger.info(
            "[RecallPipeline] done user={} elapsed_ms={} hits={} per_source={} failed={}",
            request.user_id,
            elapsed_ms,
            len(fused_hits),
            {s: len(success_hits.get(s, [])) for s in effective_sources},
            failed_sources,
        )
        return self._build_response(
            query=request.query,
            fused_hits=fused_hits,
            success_hits=success_hits,
            failed_sources=failed_sources,
            elapsed_ms=elapsed_ms,
            sources=effective_sources,
        )

    def _effective_fusion_config(self, request: RecallRequest) -> tuple[str, dict[str, float], int]:
        """合并装配期默认与请求级覆盖，得到本次生效的融合策略、权重与 RRF 常数。"""
        try:
            strategy = normalize_fusion_strategy(
                request.fusion_strategy_override or self._config.fusion_strategy
            )
            rrf_k = validate_rrf_k(
                (
                    request.rrf_k_override
                    if request.rrf_k_override is not None
                    else self._config.rrf_k
                )
            )
            weights = {
                SOURCE_BM25: validate_fusion_weight(
                    (
                        request.fusion_bm25_weight_override
                        if request.fusion_bm25_weight_override is not None
                        else self._config.fusion_bm25_weight
                    ),
                    field_name="fusion_bm25_weight",
                ),
                SOURCE_SPARSE: validate_fusion_weight(
                    (
                        request.fusion_sparse_weight_override
                        if request.fusion_sparse_weight_override is not None
                        else self._config.fusion_sparse_weight
                    ),
                    field_name="fusion_sparse_weight",
                ),
                SOURCE_DENSE: validate_fusion_weight(
                    (
                        request.fusion_dense_weight_override
                        if request.fusion_dense_weight_override is not None
                        else self._config.fusion_dense_weight
                    ),
                    field_name="fusion_dense_weight",
                ),
            }
        except ValueError as exc:
            raise RecallValidationError(str(exc)) from exc
        return strategy, weights, rrf_k

    def _effective_sources(self, request: RecallRequest) -> list[str]:
        """求本次实际触发的召回路：在已装配路集合内按 ``request.enabled_sources`` 收窄。

        - ``enabled_sources`` 为 ``None`` / 空 → 用全部已装配路；
        - 非空 → 取与已装配路的交集（保持装配顺序），列出的未装配路被忽略；
        - 交集为空（如数据集只点了系统未装配的路）→ 回退全部已装配路并记 warning，
          避免因一条过时的数据集配置把整次召回打空。
        """
        requested = request.enabled_sources
        if not requested:
            return self._sources
        requested_set = set(requested)
        effective = [s for s in self._sources if s in requested_set]
        if not effective:
            logger.warning(
                "[RecallPipeline] enabled_sources={} matched none of assembled sources={}; "
                "falling back to all assembled sources",
                requested,
                self._sources,
            )
            return self._sources
        return effective

    def _validate(self, request: RecallRequest) -> None:
        """入参校验：query 非空非空白；user_id 为正；RRF 窗口与各路 top_k 为正。

        dataset_ids 允许空（=全库召回）。HTTP 入口已在握手前做同等校验，这里是
        pipeline 自身的安全网，保证任何调用方都不能绕过。
        """
        if not isinstance(request.query, str) or not request.query.strip():
            raise RecallValidationError("query is empty or blank")
        if request.user_id is None or request.user_id <= 0:
            raise RecallValidationError("user_id must be a positive int")
        positive_int_fields = {
            "top_k": request.top_k,
            "bm25_top_k": request.bm25_top_k,
            "sparse_top_k": request.sparse_top_k,
            "dense_top_k": request.dense_top_k,
        }
        for field, value in positive_int_fields.items():
            if value is None or value <= 0:
                raise RecallValidationError(f"{field} must be a positive int")

    @staticmethod
    def _score_threshold_override_for(source: str, request: RecallRequest) -> float | None:
        """按 source 取该路的数据集级分数阈值覆盖。

        sparse / dense 各取对应字段；bm25 等其余路无分数阈值概念，返回 ``None``（retriever
        侧也会忽略该参数）。
        """
        if source == SOURCE_SPARSE:
            return request.sparse_score_threshold_override
        if source == SOURCE_DENSE:
            return request.dense_score_threshold_override
        return None

    @staticmethod
    def _top_k_for_source(source: str, request: RecallRequest) -> int:
        """按 source 取本路执行期 top_k；未知新路回退到融合候选池窗口。

        回退语义让未来新增召回路在尚未增加专属 top_k 配置前也能运行，而不会因
        缺少 ``graph_top_k`` 之类字段直接失败。
        """
        if source == SOURCE_BM25:
            return request.bm25_top_k
        if source == SOURCE_SPARSE:
            return request.sparse_top_k
        if source == SOURCE_DENSE:
            return request.dense_top_k
        return request.top_k

    async def _run_parallel(
        self,
        request: RecallRequest,
        sources: list[str],
    ) -> dict[str, list[RetrieverHit] | BaseException]:
        """并行触发：``asyncio.gather(return_exceptions=True)`` 收异常成对象返回。

        只触发 ``sources`` 列出的（本次生效的）召回路。
        """
        retrievers = [r for r in self._retrievers if r.source in set(sources)]
        tasks = [
            r.recall(
                request.query,
                request.dataset_ids,
                request.doc_ids,
                user_id=request.user_id,
                top_k=self._top_k_for_source(r.source, request),
                score_threshold_override=self._score_threshold_override_for(r.source, request),
            )
            for r in retrievers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {r.source: result for r, result in zip(retrievers, results)}

    async def _run_serial(
        self,
        request: RecallRequest,
        sources: list[str],
    ) -> dict[str, list[RetrieverHit] | BaseException]:
        """串行触发：按 retrievers 构造顺序依次 await；前一路完成才触发下一路。

        只触发 ``sources`` 列出的（本次生效的）召回路；单路异常不阻断后续路
        （与并行模式语义对齐——区别仅在触发模式）。
        """
        active = set(sources)
        results: dict[str, list[RetrieverHit] | BaseException] = {}
        for retriever in self._retrievers:
            if retriever.source not in active:
                continue
            try:
                hits = await retriever.recall(
                    request.query,
                    request.dataset_ids,
                    request.doc_ids,
                    user_id=request.user_id,
                    top_k=self._top_k_for_source(retriever.source, request),
                    score_threshold_override=self._score_threshold_override_for(
                        retriever.source, request
                    ),
                )
                results[retriever.source] = hits
            except Exception as exc:
                results[retriever.source] = exc
        return results

    def _check_failures(
        self,
        per_source_results: dict[str, list[RetrieverHit] | BaseException],
        sources: list[str],
        strict: bool,
    ) -> tuple[dict[str, list[RetrieverHit]], list[str]]:
        """分流：成功路收进 dict，失败路收成 list[source]。

        在两种情况下抛 ``RecallError``：
        - 严格模式且有任一路失败；
        - 已装配的全部路都失败（即便宽松模式也强制抛，避免"系统全挂"被误读为
          "没召回到东西"）。
        """
        success_hits: dict[str, list[RetrieverHit]] = {}
        failed: list[tuple[str, BaseException]] = []
        # 按本次生效的 sources 顺序遍历，保持失败列表的稳定顺序。
        for source in sources:
            result = per_source_results[source]
            if isinstance(result, BaseException):
                failed.append((source, result))
                logger.bind(
                    event="recall_source_failed",
                    outcome="degraded",
                    source=source,
                    error_type=type(result).__name__,
                    error_message=truncate_log_value(result),
                    stack_trace=safe_exception_stack(result),
                ).warning(
                    "[RecallPipeline] retriever source={} failed",
                    source,
                )
            else:
                success_hits[source] = result

        # 致命失败优先：必备前置缺失（如发起用户无默认 EMBEDDING 配置）必须让整请求失败，
        # **绕过** strict/lenient 逻辑——即便宽松模式也不降级为"少一路"。
        for _source, exc in failed:
            if isinstance(exc, RecallFatalError):
                raise exc

        if strict and failed:
            first_source, first_exc = failed[0]
            raise RecallError(f"strict mode: retriever source={first_source} failed: {first_exc!r}")

        if len(failed) == len(sources):
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
        sources: list[str],
    ) -> RecallResponse:
        """组装响应：per_source_counts 基于本次生效的 source 集；空列表 / 失败路都计 0。"""
        per_source_counts = {source: len(success_hits.get(source, [])) for source in sources}
        recall_diagnostics = build_recall_diagnostics(
            active_sources=sources,
            per_source_counts=per_source_counts,
            failed_sources=failed_sources,
        )
        if recall_diagnostics is not None and recall_diagnostics.degraded:
            logger.warning(
                "[RecallPipeline] source degraded mode={} active_sources={} per_source={} "
                "empty={} failed={}",
                recall_diagnostics.source_mode,
                recall_diagnostics.active_sources,
                recall_diagnostics.per_source_counts,
                recall_diagnostics.empty_sources,
                recall_diagnostics.failed_sources,
            )
        return RecallResponse(
            query=query,
            hits=fused_hits,
            per_source_counts=per_source_counts,
            failed_sources=failed_sources,
            elapsed_ms=elapsed_ms,
            recall_diagnostics=recall_diagnostics,
        )


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for v in values:
        if v in seen and v not in duplicates:
            duplicates.append(v)
        seen.add(v)
    return duplicates
