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
import posixpath
from dataclasses import dataclass, field
from typing import Any

import yaml

from src.evaluation.contracts.dataset import EvalSample, RemoteObjectRef


ALLOWED_REMOTE_SPLITS = {"test", "validation"}
ALLOWED_PARSER_FILE_TYPES = {"pdf", "doc", "docx", "html", "htm"}
DEFAULT_GROUND_TRUTH_EXTENSION = ".md"


@dataclass
class StorageManifest:
    """manifest.yaml 中的远端存储描述。"""
    backend: str
    bucket: str
    prefix: str = ""


@dataclass
class DiscoveryManifest:
    """manifest.yaml 中的自动样本发现配置。"""
    enabled: bool = False
    test_set_dir: str = "test_set"
    ground_truth_dir: str = "ground_truth"
    match_strategy: str = "same_stem"
    ground_truth_extension: str = DEFAULT_GROUND_TRUTH_EXTENSION
    include_file_types: list[str] = field(default_factory=lambda: ["pdf", "docx", "html"])
    recursive: bool = True


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
    discovery: DiscoveryManifest | None = None
    defaults: dict[str, Any] = field(default_factory=dict)
    sample_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
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

    for required_key in ("name", "version"):
        if required_key not in raw:
            raise ValueError(f"manifest 缺少必填字段: {required_key!r}")

    storage = _parse_storage(raw.get("storage"))
    discovery = _parse_discovery(raw.get("discovery"))
    defaults = _parse_mapping(raw.get("defaults", {}), field_name="defaults")
    sample_overrides = _parse_sample_overrides(raw.get("sample_overrides", {}))
    raw_samples = raw.get("samples", [])
    if not raw_samples and not (discovery and discovery.enabled):
        raise ValueError("manifest 缺少 samples，且未启用 discovery")

    samples: list[SampleManifestEntry] = []
    for idx, entry in enumerate(raw_samples):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest samples[{idx}] 格式错误: 应为 dict")
        if "id" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'id' 字段")
        if "file" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'file' 字段")
        if "file_type" not in entry:
            raise ValueError(f"manifest samples[{idx}] 缺少 'file_type' 字段")
        _validate_parser_sample_entry(entry, idx)
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
        discovery=discovery,
        defaults=defaults,
        sample_overrides=sample_overrides,
        samples=samples,
    )


def discover_manifest_samples(
    manifest: ManifestSchema,
    object_keys: list[str],
) -> list[SampleManifestEntry]:
    """Discover samples by matching source files to ground truth Markdown.

    The object keys can be absolute MinIO keys under ``manifest.storage.prefix``.
    Returned ``SampleManifestEntry`` objects keep keys relative to the dataset
    prefix so existing ``_to_remote_ref`` logic can prepend the prefix once.
    """
    discovery = manifest.discovery
    if discovery is None or not discovery.enabled:
        return []
    if manifest.storage is None:
        raise ValueError("discovery 目前仅支持带 storage 的 MinIO manifest")
    if discovery.match_strategy != "same_stem":
        raise ValueError("discovery.match_strategy 目前仅支持 same_stem")

    relative_keys = sorted(
        _strip_prefix(key, manifest.storage.prefix)
        for key in object_keys
        if _strip_prefix(key, manifest.storage.prefix)
    )
    source_keys = [
        key for key in relative_keys
        if _is_discoverable_source(key, discovery)
    ]
    ground_truth_keys = [
        key for key in relative_keys
        if key.startswith(f"{discovery.ground_truth_dir.strip('/')}/")
        and key.lower().endswith(discovery.ground_truth_extension.lower())
    ]

    samples: list[SampleManifestEntry] = []
    matched_gt: set[str] = set()
    errors: list[str] = []
    for source_key in source_keys:
        gt_key = _match_ground_truth_by_stem(source_key, ground_truth_keys, discovery)
        if gt_key is None:
            errors.append(f"{source_key} 缺少同名标准 Markdown")
            continue
        matched_gt.add(gt_key)
        sample_id = posixpath.splitext(posixpath.basename(source_key))[0]
        merged = {**manifest.defaults, **manifest.sample_overrides.get(sample_id, {})}
        file_type = str(merged.get("file_type") or _file_type_from_key(source_key))
        entry = SampleManifestEntry(
            id=sample_id,
            file=ObjectManifestRef(key=source_key),
            file_type=file_type,
            split=merged.get("split", "test"),
            domain=merged.get("domain"),
            language=merged.get("language"),
            difficulty=merged.get("difficulty"),
            ground_truth={
                "markdown": ObjectManifestRef(
                    key=gt_key,
                    content_type="text/markdown",
                )
            },
            tags=list(merged.get("tags", [])),
            extra={
                k: v for k, v in merged.items()
                if k not in {
                    "file_type", "split", "domain", "language", "difficulty",
                    "ground_truth", "tags",
                }
            },
        )
        _validate_discovered_sample(entry)
        samples.append(entry)

    if errors:
        raise ValueError("discovery 样本配对失败: " + "; ".join(errors))

    orphan_ground_truth = sorted(set(ground_truth_keys) - matched_gt)
    if orphan_ground_truth:
        for sample in samples:
            sample.extra.setdefault("discovery_warnings", []).extend(
                f"孤立标准 Markdown: {key}" for key in orphan_ground_truth
            )
    return samples


