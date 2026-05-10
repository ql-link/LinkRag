# -*- coding: utf-8 -*-
"""
Dataset Protocol — 评估数据集抽象。

EvalSample 是评估的最小粒度单元，EvalDataset 是样本集合的迭代器协议。
数据集与代码解耦：manifest.yaml 驱动加载，不硬编码路径。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Iterator


@dataclass
class EvalSample:
    """评估数据集的最小样本单元。

    Attributes:
        sample_id:    样本唯一标识，对应 manifest.yaml 中的 id 字段。
        file_path:    源文件本地路径；大文件可为 None，由 loader 延迟加载。
        file_bytes:   源文件内容；小文件内联，大文件由 loader 按需填充。
        file_type:    文件格式，如 "pdf" / "docx" / "html"。
        domain:       业务域标签，如 "技术文档" / "合同" / "财报"，用于分层分析。
        language:     语言标签，如 "zh" / "en"。
        difficulty:   难度标签，如 "easy" / "medium" / "hard"，用于分层评估。
        ground_truth: 基准答案字典，key 视 stage 而定：
                      - parse stage: {"markdown": str}（人工校验的基准 Markdown）
                      - chunk stage: {"chunks": list[dict]}（人工标注的分片边界）
                      - qa stage:    {"answer": str}（问答对）
        tags:         自由标签列表，用于过滤子集。
        extra:        预留扩展字段。
    """
    sample_id: str
    file_path: str | None
    file_bytes: bytes | None = None
    file_type: str = ""
    domain: str | None = None
    language: str | None = None
    difficulty: str | None = None
    ground_truth: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def load_bytes(self) -> bytes:
        """加载文件内容（优先使用内联 bytes，否则从 file_path 读取）。

        Returns:
            bytes: 文件原始字节内容。

        Raises:
            ValueError: 既无 file_bytes 也无 file_path 时。
            FileNotFoundError: file_path 不存在时。
        """
        if self.file_bytes is not None:
            return self.file_bytes
        if self.file_path:
            with open(self.file_path, "rb") as f:
                return f.read()
        raise ValueError(f"样本 {self.sample_id!r} 既无 file_bytes 也无 file_path")


class EvalDataset(Protocol):
    """评估数据集协议。

    实现者需提供样本迭代和子集过滤能力。
    数据集 name + version 与代码 commit 一起记录，用于跨版本趋势对比。

    Attributes:
        name:         数据集名称，如 "parser_smoke"。
        version:      数据集版本，与代码 commit 一起记录用于趋势对比。
        sample_count: 样本总数，用于进度条，无需全量加载。
    """
    name: str
    version: str
    sample_count: int

    def iter_samples(self) -> Iterator[EvalSample]:
        """按顺序迭代所有样本。

        Returns:
            Iterator[EvalSample]: 样本迭代器。
        """
        ...

    def filter(self, **criteria) -> "EvalDataset":
        """按条件过滤出子集，用于分层分析。

        Args:
            **criteria: 支持的过滤键：domain, language, difficulty, tags。

        Returns:
            EvalDataset: 过滤后的数据集视图（懒加载）。
        """
        ...
