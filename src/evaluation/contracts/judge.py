# -*- coding: utf-8 -*-
"""
Judge Protocol — LLM 裁判接口（可选 / 默认关闭）。

走 src.core.llm 工厂复用业务 LLM 抽象，但配置独立（EVAL_JUDGE_*），
避免与业务抢配额。裁判结果走 input hash 缓存，支持 TTL 过期。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class JudgeResult:
    """LLM 裁判结果。

    Attributes:
        score:        归一化分数 [0.0, 1.0]，1.0 表示完全满足评估标准。
        reasoning:    LLM 给出的判断理由（调试 / 审计用）。
        raw_response: 原始 LLM 返回字符串（完整记录，审计用）。
        cached:       是否命中缓存（命中时不消耗 LLM 配额）。
    """
    score: float
    reasoning: str
    raw_response: str = ""
    cached: bool = False


class Judge(Protocol):
    """LLM 裁判协议。

    裁判器接收结构化 prompt 上下文，返回标准化评分。
    默认实现走 LLM API，可替换为 rule_judge.py 的纯规则裁判（不调 LLM，用于单测）。

    Attributes:
        judge_id: 裁判器唯一标识，如 "llm.qwen" / "rule.regex"。
    """
    judge_id: str

    async def judge(self, prompt_ctx: dict) -> JudgeResult:
        """执行裁判评分。

        Args:
            prompt_ctx: 结构化 prompt 上下文，包含 instruction / input / output /
                       ground_truth 等字段，由各 Metric 按需构造。

        Returns:
            JudgeResult: 标准化裁判结果。
        """
        ...
