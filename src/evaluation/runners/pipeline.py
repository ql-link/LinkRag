# -*- coding: utf-8 -*-
"""
EvalPipeline — 可声明的 DAG + 前置校验。

通过 YAML 或代码构造 Pipeline，Runner 执行前调用 validate() 做：
  1. stage 拓扑无环、依赖存在
  2. 所有 evaluable name 已在 Registry 注册
  3. input_from 引用的 stage 在 DAG 上游
  4. metrics include/exclude glob 至少匹配到一个已注册指标

校验失败直接抛 PipelineConfigError，避免跑到一半才发现配置错误。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


class PipelineConfigError(Exception):
    """Pipeline 配置校验失败时抛出的异常。"""


@dataclass
class StageConfig:
    """单个 stage 的配置。

    Attributes:
        stage:             stage 名称，如 "parse" / "chunk"。
        evaluables:        本 stage 注册的 evaluable name 列表。
        depends_on:        依赖的上游 stage 名称列表（DAG 边）。
        input_from:        优先从哪个 stage 取输入 payload（优先上游增强产物）。
        fallback_input_from: input_from stage 失败/跳过时的降级数据源 stage。
        optional:          若为 True，本 stage 失败不影响下游。
    """
    stage: str
    evaluables: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    input_from: str | None = None
    fallback_input_from: str | None = None
    optional: bool = False


@dataclass
class MetricsConfig:
    """Pipeline 中指标过滤配置。"""
    include: list[str] = field(default_factory=lambda: ["*"])
    exclude: list[str] = field(default_factory=list)


@dataclass
class RunnerConfig:
    """Runner 级别运行控制配置。"""
    runs_per_sample: int = 1
    timeout_per_sample_s: int = 120
    max_memory_mb: int = 2048
    parallelism: int = 4
    retry_eval_errors: int = 2


@dataclass
class ReportConfig:
    """报告输出配置。"""
    formats: list[str] = field(default_factory=lambda: ["json"])
    output_dir: str = "./docs/evaluation_reports"
    baseline: str = "auto"


class EvalPipeline:
    """可声明的评估 DAG。

    支持从 YAML 文件加载，也支持代码直接构造（测试场景）。

    Attributes:
        dataset_name:  数据集名称。
        stages:        stage 配置列表（按 DAG 声明顺序）。
        metrics:       指标过滤配置。
        runner_cfg:    Runner 运行控制配置。
        report_cfg:    报告输出配置。
        hooks:         Hook 名称列表。
    """

    def __init__(
        self,
        dataset_name: str,
        stages: list[StageConfig],
        dataset_version: str | None = None,
        dataset_split: str | None = None,
        metrics: MetricsConfig | None = None,
        runner_cfg: RunnerConfig | None = None,
        report_cfg: ReportConfig | None = None,
        hooks: list[str] | None = None,
    ) -> None:
        self.dataset_name = dataset_name
        self.dataset_version = dataset_version
        self.dataset_split = dataset_split
        self.stages = stages
        self.metrics = metrics or MetricsConfig()
        self.runner_cfg = runner_cfg or RunnerConfig()
        self.report_cfg = report_cfg or ReportConfig()
        self.hooks = hooks or ["logging"]

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "EvalPipeline":
        """从 YAML 文件加载 Pipeline 配置。

        Args:
            yaml_path: Pipeline YAML 文件路径。

        Returns:
            EvalPipeline: 解析后的 Pipeline 对象。

        Raises:
            FileNotFoundError: YAML 文件不存在。
            PipelineConfigError: YAML 格式或字段错误。
        """
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Pipeline YAML 不存在: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f)

        if "dataset" not in raw:
            raise PipelineConfigError("Pipeline YAML 缺少 'dataset' 字段")
        if "stages" not in raw:
            raise PipelineConfigError("Pipeline YAML 缺少 'stages' 字段")

        stages: list[StageConfig] = []
        for s in raw["stages"]:
            dep = s.get("depends_on", [])
            if isinstance(dep, str):
                dep = [dep]
            stages.append(StageConfig(
                stage=s["stage"],
                evaluables=s.get("evaluables", []),
                depends_on=dep,
                input_from=s.get("input_from"),
                fallback_input_from=s.get("fallback_input_from"),
                optional=s.get("optional", False),
            ))

        raw_metrics = raw.get("metrics", {})
        metrics = MetricsConfig(
            include=raw_metrics.get("include", ["*"]),
            exclude=raw_metrics.get("exclude", []),
        )

        raw_runner = raw.get("runner", {})
        runner_cfg = RunnerConfig(
            runs_per_sample=raw_runner.get("runs_per_sample", 1),
            timeout_per_sample_s=raw_runner.get("timeout_per_sample_s", 120),
            max_memory_mb=raw_runner.get("max_memory_mb", 2048),
            parallelism=raw_runner.get("parallelism", 4),
            retry_eval_errors=raw_runner.get("retry_eval_errors", 2),
        )

        raw_report = raw.get("report", {})
        report_cfg = ReportConfig(
            formats=raw_report.get("formats", ["json"]),
            output_dir=raw_report.get("output_dir", "./docs/evaluation_reports"),
            baseline=raw_report.get("baseline", "auto"),
        )

        return cls(
            dataset_name=raw["dataset"],
            dataset_version=raw.get("dataset_version"),
            dataset_split=raw.get("split"),
            stages=stages,
            metrics=metrics,
            runner_cfg=runner_cfg,
            report_cfg=report_cfg,
            hooks=raw.get("hooks", ["logging"]),
        )

    def topological_order(self) -> list[StageConfig]:
        """按 DAG 拓扑顺序返回 stage 列表（Kahn 算法）。O(V+E)。

        Returns:
            list[StageConfig]: 拓扑排序后的 stage 列表。

        Raises:
            PipelineConfigError: DAG 有环时抛出。
        """
        stage_map = {s.stage: s for s in self.stages}
        in_degree = {s.stage: len(s.depends_on) for s in self.stages}
        queue = [s.stage for s, deg in zip(self.stages, in_degree.values()) if deg == 0]
        result: list[StageConfig] = []

        while queue:
            cur = queue.pop(0)
            result.append(stage_map[cur])
            for s in self.stages:
                if cur in s.depends_on:
                    in_degree[s.stage] -= 1
                    if in_degree[s.stage] == 0:
                        queue.append(s.stage)

        if len(result) != len(self.stages):
            raise PipelineConfigError("Pipeline DAG 存在环形依赖，请检查 depends_on 配置")

        return result

    def validate(
        self,
        registry: Any | None = None,
        metric_registry: Any | None = None,
    ) -> None:
        """Runner 执行前的前置校验。

        Args:
            registry:        EvaluableRegistry 实例（可选），用于校验 evaluable 注册状态。
            metric_registry: MetricRegistry 实例（可选），用于校验 metrics glob 匹配。

        Raises:
            PipelineConfigError: 任一校验项失败时抛出，说明具体原因。
        """
        stage_names = {s.stage for s in self.stages}

        # 1. depends_on 引用的 stage 必须存在
        for stage in self.stages:
            for dep in stage.depends_on:
                if dep not in stage_names:
                    raise PipelineConfigError(
                        f"stage '{stage.stage}' depends_on '{dep}'，但该 stage 未在 pipeline 中定义"
                    )

        # 2. input_from / fallback_input_from 必须在 DAG 上游
        ordered = self.topological_order()
        ordered_names = [s.stage for s in ordered]
        for stage in self.stages:
            idx = ordered_names.index(stage.stage)
            for ref in [stage.input_from, stage.fallback_input_from]:
                if ref and ref not in ordered_names[:idx]:
                    raise PipelineConfigError(
                        f"stage '{stage.stage}' 的 input_from/fallback_input_from '{ref}' "
                        f"不在其 DAG 上游"
                    )

        # 3. evaluable name 已注册（可选校验）
        if registry is not None:
            for stage in self.stages:
                for name in stage.evaluables:
                    try:
                        registry.get(name)
                    except KeyError as e:
                        raise PipelineConfigError(str(e)) from e

        # 4. metrics glob 至少匹配到一个已注册指标（可选校验）
        if metric_registry is not None:
            import fnmatch
            all_ids = metric_registry.all_metric_ids()
            for pattern in self.metrics.include:
                if pattern != "*" and not any(
                    fnmatch.fnmatch(mid, pattern) for mid in all_ids
                ):
                    raise PipelineConfigError(
                        f"metrics.include 中的 glob '{pattern}' 未匹配到任何已注册指标。"
                        f"已注册: {all_ids}"
                    )
