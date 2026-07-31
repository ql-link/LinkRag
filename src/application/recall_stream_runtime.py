"""召回 SSE 流式执行 runtime。

对外 RAG 问答流端点 ``/api/v1/rag/stream``（``routes/rag.py``）的召回融合 +
LLM 流式生成执行与事件序列化的**单一来源**。

- ``recall_event``：序列化单帧 SSE 事件；
- ``recall_event_stream``：流内执行 pipeline，把结果/异常映射为 SSE 终态事件。

hits 序列化抽至 ``recall_serialization``：本 runtime 用 ``serialize_reranked_hits``
（含 rerank 字段与 chunk 正文，供前端展示召回片段），纯召回 JSON 端点用
``serialize_hits``（仅融合字段、不回填正文）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncGenerator

from loguru import logger

from src.application.ltr_provider import get_initialized_ltr_ranker
from src.application.ltr_shadow_executor import get_ltr_shadow_executor
from src.application.recall_errors import (
    CODE_ALL_SOURCES_FAILED,
    CODE_EMBEDDING_CONFIG_MISSING,
    CODE_GENERATION_FAILED,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_REQUEST,
    CODE_MODEL_CONFIG_MISSING,
    CODE_TIMEOUT,
)
from src.application.recall_serialization import (
    serialize_recall_diagnostics,
    serialize_reranked_hits,
)
from src.config import settings
from src.core.llm.exceptions import LLMConfigResolutionError
from src.core.llm.response import UsageInfo
from src.core.llm.user_model_resolver import aresolve_model
from src.core.mq.messages import ChatTurnMessage
from src.core.pipeline.ltr import LtrRankResult
from src.core.pipeline.ltr.features import weighted_baseline_order
from src.core.pipeline.recall import (
    RecallDiagnostics,
    RecallError,
    RecallFatalError,
    RecallHit,
    RecallPipeline,
    RecallRequest,
    RecallValidationError,
    RetrieverHit,
)
from src.core.pipeline.recall.generation import assemble_context, fetch_chunk_contents
from src.core.pipeline.rerank import (
    PostRecallReranker,
    RerankedHit,
    RerankRequest,
    degrade_to_fusion_order,
    reranked_from_recall,
)
from src.core.prompts import (
    CONVERSATION_TITLE_SYSTEM_PROMPT,
    RAG_GENERATION_SYSTEM_PROMPT,
    build_rag_user_prompt,
    build_title_user_prompt,
    clean_title,
    fallback_title_from_query,
)
from src.core.prompts.conversation_title import TITLE_MAX_OUTPUT_TOKENS
from src.observability.logging import safe_exception_stack, truncate_log_value
from src.services.mq_service import MQService
from src.services.usage_reporter import report_usage_nowait


def recall_event(name: str, payload: dict) -> str:
    """序列化为单帧 SSE 事件（``data`` 为单行 JSON）。"""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _try_llm_title(resolved, query: str, request_id: str) -> str | None:
    """用本轮对话模型基于 ``query`` 生成标题（best-effort）。

    失败/超时/清洗后为空一律返回 ``None``，由调用方回落首问截断兜底——标题是增强项，
    任何异常都不得影响答案与落库。``CancelledError`` 向上传播（进程关闭取消任务）。
    """
    try:
        result = await asyncio.wait_for(
            resolved.provider.generate(
                prompt=build_title_user_prompt(query),
                system_prompt=CONVERSATION_TITLE_SYSTEM_PROMPT,
                temperature=0.2,
                # 推理模型需留足思考预算，否则正文被截空（见 TITLE_MAX_OUTPUT_TOKENS 说明）。
                max_tokens=TITLE_MAX_OUTPUT_TOKENS,
            ),
            timeout=settings.TITLE_GENERATION_TIMEOUT_MS / 1000,
        )
        return clean_title(result.content)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 标题为增强项，失败回落兜底
        logger.bind(
            event="recall_title_generation_failed",
            outcome="degraded",
            request_id=request_id,
            provider_type=getattr(resolved, "provider_type", "") or "",
            model_name=getattr(resolved, "model_name", "") or "",
            config_id=getattr(resolved, "config_id", None),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning("[recall] title generation failed request_id={}", request_id)
        return None


async def _resolve_title(resolved, query: str, fallback_title: str, request_id: str) -> str:
    """首轮标题任务体：LLM 标题优先，不可用即回落首问截断（必返回非空）。

    作为独立 ``asyncio.Task`` 与召回 + 生成并行起跑，标题调用延迟被答案流式输出与模型
    思考过程掩盖，不串行增加问答耗时。
    """
    llm_title = await _try_llm_title(resolved, query, request_id)
    return llm_title or fallback_title


async def _await_title_result(
    title_task: asyncio.Task | None, fallback_title: str | None
) -> str | None:
    """终态取回首轮标题：await 已并行起跑的任务（LLM 优先、必非空）。

    非首轮（``title_task is None``）返回 ``None``。任务体已自兜底，正常返回非空标题；
    防御性异常回落 ``fallback_title``。
    """
    if title_task is None:
        return None
    try:
        return await title_task
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - 任务体已兜底，这里仅防御
        return fallback_title


async def _drain_title_task(title_task: asyncio.Task | None) -> None:
    """失败终态回收标题任务：取消并等待，避免孤儿/未消费告警。

    失败首轮的会话标题用首问截断兜底即可（方案 A），不值得为失败请求多等一次 LLM。
    """
    if title_task is None or title_task.done():
        return
    title_task.cancel()
    try:
        await title_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 主动取消，吞掉本任务异常
        pass


async def recall_event_stream(
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
    request_id: str,
    config_id: int,
    conversation_id: int,
    turn_id: str,
    reranker: PostRecallReranker,
    token_budget: int,
    rerank_top_n: int,
    is_first_turn: bool = False,
    shadow_recall_req: RecallRequest | None = None,
) -> AsyncGenerator[str, None]:
    """流内执行召回 + 重排 + 生成，把结果/异常映射为 SSE 终态事件。

    ``token_budget`` 为生成阶段上下文拼装的 token 预算，``rerank_top_n`` 为重排后候选条数
    上限，二者均来自数据集级 ``recall_config``（分别为 ``recall_context_token_budget`` /
    ``rerank_top_n``，无数据集配置时为系统默认）。

    先按 ``(user_id, CHAT, config_id)`` 前置校验模型——不可用即 ``error``
    MODEL_CONFIG_MISSING、**不进入召回**；通过后执行召回融合，一次性回填片段正文（供
    rerank 与生成共用），对融合候选做 rerank 精排（不可用即降级为当前融合顺序，见
    ``_rerank_hits``；与召回共享同一条流超时预算），用重排后的最终候选按 token 预算拼装
    上下文，用该模型流式生成——逐 token ``answer_delta``、结束 ``answer_done``（附最终候选
    元信息与 ``rerank_applied``）。生成阶段失败 → ``error`` GENERATION_FAILED（整请求失败）。
    0 命中 / 全部片段缺正文 → ``recall_done``（不生成）。

    通用失败终态：必备前置缺失（用户无默认 EMBEDDING 配置）→ ``error`` EMBEDDING_CONFIG_MISSING；
    全路失败 → ``error`` ALL_SOURCES_FAILED；超时 → ``error`` TIMEOUT；客户端断连 → 停止发送并向上
    传播取消；未预期异常 → ``error`` INTERNAL_ERROR。message 不含内部堆栈。

    落库（chat-stream-resilient-persist）：入口先发 ``GENERATING`` 起点轮次消息（``turn_id``
    幂等键贯穿起点与终态，Java 据此 upsert 同一行）；**每个失败终态都补发一条 ``FAILED``
    轮次消息**（带 ``error_code``），而非只发 SSE error——保证后台续跑后状态可落库可判定。
    成功 / 空命中的 ``COMPLETED`` 由 ``_generate_answer`` 发出。
    """
    timeout_seconds = settings.RECALL_STREAM_TIMEOUT_MS / 1000
    started = time.perf_counter()
    recall_deadline = time.monotonic() + timeout_seconds

    def _remaining_recall_budget() -> float:
        remaining = recall_deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError
        return remaining

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    # 起点：发 GENERATING（answer 空、模型未解析）。任一后续失败终态会补发 FAILED 关闭该行。
    # GENERATING 不带 title——若起点先写截断标题，Java 视其为非默认值，后续 LLM 标题就被
    # 「空/默认才写」挡掉而落不进库；标题只在终态携带。
    resolved = None
    # 首轮才生成标题：fallback_title 是首问截断兜底（必非空），title_task 是与召回+生成
    # 并行的标题任务（resolved 成功后才起）。非首轮二者分别为 None。
    fallback_title = fallback_title_from_query(recall_req.query) if is_first_turn else None
    title_task: asyncio.Task | None = None
    await _emit_chat_turn(
        recall_req=recall_req,
        request_id=request_id,
        turn_id=turn_id,
        conversation_id=conversation_id,
        config_id=config_id,
        resolved=None,
        answer="",
        usage=UsageInfo(),
        references=[],
        latency_ms=0,
        status="GENERATING",
    )
    try:
        # 召回前置校验用户模型；不可用即硬失败、不进入召回。
        try:
            resolved = await aresolve_model(
                user_id=recall_req.user_id,
                capability="CHAT",
                config_id=config_id,
            )
        except LLMConfigResolutionError as exc:
            logger.bind(
                event="recall_model_config_unavailable",
                outcome="failed",
                request_id=request_id,
                turn_id=turn_id,
                conversation_id=conversation_id,
                user_id=recall_req.user_id,
                config_id=config_id,
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
            ).warning(
                "[recall] model config unavailable request_id={} config_id={}",
                request_id,
                config_id,
            )
            yield recall_event(
                "error",
                {
                    "code": exc.code,
                    "message": str(exc),
                },
            )
            await _emit_chat_turn(
                recall_req=recall_req,
                request_id=request_id,
                turn_id=turn_id,
                conversation_id=conversation_id,
                config_id=config_id,
                resolved=None,
                answer="",
                usage=UsageInfo(),
                references=[],
                latency_ms=_elapsed_ms(),
                status="FAILED",
                error_code=exc.code,
                error_message=str(exc),
                title=fallback_title,  # 模型未解析无法调 LLM，首轮直接用首问截断兜底
            )
            return

        # 模型解析成功：首轮起并行标题任务，与下面的召回 + rerank + 流式生成全程重叠。
        if is_first_turn:
            assert fallback_title is not None
            title_task = asyncio.create_task(
                _resolve_title(resolved, recall_req.query, fallback_title, request_id)
            )

        response = await asyncio.wait_for(
            pipeline.execute(recall_req), timeout=_remaining_recall_budget()
        )

        ltr_mode = settings.RECALL_LTR_MODE
        shadow_sampled = ltr_mode == "shadow" and _sample_ltr_shadow(request_id)
        ltr_candidate_hits = response.candidate_hits or response.hits
        content_hits = ltr_candidate_hits if ltr_mode in {"active", "baseline"} else response.hits
        # 正文回填一次：Active/Baseline 读取完整候选；Off/Shadow 主链只读取 serving 窗口。
        contents = (
            await asyncio.wait_for(
                fetch_chunk_contents([h.chunk_id for h in content_hits], recall_req.user_id),
                timeout=_remaining_recall_budget(),
            )
            if content_hits
            else {}
        )

        routes = _ltr_routes(response.route_hits, ltr_candidate_hits, contents)
        ranker = get_initialized_ltr_ranker() if ltr_mode == "active" else None
        ranking_diagnostics = None

        if ltr_mode in {"active", "baseline"}:
            # active 由本地 LTR 取代远程 rerank；模型不可用/异常与 baseline 模式均走
            # 同一份 frozen weighted-score 排序，不发起任何 RERANK 模型调用。
            reranked_hits, ranking_diagnostics = await asyncio.wait_for(
                _ltr_or_baseline_hits(
                    ranker=ranker,
                    query=recall_req.query,
                    routes=routes,
                    contents=contents,
                    candidate_hits=ltr_candidate_hits,
                    top_n=rerank_top_n,
                    request_id=request_id,
                    force_baseline=ltr_mode == "baseline",
                    candidate_contract_version=recall_req.candidate_contract_version,
                    required_sources=recall_req.required_sources or [],
                ),
                timeout=_remaining_recall_budget(),
            )
            rerank_applied = False
        else:
            # off/shadow 阶段保持旧结果，shadow 只记录差异，不增加主链路模型等待。
            rerank_budget = recall_deadline - time.monotonic()
            reranked_hits, rerank_applied = await _rerank_hits(
                reranker,
                recall_req,
                response.hits,
                contents,
                rerank_budget,
                request_id,
                rerank_top_n,
            )
        if shadow_sampled and shadow_recall_req is not None:
            # Shadow 使用独立冻结候选请求；主请求始终保持 off 语义。提交是非阻塞且有界的，
            # 饱和时直接丢弃样本，绝不把后台排队时间施加到 serving 主链。
            get_ltr_shadow_executor().submit(
                lambda: _run_ltr_shadow(
                    pipeline=pipeline,
                    recall_req=shadow_recall_req,
                ),
                request_id=request_id,
                on_success=lambda result: _log_ltr_shadow_success(
                    result,
                    serving_chunk_ids=[hit.chunk_id for hit in reranked_hits],
                    request_id=request_id,
                ),
            )

        # 空命中 / 上下文拼装 / 流式生成（用 rerank 后的最终候选与已回填正文）。
        # token_budget 来自数据集级 recall 配置（LINK-148），透传给生成阶段上下文拼装。
        async for event in _generate_answer(
            resolved,
            reranked_hits,
            rerank_applied,
            ranking_diagnostics,
            contents,
            response.failed_sources,
            recall_req,
            request_id,
            turn_id,
            token_budget,
            conversation_id,
            config_id,
            title_task,
            fallback_title,
            recall_diagnostics=response.recall_diagnostics,
        ):
            yield event
    except RecallValidationError as exc:
        # 正常已在握手前拦截；此处为 pipeline 自身安全网的兜底。
        logger.bind(
            event="recall_validation_failed",
            request_id=request_id,
            user_id=recall_req.user_id,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
        ).info("[recall] validation error request_id={}", request_id)
        yield recall_event("error", {"code": CODE_INVALID_REQUEST, "message": str(exc)})
        await _drain_title_task(title_task)
        await _emit_failed_turn(
            recall_req,
            request_id,
            turn_id,
            conversation_id,
            config_id,
            resolved,
            _elapsed_ms(),
            CODE_INVALID_REQUEST,
            "invalid recall request",
            fallback_title,
        )
    except RecallFatalError as exc:
        # 必备前置缺失（当前：发起用户无默认 EMBEDDING 配置，dense 路无法编码 query）。
        # 须置于 RecallError 之前——RecallFatalError 是其子类。整请求硬失败，不做宽松降级。
        logger.bind(
            event="recall_embedding_config_missing",
            outcome="failed",
            request_id=request_id,
            user_id=recall_req.user_id,
            config_id=config_id,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning("[recall] embedding config missing request_id={}", request_id)
        yield recall_event(
            "error",
            {"code": CODE_EMBEDDING_CONFIG_MISSING, "message": "user embedding config missing"},
        )
        await _drain_title_task(title_task)
        await _emit_failed_turn(
            recall_req,
            request_id,
            turn_id,
            conversation_id,
            config_id,
            resolved,
            _elapsed_ms(),
            CODE_EMBEDDING_CONFIG_MISSING,
            "user embedding config missing",
            fallback_title,
        )
    except RecallError as exc:
        logger.bind(
            event="recall_all_sources_failed",
            outcome="failed",
            request_id=request_id,
            user_id=recall_req.user_id,
            dataset_count=len(getattr(recall_req, "dataset_ids", None) or []),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning("[recall] all sources failed request_id={}", request_id)
        yield recall_event(
            "error", {"code": CODE_ALL_SOURCES_FAILED, "message": "all retrievers failed"}
        )
        await _drain_title_task(title_task)
        await _emit_failed_turn(
            recall_req,
            request_id,
            turn_id,
            conversation_id,
            config_id,
            resolved,
            _elapsed_ms(),
            CODE_ALL_SOURCES_FAILED,
            "all retrievers failed",
            fallback_title,
        )
    except asyncio.TimeoutError:
        logger.warning("[recall] timeout request_id={}", request_id)
        yield recall_event("error", {"code": CODE_TIMEOUT, "message": "recall timeout"})
        await _drain_title_task(title_task)
        await _emit_failed_turn(
            recall_req,
            request_id,
            turn_id,
            conversation_id,
            config_id,
            resolved,
            _elapsed_ms(),
            CODE_TIMEOUT,
            "recall timeout",
            fallback_title,
        )
    except asyncio.CancelledError:
        # 后台生产者任务被取消（仅进程关闭等）；客户端断连不再取消本协程（消费者已解耦）。
        # 任务未完成，不补发终态，向上传播取消；并取消并行标题任务，避免孤儿。
        logger.info("[recall] generation task cancelled request_id={}", request_id)
        if title_task is not None and not title_task.done():
            title_task.cancel()
        raise
    except Exception as exc:  # noqa: BLE001 - 兜底，避免未预期异常泄露堆栈给调用方
        logger.bind(
            event="recall_unexpected_error",
            outcome="failed",
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            user_id=recall_req.user_id,
            config_id=config_id,
            duration_ms=_elapsed_ms(),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).error("[recall] unexpected error request_id={}", request_id)
        yield recall_event("error", {"code": CODE_INTERNAL_ERROR, "message": "internal error"})
        await _drain_title_task(title_task)
        await _emit_failed_turn(
            recall_req,
            request_id,
            turn_id,
            conversation_id,
            config_id,
            resolved,
            _elapsed_ms(),
            CODE_INTERNAL_ERROR,
            "internal error",
            fallback_title,
        )


def _sample_ltr_shadow(request_id: str) -> bool:
    rate = settings.RECALL_LTR_SHADOW_SAMPLE_RATE
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    bucket = int(hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def _ltr_routes(
    route_hits: dict[str, list[RetrieverHit]],
    candidate_hits: list[RecallHit],
    contents: dict[str, str],
) -> dict[str, list[RetrieverHit]]:
    """取得正文完整的分路候选；旧 fake/调用方没有 route_hits 时从 scores 兼容重建。"""
    present = set(contents)
    if route_hits:
        return {
            source: [hit for hit in hits if hit.chunk_id in present]
            for source, hits in route_hits.items()
        }
    reconstructed: dict[str, list[RetrieverHit]] = {}
    for hit in candidate_hits:
        if hit.chunk_id not in present:
            continue
        for source, score in hit.scores.items():
            if score is None:
                continue
            reconstructed.setdefault(source, []).append(
                RetrieverHit(
                    chunk_id=hit.chunk_id,
                    doc_id=hit.doc_id,
                    dataset_id=hit.dataset_id,
                    score=float(score),
                    source=source,
                )
            )
    for hits in reconstructed.values():
        hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return reconstructed


async def _weighted_baseline_ids(
    query: str,
    routes: dict[str, list[RetrieverHit]],
    contents: dict[str, str],
) -> list[str]:
    del query, contents
    return await asyncio.to_thread(weighted_baseline_order, routes)


async def _ltr_or_baseline_hits(
    *,
    ranker,
    query: str,
    routes: dict[str, list[RetrieverHit]],
    contents: dict[str, str],
    candidate_hits: list[RecallHit],
    top_n: int,
    request_id: str,
    force_baseline: bool,
    candidate_contract_version: str | None = None,
    required_sources: list[str] | None = None,
) -> tuple[list[RerankedHit], dict[str, object]]:
    content_hits = {hit.chunk_id: hit for hit in candidate_hits if contents.get(hit.chunk_id)}
    try:
        if not force_baseline and ranker is not None:
            result = await ranker.rank(query=query, routes=routes, candidate_contents=contents)
            ranked_ids = result.ranked_chunk_ids
            mode = result.mode
            model_version = result.model_version
            elapsed_ms = result.elapsed_ms
            reason = result.reason
        else:
            started = time.perf_counter()
            ranked_ids = await _weighted_baseline_ids(query, routes, contents) if routes else []
            elapsed_ms = (time.perf_counter() - started) * 1000
            mode = "fallback_weighted_score"
            model_version = "weighted-score-baseline"
            reason = "baseline_active" if force_baseline else "model_unavailable"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # 特征构造也必须 fail-safe
        ranked_ids = [hit.chunk_id for hit in candidate_hits if contents.get(hit.chunk_id)]
        elapsed_ms = 0.0
        mode = "fallback_fusion_order"
        model_version = "weighted-score-baseline"
        reason = type(exc).__name__

    logger.bind(
        event="recall_ltr_ranked",
        outcome="degraded" if mode.startswith("fallback_") else "succeeded",
        request_id=request_id,
        model_version=model_version,
        rank_mode=mode,
        candidate_count=len(content_hits),
        output_count=min(top_n, len(ranked_ids)),
        duration_ms=round(elapsed_ms, 3),
        reason=reason,
    ).info("[recall] local ranking completed request_id={}", request_id)
    hits = [
        reranked_from_recall(content_hits[chunk_id])
        for chunk_id in ranked_ids
        if chunk_id in content_hits
    ][:top_n]
    diagnostics: dict[str, object] = {
        "strategy": "lambdamart" if mode == "ltr" else "weighted_score",
        "mode": mode,
        "model_version": model_version,
        "candidate_contract_version": candidate_contract_version,
        "candidate_contract_status": (
            "complete" if candidate_contract_version is not None else "not_applicable"
        ),
        "required_sources": list(required_sources or []),
        "actual_sources": list(routes),
        "duration_ms": round(elapsed_ms, 3),
        "reason": reason,
    }
    return hits, diagnostics


def _log_ltr_shadow_success(
    result: LtrRankResult,
    *,
    serving_chunk_ids: list[str],
    request_id: str,
) -> None:
    comparison_k = min(10, len(result.ranked_chunk_ids), len(serving_chunk_ids))
    ltr_top = result.ranked_chunk_ids[:comparison_k]
    serving_top = serving_chunk_ids[:comparison_k]
    overlap = len(set(ltr_top).intersection(serving_top))
    logger.bind(
        event="recall_ltr_shadow_completed",
        outcome="succeeded",
        request_id=request_id,
        model_version=result.model_version,
        rank_mode=result.mode,
        candidate_count=len(result.ranked_chunk_ids),
        serving_count=len(serving_chunk_ids),
        comparison_top_k=comparison_k,
        top10_changed=ltr_top != serving_top,
        top10_overlap=overlap,
        duration_ms=round(result.elapsed_ms, 3),
        reason=result.reason,
    ).info("[recall] LambdaMART shadow completed request_id={}", request_id)


async def _run_ltr_shadow(
    *,
    pipeline: RecallPipeline,
    recall_req: RecallRequest,
) -> LtrRankResult:
    """独立执行冻结候选召回、正文读取和排序；总超时由有界执行器统一控制。"""
    ranker = get_initialized_ltr_ranker()
    if ranker is None:
        raise RuntimeError("LambdaMART shadow model unavailable")
    response = await pipeline.execute(recall_req)
    candidate_hits = response.candidate_hits or response.hits
    contents = await fetch_chunk_contents(
        [hit.chunk_id for hit in candidate_hits], recall_req.user_id
    )
    routes = _ltr_routes(response.route_hits, candidate_hits, contents)
    if not routes:
        raise RuntimeError("LambdaMART shadow has no candidates with content")
    return await ranker.rank(query=recall_req.query, routes=routes, candidate_contents=contents)


async def _rerank_hits(
    reranker: PostRecallReranker,
    recall_req: RecallRequest,
    fusion_hits: list[RecallHit],
    contents: dict[str, str],
    timeout_s: float,
    request_id: str,
    top_n: int,
) -> tuple[list[RerankedHit], bool]:
    """对融合候选执行 rerank 精排，返回 ``(最终候选, rerank_applied)``。

    ``top_n`` 为重排后返回条数上限，来自数据集级 ``recall_config.rerank_top_n``
    （无数据集配置时为系统默认 ``RERANK_DEFAULT_TOP_N``）。

    rerank 是 best-effort 增强：**已知不可用情形降级为当前融合顺序**，保证 ``rag/stream``
    不因 rerank 不可用而整条失败。降级口径与 reranker 软降级
    一致：复用 ``degrade_to_fusion_order`` 对**有正文候选**截断到 ``top_n``，
    确保无论走哪条降级路，喂给下游的片段集合与数量一致。

    降级覆盖：
    - 软降级（模型调用失败 / 返回不可用）：reranker 内部已返回当前融合顺序候选且
      ``rerank_applied=False``，原样透出；
    - provider 不可用、rerank 超时、预算耗尽：此处兜底降级。

    只 catch 已知运维失败；其它未预期异常**向上抛**，由顶层收敛为 ``INTERNAL_ERROR``
    （带堆栈），不被静默吞成"降级"而掩盖真实缺陷。``CancelledError``（客户端断连）向上传播。
    """

    def _degrade() -> tuple[list[RerankedHit], bool]:
        scored = [h for h in fusion_hits if contents.get(h.chunk_id)]
        return degrade_to_fusion_order(scored, top_n), False

    # 预算（共享流超时的剩余部分）已耗尽：不再发起 rerank，直接降级。
    if timeout_s <= 0:
        logger.info(
            "[recall] no budget left for rerank, fallback to fusion order request_id={}",
            request_id,
        )
        return _degrade()

    contexts = recall_req.dataset_contexts or {}
    if not any(ctx.config.recall.enable_rerank for ctx in contexts.values()):
        return _degrade()

    try:
        resp = await asyncio.wait_for(
            reranker.rerank(
                RerankRequest(
                    query=recall_req.query,
                    user_id=recall_req.user_id,
                    hits=fusion_hits,
                    top_n=top_n,
                    contents=contents,
                    dataset_contexts=recall_req.dataset_contexts,
                )
            ),
            timeout=timeout_s,
        )
        return resp.hits, resp.rerank_applied
    except asyncio.CancelledError:
        raise
    except (LLMConfigResolutionError, ValueError, asyncio.TimeoutError) as exc:
        logger.bind(
            event="recall_rerank_unavailable",
            outcome="degraded",
            request_id=request_id,
            user_id=recall_req.user_id,
            candidate_count=len(fusion_hits),
            top_n=top_n,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).info(
            "[recall] rerank unavailable, fallback to fusion order request_id={}",
            request_id,
        )
        return _degrade()


async def _generate_answer(
    resolved,
    hits: list[RerankedHit],
    rerank_applied: bool,
    ranking_diagnostics: dict[str, object] | None,
    contents: dict[str, str],
    failed_sources: list[str],
    recall_req: RecallRequest,
    request_id: str,
    turn_id: str,
    token_budget: int,
    conversation_id: int,
    config_id: int,
    title_task: asyncio.Task | None,
    fallback_title: str | None,
    recall_diagnostics: RecallDiagnostics | None = None,
) -> AsyncGenerator[str, None]:
    """生成模式后续：空命中判定 → 上下文拼装 → 流式生成 → 对话轮次落库通知。

    入参 ``hits`` 是 rerank 后的最终候选（降级时为当前融合顺序），``contents`` 是上游一次性
    回填的正文（rerank 与生成共用，不在此重复查库）。上下文拼装与 ``answer_done`` /
    ``recall_done`` 回报均以 ``hits`` 为准；``rerank_applied`` 原样透出。

    首轮标题（``title_task is not None`` 即首轮）：标题任务已在上游与召回+生成并行起跑。
    本函数在流式吐字过程中一旦发现任务完成即插发 ``conversation_title`` 事件（不等答案结束），
    成功终态再补发未发出的标题；标题随 COMPLETED 的 ``chat_turn.title`` 落库。生成失败终态
    用首问截断 ``fallback_title`` 落库（方案 A：失败首轮也命名会话），不发 SSE 标题事件。
    非首轮 ``title_task`` / ``fallback_title`` 均为 None，标题相关分支全部跳过。

    落库终态（chat-stream-resilient-persist，均携起点同一 ``turn_id``，Java upsert 同一行）：
    - 0 命中 / 全部片段缺正文 → ``recall_done`` + ``COMPLETED``（空 answer 占位）；
    - 正常结束 → ``answer_done`` + ``COMPLETED``（完整 answer/usage/references）；
    - 生成异常 → ``error`` GENERATION_FAILED + ``FAILED``（``error_code=RECALL_GENERATION_FAILED``）；
    - 生成超时 → ``error`` + ``FAILED``（``error_code=GENERATION_TIMEOUT``，保留半截 answer）。

    生成阶段独立超时（``RECALL_GENERATION_TIMEOUT_MS``）：后台续跑下连接断开不再兜底，
    需独立超时防孤儿任务无限烧 token。按 deadline 在帧间检查（帧内卡死由 provider httpx
    超时兜底）。``partial`` 状态已退役——断连不取消任务，正常跑到 COMPLETED。
    """

    def _with_recall_diagnostics(payload: dict) -> dict:
        if recall_diagnostics is not None:
            payload["recall_diagnostics"] = serialize_recall_diagnostics(recall_diagnostics)
        if ranking_diagnostics is not None:
            payload["ranking_diagnostics"] = ranking_diagnostics
        return payload

    # 空命中：不生成，但仍落 COMPLETED 占位行（前端按空内容展示占位）。标题必须先于
    # recall_done 发出，保证 recall_done 作为真正终态后不再有业务事件。
    if not hits:
        title = await _await_title_result(title_task, fallback_title)
        if title:
            yield recall_event("conversation_title", {"title": title})
        yield recall_event(
            "recall_done",
            _with_recall_diagnostics(
                {"hits": [], "rerank_applied": rerank_applied, "failed_sources": failed_sources}
            ),
        )
        await _emit_chat_turn(
            recall_req=recall_req,
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            config_id=int(config_id),
            resolved=resolved,
            answer="",
            usage=UsageInfo(),
            references=[],
            latency_ms=0,
            status="COMPLETED",
            title=title,
        )
        return

    # 上下文拼装（正文已在上游一次性回填，按 rerank 后顺序纳入）。
    # token_budget 为数据集级 recall 配置（LINK-148），无数据集配置时由上游填入系统默认。
    assembled = assemble_context(hits, contents, token_budget)
    logger.info(
        "[recall] generation context request_id={} rerank_applied={} hits={} blocks={} skipped_no_content={} truncated={}",
        request_id,
        rerank_applied,
        len(hits),
        len(assembled.blocks),
        assembled.skipped_no_content,
        assembled.truncated,
    )

    # 全部片段缺正文：按空命中处理，不生成，同样落 COMPLETED 占位。
    if not assembled.blocks:
        title = await _await_title_result(title_task, fallback_title)
        if title:
            yield recall_event("conversation_title", {"title": title})
        yield recall_event(
            "recall_done",
            _with_recall_diagnostics(
                {
                    "hits": serialize_reranked_hits(hits, contents),
                    "rerank_applied": rerank_applied,
                    "failed_sources": failed_sources,
                }
            ),
        )
        await _emit_chat_turn(
            recall_req=recall_req,
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            config_id=int(config_id),
            resolved=resolved,
            answer="",
            usage=UsageInfo(),
            references=[],
            latency_ms=0,
            status="COMPLETED",
            title=title,
        )
        return

    # 流式生成：生成阶段失败即整请求失败。
    # references 取 rerank 后最终候选的 chunk_id（仅标识，不含正文），随各终态一起上报。
    user_prompt = build_rag_user_prompt(recall_req.query, assembled.context_text)
    answer_parts: list[str] = []
    usage = UsageInfo()  # 流式 usage 通常挂在末帧；超时未收到时维持 0
    references = [h.chunk_id for h in hits]
    gen_started = time.perf_counter()
    gen_deadline = time.monotonic() + settings.RECALL_GENERATION_TIMEOUT_MS / 1000
    # 首轮标题：并行任务完成即在吐字间隙插发，记下已发标题供终态落库与失败兜底复用。
    sent_title: str | None = None

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - gen_started) * 1000)

    try:
        async for chunk in resolved.provider.stream(
            prompt=user_prompt,
            system_prompt=RAG_GENERATION_SYSTEM_PROMPT,
        ):
            # 生成阶段独立超时：帧间检查 deadline，超过即终止落 FAILED+GENERATION_TIMEOUT。
            if time.monotonic() > gen_deadline:
                raise asyncio.TimeoutError
            if chunk.delta:
                answer_parts.append(chunk.delta)
                yield recall_event("answer_delta", {"text": chunk.delta})
            if chunk.usage is not None:
                usage = chunk.usage
            # 标题已并行算好则尽早插发（不等答案结束），让侧栏在吐字过程中即时刷新。
            if title_task is not None and sent_title is None and title_task.done():
                try:
                    sent_title = title_task.result() or fallback_title
                except Exception:  # noqa: BLE001 - 任务体已兜底，防御
                    sent_title = fallback_title
                if sent_title:
                    yield recall_event("conversation_title", {"title": sent_title})
    except asyncio.TimeoutError:
        # 生成超时：保留半截答案，落 FAILED + GENERATION_TIMEOUT。
        logger.warning("[recall] generation timeout request_id={}", request_id)
        yield recall_event(
            "error",
            {"code": CODE_GENERATION_FAILED, "message": "answer generation timeout"},
        )
        await _drain_title_task(title_task)
        await _emit_chat_turn(
            recall_req=recall_req,
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            config_id=config_id,
            resolved=resolved,
            answer="".join(answer_parts),
            usage=usage,
            references=references,
            latency_ms=_elapsed_ms(),
            status="FAILED",
            error_code="GENERATION_TIMEOUT",
            error_message="answer generation timeout",
            title=sent_title or fallback_title,
        )
        return
    except Exception as exc:  # noqa: BLE001 - 生成失败统一收敛为 GENERATION_FAILED
        logger.bind(
            event="recall_generation_failed",
            outcome="failed",
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            user_id=recall_req.user_id,
            dataset_count=len(getattr(recall_req, "dataset_ids", None) or []),
            config_id=config_id,
            provider_type=getattr(resolved, "provider_type", "") or "",
            model_name=getattr(resolved, "model_name", "") or "",
            duration_ms=_elapsed_ms(),
            partial_answer_chars=sum(len(part) for part in answer_parts),
            reference_count=len(references),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).error(
            "[recall] generation failed request_id={} turn_id={} user_id={}",
            request_id,
            turn_id,
            recall_req.user_id,
        )
        yield recall_event(
            "error",
            {"code": CODE_GENERATION_FAILED, "message": "answer generation failed"},
        )
        await _drain_title_task(title_task)
        await _emit_chat_turn(
            recall_req=recall_req,
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            config_id=config_id,
            resolved=resolved,
            answer="".join(answer_parts),
            usage=usage,
            references=references,
            latency_ms=_elapsed_ms(),
            status="FAILED",
            error_code=CODE_GENERATION_FAILED,
            error_message="answer generation failed",
            title=sent_title or fallback_title,
        )
        return

    # 首轮标题：吐字期间已发则复用 sent_title；否则（LLM 比答案慢）在终态前等待并补发。
    # answer_done 必须是最后一帧业务事件，便于消费者收到后立即清除“回复中”状态。
    title = sent_title
    if title_task is not None and title is None:
        title = await _await_title_result(title_task, fallback_title)
        if title:
            yield recall_event("conversation_title", {"title": title})

    # 正常结束：answer_done 附 usage，随后发 COMPLETED 轮次消息（在 SSE 终态之后）。
    yield recall_event(
        "answer_done",
        _with_recall_diagnostics(
            {
                "answer": "".join(answer_parts),
                "usage": usage.model_dump(),
                "hits": serialize_reranked_hits(hits, contents),
                "rerank_applied": rerank_applied,
                "failed_sources": failed_sources,
            }
        ),
    )
    await _emit_chat_turn(
        recall_req=recall_req,
        request_id=request_id,
        turn_id=turn_id,
        conversation_id=conversation_id,
        config_id=config_id,
        resolved=resolved,
        answer="".join(answer_parts),
        usage=usage,
        references=references,
        latency_ms=_elapsed_ms(),
        status="COMPLETED",
        title=title,
    )


async def _emit_failed_turn(
    recall_req: RecallRequest,
    request_id: str,
    turn_id: str,
    conversation_id: int,
    config_id: int,
    resolved,
    latency_ms: int,
    error_code: str,
    error_message: str,
    title: str | None = None,
) -> None:
    """前置失败终态的 FAILED 落库便捷封装（answer/usage/references 均空）。

    ``title`` 仅首轮非空（首问截断兜底），让失败首轮也命名会话；非首轮为 None。
    """
    await _emit_chat_turn(
        recall_req=recall_req,
        request_id=request_id,
        turn_id=turn_id,
        conversation_id=conversation_id,
        config_id=config_id,
        resolved=resolved,
        answer="",
        usage=UsageInfo(),
        references=[],
        latency_ms=latency_ms,
        status="FAILED",
        error_code=error_code,
        error_message=error_message,
        title=title,
    )


async def _emit_chat_turn(
    *,
    recall_req: RecallRequest,
    request_id: str,
    turn_id: str,
    conversation_id: int,
    config_id: int,
    resolved,
    answer: str,
    usage: UsageInfo,
    references: list[str],
    latency_ms: int,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    title: str | None = None,
) -> None:
    """构造并发送对话轮次消息 + generate token 用量（两者解耦，LINK-191）。

    起点 GENERATING / 各终态均经此发送，``turn_id`` 贯穿同一轮供 Java upsert 同一行。
    后续终态补齐。chat_turn 只承载对话内容（**不含 token**）；本轮 generate 的 token 用量另走
    统一 ``TokenUsageMessage``（stage='chat'、operation='generate'，LINK-191）。``title`` 仅会话
    首轮终态非空（Python 基于 query 生成或首问截断兜底），GENERATING / 非首轮为 None，Java 仅在
    标题空/默认时落库。三者均最终一致、不进关键路径：chat_turn 发送失败仅告警，用量上报旁路
    fire-and-forget，标题为增强项失败回落兜底。
    """
    try:
        msg = ChatTurnMessage.build(
            conversation_id=conversation_id,
            request_id=request_id,
            turn_id=turn_id,
            user_id=recall_req.user_id,
            query=recall_req.query,
            answer=answer,
            config_id=int(config_id),
            provider_type=resolved.provider_type if resolved is not None else "",
            model_name=(resolved.model_name or "") if resolved is not None else "",
            status=status,
            references=references,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            title=title,
        )
        await MQService().send(msg)
    except Exception as exc:  # noqa: BLE001 - 落库通知失败不影响问答主流程
        logger.bind(
            event="chat_turn_emit_failed",
            outcome="skipped",
            request_id=request_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            user_id=recall_req.user_id,
            status=status,
            config_id=config_id,
            provider_type=resolved.provider_type if resolved is not None else "",
            model_name=(resolved.model_name or "") if resolved is not None else "",
            answer_chars=len(answer),
            reference_count=len(references),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning(
            "[recall] chat_turn emit failed request_id={} turn_id={} status={}",
            request_id,
            turn_id,
            status,
        )

    # generate token 用量统一上报（旁路、非阻塞）：与 chat_turn 解耦，发送独立于上面的落库通知。
    # GENERATING 起点与各失败前置态 usage 维持 0（且 resolved 可能为 None），跳过避免落空行。
    if usage.total_tokens > 0 and resolved is not None:
        report_usage_nowait(
            user_id=recall_req.user_id,
            provider_type=resolved.provider_type,
            model_name=resolved.model_name or "",
            stage="chat",
            operation="generate",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            config_id=int(config_id),
            latency_ms=latency_ms,
            # chat_turn 的 GENERATING/COMPLETED/FAILED 映射到用量口径的 success/failed。
            status="failed" if status == "FAILED" else "success",
        )
