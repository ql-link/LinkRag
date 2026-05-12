# -*- coding: utf-8 -*-
"""
EvaluationRunner — 核心编排器。

特性（对应架构文档 7.4）：
- 故障隔离：单 evaluable / 单 sample 失败不打断整体，计入 success=False
- 超时保护：timeout_per_sample_s 防止卡死（asyncio.wait_for）
- 并发：sample 维度通过 asyncio.Semaphore(parallelism) 控制
- 重试：仅对"评估自身错误"（IO / 序列化异常）重试，业务异常直接如实计入
- 趋势对比：Reporter 自动加载上次 baseline，输出 delta 列
- Hook 广播：关键节点广播 EvalEvent
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from src.evaluation.adapters.registry import EvaluableRegistry
from src.evaluation.artifacts.top3_archiver import Top3Archiver
from src.evaluation.contracts.hook import (
    EvalEvent, EVENT_RUN_START, EVENT_STAGE_START,
    EVENT_SAMPLE_DONE, EVENT_STAGE_DONE, EVENT_RUN_COMPLETE, EVENT_ERROR,
)
from src.evaluation.contracts.store import EvalRun, EvalRunSummary
from src.evaluation.evaluators.parser_evaluator import ParserEvaluator
from src.evaluation.evaluators.chunker_evaluator import ChunkerEvaluator
from src.evaluation.metrics.registry import MetricRegistry
from src.evaluation.runners.context import RunContext
from src.evaluation.runners.pipeline import EvalPipeline

if TYPE_CHECKING:
    from src.evaluation.contracts.dataset import EvalDataset, EvalSample
    from src.evaluation.contracts.store import ResultStore
    from src.evaluation.contracts.hook import Hook
    from src.evaluation.reporters.base import BaseReporter

logger = logging.getLogger("evaluation.runner")

# evaluable scope → Evaluator 类映射（新增 scope 在此注册即可）
_EVALUATOR_MAP = {
    "parse": ParserEvaluator,
    "chunk": ChunkerEvaluator,
}


class EvaluationRunner:
    """评估框架核心编排器。

    负责：
    1. 加载 dataset + pipeline 配置
    2. pipeline.validate() 前置校验
    3. 并发跑 sample（Semaphore 控制并发度）
    4. 广播 EvalEvent 给所有 Hook
    5. 调用 Evaluator 两阶段指标计算
    6. 通过 ResultStore 持久化
    7. 通过 Reporter 渲染报告（可选）
    """

    def __init__(
        self,
        pipeline: EvalPipeline,
        dataset: "EvalDataset",
        store: "ResultStore",
        reporters: list["BaseReporter"] | None = None,
        hooks: list["Hook"] | None = None,
        metric_registry: MetricRegistry | None = None,
    ) -> None:
        """初始化 EvaluationRunner。

        Args:
            pipeline:        已加载的 EvalPipeline 配置。
            dataset:         评估数据集。
            store:           结果持久化 Store。
            reporters:       报告渲染器列表（可选）。
            hooks:           事件钩子列表（可选）。
            metric_registry: 指标注册表（None 时使用全局注册表）。
        """
        self.pipeline = pipeline
        self.dataset = dataset
        self.store = store
        self.reporters = reporters or []
        self.hooks = hooks or []
        self._metric_registry = metric_registry or MetricRegistry

    async def run(self) -> EvalRun:
        """执行完整评估流程。

        Returns:
            EvalRun: 包含所有 metrics 结果的完整运行记录。
        """
        run_id = str(uuid.uuid4())
        t_start = time.perf_counter()

        # 前置校验
        self.pipeline.validate(
            registry=EvaluableRegistry,
            metric_registry=self._metric_registry,
        )

        # 过滤指标注册表（按 YAML metrics.include / exclude）
        registry = self._metric_registry.filter_by_glob(
            include=self.pipeline.metrics.include,
            exclude=self.pipeline.metrics.exclude or None,
        )

        # 初始化运行记录
        run_summary = EvalRunSummary(
            run_id=run_id,
            dataset_name=self.dataset.name,
            pipeline_config=str(self.pipeline.stages),
            status="running",
            sample_count=self.dataset.sample_count,
        )
        eval_run = EvalRun(summary=run_summary)

        await self._broadcast(EvalEvent(
            event_type=EVENT_RUN_START,
            payload={
                "run_id": run_id,
                "dataset_name": self.dataset.name,
                "sample_count": self.dataset.sample_count,
            },
        ))

        # 按拓扑顺序确定 stage 执行顺序
        ordered_stages = self.pipeline.topological_order()

        # 并发控制：sample 维度 Semaphore
        parallelism = self.pipeline.runner_cfg.parallelism
        semaphore = asyncio.Semaphore(parallelism)

        # {stage_name: {evaluable_name: list[StageOutput]}}（按 sample 顺序）
        all_stage_outputs: dict[str, dict[str, list]] = {
            s.stage: {} for s in ordered_stages
        }

        samples = list(self.dataset.iter_samples())

        # 逐 sample 并发执行所有 stages
        tasks = [
            self._run_sample(
                sample=sample,
                ordered_stages=ordered_stages,
                all_stage_outputs=all_stage_outputs,
                run_id=run_id,
                semaphore=semaphore,
            )
            for sample in samples
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        _sort_outputs_by_sample_order(all_stage_outputs, samples)

        run_summary.success_count = sum(
            1 for stage_outs in all_stage_outputs.values()
            for ev_outs in stage_outs.values()
            for out in ev_outs
            if out.success
        )

        # 两阶段指标计算（所有 sample 完成后）
        all_metric_results: list[dict] = []
        for stage_cfg in ordered_stages:
            await self._broadcast(EvalEvent(
                event_type=EVENT_STAGE_DONE,
                payload={"run_id": run_id, "stage": stage_cfg.stage},
            ))

            evaluator_cls = _EVALUATOR_MAP.get(stage_cfg.stage)
            if evaluator_cls is None:
                logger.warning("未找到 stage '%s' 对应的 Evaluator，跳过指标计算", stage_cfg.stage)
                continue

            evaluator = evaluator_cls()
            stage_result = evaluator.evaluate(
                outputs_by_evaluable=all_stage_outputs[stage_cfg.stage],
                samples=samples,
                registry=registry,
            )

            eval_run.extra[f"stage_result.{stage_cfg.stage}"] = stage_result.to_dict()
            for mr in stage_result.all_results():
                all_metric_results.append({
                    "metric_id": mr.metric_id,
                    "value": mr.value,
                    "detail": mr.detail,
                })

        eval_run.metrics = all_metric_results
        eval_run.sample_outputs = _serialize_stage_outputs(all_stage_outputs)
        await self._save_parsed_results(eval_run, all_stage_outputs, samples)
        if "parse" in all_stage_outputs and hasattr(self.store, "save_artifact"):
            eval_run.extra["archives"] = await Top3Archiver().archive(
                run=eval_run,
                samples=samples,
                outputs_by_evaluable=all_stage_outputs["parse"],
                store=self.store,
            )
        run_summary.status = "done"

        # 趋势对比：保存当前 run 前加载 baseline，避免把本次运行当作自己的基准。
        baseline = await self.store.load_baseline(self.dataset.name)

        # 渲染报告
        report_outputs: list[str] = []
        for reporter in self.reporters:
            try:
                if hasattr(self.store, "save_report"):
                    content, format_name, content_type = reporter.render_bytes(
                        eval_run,
                        baseline=baseline,
                    )
                    report_key = await self.store.save_report(
                        self.dataset.name,
                        run_id,
                        format_name,
                        content,
                        content_type,
                    )
                    report_outputs.append(f"{getattr(self.store, 'bucket', '')}/{report_key}".lstrip("/"))
                else:
                    report_outputs.append(reporter.render(eval_run, baseline=baseline))
            except Exception as exc:
                logger.error("Reporter %s 渲染失败: %s", type(reporter).__name__, exc)
        if report_outputs:
            eval_run.extra["reports"] = report_outputs

        await self.store.save_run(eval_run)

        elapsed = round(time.perf_counter() - t_start, 2)
        await self._broadcast(EvalEvent(
            event_type=EVENT_RUN_COMPLETE,
            payload={
                "run_id": run_id,
                "total_samples": len(samples),
                "elapsed_s": elapsed,
            },
        ))

        return eval_run

    async def _run_sample(
        self,
        sample: "EvalSample",
        ordered_stages: list,
        all_stage_outputs: dict,
        run_id: str,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """单个 sample 的完整 stage 执行流程（并发安全）。

        Args:
            sample:            当前样本。
            ordered_stages:    拓扑排序后的 stage 列表。
            all_stage_outputs: 全局输出收集字典（写入时需加锁或使用单协程 append）。
            run_id:            当前运行 ID。
            semaphore:         并发控制 Semaphore。
        """
        async with semaphore:
            ctx = RunContext(sample)

            for stage_cfg in ordered_stages:
                await self._broadcast(EvalEvent(
                    event_type=EVENT_STAGE_START,
                    payload={
                        "run_id": run_id,
                        "stage": stage_cfg.stage,
                        "sample_id": sample.sample_id,
                        "evaluable_count": len(stage_cfg.evaluables),
                    },
                ))

                for evaluable_name in stage_cfg.evaluables:
                    # 初始化该 evaluable 的输出列表（首次写入）
                    if evaluable_name not in all_stage_outputs[stage_cfg.stage]:
                        all_stage_outputs[stage_cfg.stage][evaluable_name] = []

                    runs_per_sample = self.pipeline.runner_cfg.runs_per_sample
                    timeout_s = self.pipeline.runner_cfg.timeout_per_sample_s

                    last_output = None
                    for run_idx in range(runs_per_sample):
                        stage_input = ctx.build_stage_input(stage_cfg, evaluable_name, run_idx)
                        try:
                            evaluable = EvaluableRegistry.get(evaluable_name)
                            last_output = await asyncio.wait_for(
                                evaluable.run(stage_input),
                                timeout=timeout_s,
                            )
                        except asyncio.TimeoutError:
                            from src.evaluation.contracts.evaluable import StageOutput
                            last_output = StageOutput(
                                sample_id=sample.sample_id,
                                payload=None,
                                elapsed_ms=timeout_s * 1000.0,
                                success=False,
                                error=f"超时（>{timeout_s}s）",
                                error_type="TimeoutError",
                            )
                        except Exception as exc:
                            from src.evaluation.contracts.evaluable import StageOutput
                            last_output = StageOutput(
                                sample_id=sample.sample_id,
                                payload=None,
                                elapsed_ms=0.0,
                                success=False,
                                error=str(exc),
                                error_type=type(exc).__name__,
                            )

                        ctx.put(stage_cfg.stage, evaluable_name, last_output)

                    # 仅保留最后一轮输出用于指标计算（多轮稳定性由专用指标处理）
                    if last_output is not None:
                        last_output.extras.setdefault("sample", {
                            "file_type": sample.file_type,
                            "tags": sample.tags,
                            "extra": sample.extra,
                        })
                        all_stage_outputs[stage_cfg.stage][evaluable_name].append(last_output)

                    await self._broadcast(EvalEvent(
                        event_type=EVENT_SAMPLE_DONE,
                        payload={
                            "run_id": run_id,
                            "stage": stage_cfg.stage,
                            "sample_id": sample.sample_id,
                            "evaluable": evaluable_name,
                            "success": last_output.success if last_output else False,
                            "elapsed_ms": last_output.elapsed_ms if last_output else 0.0,
                        },
                    ))

    async def _broadcast(self, event: EvalEvent) -> None:
        """向所有 Hook 广播事件；单个 Hook 异常不影响整体。

        Args:
            event: 要广播的评估事件。
        """
        for hook in self.hooks:
            try:
                await hook.on_event(event)
            except Exception as exc:
                logger.warning("Hook %s 处理事件 %s 异常: %s", type(hook).__name__, event.event_type, exc)

    async def _save_parsed_results(
        self,
        eval_run: EvalRun,
        all_stage_outputs: dict,
        samples: list["EvalSample"],
    ) -> None:
        if not hasattr(self.store, "save_parsed_result"):
            return
        parse_outputs = all_stage_outputs.get("parse", {})
        errors: list[dict] = []
        refs: list[dict] = []
        sample_by_id = {sample.sample_id: sample for sample in samples}
        for evaluable_name, outputs in parse_outputs.items():
            for output in outputs:
                if not output.success or not isinstance(output.payload, str):
                    continue
                try:
                    saved = await self.store.save_parsed_result(
                        eval_run.summary.dataset_name,
                        eval_run.summary.run_id,
                        output.sample_id,
                        evaluable_name,
                        output.payload,
                        {
                            "sample_id": output.sample_id,
                            "evaluable_name": evaluable_name,
                            "elapsed_ms": output.elapsed_ms,
                            "metadata": output.extras.get("metadata", {}),
                            "sample": output.extras.get("sample", {}),
                            "source_ref": (
                                sample_by_id[output.sample_id].remote_file.key
                                if output.sample_id in sample_by_id and sample_by_id[output.sample_id].remote_file
                                else None
                            ),
                        },
                    )
                    refs.append({
                        "sample_id": output.sample_id,
                        "evaluable_name": evaluable_name,
                        **saved,
                    })
                except Exception as exc:
                    errors.append({
                        "sample_id": output.sample_id,
                        "evaluable_name": evaluable_name,
                        "error": str(exc),
                    })
        eval_run.extra["parsed_results"] = refs
        if errors:
            eval_run.extra["parsed_result_errors"] = errors


def _sort_outputs_by_sample_order(all_stage_outputs: dict, samples: list["EvalSample"]) -> None:
    order = {sample.sample_id: index for index, sample in enumerate(samples)}
    for stage_outputs in all_stage_outputs.values():
        for evaluable_name, outputs in stage_outputs.items():
            stage_outputs[evaluable_name] = sorted(
                outputs,
                key=lambda output: order.get(output.sample_id, len(order)),
            )


def _serialize_stage_outputs(all_stage_outputs: dict) -> list[dict]:
    serialized: list[dict] = []
    for stage_name, outputs_by_evaluable in all_stage_outputs.items():
        for evaluable_name, outputs in outputs_by_evaluable.items():
            for output in outputs:
                serialized.append({
                    "stage": stage_name,
                    "evaluable_name": evaluable_name,
                    "sample_id": output.sample_id,
                    "elapsed_ms": output.elapsed_ms,
                    "success": output.success,
                    "error": output.error,
                    "error_type": output.error_type,
                    "payload_preview": (
                        output.payload[:500]
                        if isinstance(output.payload, str)
                        else None
                    ),
                    "extras": output.extras,
                })
    return serialized