def _match_ground_truth_by_stem(
    source_key: str,
    ground_truth_keys: list[str],
    discovery: DiscoveryManifest,
) -> str | None:
    source_dir = discovery.test_set_dir.strip("/")
    truth_dir = discovery.ground_truth_dir.strip("/")
    relative_source = source_key[len(source_dir):].lstrip("/")
    source_parent = posixpath.dirname(relative_source)
    stem = posixpath.splitext(posixpath.basename(source_key))[0]
    expected = posixpath.join(truth_dir, source_parent, f"{stem}{discovery.ground_truth_extension}")
    if expected in ground_truth_keys:
        return expected

    fallback = [
        key for key in ground_truth_keys
        if posixpath.splitext(posixpath.basename(key))[0] == stem
    ]
    if len(fallback) > 1:
        raise ValueError(f"源文件 {source_key} 找到多个同名标准 Markdown: {fallback}")
    return fallback[0] if fallback else None


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


def _parse_discovery(raw: Any) -> DiscoveryManifest | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("manifest discovery 字段必须为 dict")
    include_file_types = [
        str(item).lower().lstrip(".")
        for item in raw.get("include_file_types", ["pdf", "docx", "html"])
    ]
    invalid = sorted(set(include_file_types) - ALLOWED_PARSER_FILE_TYPES)
    if invalid:
        raise ValueError(f"discovery.include_file_types 包含不支持的格式: {invalid}")
    ground_truth_extension = str(
        raw.get("ground_truth_extension", DEFAULT_GROUND_TRUTH_EXTENSION)
    )
    if not ground_truth_extension.startswith("."):
        ground_truth_extension = f".{ground_truth_extension}"
    return DiscoveryManifest(
        enabled=bool(raw.get("enabled", False)),
        test_set_dir=str(raw.get("test_set_dir", "test_set")).strip("/"),
        ground_truth_dir=str(raw.get("ground_truth_dir", "ground_truth")).strip("/"),
        match_strategy=str(raw.get("match_strategy", "same_stem")),
        ground_truth_extension=ground_truth_extension,
        include_file_types=include_file_types,
        recursive=bool(raw.get("recursive", True)),
    )


def _parse_mapping(raw: Any, field_name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"manifest {field_name} 字段必须为 dict")
    return dict(raw)


def _parse_sample_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("manifest sample_overrides 字段必须为 dict")
    overrides: dict[str, dict[str, Any]] = {}
    for sample_id, override in raw.items():
        if not isinstance(override, dict):
            raise ValueError(f"manifest sample_overrides.{sample_id} 必须为 dict")
        overrides[str(sample_id)] = dict(override)
    return overrides


def _validate_parser_sample_entry(entry: dict[str, Any], idx: int) -> None:
    file_type = str(entry.get("file_type", "")).lower().lstrip(".")
    if file_type not in ALLOWED_PARSER_FILE_TYPES:
        raise ValueError(
            f"manifest samples[{idx}].file_type 不支持: {entry.get('file_type')!r}"
        )
    ground_truth = entry.get("ground_truth", {})
    if not isinstance(ground_truth, dict) or "markdown" not in ground_truth:
        raise ValueError(f"manifest samples[{idx}].ground_truth.markdown 缺失")
    tags = entry.get("tags", [])
    if tags is not None and not isinstance(tags, list):
        raise ValueError(f"manifest samples[{idx}].tags 必须为 list")
    for numeric_key in ("page_count", "length_hint", "file_size"):
        if numeric_key in entry and entry[numeric_key] is not None:
            try:
                value = int(entry[numeric_key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"manifest samples[{idx}].{numeric_key} 必须为非负数") from exc
            if value < 0:
                raise ValueError(f"manifest samples[{idx}].{numeric_key} 必须为非负数")


def _validate_discovered_sample(entry: SampleManifestEntry) -> None:
    if entry.split not in ALLOWED_REMOTE_SPLITS:
        raise ValueError(f"discovery sample {entry.id!r}.split 必须为 test 或 validation")
    if entry.file_type.lower() not in ALLOWED_PARSER_FILE_TYPES:
        raise ValueError(f"discovery sample {entry.id!r}.file_type 不支持: {entry.file_type}")


def _is_discoverable_source(key: str, discovery: DiscoveryManifest) -> bool:
    source_dir = discovery.test_set_dir.strip("/")
    if not key.startswith(f"{source_dir}/"):
        return False
    relative = key[len(source_dir):].lstrip("/")
    if not discovery.recursive and "/" in relative:
        return False
    file_type = _file_type_from_key(key)
    return file_type in set(discovery.include_file_types)


def _file_type_from_key(key: str) -> str:
    return posixpath.splitext(key)[1].lower().lstrip(".")


def _strip_prefix(key: str, prefix: str) -> str:
    clean_key = str(key).strip("/")
    clean_prefix = str(prefix).strip("/")
    if not clean_prefix:
        return clean_key
    if clean_key == clean_prefix:
        return ""
    if clean_key.startswith(f"{clean_prefix}/"):
        return clean_key[len(clean_prefix) + 1:]
    return clean_key


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
