from __future__ import annotations

import pytest

from scripts import benchmark_bge_m3_sparse as benchmark


def test_benchmark_should_not_expose_external_fp16_flag(monkeypatch):
    """benchmark 脚本不得保留和主程序冲突的外部 fp16 配置入口。"""

    monkeypatch.setenv("SPARSE_VECTOR_USE_FP16", "false")

    args = benchmark.parse_args(["--device", "cuda:0", "--list-cases"])

    assert not hasattr(args, "use_fp16")


def test_benchmark_should_reject_removed_fp16_flag():
    """废弃的 --use-fp16 参数应被 argparse 拒绝，避免测试配置误导。"""

    with pytest.raises(SystemExit):
        benchmark.parse_args(["--use-fp16"])


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("cpu", False),
        ("cuda", True),
        ("cuda:0", True),
        ("CUDA:1", True),
        ("", False),
    ],
)
def test_benchmark_should_derive_fp16_from_device(device, expected):
    """benchmark 和主程序保持同一精度规则：CUDA 使用 fp16，其它设备使用 fp32。"""

    assert benchmark.use_fp16_for_device(device) is expected
