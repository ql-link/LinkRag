# -*- coding: utf-8 -*-
"""
FileSystemDataset — 基于本地文件系统的数据集加载器。

支持：
- 从 manifest.yaml 目录加载。
- 按 domain / language / difficulty / tags 过滤子集（懒加载视图）。
- 大文件延迟加载（file_bytes 在迭代时按需读取）。
"""
from __future__ import annotations

import os
from typing import Iterator

from src.evaluation.contracts.dataset import EvalSample
from .manifest import ManifestSchema, load_manifest, manifest_to_eval_samples


class FileSystemDataset:
    """基于本地文件系统的评估数据集。

    实现 EvalDataset 协议，从 manifest.yaml 加载样本元数据，
    大文件延迟加载（迭代时按需读取 bytes）。

    Attributes:
        name:         数据集名称（从 manifest 读取）。
        version:      数据集版本（从 manifest 读取）。
        sample_count: 样本总数（用于进度条，无需全量加载 bytes）。
    """

    def __init__(
        self,
        manifest_path: str,
        preload_bytes: bool = False,
        _samples: list[EvalSample] | None = None,
        _manifest: ManifestSchema | None = None,
    ) -> None:
        """初始化数据集，加载 manifest 并解析样本元数据。

        Args:
            manifest_path:  manifest.yaml 的路径。
            preload_bytes:  若为 True，初始化时立即加载所有文件字节内容
                            （小数据集或 smoke 测试时使用）。
            _samples:       内部参数，filter() 传入过滤后的子集，不直接使用。
            _manifest:      内部参数，filter() 传入已加载的 manifest，不重复加载。
        """
        self._manifest_path = manifest_path
        self._base_dir = os.path.dirname(os.path.abspath(manifest_path))

        if _manifest is not None and _samples is not None:
            # filter() 内部快速路径：直接复用已加载数据
            self._manifest = _manifest
            self._samples = _samples
        else:
            self._manifest = load_manifest(manifest_path)
            self._samples = manifest_to_eval_samples(self._manifest, self._base_dir)

        if preload_bytes:
            for sample in self._samples:
                if sample.file_bytes is None and sample.file_path:
                    with open(sample.file_path, "rb") as f:
                        sample.file_bytes = f.read()

    @property
    def name(self) -> str:
        """数据集名称。"""
        return self._manifest.name

    @property
    def version(self) -> str:
        """数据集版本。"""
        return self._manifest.version

    @property
    def sample_count(self) -> int:
        """样本总数。"""
        return len(self._samples)

    def iter_samples(self) -> Iterator[EvalSample]:
        """按顺序迭代所有样本（大文件按需加载 bytes）。

        Yields:
            EvalSample: 每个样本（file_bytes 可能为 None，调用 load_bytes() 按需加载）。
        """
        yield from self._samples

    def filter(self, **criteria) -> "FileSystemDataset":
        """按条件过滤出子集（返回新的 FileSystemDataset 视图）。

        Args:
            **criteria: 支持的过滤键：
                - domain (str):      精确匹配。
                - language (str):    精确匹配。
                - difficulty (str):  精确匹配。
                - tags (list[str] | str): 包含任一 tag（OR 匹配）。

        Returns:
            FileSystemDataset: 过滤后的子集视图。
        """
        filtered = list(self._samples)

        if "domain" in criteria:
            filtered = [s for s in filtered if s.domain == criteria["domain"]]
        if "language" in criteria:
            filtered = [s for s in filtered if s.language == criteria["language"]]
        if "difficulty" in criteria:
            filtered = [s for s in filtered if s.difficulty == criteria["difficulty"]]
        if "tags" in criteria:
            tag_filter = criteria["tags"]
            if isinstance(tag_filter, str):
                tag_filter = [tag_filter]
            tag_set = set(tag_filter)
            filtered = [s for s in filtered if tag_set & set(s.tags)]

        # 返回同类实例，复用 manifest 避免重复解析
        return FileSystemDataset(
            manifest_path=self._manifest_path,
            _samples=filtered,
            _manifest=self._manifest,
        )

    def __repr__(self) -> str:
        return (
            f"FileSystemDataset(name={self.name!r}, version={self.version!r}, "
            f"count={self.sample_count})"
        )
