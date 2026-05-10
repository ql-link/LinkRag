# -*- coding: utf-8 -*-
"""
manifest.yaml Schema 定义与校验。

manifest.yaml 是数据集目录的入口描述文件，约束样本列表结构，
支持 CI 时直接校验数据集完整性，避免运行到一半才发现缺文件。

manifest.yaml 格式示例：
    name: parser_smoke
    version: "v1"
    description: "解析冒烟测试集，含 PDF/Word/HTML 各 10 个样本"
    samples:
      - id: pdf_001
        file: samples/pdf_001.pdf
        file_type: pdf
        domain: 技术文档
        language: zh
        difficulty: medium
        ground_truth:
          markdown: samples/pdf_001_gt.md
        tags: [table, image]
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from src.evaluation.contracts.dataset import EvalSample


@dataclass
class SampleManifestEntry:
    """manifest.yaml 中单个 sample 条目的结构化表示。

    Attributes:
        id:           样本唯一标识。
        file:         相对于 manifest.yaml 所在目录的源文件路径。
        file_type:    文件格式。
        domain:       业务域标签（可选）。
        language:     语言标签（可选）。
        difficulty:   难度标签（可选）。
        ground_truth: 基准文件路径字典，如 {"markdown": "samples/xxx_gt.md"}。
        tags:         自由标签列表。
        extra:        扩展字段。
    """
    id: str
    file: str
    file_type: str
    domain: str | None = None
    language: str | None = None
    difficulty: str | None = None
    ground_truth: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ManifestSchema:
    """manifest.yaml 的完整 Schema。

    Attributes:
        name:        数据集名称。
        version:     数据集版本字符串（纳入版本管理）。
        description: 数据集描述。
        samples:     样本条目列表。
    """
    name: str
    version: str
    description: str = ""
    samples: list[SampleManifestEntry] = field(default_factory=list)


def load_manifest(manifest_path: str) -> ManifestSchema:
    """从 manifest.yaml 加载并校验数据集描述。

    Args:
        manifest_path: manifest.yaml 的绝对或相对路径。

    Returns:
        ManifestSchema: 解析并校验后的 manifest 对象。

    Raises:
        FileNotFoundError: manifest 文件不存在。
        ValueError:        manifest 格式错误（缺少必填字段）。
    """
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest 文件不存在: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"manifest 格式错误: 顶层应为 dict，实际为 {type(raw)}")

    for required_key in ("name", "version", "samples"):
        if required_key not in raw:
            raise ValueError(f"manifest 缺少必填字段: {required_key!r}")

    samples: list[SampleManifestEntry] = []
    for idx, entry in enumerate(raw.get("samples", [])):
        if "id" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'id' 字段")
        if "file" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'file' 字段")
        if "file_type" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'file_type' 字段")

        samples.append(SampleManifestEntry(
            id=entry["id"],
            file=entry["file"],
            file_type=entry["file_type"],
            domain=entry.get("domain"),
            language=entry.get("language"),
            difficulty=entry.get("difficulty"),
            ground_truth=entry.get("ground_truth", {}),
            tags=entry.get("tags", []),
            extra={k: v for k, v in entry.items()
                   if k not in {"id", "file", "file_type", "domain", "language",
                                "difficulty", "ground_truth", "tags"}},
        ))

    return ManifestSchema(
        name=raw["name"],
        version=str(raw["version"]),
        description=raw.get("description", ""),
        samples=samples,
    )


def manifest_to_eval_samples(
    manifest: ManifestSchema,
    base_dir: str,
) -> list[EvalSample]:
    """将 manifest 样本条目转换为 EvalSample 列表，并解析 ground_truth 文件路径。

    ground_truth 字典中的值若为相对路径，则解析为相对于 base_dir 的绝对路径；
    若文件存在，则读取并内联（仅限文本格式的 ground truth，如 .md / .txt）。

    Args:
        manifest: 已加载的 ManifestSchema 对象。
        base_dir: manifest.yaml 所在目录的绝对路径。

    Returns:
        list[EvalSample]: 转换后的样本列表。
    """
    samples: list[EvalSample] = []

    for entry in manifest.samples:
        abs_file = os.path.join(base_dir, entry.file)

        # 解析 ground_truth：将路径值替换为实际文本内容（若文件存在）
        resolved_gt: dict[str, Any] = {}
        for gt_key, gt_val in entry.ground_truth.items():
            if isinstance(gt_val, str):
                gt_path = os.path.join(base_dir, gt_val)
                if os.path.exists(gt_path):
                    with open(gt_path, "r", encoding="utf-8") as f:
                        resolved_gt[gt_key] = f.read()
                else:
                    resolved_gt[gt_key] = gt_val  # 保留原始字符串
            else:
                resolved_gt[gt_key] = gt_val

        samples.append(EvalSample(
            sample_id=entry.id,
            file_path=abs_file if os.path.exists(abs_file) else None,
            file_type=entry.file_type,
            domain=entry.domain,
            language=entry.language,
            difficulty=entry.difficulty,
            ground_truth=resolved_gt,
            tags=entry.tags,
            extra=entry.extra,
        ))

    return samples
