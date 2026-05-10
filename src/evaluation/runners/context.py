# -*- coding: utf-8 -*-
"""
RunContext — 管理单个 sample 跨 stage 的中间产物传递。

每个 sample 有独立的 RunContext，并发安全（无共享状态）。
上游 stage 产物（如 ParseResult）通过 context 传递，
ChunkerAdapter 不需要重新 parse，减少重复计算。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.evaluation.contracts.evaluable import StageInput, StageOutput
    from src.evaluation.contracts.dataset import EvalSample
    from src.evaluation.runners.pipeline import StageConfig


class RunContext:
    """管理单个 sample 跨 stage 的中间产物。

    每个 sample 有独立的 RunContext，并发安全（不共享任何类级别状态）。

    Attributes:
        sample: 当前处理的 EvalSample。
    """

    def __init__(self, sample: "EvalSample") -> None:
        self.sample = sample
        # {stage_name: {evaluable_name: StageOutput}}
        self._stage_outputs: dict[str, dict[str, "StageOutput"]] = {}

    def put(self, stage: str, evaluable_name: str, output: "StageOutput") -> None:
        """存入某 stage + evaluable 的执行结果。

        Args:
            stage:          stage 名称。
            evaluable_name: evaluable 唯一标识。
            output:         执行结果。
        """
        self._stage_outputs.setdefault(stage, {})[evaluable_name] = output

    def get_output(self, stage: str, evaluable_name: str) -> "StageOutput | None":
        """获取某 stage + evaluable 的执行结果。

        Args:
            stage:          stage 名称。
            evaluable_name: evaluable 唯一标识。

        Returns:
            StageOutput | None: 不存在时返回 None。
        """
        return self._stage_outputs.get(stage, {}).get(evaluable_name)

    def get_all_outputs_for_stage(self, stage: str) -> dict[str, "StageOutput"]:
        """获取某 stage 所有 evaluable 的执行结果。

        Args:
            stage: stage 名称。

        Returns:
            dict[str, StageOutput]: {evaluable_name: output} 字典，可能为空。
        """
        return dict(self._stage_outputs.get(stage, {}))

    def build_stage_input(
        self,
        stage_cfg: "StageConfig",
        evaluable_name: str,
        run_index: int = 0,
    ) -> "StageInput":
        """按 input_from / fallback_input_from 策略组装下游 StageInput。

        选取策略：
        1. 若 input_from 指定且对应 stage 有成功输出 → 使用该输出的 payload。
        2. 若 1 不满足且 fallback_input_from 指定且有成功输出 → 降级使用。
        3. 否则 payload 为 None（由被评估对象自行处理，通常直接从 sample 取 bytes）。

        Args:
            stage_cfg:      当前 stage 配置。
            evaluable_name: 当前 evaluable 名称（用于 context 传递时不取自身输出）。
            run_index:      当前轮次（多轮稳定性评估时注入）。

        Returns:
            StageInput: 组装后的输入容器。
        """
        from src.evaluation.contracts.evaluable import StageInput

        payload = None
        context: dict = {}

        # 组装 context：把所有上游 stage 的成功输出传入
        for stage_name, evaluable_map in self._stage_outputs.items():
            for ev_name, out in evaluable_map.items():
                if out.success:
                    context_key = f"{stage_name}.{ev_name}"
                    context[context_key] = out.payload

        # 特殊 key：parse_result 快捷键，供 ChunkerAdapter 复用
        parse_stage_outputs = self._stage_outputs.get("parse", {})
        for out in parse_stage_outputs.values():
            if out.success and out.payload:
                # 存储 Markdown 文本（ChunkerAdapter 内部会 parse 成 ParseResult）
                context.setdefault("parse_result_md", out.payload)
                break

        # 选取主 payload
        def _pick_payload(from_stage: str | None) -> object | None:
            if not from_stage:
                return None
            stage_outs = self._stage_outputs.get(from_stage, {})
            # 优先取第一个成功的 evaluable 产物
            for out in stage_outs.values():
                if out.success:
                    return out.payload
            return None

        payload = _pick_payload(stage_cfg.input_from)
        if payload is None:
            payload = _pick_payload(stage_cfg.fallback_input_from)
        if payload is None:
            # 无上游产物，直接从 sample 加载原始文件
            try:
                payload = self.sample.load_bytes()
            except Exception:
                payload = None

        return StageInput(
            sample_id=self.sample.sample_id,
            payload=payload,
            context=context,
            run_index=run_index,
        )
