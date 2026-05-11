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

from src.evaluation.contracts.dataset import EvalSample, RemoteObjectRef


ALLOWED_REMOTE_SPLITS = {"test", "validation"}


@dataclass
class StorageManifest:
    """manifest.yaml 中的远端存储描述。"""
    backend: str
    bucket: str
    prefix: str = ""


@dataclass
class ObjectManifestRef:
    """manifest.yaml 中的对象引用。"""
    key: str
    content_type: str | None = None
    size: int | None = None
    etag: str | None = None


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
    file: str | ObjectManifestRef
    file_type: str
    split: str | None = None
    domain: str | None = None
    language: str | None = None
    difficulty: str | None = None
    ground_truth: dict[str, str | ObjectManifestRef] = field(default_factory=dict)
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
    storage: StorageManifest | None = None
    samples: list[SampleManifestEntry] = field(default_factory=list)


def load_manifest(manifest_source: str | bytes, source_type: str = "path") -> ManifestSchema:
    """从 manifest.yaml 加载并校验数据集描述。

    Args:
        manifest_source: manifest.yaml 路径，或远端下载得到的 bytes / 文本。
        source_type:     "path" 表示本地路径；"bytes" 表示内容。

    Returns:
        ManifestSchema: 解析并校验后的 manifest 对象。

    Raises:
        FileNotFoundError: manifest 文件不存在。
        ValueError:        manifest 格式错误（缺少必填字段）。
    """
    if source_type == "path":
        manifest_path = str(manifest_source)
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"manifest 文件不存在: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    elif source_type == "bytes":
        if isinstance(manifest_source, bytes):
            manifest_text = manifest_source.decode("utf-8")
        else:
            manifest_text = manifest_source
        raw = yaml.safe_load(manifest_text)
    else:
        raise ValueError(f"不支持的 manifest source_type: {source_type!r}")

    if not isinstance(raw, dict):
        raise ValueError(f"manifest 格式错误: 顶层应为 dict，实际为 {type(raw)}")

    for required_key in ("name", "version", "samples"):
        if required_key not in raw:
            raise ValueError(f"manifest 缺少必填字段: {required_key!r}")

    storage = _parse_storage(raw.get("storage"))
    samples: list[SampleManifestEntry] = []
    for idx, entry in enumerate(raw.get("samples", [])):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest samples[{idx}] 格式错误: 应为 dict")
        if "id" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'id' 字段")
        if "file" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'file' 字段")
        if "file_type" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'file_type' 字段")
        split = entry.get("split")
        if storage is not None:
            if split not in ALLOWED_REMOTE_SPLITS:
                raise ValueError(
                    f"manifest samples[{idx}].split 必须为 test 或 validation"
                )

        samples.append(SampleManifestEntry(
            id=entry["id"],
            file=_parse_object_ref(entry["file"], field_name=f"samples[{idx}].file"),
            file_type=entry["file_type"],
            split=split,
            domain=entry.get("domain"),
            language=entry.get("language"),
            difficulty=entry.get("difficulty"),
            ground_truth=_parse_ground_truth(entry.get("ground_truth", {}), sample_idx=idx),
            tags=entry.get("tags", []),
            extra={k: v for k, v in entry.items()
                   if k not in {"id", "file", "file_type", "split", "domain", "language",
                                "difficulty", "ground_truth", "tags"}},
        ))

    return ManifestSchema(
        name=raw["name"],
        version=str(raw["version"]),
        description=raw.get("description", ""),
        storage=storage,
        samples=samples,
    )


