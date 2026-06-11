"""部署并冒烟验证本地 BGE-M3 稀疏向量模型。"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

from .constants import DEFAULT_SPARSE_VECTOR_MODEL_NAME
from .exceptions import SparseVectorConfigurationError, SparseVectorOutputError


DEFAULT_SAMPLE_TEXT = "Local BGE-M3 sparse vector smoke test for toLink RAG."


@dataclass(slots=True)
class DeploymentConfig:
    """记录解析后的 BGE-M3 部署参数。"""

    model_name: str
    revision: str | None
    cache_dir: str | None
    local_files_only: bool
    device: str
    batch_size: int
    max_length: int
    sample_text: str
    skip_encode: bool


def main(argv: Sequence[str] | None = None) -> int:
    """执行命令行部署入口，并返回进程退出码。

    Args:
        argv: 可选命令行参数；为空时使用当前进程参数。

    Returns:
        进程退出码，0 表示部署和冒烟流程完成。
    """

    config = _parse_args(argv)
    deployment = deploy_bge_m3(config)
    _print_deployment_summary(deployment)
    return 0


def deploy_bge_m3(config: DeploymentConfig) -> dict[str, Any]:
    """下载或定位 BGE-M3，加载模型，并按需执行稀疏编码冒烟。

    Args:
        config: 已解析并校验前的部署配置。

    Returns:
        部署摘要，包含模型路径、设备、加载耗时和可选的编码结果。

    Raises:
        SparseVectorConfigurationError: 模型文件、推理设备或依赖包不可用时抛出。
        SparseVectorOutputError: 冒烟编码返回空稀疏向量或非法输出时抛出。
    """

    _validate_config(config)
    model_path = _resolve_model_path(config)
    device = _resolve_device(config.device)
    # 精度由设备唯一决定：CPU 使用 fp32，CUDA 使用 fp16，避免暴露第二个配置入口。
    use_fp16 = device.startswith("cuda")

    started_at = perf_counter()
    model = _load_model(
        model_path=model_path,
        cache_dir=config.cache_dir,
        device=device,
        batch_size=config.batch_size,
        max_length=config.max_length,
        use_fp16=use_fp16,
    )
    load_seconds = perf_counter() - started_at

    result: dict[str, Any] = {
        "model_name": config.model_name,
        "model_path": str(model_path),
        "revision": config.revision,
        "device": device,
        "batch_size": config.batch_size,
        "max_length": config.max_length,
        "use_fp16": use_fp16,
        "load_seconds": round(load_seconds, 3),
        "encoded": False,
    }

    if not config.skip_encode:
        encode_started_at = perf_counter()
        sparse = _encode_sparse(
            model=model,
            text=config.sample_text,
            batch_size=config.batch_size,
            max_length=config.max_length,
        )
        encode_seconds = perf_counter() - encode_started_at
        result.update(
            {
                "encoded": True,
                "nonzero_tokens": len(sparse),
                "first_indices": [item[0] for item in sparse[:8]],
                "first_values": [round(item[1], 6) for item in sparse[:8]],
                "encode_seconds": round(encode_seconds, 3),
            }
        )

    return result


def _parse_args(argv: Sequence[str] | None) -> DeploymentConfig:
    """解析命令行参数和环境变量，生成部署配置。"""

    parser = argparse.ArgumentParser(
        description="Download, load, and smoke-test BAAI/bge-m3 for sparse vectors.",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("SPARSE_VECTOR_MODEL_NAME", DEFAULT_SPARSE_VECTOR_MODEL_NAME),
        help="Hugging Face model id or local model directory.",
    )
    parser.add_argument(
        "--revision",
        default=os.getenv("SPARSE_VECTOR_MODEL_REVISION") or None,
        help="Optional Hugging Face model revision or commit id.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.getenv("SPARSE_VECTOR_MODEL_CACHE_DIR") or None,
        help="Optional Hugging Face cache directory.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        default=_env_bool("SPARSE_VECTOR_LOCAL_FILES_ONLY", False),
        help="Use only files already present in the local cache or model directory.",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("SPARSE_VECTOR_DEVICE", "auto"),
        help="auto, cpu, cuda, cuda:0, or another torch device string.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_env_int("SPARSE_VECTOR_BATCH_SIZE", 1),
        help="Encoding batch size for the smoke test.",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=_env_int("SPARSE_VECTOR_MAX_LENGTH", 8192),
        help="Maximum input token length.",
    )
    parser.add_argument(
        "--sample-text",
        default=os.getenv("SPARSE_VECTOR_DEPLOY_SAMPLE_TEXT", DEFAULT_SAMPLE_TEXT),
        help="Text used for the sparse encoding smoke test.",
    )
    parser.add_argument(
        "--skip-encode",
        action="store_true",
        help="Only download and load the model; do not run encoding.",
    )

    args = parser.parse_args(argv)
    return DeploymentConfig(
        model_name=args.model_name,
        revision=args.revision,
        cache_dir=args.cache_dir,
        local_files_only=args.local_files_only,
        device=args.device,
        batch_size=args.batch_size,
        max_length=args.max_length,
        sample_text=args.sample_text,
        skip_encode=args.skip_encode,
    )


def _validate_config(config: DeploymentConfig) -> None:
    """校验部署配置中会影响模型加载的必填参数。"""

    if not config.model_name:
        raise SparseVectorConfigurationError("SPARSE_VECTOR_MODEL_NAME must not be empty.")
    if config.batch_size <= 0:
        raise SparseVectorConfigurationError("SPARSE_VECTOR_BATCH_SIZE must be greater than 0.")
    if config.max_length <= 0:
        raise SparseVectorConfigurationError("SPARSE_VECTOR_MAX_LENGTH must be greater than 0.")


def _resolve_model_path(config: DeploymentConfig) -> Path | str:
    """解析模型目录；远程模型名会通过 Hugging Face 缓存定位。"""

    candidate = Path(config.model_name)
    if candidate.exists():
        return candidate.resolve()

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SparseVectorConfigurationError(
            "huggingface_hub is required to download BGE-M3. "
            "Install project dependencies in the virtual environment first."
        ) from exc

    return snapshot_download(
        repo_id=config.model_name,
        revision=config.revision,
        cache_dir=config.cache_dir,
        local_files_only=config.local_files_only,
    )


def _resolve_device(device: str) -> str:
    """解析推理设备，auto 会优先选择可用 CUDA。"""

    normalized = device.strip().lower()
    if normalized == "auto":
        try:
            import torch
        except ImportError as exc:
            raise SparseVectorConfigurationError(
                "torch is required to choose SPARSE_VECTOR_DEVICE=auto."
            ) from exc
        # 部署脚本默认选择 GPU；没有 CUDA 时降级到 CPU，便于验证模型文件是否可加载。
        return "cuda" if torch.cuda.is_available() else "cpu"

    if normalized.startswith("cuda"):
        try:
            import torch
        except ImportError as exc:
            raise SparseVectorConfigurationError("torch is required for CUDA devices.") from exc
        if not torch.cuda.is_available():
            raise SparseVectorConfigurationError(
                f"Requested device {device!r}, but torch reports CUDA is unavailable."
            )
    return device


def _load_model(
    *,
    model_path: Path | str,
    cache_dir: str | None,
    device: str,
    batch_size: int,
    max_length: int,
    use_fp16: bool,
) -> Any:
    """创建 BGEM3FlagModel 实例，并传入设备、缓存和长度配置。

    Args:
        model_path: 已解析的本地模型路径或 Hugging Face 缓存路径。
        cache_dir: Hugging Face 缓存目录。
        device: 推理设备。
        batch_size: 冒烟编码批大小。
        max_length: 输入文本最大 token 长度。
        use_fp16: 是否启用半精度推理。

    Returns:
        已加载的 BGEM3FlagModel 实例。

    Raises:
        SparseVectorConfigurationError: FlagEmbedding 未安装时抛出。
    """

    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        raise SparseVectorConfigurationError(
            "FlagEmbedding is required for local BGE-M3 deployment."
        ) from exc

    # 部署脚本只验证稀疏能力，因此显式关闭 dense 和 colbert 输出，减少显存占用。
    return BGEM3FlagModel(
        str(model_path),
        use_fp16=use_fp16,
        devices=device,
        cache_dir=cache_dir,
        batch_size=batch_size,
        passage_max_length=max_length,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )


def _encode_sparse(
    *,
    model: Any,
    text: str,
    batch_size: int,
    max_length: int,
) -> list[tuple[int, float]]:
    """对样本文本执行 sparse 编码并返回排序后的 token 权重。

    Args:
        model: 已加载的 BGEM3FlagModel 实例。
        text: 用于冒烟验证的样本文本。
        batch_size: 编码批大小。
        max_length: 输入文本最大 token 长度。

    Returns:
        按 token_id 升序排列的 ``(token_id, weight)`` 列表。

    Raises:
        SparseVectorOutputError: 模型输出缺失 lexical_weights 或稀疏结果为空。
    """

    output = model.encode(
        [text],
        batch_size=batch_size,
        max_length=max_length,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    lexical_weights = _get_lexical_weights(output)
    sparse = _normalize_lexical_weights(lexical_weights)
    if not sparse:
        raise SparseVectorOutputError("BGE-M3 returned an empty sparse vector.")
    return sparse


def _get_lexical_weights(output: Mapping[str, Any]) -> Mapping[str | int, float]:
    """从 BGE-M3 输出中取出第一条 lexical weights。"""

    lexical_weights = output.get("lexical_weights")
    if not isinstance(lexical_weights, list) or not lexical_weights:
        raise SparseVectorOutputError("BGE-M3 output missing lexical_weights.")

    first = lexical_weights[0]
    if not isinstance(first, Mapping):
        raise SparseVectorOutputError("BGE-M3 lexical_weights[0] is not a mapping.")
    return first


def _normalize_lexical_weights(weights: Mapping[str | int, float]) -> list[tuple[int, float]]:
    """把 token_id 到 weight 的映射规整成按 token_id 排序的二元组。"""

    sparse: list[tuple[int, float]] = []
    for raw_index, raw_value in weights.items():
        try:
            index = int(raw_index)
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise SparseVectorOutputError(
                f"BGE-M3 returned invalid sparse item: {raw_index!r} -> {raw_value!r}"
            ) from exc
        if value > 0:
            sparse.append((index, value))
    sparse.sort(key=lambda item: item[0])
    return sparse


def _print_deployment_summary(deployment: Mapping[str, Any]) -> None:
    """把部署和冒烟结果打印到控制台，便于人工确认。"""

    print("BGE-M3 sparse vector deployment complete")
    for key, value in deployment.items():
        print(f"{key}: {value}")


def _env_bool(name: str, default: bool) -> bool:
    """从环境变量读取布尔配置，兼容常见真值写法。"""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数配置，未设置时返回默认值。"""

    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


if __name__ == "__main__":
    raise SystemExit(main())
