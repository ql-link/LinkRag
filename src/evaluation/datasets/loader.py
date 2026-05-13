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
from .manifest import (
    ManifestSchema,
    discover_manifest_samples,
    load_manifest,
    manifest_to_eval_samples,
)


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


class MinioDataset:
    """完全基于 MinIO 的评估数据集。

    初始化阶段只下载 manifest，样本源文件通过 EvalSample.load_bytes()
    按需下载，避免大数据集启动时一次性拉取全部文件。
    """

    def __init__(
        self,
        dataset_name: str,
        version: str,
        split: str,
        object_storage,
        bucket: str = "test_set",
        prefix: str = "datasets",
        _samples: list[EvalSample] | None = None,
        _manifest: ManifestSchema | None = None,
    ) -> None:
        self._object_storage = object_storage
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._requested_name = dataset_name
        self._requested_version = version
        self._split = split

        if _manifest is not None and _samples is not None:
            self._manifest = _manifest
            self._samples = _samples
            return

        resolved_version = self._resolve_version(dataset_name, version)
        manifest_key = self._manifest_key(dataset_name, resolved_version)
        manifest_bytes = self._object_storage.download_bytes(bucket, manifest_key)
        self._manifest = load_manifest(manifest_bytes, source_type="bytes")

        if self._manifest.name != dataset_name:
            raise ValueError(
                f"远端 manifest name={self._manifest.name!r} 与请求数据集 {dataset_name!r} 不一致"
            )

        if self._manifest.discovery and self._manifest.discovery.enabled:
            discovered = discover_manifest_samples(
                self._manifest,
                object_keys=self._list_dataset_objects(self._manifest.storage.prefix),
            )
            explicit_by_id = {sample.id: sample for sample in self._manifest.samples}
            discovered_by_id = {sample.id: sample for sample in discovered}
            discovered_by_id.update(explicit_by_id)
            self._manifest.samples = [
                discovered_by_id[sample_id]
                for sample_id in sorted(discovered_by_id)
            ]

        self._samples = manifest_to_eval_samples(
            self._manifest,
            base_dir=None,
            byte_loader=self._load_sample_bytes,
            text_loader=self._load_text,
        )
        self._samples = self._apply_filter(self._samples, split=split)
        if not self._samples:
            raise ValueError(
                f"数据集 {dataset_name!r} version={resolved_version!r} split={split!r} 无样本"
            )

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def version(self) -> str:
        return self._manifest.version

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def iter_samples(self) -> Iterator[EvalSample]:
        yield from self._samples

    def filter(self, **criteria) -> "MinioDataset":
        filtered = self._apply_filter(list(self._samples), **criteria)
        return MinioDataset(
            dataset_name=self.name,
            version=self.version,
            split=criteria.get("split", self._split),
            object_storage=self._object_storage,
            bucket=self._bucket,
            prefix=self._prefix,
            _samples=filtered,
            _manifest=self._manifest,
        )

    def _resolve_version(self, dataset_name: str, version: str) -> str:
        if version != "latest":
            return version
        import json

        for latest_key in self._candidate_latest_keys(dataset_name):
            try:
                raw = self._object_storage.download_bytes(self._bucket, latest_key).decode("utf-8")
                latest = json.loads(raw)
                return str(latest["version"])
            except FileNotFoundError:
                continue
        return version

    def _manifest_key(self, dataset_name: str, version: str) -> str:
        for key in self._candidate_manifest_keys(dataset_name, version):
            try:
                self._object_storage.download_bytes(self._bucket, key)
                return key
            except FileNotFoundError:
                continue
        return self._candidate_manifest_keys(dataset_name, version)[0]

    def _load_sample_bytes(self, sample: EvalSample) -> bytes:
        if sample.remote_file is None:
            raise ValueError(f"样本 {sample.sample_id!r} 缺少远端文件引用")
        return self._object_storage.download_bytes(sample.remote_file.bucket, sample.remote_file.key)

    def _load_text(self, ref) -> str:
        return self._object_storage.download_bytes(ref.bucket, ref.key).decode("utf-8")

    def _list_dataset_objects(self, prefix: str) -> list[str]:
        if not hasattr(self._object_storage, "list_objects"):
            raise ValueError("当前 object_storage 不支持 discovery 所需的 list_objects")
        return self._object_storage.list_objects(self._bucket, prefix)

    @staticmethod
    def _apply_filter(samples: list[EvalSample], **criteria) -> list[EvalSample]:
        filtered = samples
        if "split" in criteria and criteria["split"] is not None:
            filtered = [s for s in filtered if s.extra.get("split") == criteria["split"]]
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
        return filtered

    @staticmethod
    def _join_key(*parts: str) -> str:
        return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))

    def _candidate_latest_keys(self, dataset_name: str) -> list[str]:
        return [
            self._join_key(self._prefix, dataset_name, "latest.json"),
            self._join_key(self._prefix, "latest.json"),
        ]

    def _candidate_manifest_keys(self, dataset_name: str, version: str) -> list[str]:
        return [
            self._join_key(self._prefix, dataset_name, version, "manifest.yaml"),
            self._join_key(self._prefix, version, "manifest.yaml"),
            self._join_key(self._prefix, "manifest.yaml"),
        ]

    def __repr__(self) -> str:
        return (
            f"MinioDataset(name={self.name!r}, version={self.version!r}, "
            f"split={self._split!r}, count={self.sample_count})"
        )