def manifest_to_eval_samples(
    manifest: ManifestSchema,
    base_dir: str | None,
    byte_loader=None,
    text_loader=None,
) -> list[EvalSample]:
    """将 manifest 样本条目转换为 EvalSample 列表，并解析 ground_truth 文件路径。

    ground_truth 字典中的值若为相对路径，则解析为相对于 base_dir 的绝对路径；
    若文件存在，则读取并内联（仅限文本格式的 ground truth，如 .md / .txt）。

    Args:
        manifest: 已加载的 ManifestSchema 对象。
        base_dir: manifest.yaml 所在目录的绝对路径；远端 manifest 可传 None。
        byte_loader: 远端样本 bytes 加载回调。
        text_loader: 远端 ground truth 文本加载回调。

    Returns:
        list[EvalSample]: 转换后的样本列表。
    """
    samples: list[EvalSample] = []

    for entry in manifest.samples:
        if manifest.storage is not None:
            remote_file = _to_remote_ref(manifest.storage, entry.file)
            resolved_gt: dict[str, Any] = {}
            gt_refs: dict[str, RemoteObjectRef] = {}
            for gt_key, gt_val in entry.ground_truth.items():
                if isinstance(gt_val, ObjectManifestRef):
                    ref = _to_remote_ref(manifest.storage, gt_val)
                    gt_refs[gt_key] = ref
                    resolved_gt[gt_key] = text_loader(ref) if text_loader else ref.key
                else:
                    resolved_gt[gt_key] = gt_val

            samples.append(EvalSample(
                sample_id=entry.id,
                file_path=None,
                remote_file=remote_file,
                byte_loader=byte_loader,
                file_type=entry.file_type,
                domain=entry.domain,
                language=entry.language,
                difficulty=entry.difficulty,
                ground_truth=resolved_gt,
                ground_truth_refs=gt_refs,
                tags=entry.tags,
                extra={**entry.extra, "split": entry.split},
            ))
            continue

        if base_dir is None:
            raise ValueError("本地 manifest 转换必须传入 base_dir")
        if not isinstance(entry.file, str):
            raise ValueError("本地 manifest 的 file 字段必须为字符串路径")
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


def _parse_storage(raw: Any) -> StorageManifest | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("manifest storage 字段必须为 dict")
    backend = raw.get("backend")
    bucket = raw.get("bucket")
    if backend != "minio":
        raise ValueError("manifest storage.backend 目前仅支持 minio")
    if not bucket:
        raise ValueError("manifest storage.bucket 缺失")
    return StorageManifest(
        backend=backend,
        bucket=bucket,
        prefix=str(raw.get("prefix", "")).strip("/"),
    )


def _parse_object_ref(raw: Any, field_name: str) -> str | ObjectManifestRef:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        key = raw.get("key")
        if not key:
            raise ValueError(f"manifest {field_name}.key 缺失")
        size = raw.get("size")
        return ObjectManifestRef(
            key=str(key),
            content_type=raw.get("content_type"),
            size=int(size) if size is not None else None,
            etag=raw.get("etag"),
        )
    raise ValueError(f"manifest {field_name} 必须为字符串或对象引用")


def _parse_ground_truth(raw: Any, sample_idx: int) -> dict[str, str | ObjectManifestRef]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"manifest samples[{sample_idx}].ground_truth 必须为 dict")
    return {
        str(key): _parse_object_ref(
            value,
            field_name=f"samples[{sample_idx}].ground_truth.{key}",
        )
        for key, value in raw.items()
    }


def _to_remote_ref(storage: StorageManifest, ref: str | ObjectManifestRef) -> RemoteObjectRef:
    if isinstance(ref, str):
        obj_ref = ObjectManifestRef(key=ref)
    else:
        obj_ref = ref
    object_key = _join_object_key(storage.prefix, obj_ref.key)
    return RemoteObjectRef(
        bucket=storage.bucket,
        key=object_key,
        content_type=obj_ref.content_type,
        size=obj_ref.size,
        etag=obj_ref.etag,
    )


def _join_object_key(prefix: str, key: str) -> str:
    clean_key = str(key).lstrip("/")
    clean_prefix = prefix.strip("/")
    if not clean_prefix:
        return clean_key
    if clean_key.startswith(f"{clean_prefix}/"):
        return clean_key
    return f"{clean_prefix}/{clean_key}"
